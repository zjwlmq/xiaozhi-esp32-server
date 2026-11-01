"""Migration update checks use a fake Docker engine, never a real daemon."""
from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
import gzip
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('plugin_json_updater', ROOT / 'deploy/update-plugin-compose-json.py')
UPDATER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UPDATER)
SERVER, WEB, DB = UPDATER.SERVER, UPDATER.WEB, UPDATER.DB


class MigrationUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='plugin-json-update-')
        self.root = Path(self.temp.name)
        self.directory = self.root / 'migration'
        self.directory.mkdir()
        self.file = self.directory / 'compose.json'
        self.project = 'migration-test-xiaozhi'
        self.config = {'services': {}, 'volumes': {'old-data': {'name': 'existing-named-volume'}},
                       'networks': {'default': {'name': 'existing-network'}}}
        self.containers, self.current, self.images = {}, {}, {}
        for service, target in ((SERVER, UPDATER.APP_DIR + '/data'), (WEB, '/uploadfile'), (DB, '/var/lib/mysql')):
            image = service + ':cpu-only-demo' if service == SERVER else 'migration/' + service + ':old'
            self.config['services'][service] = {
                'image': image, 'working_dir': UPDATER.APP_DIR if service == SERVER else '/',
                'command': ['python', 'app.py'] if service == SERVER else ['/start.sh'],
                'environment': {'PRIVATE_VALUE': 'test-secret-never-print'},
                'volumes': [{'type': 'volume', 'source': 'old-data', 'target': target}],
                'ports': [{'host_ip': '127.0.0.1', 'published': '8002', 'target': 8002}],
                'networks': {'default': {'aliases': [service]}}, 'restart': 'unless-stopped'}
            cid, image_id = 'container-' + service, 'sha256:old-' + service
            self.current[service] = cid
            self.images[image] = self.images[image_id] = image_id
            self.containers[cid] = {
                'Id': cid, 'Name': '/' + self.project + '-' + service + '-1', 'Image': image_id,
                'State': {'Running': True},
                'Config': {'Image': image, 'WorkingDir': self.config['services'][service]['working_dir'],
                           'User': '', 'Env': ['MYSQL_ROOT_PASSWORD=test-secret-never-print'],
                           'Labels': {'com.docker.compose.project': self.project,
                                      'com.docker.compose.service': service,
                                      'com.docker.compose.project.config_files': str(self.file),
                                      'com.docker.compose.project.working_dir': str(self.directory)}},
                'Mounts': [{'Type': 'volume', 'Name': 'original-volume', 'Destination': target, 'RW': True}]}
        self.config['services']['untouched-redis'] = {'image': 'redis:example', 'volumes': ['old-data:/data']}
        self.file.write_bytes(UPDATER.json_bytes(self.config))
        self.before = self.file.read_bytes()
        self.calls, self.recipes, self.restarts = [], [], []
        self.build_error = self.backup_error = self.web_error = False
        self.edit_during_build = False
        self.backup_count = 0
        self.output = io.StringIO()
        self.patches = [patch.object(UPDATER, 'docker', side_effect=self.docker),
                        patch.object(UPDATER.Installation, 'backup_database', side_effect=self.backup)]
        for item in self.patches:
            item.start()
        self.installation = UPDATER.Installation(self.project, self.file, ROOT)

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.assertTrue(self.root.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.temp.cleanup()

    def docker(self, args, capture=True, check=True, input_text=None):
        self.calls.append(args[:])
        code, output = 0, ''
        if args[0] == 'compose':
            if 'config' in args:
                if '--format' in args:
                    output = self.file.read_text(encoding='utf-8')
            elif 'ps' in args:
                output = self.current[args[-1]] if '--quiet' in args else ''
            elif 'up' in args:
                services = args[args.index('--force-recreate') + 1:]
                self.restarts.append(services)
                self.assertGreater(self.backup_count, 0, 'The database must be backed up before a restart')
                cfg = json.loads(self.file.read_text(encoding='utf-8'))
                if self.web_error and WEB in services and ':rollback-' not in cfg['services'][WEB]['image']:
                    raise RuntimeError('simulated web start failure')
                for service in services:
                    original = deepcopy(self.containers[self.current[service]])
                    cid = 'new-' + str(len(self.restarts)) + '-' + service
                    original.update(Id=cid, Image=self.images[cfg['services'][service]['image']])
                    original['Config']['Image'] = cfg['services'][service]['image']
                    self.containers[cid] = original
                    self.current[service] = cid
            else:
                self.fail('Unexpected Compose action: ' + repr(args))
        elif args[0] == 'inspect':
            output = json.dumps([self.containers[args[1]]])
        elif args[:2] == ['image', 'inspect']:
            if args[-1] in self.images:
                output = self.images[args[-1]]
            else:
                code = 1
        elif args[:2] == ['image', 'tag']:
            self.images[args[-1]] = args[-2]
        elif args[0] == 'build':
            self.recipes.append(input_text)
            if self.build_error:
                raise RuntimeError('simulated build failure')
            tag = args[args.index('-t') + 1]
            self.images[tag] = 'sha256:' + tag
            if self.edit_during_build:
                changed = json.loads(self.file.read_text(encoding='utf-8'))
                changed['services'][SERVER]['ports'][0]['host_ip'] = '192.0.2.10'
                self.file.write_bytes(UPDATER.json_bytes(changed))
        elif args[0] == 'exec':
            if args[2:4] == ['test', '-f']:
                code = 1
            elif args[2:4] == ['sh', '-c'] and 'SHOW TABLES' in args[-1]:
                output = 'ai_agent_extension_config\n'
            elif args[2] == 'python' and 'PluginRuntime' in args[-1] and self.containers[args[1]]['Image'].startswith('sha256:old-'):
                raise RuntimeError('The old server does not contain PluginRuntime')
        else:
            self.fail('Unexpected Docker action: ' + repr(args))
        if check and code:
            raise RuntimeError('simulated missing image')
        return subprocess.CompletedProcess(args, code, stdout=output, stderr='')

    def backup(self, container_id, target):
        self.backup_count += 1
        if self.backup_error:
            raise RuntimeError('simulated database backup failure')
        with gzip.open(str(target), 'wb') as output:
            output.write(b'-- simulated database dump\n')

    def apply(self):
        with redirect_stdout(self.output), redirect_stderr(self.output):
            self.installation.apply()
        self.assertNotIn('test-secret-never-print', self.output.getvalue())

    def assert_only_images_changed(self):
        actual = json.loads(self.file.read_text(encoding='utf-8'))
        for service in (SERVER, WEB):
            actual['services'][service]['image'] = self.config['services'][service]['image']
        self.assertEqual(actual, self.config)
        self.assertFalse((self.directory / '.env').exists())

    def test_prefixed_containers_and_no_env_are_read_only(self):
        info = self.installation.inspect()
        self.assertEqual(info['containers'][SERVER]['Name'], '/' + self.project + '-' + SERVER + '-1')
        with patch.object(UPDATER.sys, 'argv', ['updater', '--check', '--project', self.project, '--file', str(self.file)]), \
                patch.object(UPDATER.os, 'umask'), redirect_stdout(self.output):
            self.assertEqual(UPDATER.main(), 0)
        self.assertIn('检查通过', self.output.getvalue())
        self.assertNotIn('test-secret-never-print', self.output.getvalue())
        self.assertEqual(self.file.read_bytes(), self.before)
        self.assertTrue(all(args[0] in ('compose', 'inspect') or args[:2] == ['image', 'inspect'] for args in self.calls))
        self.assertFalse((self.directory / 'backups').exists())

    def test_untagged_migration_images_use_actual_running_image_id(self):
        for service in (WEB, DB):
            self.images.pop(self.config['services'][service]['image'])
        self.installation.inspect()
        self.assertEqual(self.file.read_bytes(), self.before)

    def test_configured_image_mismatch_stops(self):
        self.images[self.config['services'][SERVER]['image']] = 'sha256:unrelated'
        with self.assertRaisesRegex(RuntimeError, '不一致'):
            self.installation.inspect()

    def test_code_mount_stops_but_data_and_wakeup_volumes_are_allowed(self):
        container = self.containers[self.current[SERVER]]
        container['Mounts'].append({'Destination': UPDATER.APP_DIR + '/config/assets/wakeup_words', 'RW': True})
        self.installation.inspect()
        container['Mounts'].append({'Destination': UPDATER.APP_DIR + '/core', 'RW': True})
        with self.assertRaisesRegex(RuntimeError, '覆盖新版本代码'):
            self.installation.inspect()

    def test_success_preserves_everything_except_two_images_and_cpu_base(self):
        self.apply()
        self.assert_only_images_changed()
        self.assertEqual(self.restarts, [[WEB], [SERVER]])
        first_build = next(args for args in self.calls if args[0] == 'build')
        self.assertIn('PLUGIN_BASE_IMAGE=' + SERVER + ':rollback-', ' '.join(first_build))
        self.assertIn('FROM ${PLUGIN_BASE_IMAGE}', self.recipes[0])
        self.assertNotIn('pip install --no-cache-dir torch', self.recipes[0])
        backup = next((self.directory / 'backups').iterdir())
        self.assertEqual((backup / 'compose.before.json').read_bytes(), self.before)
        self.assertTrue((backup / 'database.sql.gz').is_file())

    def test_backup_failure_never_changes_config_or_restarts(self):
        self.backup_error = True
        with self.assertRaisesRegex(RuntimeError, 'backup failure'):
            self.apply()
        self.assertEqual(self.file.read_bytes(), self.before)
        self.assertEqual(self.restarts, [])

    def test_build_failure_never_changes_config_or_restarts(self):
        self.build_error = True
        with self.assertRaisesRegex(RuntimeError, 'build failure'):
            self.apply()
        self.assertEqual(self.file.read_bytes(), self.before)
        self.assertEqual(self.restarts, [])
        self.assertEqual(self.backup_count, 0)

    def test_concurrent_config_edit_is_preserved_and_stops_update(self):
        self.edit_during_build = True
        with self.assertRaisesRegex(RuntimeError, '已变化'):
            self.apply()
        actual = json.loads(self.file.read_text(encoding='utf-8'))
        self.assertEqual(actual['services'][SERVER]['ports'][0]['host_ip'], '192.0.2.10')
        self.assertEqual(self.restarts, [])

    def test_start_failure_rolls_back_only_application_services(self):
        self.web_error = True
        with self.assertRaisesRegex(RuntimeError, 'web start failure'):
            self.apply()
        self.assert_only_images_changed()
        self.assertEqual(self.restarts, [[WEB], [WEB, SERVER]])
        cfg = json.loads(self.file.read_text(encoding='utf-8'))
        for service in (SERVER, WEB):
            self.assertEqual(self.images[cfg['services'][service]['image']], 'sha256:old-' + service)
        self.assertNotIn('自动恢复未完成', self.output.getvalue())

    def test_server_readiness_failure_restores_both_old_services(self):
        original_wait = UPDATER.Installation.wait_ready
        def wait(instance, service, plugins=True):
            if service == SERVER and plugins:
                raise RuntimeError('simulated server startup failure')
            return original_wait(instance, service, plugins=plugins)
        with patch.object(UPDATER.Installation, 'wait_ready', new=wait):
            with self.assertRaisesRegex(RuntimeError, 'server startup failure'):
                self.apply()
        self.assert_only_images_changed()
        self.assertEqual(self.restarts, [[WEB], [SERVER], [WEB, SERVER]])
        self.assertNotIn('自动恢复未完成', self.output.getvalue())

    def test_manual_rollback_refuses_to_overwrite_later_operator_edits(self):
        self.apply()
        updated = json.loads(self.file.read_text(encoding='utf-8'))
        updated['services'][SERVER]['restart'] = 'on-failure'
        self.file.write_bytes(UPDATER.json_bytes(updated))
        backup = next((self.directory / 'backups').iterdir())
        with self.assertRaisesRegex(RuntimeError, '后来被修改'):
            UPDATER.restore(backup)
        self.assertEqual(json.loads(self.file.read_text(encoding='utf-8')), updated)
        self.assertEqual(self.restarts, [[WEB], [SERVER]])


if __name__ == '__main__':
    unittest.main()
