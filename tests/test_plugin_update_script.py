"""Exercise deployment detection with a fake Docker executable; no services run."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = (r'C:\Program Files\Git\bin\bash.exe' if os.name == 'nt' else shutil.which('bash'))


def shell_path(path):
    value = Path(path).resolve().as_posix()
    return '/' + value[0].lower() + value[2:] if os.name == 'nt' else value


@unittest.skipUnless(BASH and Path(BASH).exists(), 'Bash is required for the deployment script checks')
class PluginUpdateScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='xiaozhi-update-check-')
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.deploy = self.root / 'installation'
        self.deploy.mkdir()
        self.compose = self.deploy / 'docker-compose.yml'
        self.compose.write_text('services:\n  xiaozhi-esp32-server:\n    image: ${XIAOZHI_SERVER_IMAGE}\n  xiaozhi-esp32-server-web:\n    image: ${XIAOZHI_WEB_IMAGE}\n', encoding='utf-8')
        (self.deploy / '.env').write_text('XIAOZHI_SERVER_IMAGE=old:server\nXIAOZHI_WEB_IMAGE=old:web\n', encoding='utf-8')
        self.fixture = self.root / 'fixture.json'
        self.fixture.write_text(json.dumps({'directory': shell_path(self.deploy), 'compose': shell_path(self.compose), 'mismatch': False}), encoding='utf-8')
        self.calls = self.root / 'docker-calls.jsonl'
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        UPDATE_FIXTURE=str(self.fixture), UPDATE_CALLS=str(self.calls), PYTHONUTF8='1')
        (self.bin / 'python3').write_text('#!/usr/bin/env bash\nexec ' + shlex.quote(Path(sys.executable).as_posix()) + ' "$@"\n', encoding='utf-8')
        (self.bin / 'flock').write_text('#!/usr/bin/env bash\nexit 0\n', encoding='utf-8')
        (self.bin / 'docker').write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
fixture=json.loads(Path(os.environ['UPDATE_FIXTURE']).read_text(encoding='utf-8'))
with open(os.environ['UPDATE_CALLS'],'a',encoding='utf-8') as output: output.write(json.dumps(args)+'\\n')
if args[:2]==['compose','version']: print('Docker Compose version v2.test')
elif args[0]=='inspect':
    template=args[2]
    if 'project.working_dir' in template: print(fixture['directory'])
    elif 'project.config_files' in template: print(fixture['compose'])
    elif '.project' in template: print('xiaozhi-test')
    elif '.State.Running' in template: print('true')
    elif '.Image' in template:
        print('sha256:mismatch' if fixture['mismatch'] else 'sha256:'+('web' if args[-1].endswith('-web') else 'server'))
    else: raise SystemExit('Unexpected inspect')
elif args[0]=='compose' and 'config' in args:
    if '--format' in args: print(json.dumps({'services': {'xiaozhi-esp32-server': {'image':'old:server'}, 'xiaozhi-esp32-server-web': {'image':'old:web'}}}))
elif args[:2]==['image','inspect']: print('sha256:'+('web' if args[-1].endswith(':web') else 'server'))
else: raise SystemExit('A read-only check tried an unexpected Docker command: '+repr(args))
''', encoding='utf-8')
        for path in self.bin.iterdir(): path.chmod(0o755)

    def tearDown(self):
        self.assertTrue(self.root.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve()))
        self.temp.cleanup()

    def run_check(self):
        before = self.compose.read_bytes(), (self.deploy / '.env').read_bytes()
        result = subprocess.run([BASH, '--noprofile', '--norc', shell_path(ROOT / 'deploy/update-plugin-center.sh'), '--check'],
                                env=self.env, capture_output=True, encoding='utf-8', timeout=25)
        self.assertEqual(before, (self.compose.read_bytes(), (self.deploy / '.env').read_bytes()))
        calls = [json.loads(line) for line in self.calls.read_text(encoding='utf-8').splitlines()]
        self.assertTrue(all(args[0] == 'inspect' or args[:2] == ['image','inspect'] or
                            (args[0] == 'compose' and ('version' in args or 'config' in args)) for args in calls))
        self.assertFalse((self.deploy / 'backups').exists())
        return result

    def test_standard_installation_is_detected_without_mutation(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('检查通过', result.stdout)

    def test_fixed_image_layout_stops_without_mutation(self):
        self.compose.write_text('services:\n  xiaozhi-esp32-server:\n    image: old:server\n', encoding='utf-8')
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('固定镜像', result.stderr)

    def test_multiple_compose_files_stop_without_mutation(self):
        fixture = json.loads(self.fixture.read_text(encoding='utf-8'))
        fixture['compose'] += ',/another-compose.yml'
        self.fixture.write_text(json.dumps(fixture), encoding='utf-8')
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('多份 Compose', result.stderr)

    def test_running_image_mismatch_stops_without_mutation(self):
        fixture = json.loads(self.fixture.read_text(encoding='utf-8'))
        fixture['mismatch'] = True
        self.fixture.write_text(json.dumps(fixture), encoding='utf-8')
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('配置与正在运行', result.stderr)


if __name__ == '__main__': unittest.main()
