#!/usr/bin/env python3
"""Connect a migrated Xiaozhi service to an existing SnowLuma privately.

Reads the gateway's two tokens through the existing qqfish container. Tokens
travel over subprocess stdin/stdout pipes, never terminal output or arguments.
Only Xiaozhi's network/configuration is changed; no QQ messages are sent.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit
import uuid

spec = importlib.util.spec_from_file_location('compose_qq_updater', Path(__file__).with_name('update-plugin-compose-json.py'))
updater = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updater)
SERVER = updater.SERVER
CONFIG_PATH = 'data/.qq-bridge.yaml'

DISCOVER = r'''
import fs from 'node:fs';
import { pathToFileURL } from 'node:url';
const root = process.cwd();
const cfg = JSON.parse(fs.readFileSync(root + '/config.json', 'utf8'));
const { discoverSnowLumaConnection } = await import(pathToFileURL(root + '/src/snowluma-conn.js').href);
const r = await discoverSnowLumaConnection({cfg, timeoutMs:4000});
if (!r.ok || !r.self?.user_id || typeof r.token !== 'string' || typeof r.wsToken !== 'string') {
  throw new Error('Cannot obtain verified HTTP and WebSocket credentials');
}
process.stdout.write(JSON.stringify({
  self_id:String(r.self.user_id), http_url:r.baseUrl,
  websocket_url:r.wsUrl || cfg.snowluma?.wsUrl,
  access_token:r.token, websocket_access_token:r.wsToken
}));
'''

CHECK_CONFIG = r'''
import hashlib,json,pathlib,sys,yaml
expected=json.load(sys.stdin)
p=pathlib.Path('data/.qq-bridge.yaml')
if p.is_symlink(): raise ValueError('Config cannot be a symlink')
if not p.exists():
 print(json.dumps({'exists':False}));sys.exit(0)
raw=p.read_bytes();document=yaml.safe_load(raw) or {};cfg=document.get('qq_bridge') or {}
checks={k:cfg.get(k)==v for k,v in expected.items()}
print(json.dumps({'exists':True,'matches':all(checks.values()),'sha256':hashlib.sha256(raw).hexdigest()}))
'''

DISABLE_CREATED_CONFIG = r'''
import hashlib,json,pathlib,sys
expected=json.load(sys.stdin)
p=pathlib.Path('data/.qq-bridge.yaml')
if not p.exists():sys.exit(0)
if p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected['sha256']:
 raise ValueError('Config changed; refusing to move it')
target=p.with_name('.qq-bridge.yaml.setup-failed-'+expected['suffix'])
if target.exists():raise ValueError('Recovery destination already exists')
p.rename(target)
'''


def command(args, payload=None, check=True, timeout=90):
    try:
        result = subprocess.run(['docker', *args], input=payload, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError('Docker操作未完成；未自动重试或输出凭据。') from None
    if check and result.returncode:
        raise RuntimeError('Docker操作失败，退出码{}；未输出可能含凭据的子进程内容。'.format(result.returncode))
    return result


def one_container(name):
    values = json.loads(command(['inspect', name]).stdout)
    if len(values) != 1 or not values[0].get('State', {}).get('Running'):
        raise RuntimeError('容器未运行：' + name)
    return values[0]


def id_value(value):
    if not re.fullmatch(r'[1-9][0-9]{4,19}', value):
        raise RuntimeError('QQ号格式无效。')
    return value


def gateway_url(value, gateway_name, schemes):
    parsed = urlsplit(value)
    if (parsed.scheme not in schemes or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise RuntimeError('网关端点格式无效；未输出其内容。')
    port = parsed.port
    host = gateway_name + (':' + str(port) if port else '')
    return urlunsplit((parsed.scheme, host, parsed.path, '', '')).rstrip('/')


def with_network(raw, name, effective_networks=None):
    updated = deepcopy(raw)
    service = updated['services'][SERVER]
    if service.get('network_mode'):
        raise RuntimeError('Python服务使用network_mode，需要单独适配。')
    if updated.get('networks') is None:
        updated['networks'] = {}
    networks = updated['networks']
    if not isinstance(networks, dict):
        raise RuntimeError('项目网络定义格式无效。')
    wanted = {'external': True, 'name': name}
    key = 'qq-channel'
    if key in networks and networks[key] != wanted:
        raise RuntimeError('qq-channel网络键已被其他配置占用。')
    networks[key] = wanted
    previous = service.get('networks')
    if not previous:
        # Once an explicit network is added, Compose no longer adds default.
        existing = list(effective_networks) if effective_networks is not None else ['default']
        if 'default' in existing:
            networks.setdefault('default', {})
        service['networks'] = {n:{} for n in existing}
        service['networks'][key] = {}
    elif isinstance(previous, list):
        if key not in previous:
            previous.append(key)
    elif isinstance(previous, dict):
        previous.setdefault(key, {})
    else:
        raise RuntimeError('原有网络配置格式无效。')
    return updated


def discover(credential_container, bridge_dir, self_id, gateway_name):
    value = json.loads(command(['exec', '-i', '-w', bridge_dir, credential_container,
                                'node', '--input-type=module'], DISCOVER).stdout)
    if str(value.get('self_id')) != self_id:
        raise RuntimeError('网关当前登录账号与指定机器人QQ不同；未修改配置。')
    for key in ('access_token', 'websocket_access_token'):
        token = value.get(key)
        if not isinstance(token, str) or len(token) > 16384 or '\r' in token or '\n' in token:
            raise RuntimeError('未读取到有效的HTTP / WS密钥；未修改配置。')
    value['http_url'] = gateway_url(value.get('http_url', ''), gateway_name, ('http', 'https'))
    value['websocket_url'] = gateway_url(value.get('websocket_url', ''), gateway_name, ('ws', 'wss'))
    return value


def configure(installation, gateway, credentials, bridge_dir, network, self_id, peer_id, apply=False):
    id_value(self_id)
    id_value(peer_id)
    if self_id == peer_id:
        raise RuntimeError('机器人QQ和测试QQ必须不同。')
    initial = installation.inspect()
    server = initial['containers'][SERVER]
    gateway_info = one_container(gateway)
    one_container(credentials)
    if network not in gateway_info['NetworkSettings']['Networks']:
        raise RuntimeError('指定网关不在该网络中。')
    gateway_name = gateway_info['Name'].lstrip('/')
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*', gateway_name):
        raise RuntimeError('网关容器名称无效。')
    command(['exec', server['Id'], 'python', '-c',
             "from core.channels.qq.settings import Settings; assert 'websocket_access_token' in Settings.__dataclass_fields__"])
    private = discover(credentials, bridge_dir, self_id, gateway_name)
    expected = {k:private[k] for k in ('self_id','http_url','websocket_url','access_token','websocket_access_token')}
    expected.update(enabled=True, routes=[{'id':'friend','kind':'private','peer_id':peer_id,'reply_mode':'text'}])
    expected_input = json.dumps(expected, ensure_ascii=False)
    config_state = json.loads(command(['exec','-i',server['Id'],'python','-c',CHECK_CONFIG], expected_input).stdout)
    if config_state.get('exists') and not config_state.get('matches'):
        raise RuntimeError('已有QQ配置与目标或密钥不同，未覆盖；请先核对现有配置。')
    updated = with_network(initial['raw'], network,
                           initial['effective']['services'][SERVER].get('networks', {}))
    print('机器人QQ：{}；测试QQ：{}'.format(self_id,peer_id), flush=True)
    print('小智将使用：{} / {}'.format(private['http_url'],private['websocket_url']), flush=True)
    print('密钥已在服务器内读取；HTTP / WS独立保存，不输出值。', flush=True)
    if not apply:
        print('检查通过；--apply才连接网络、生成配置并重建Python容器。', flush=True)
        return
    installation.unchanged(initial)
    backup_parent = installation.directory/'backups'
    if backup_parent.is_symlink():
        raise RuntimeError('backups目录是符号链接，已停止。')
    backup_parent.mkdir(exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='qq-channel-',dir=backup_parent))
    (backup/'compose.before.json').write_bytes(initial['original'])
    record = {'at':datetime.now(timezone.utc).isoformat(),'project':installation.project,
              'self_id':self_id,'peer_id':peer_id,'network':network,'status':'prepared',
              'compose_before_sha256':hashlib.sha256(initial['original']).hexdigest()}
    (backup/'setup-state.json').write_bytes(updater.json_bytes(record))
    added_live = network not in server['NetworkSettings']['Networks']
    created_digest, written = None, False
    updated_bytes = updater.json_bytes(updated)
    try:
        if added_live:
            command(['network','connect',network,server['Id']])
        if not config_state.get('exists'):
            tokens = {k:private[k] for k in ('access_token','websocket_access_token')}
            command(['exec','-i',server['Id'],'python','tools/qq_bridge.py','init','--tokens-stdin',
                     '--self-id',self_id,'--peer-id',peer_id,'--http-url',private['http_url'],
                     '--ws-url',private['websocket_url']],json.dumps(tokens))
            state = json.loads(command(['exec','-i',server['Id'],'python','-c',CHECK_CONFIG],expected_input).stdout)
            if not state.get('matches'):
                raise RuntimeError('新配置校验失败。')
            created_digest = state['sha256']
        print('检查小智容器到OneBot的HTTP / WebSocket与账号。',flush=True)
        command(['exec',server['Id'],'python','tools/qq_bridge.py','check','--websocket'])
        installation.unchanged(initial)
        if updated != initial['raw']:
            updater.atomic_write(installation.file,updated_bytes)
            written = True
            command([*installation.compose,'config','--quiet'])
        needs_restart = written or created_digest is not None
        if not needs_restart:
            needs_restart = command(['exec',server['Id'],'python','tools/qq_bridge.py','status'],check=False).returncode != 0
        if needs_restart:
            installation.restart([SERVER])
        deadline = time.monotonic()+120
        while True:
            current_id = command([*installation.compose,'ps','--quiet',SERVER]).stdout.strip()
            status = command(['exec',current_id,'python','tools/qq_bridge.py','status'],check=False,timeout=35)
            if status.returncode == 0:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('QQ接口未就绪，启动恢复流程。')
            time.sleep(3)
    except BaseException:
        print('QQ配置未完成，正在恢复本次网络/启动配置。',file=sys.stderr,flush=True)
        record['status'] = 'failed_or_unknown'
        record['created_config_sha256'] = created_digest
        (backup/'setup-state.json').write_bytes(updater.json_bytes(record))
        cleanup_failed = False
        if created_digest:
            try:
                # A failed service may no longer accept docker exec. A one-off
                # Python process uses its persistent data mount without starting
                # the application or publishing service ports.
                command([*installation.compose,'run','--rm','--no-deps','-T','--entrypoint','python',
                         SERVER,'-c',DISABLE_CREATED_CONFIG],
                        json.dumps({'sha256':created_digest,'suffix':uuid.uuid4().hex[:12]}))
            except BaseException:
                cleanup_failed = True
                print('新QQ配置未移到失败备份，请检查持久化data目录。',file=sys.stderr,flush=True)
        try:
            if written:
                if installation.file.read_bytes() != updated_bytes:
                    raise RuntimeError('Compose被其他任务修改，未自动覆盖。')
                updater.atomic_write(installation.file,initial['original'])
                installation.restart([SERVER])
                if not added_live:
                    current_id = command([*installation.compose,'ps','--quiet',SERVER]).stdout.strip()
                    command(['network','connect',network,current_id],check=False)
            elif added_live:
                command(['network','disconnect',network,server['Id']],check=False)
        except BaseException:
            print('自动恢复未完成，请结合备份检查：'+str(backup),file=sys.stderr,flush=True)
        if cleanup_failed:
            print('本次凭据仍保存在私有data文件中；备份：'+str(backup),file=sys.stderr,flush=True)
        raise
    record['status'] = 'verified'
    (backup/'setup-state.json').write_bytes(updater.json_bytes(record))
    print('QQ HTTP / WebSocket均已核对，网络已写入Compose。备份：'+str(backup),flush=True)
    print(status.stdout.strip(),flush=True)
    print('下一步运行 python tools/qq_bridge.py prepare --route friend 获取设备激活码；尚未发送QQ消息。',flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True)
    parser.add_argument('--file',required=True)
    parser.add_argument('--self-id',required=True)
    parser.add_argument('--peer-id',required=True)
    parser.add_argument('--gateway-container',default='qqfish-snowluma')
    parser.add_argument('--credential-container',default='qqfish-app')
    parser.add_argument('--bridge-dir',default='/opt/qqfish/bridge')
    parser.add_argument('--network',default='qqfish-private')
    parser.add_argument('--apply',action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.apply:
            if not hasattr(os,'geteuid') or os.geteuid()!=0:
                raise RuntimeError('配置需要root权限。')
            import fcntl
            lock = open('/var/lock/xiaozhi-server-install.lock','a')
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        installation = updater.Installation(args.project,args.file)
        configure(installation,args.gateway_container,args.credential_container,args.bridge_dir,
                  args.network,args.self_id,args.peer_id,args.apply)
    except RuntimeError as error:
        print('[xiaozhi-qq] '+str(error),file=sys.stderr)
        return 1
    except (ValueError,OSError,KeyError,TypeError):
        # Never echo provider output, data structures or subprocess input.
        print('[xiaozhi-qq] 配置失败；请核对上一条阶段信息、容器状态与备份。未输出密钥。',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':
    sys.exit(main())
