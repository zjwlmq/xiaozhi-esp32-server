"""Network/configuration orchestration against a fake Docker engine."""
from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qq_compose_setup',ROOT/'deploy/configure-qq-compose-json.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


class FakeInstallation:
    project='migration-test'
    def __init__(self,root):
        self.directory=root
        self.file=root/'compose.json'
        self.raw={'services':{setup.SERVER:{'image':'python:existing','working_dir':setup.updater.APP_DIR,
            'ports':['8000:8000','8003:8003'],'volumes':['persistent-data:/opt/xiaozhi-esp32-server/data']},
            'unchanged-web':{'image':'web:existing'}},'volumes':{'persistent-data':{}},
            'networks':{'default':{'name':'original-default'}}}
        self.file.write_bytes(setup.updater.json_bytes(self.raw))
        self.compose=['compose','-p',self.project,'-f',str(self.file)]
        self.cid='server-original'
        self.networks={'original-default':{}}
        self.restarts=[]
        self.fail_restart_once=False
        self.loaded=False

    def inspect(self):
        raw=json.loads(self.file.read_text(encoding='utf-8'))
        effective=deepcopy(raw)
        effective['services'][setup.SERVER].setdefault('networks',{'default':{}})
        return {'original':self.file.read_bytes(),'raw':raw,'effective':effective,
                'containers':{setup.SERVER:{'Id':self.cid,'NetworkSettings':{'Networks':deepcopy(self.networks)}}}}

    def unchanged(self,initial):
        if self.file.read_bytes()!=initial['original'] or self.cid!=initial['containers'][setup.SERVER]['Id']:
            raise RuntimeError('concurrent edit')

    def restart(self,services):
        self.restarts.append(services)
        if self.fail_restart_once:
            self.fail_restart_once=False
            raise RuntimeError('simulated restart failure')
        self.cid='server-new-'+str(len(self.restarts))
        spec=json.loads(self.file.read_text(encoding='utf-8'))['services'][setup.SERVER]
        self.networks={'original-default':{}}
        if 'qq-channel' in spec.get('networks',{}):self.networks['qqfish-private']={}
        self.loaded=True


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='qq-compose-test-')
        self.root=Path(self.temp.name)
        def cleanup():
            assert self.root.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
            self.temp.cleanup()
        self.addCleanup(cleanup)
        self.installation=FakeInstallation(self.root)
        self.original=self.installation.file.read_bytes()
        self.stdout=io.StringIO()
        self.calls=[]
        self.config=None
        self.probe_failed=False
        self.private={'self_id':'100001','http_url':'http://snowluma:3000/',
                      'websocket_url':'ws://0.0.0.0:3001/',
                      'access_token':'private-http-test-secret','websocket_access_token':'private-ws-test-secret'}
        patcher=patch.object(setup,'command',side_effect=self.command)
        patcher.start()
        self.addCleanup(patcher.stop)

    def config_digest(self):
        return hashlib.sha256(json.dumps(self.config,sort_keys=True).encode()).hexdigest()

    def command(self,args,payload=None,check=True,timeout=90):
        self.calls.append((args[:],payload))
        output=''
        code=0
        if args[0]=='inspect':
            output=json.dumps([{'Name':'/'+args[1],'State':{'Running':True},
                'NetworkSettings':{'Networks':{'qqfish-private':{}}}}])
        elif args[:2]==['network','connect']:
            self.installation.networks['qqfish-private']={}
        elif args[:2]==['network','disconnect']:
            self.installation.networks.pop('qqfish-private',None)
        elif args[0]=='compose':
            if 'ps' in args:output=self.installation.cid
            elif 'run' in args:
                self.assertIn('--no-deps',args)
                self.assertIn('--rm',args)
                self.assertIn('--entrypoint',args)
                self.assertEqual(json.loads(payload)['sha256'],self.config_digest())
                self.config=None
            else:self.assertIn('config',args)
        elif args[0]=='exec':
            if setup.DISCOVER in (payload or ''):
                output=json.dumps(self.private)
            elif setup.CHECK_CONFIG in args:
                expected=json.loads(payload)
                state={'exists':self.config is not None}
                if self.config is not None:
                    state.update(matches=all(self.config.get(k)==v for k,v in expected.items()),sha256=self.config_digest())
                output=json.dumps(state)
            elif 'init' in args:
                self.assertIn('--tokens-stdin',args)
                self.assertIsNone(self.config)
                value=lambda key:args[args.index(key)+1]
                self.config={'enabled':True,'self_id':value('--self-id'),'http_url':value('--http-url'),
                    'websocket_url':value('--ws-url'),'routes':[{'id':'friend','kind':'private',
                    'peer_id':value('--peer-id'),'reply_mode':'text'}],**json.loads(payload),
                    'api_key':'private-api-test-secret','webhook_secret':'private-webhook-test-secret'}
            elif 'check' in args:
                self.assertIn('--websocket',args)
                if self.probe_failed:raise RuntimeError('simulated WebSocket failure')
            elif 'status' in args:
                code=0 if self.config and self.installation.loaded else 1
                output='{"onebot_connected":true,"routes":[]}'
            else:self.assertIn('websocket_access_token',args[-1])
        else:self.fail('Unexpected Docker action')
        if check and code:raise RuntimeError('simulated Docker failure')
        return subprocess.CompletedProcess(args,code,stdout=output,stderr='')

    def run_setup(self,apply=False):
        with redirect_stdout(self.stdout),redirect_stderr(self.stdout):
            return setup.configure(self.installation,'qqfish-snowluma','qqfish-app','/opt/qqfish/bridge',
                                   'qqfish-private','100001','200001',apply)

    def assert_no_leaks(self):
        log=self.stdout.getvalue()+''.join(p.read_text(encoding='utf-8') for p in self.root.rglob('*.json'))
        arguments=''.join(repr(args) for args,_ in self.calls)
        for value in ('private-http-test-secret','private-ws-test-secret','private-api-test-secret','private-webhook-test-secret'):
            self.assertNotIn(value,log)
            self.assertNotIn(value,arguments)

    def test_readonly_checks_do_not_connect_or_write(self):
        self.run_setup()
        self.assertEqual(self.installation.file.read_bytes(),self.original)
        self.assertFalse(any(args[0]=='network' for args,_ in self.calls))
        self.assertIsNone(self.config)
        self.assertFalse((self.root/'backups').exists())
        self.assert_no_leaks()

    def test_apply_persists_default_and_qq_network_and_private_split_tokens(self):
        self.run_setup(True)
        updated=json.loads(self.installation.file.read_text(encoding='utf-8'))
        original=json.loads(self.original)
        self.assertEqual(updated['services']['unchanged-web'],original['services']['unchanged-web'])
        service=updated['services'][setup.SERVER]
        self.assertEqual(service['networks'],{'default':{},'qq-channel':{}})
        self.assertEqual(updated['networks']['qq-channel'],{'external':True,'name':'qqfish-private'})
        service.pop('networks')
        self.assertEqual(service,original['services'][setup.SERVER])
        self.assertEqual(self.config['access_token'],self.private['access_token'])
        self.assertEqual(self.config['websocket_access_token'],self.private['websocket_access_token'])
        self.assertEqual(self.config['http_url'],'http://qqfish-snowluma:3000')
        self.assertEqual(self.config['websocket_url'],'ws://qqfish-snowluma:3001')
        self.assertEqual(self.installation.restarts,[[setup.SERVER]])
        self.assert_no_leaks()

    def test_failed_probe_disables_new_config_and_disconnects_temporary_network(self):
        self.probe_failed=True
        with self.assertRaisesRegex(RuntimeError,'WebSocket failure'):
            self.run_setup(True)
        self.assertIsNone(self.config)
        self.assertNotIn('qqfish-private',self.installation.networks)
        self.assertEqual(self.installation.file.read_bytes(),self.original)
        self.assertFalse(self.installation.restarts)
        self.assert_no_leaks()

    def test_failed_restart_restores_compose_even_if_service_was_not_running(self):
        self.installation.fail_restart_once=True
        with self.assertRaisesRegex(RuntimeError,'restart failure'):
            self.run_setup(True)
        self.assertEqual(self.installation.file.read_bytes(),self.original)
        self.assertIsNone(self.config)
        self.assertEqual(self.installation.restarts,[[setup.SERVER],[setup.SERVER]])
        self.assert_no_leaks()

    def test_rerun_does_not_rotate_matching_config_or_restart(self):
        self.run_setup(True)
        config=deepcopy(self.config)
        self.calls.clear();self.installation.restarts.clear()
        self.run_setup(True)
        self.assertEqual(self.config,config)
        self.assertFalse(self.installation.restarts)
        self.assertFalse(any('init' in args for args,_ in self.calls))
        self.assert_no_leaks()

    def test_wrong_login_stops_before_modification(self):
        self.private['self_id']='100002'
        with self.assertRaisesRegex(RuntimeError,'账号'):
            self.run_setup(True)
        self.assertEqual(self.installation.file.read_bytes(),self.original)
        self.assertFalse(any(args[0]=='network' for args,_ in self.calls))

    def test_existing_different_config_never_overwritten(self):
        self.config={'enabled':True,'self_id':'100003'}
        with self.assertRaisesRegex(RuntimeError,'未覆盖'):
            self.run_setup(True)
        self.assertEqual(self.config,{'enabled':True,'self_id':'100003'})
        self.assertFalse(self.installation.restarts)

    def test_explicit_network_aliases_are_preserved(self):
        for networks in (['default'],{'default':{'aliases':['existing-alias']}}):
            original=deepcopy(self.installation.raw)
            original['services'][setup.SERVER]['networks']=networks
            updated=setup.with_network(original,'qqfish-private')
            if isinstance(networks,list):self.assertEqual(updated['services'][setup.SERVER]['networks'],['default','qq-channel'])
            else:self.assertEqual(updated['services'][setup.SERVER]['networks']['default'],{'aliases':['existing-alias']})
            self.assertEqual(original['services'][setup.SERVER]['networks'],networks)

    def test_empty_network_definition_preserves_effective_default(self):
        original=deepcopy(self.installation.raw)
        original['networks']=None
        original['services'][setup.SERVER]['networks']=[]
        updated=setup.with_network(original,'qqfish-private',{'default':{}})
        self.assertIn('default',updated['services'][setup.SERVER]['networks'])

    def test_network_key_collision_is_not_overwritten(self):
        original=deepcopy(self.installation.raw)
        original['networks']['qq-channel']={'external':True,'name':'unrelated-network'}
        with self.assertRaises(RuntimeError):setup.with_network(original,'qqfish-private')


if __name__=='__main__':
    unittest.main()
