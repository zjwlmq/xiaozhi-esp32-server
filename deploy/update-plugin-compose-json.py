#!/usr/bin/env python3
"""Update an existing migrated Compose JSON deployment, retaining its volumes."""
import argparse
from copy import deepcopy
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

SERVER = 'xiaozhi-esp32-server'
WEB = SERVER + '-web'
DB = SERVER + '-db'
APP_DIR = '/opt/xiaozhi-esp32-server'

SERVER_DOCKERFILE = '''ARG PLUGIN_BASE_IMAGE
FROM ${PLUGIN_BASE_IMAGE}
USER root
WORKDIR /opt/xiaozhi-esp32-server
RUN python -m pip install --no-cache-dir cnlunar==0.2.0 httpx==0.28.1 Jinja2==3.1.6
COPY main/xiaozhi-server/ /opt/xiaozhi-esp32-server/
RUN python -c "import cnlunar, httpx, jinja2; from core.plugins.runtime import PluginRuntime"
'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def with_images(config, server_image, web_image):
    updated = deepcopy(config)
    updated['services'][SERVER]['image'] = server_image
    updated['services'][WEB]['image'] = web_image
    return updated


def atomic_write(path, data):
    """Replace a regular config file without changing its ownership or mode."""
    path = Path(path)
    if path.is_symlink():
        raise RuntimeError('配置是符号链接，已停止。')
    previous = path.stat()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.plugins-', delete=False) as output:
            temporary = output.name
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, stat.S_IMODE(previous.st_mode))
        if hasattr(os, 'chown'):
            os.chown(temporary, previous.st_uid, previous.st_gid)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)


def docker(args, capture=True, check=True, input_text=None):
    result = subprocess.run(['docker', *args], input=input_text, text=True,
                            stdout=subprocess.PIPE if capture else None,
                            stderr=subprocess.PIPE if capture else None)
    if check and result.returncode:
        # Never echo resolved Compose configuration or container environment values.
        raise RuntimeError('Docker 命令失败（退出码 {}）：{}'.format(
            result.returncode, ' '.join(shlex.quote(str(x)) for x in args)))
    return result


def web_dockerfile(source):
    content = (source / 'Dockerfile-web').read_text(encoding='utf-8')
    node_line = 'RUN npm run build'
    java_line = 'RUN mvn clean package -Dmaven.test.skip=true'
    if content.count(node_line) != 1 or content.count(java_line) != 1:
        raise RuntimeError('Dockerfile-web 构建步骤已变化，请更新适配脚本。')
    return content.replace(node_line, '''RUN printf '%s\\n' 'const os=require("os");const cpu=os.cpus().slice(0,1);os.cpus=()=>cpu;os.availableParallelism=()=>1;' > /tmp/plugin-build-worker.cjs \\
    && NODE_OPTIONS='--max-old-space-size=768 --require=/tmp/plugin-build-worker.cjs' VUE_APP_USE_CDN=false npm run build''').replace(
        java_line, "RUN MAVEN_OPTS='-Xms32m -Xmx512m -XX:+UseSerialGC' mvn clean package -Dmaven.test.skip=true")


class Installation:
    def __init__(self, project, config_file, source=None):
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]*', project):
            raise RuntimeError('项目名称无效。')
        self.project = project
        self.file = Path(config_file).absolute()
        if self.file.is_symlink() or not self.file.is_file():
            raise RuntimeError('需要现有的普通 compose.json 文件。')
        self.file = self.file.resolve()
        self.directory = self.file.parent
        if str(self.directory) in ('/', '/root', '/home', '/opt', '/etc', '/var'):
            raise RuntimeError('Compose 配置必须在专用部署目录中。')
        self.source = Path(source).resolve() if source else Path(__file__).resolve().parents[1]
        self.compose = ['compose', '--project-directory', str(self.directory),
                        '-p', project, '-f', str(self.file)]

    def container(self, service):
        ids = docker([*self.compose, 'ps', '--all', '--quiet', service]).stdout.split()
        if len(ids) != 1:
            raise RuntimeError('服务 {} 需要且只能有一个现有容器。'.format(service))
        value = json.loads(docker(['inspect', ids[0]]).stdout)[0]
        labels = value.get('Config', {}).get('Labels', {}) or {}
        if (labels.get('com.docker.compose.project') != self.project or
                labels.get('com.docker.compose.service') != service):
            raise RuntimeError('容器的 Compose 项目或服务标签不匹配：' + service)
        files = labels.get('com.docker.compose.project.config_files', '')
        if ',' in files or not files or Path(files).resolve() != self.file:
            raise RuntimeError('容器没有使用指定的单份 Compose 配置：' + service)
        working_dir = labels.get('com.docker.compose.project.working_dir', '')
        if not working_dir or Path(working_dir).resolve() != self.directory:
            raise RuntimeError('Compose 项目目录与运行中的容器不一致：' + service)
        if not value.get('State', {}).get('Running'):
            raise RuntimeError('原容器未运行：' + service)
        return value

    @staticmethod
    def check_mounts(container, service):
        protected = ([APP_DIR + '/core', APP_DIR + '/config/manage_api_client.py',
                      APP_DIR + '/config/config_loader.py', APP_DIR + '/app.py'] if service == SERVER
                     else ['/app/xiaozhi-esp32-api.jar', '/usr/share/nginx/html', '/etc/nginx/nginx.conf'])
        for mount in container.get('Mounts', []):
            target = PurePosixPath(mount['Destination'])
            for code_path in protected:
                code = PurePosixPath(code_path)
                if target == code or target in code.parents or code in target.parents:
                    raise RuntimeError('挂载会覆盖新版本代码，需要单独处理：{} {}'.format(service, target))

    def inspect(self):
        original = self.file.read_bytes()
        raw = json.loads(original.decode('utf-8-sig'))
        effective = json.loads(docker([*self.compose, 'config', '--format', 'json']).stdout)
        containers = {}
        for service in (SERVER, WEB, DB):
            spec = effective.get('services', {}).get(service)
            if not spec or service not in raw.get('services', {}) or not spec.get('image'):
                raise RuntimeError('配置缺少服务或镜像：' + service)
            container = self.container(service)
            resolved_image = docker(['image', 'inspect', '--format', '{{.Id}}', spec['image']], check=False)
            if resolved_image.returncode == 0:
                if resolved_image.stdout.strip() != container['Image']:
                    raise RuntimeError('配置镜像与正在运行的镜像不一致：' + service)
            elif spec['image'] != container['Config'].get('Image'):
                raise RuntimeError('镜像标签不存在，且配置与运行容器的镜像引用不同：' + service)
            else:
                # Migration exports may retain an old tag after the local image is untagged.
                docker(['image', 'inspect', '--format', '{{.Id}}', container['Image']])
            containers[service] = container
        for service in (SERVER, WEB):
            self.check_mounts(containers[service], service)
        if containers[SERVER]['Config'].get('WorkingDir') != APP_DIR:
            raise RuntimeError('Python 服务工作目录不同，需要单独适配。')
        if containers[SERVER]['Config'].get('User', '') not in ('', 'root', '0', '0:0'):
            raise RuntimeError('Python 服务使用非 root 用户，需要单独适配依赖安装。')
        server_data = containers[SERVER].get('Mounts', [])
        if not any(m['Destination'] == APP_DIR + '/data' and m.get('RW') for m in server_data):
            raise RuntimeError('Python data 目录没有可写的持久化挂载。')
        if not any(m['Destination'] == '/var/lib/mysql' and m.get('RW') for m in containers[DB].get('Mounts', [])):
            raise RuntimeError('MySQL 数据目录没有可写的持久化挂载。')
        database_env = dict(item.split('=', 1) for item in containers[DB]['Config'].get('Env', []) if '=' in item)
        if not database_env.get('MYSQL_ROOT_PASSWORD'):
            raise RuntimeError('MySQL 容器未提供备份所需的 MYSQL_ROOT_PASSWORD；未修改服务。')
        return {'original': original, 'raw': raw, 'effective': effective, 'containers': containers}

    def unchanged(self, before):
        after = self.inspect()
        if (after['original'] != before['original'] or after['effective'] != before['effective'] or
                any(after['containers'][name]['Id'] != before['containers'][name]['Id']
                    for name in (SERVER, WEB, DB))):
            raise RuntimeError('准备期间配置或容器已变化，未切换服务；请重新检查。')

    def backup_database(self, container_id, target):
        command = '''set -eu
export MYSQL_PWD="${MYSQL_ROOT_PASSWORD:?}"
exec mysqldump --user=root --single-transaction --routines --triggers --events \\
  --set-gtid-purged=OFF --no-tablespaces --databases "${MYSQL_DATABASE:-xiaozhi_esp32_server}"
'''
        with (target.parent / 'database-backup.stderr.log').open('wb') as errors:
            process = subprocess.Popen(['docker', 'exec', container_id, 'sh', '-c', command],
                                       stdout=subprocess.PIPE, stderr=errors)
            try:
                with gzip.open(str(target), 'wb') as output:
                    shutil.copyfileobj(process.stdout, output, 1024 * 1024)
                if process.wait() != 0:
                    raise RuntimeError('数据库备份失败，未切换服务；详情保存在备份目录。')
            except BaseException:
                if process.poll() is None:
                    process.kill()
                process.wait()
                raise
            finally:
                process.stdout.close()
        with gzip.open(str(target), 'rb') as backup:
            if not backup.read(1):
                raise RuntimeError('数据库备份为空，未切换服务。')
            while backup.read(1024 * 1024):
                pass

    def backup_runtime_config(self, container_id, directory):
        path = APP_DIR + '/data/.config.yaml'
        result = docker(['exec', container_id, 'test', '-f', path], check=False)
        if result.returncode == 0:
            docker(['cp', container_id + ':' + path, str(directory / 'runtime-config.before.yaml')])
        elif result.returncode != 1:
            raise RuntimeError('无法检查运行配置，未切换服务。')

    def restart(self, services):
        docker([*self.compose, 'up', '-d', '--no-deps', '--no-build', '--pull', 'never',
                '--force-recreate', *services], capture=False)

    def wait_ready(self, service, plugins=True):
        container_id = self.container(service)['Id']
        if service == WEB:
            command = ['wget', '-q', '-T', '5', '-O', '/dev/null',
                       'http://127.0.0.1:8002/xiaozhi/user/pub-config']
        else:
            command = ['python', '-c', 'import socket; ' +
                       ('from core.plugins.runtime import PluginRuntime; ' if plugins else '') +
                       'socket.create_connection(("127.0.0.1",8000),timeout=2).close()']
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if docker(['exec', container_id, *command], check=False).returncode == 0:
                return container_id
            time.sleep(5)
        raise RuntimeError('新服务未就绪：' + service)

    def apply(self):
        initial = self.inspect()
        if not (self.source / 'main/xiaozhi-server/core/plugins/catalog.json').is_file():
            raise RuntimeError('需要插件中心版本的完整源码；可复用已解压的源码目录。')
        web_recipe = web_dockerfile(self.source)
        release = 'plugins-' + time.strftime('%Y%m%d-%H%M%S', time.gmtime()) + '-' + str(os.getpid())
        old_server = SERVER + ':rollback-' + release
        old_web = WEB + ':rollback-' + release
        new_server, new_web = SERVER + ':' + release, WEB + ':' + release
        docker(['image', 'tag', initial['containers'][SERVER]['Image'], old_server])
        docker(['image', 'tag', initial['containers'][WEB]['Image'], old_web])
        print('构建 Python 镜像：沿用现有 CPU 依赖，只补充插件依赖和应用代码。', flush=True)
        docker(['build', '--pull=false', '--build-arg', 'PLUGIN_BASE_IMAGE=' + old_server,
                '-f', '-', '-t', new_server, str(self.source)], capture=False, input_text=SERVER_DOCKERFILE)
        print('构建管理端镜像（前端单进程编译）。', flush=True)
        docker(['build', '--pull=false', '-f', '-', '-t', new_web, str(self.source)],
               capture=False, input_text=web_recipe)
        self.unchanged(initial)
        parent = self.directory / 'backups'
        if parent.is_symlink():
            raise RuntimeError('backups 是符号链接，请单独确认备份位置。')
        parent.mkdir(exist_ok=True)
        backup = Path(tempfile.mkdtemp(prefix=release + '-', dir=str(parent)))
        (backup / 'compose.before.json').write_bytes(initial['original'])
        if (self.directory / '.env').is_file():
            shutil.copyfile(str(self.directory / '.env'), str(backup / 'env.before'))
        print('备份配置和数据库：' + str(backup), flush=True)
        self.backup_runtime_config(initial['containers'][SERVER]['Id'], backup)
        self.backup_database(initial['containers'][DB]['Id'], backup / 'database.sql.gz')
        self.unchanged(initial)
        updated = json_bytes(with_images(initial['raw'], new_server, new_web))
        rollback = json_bytes(with_images(initial['raw'], old_server, old_web))
        (backup / 'compose.rollback.json').write_bytes(rollback)
        (backup / 'rollback-state.json').write_bytes(json_bytes({
            'project': self.project, 'file': str(self.file),
            'allowed_hashes': [digest(initial['original']), digest(updated), digest(rollback)]}))
        shutil.copyfile(str(Path(__file__).resolve()), str(backup / 'updater.py'))
        rollback_command = 'python3 {} --rollback {}'.format(
            shlex.quote(str(backup / 'updater.py')), shlex.quote(str(backup)))
        print('回滚命令：' + rollback_command, flush=True)
        try:
            atomic_write(self.file, updated)
            docker([*self.compose, 'config', '--quiet'])
            if self.file.read_bytes() != updated:
                raise RuntimeError('切换前配置被其他操作修改，已停止。')
            self.restart([WEB])
            web_id = self.wait_ready(WEB)
            table = docker(['exec', initial['containers'][DB]['Id'], 'sh', '-c', '''set -eu
export MYSQL_PWD="${MYSQL_ROOT_PASSWORD:?}"
exec mysql --user=root --batch --skip-column-names "${MYSQL_DATABASE:-xiaozhi_esp32_server}" -e "SHOW TABLES LIKE 'ai_agent_extension_config';"
''']).stdout.strip()
            if table != 'ai_agent_extension_config':
                raise RuntimeError('插件配置表未创建，请检查 Liquibase 日志。')
            docker(['exec', web_id, 'test', '-s', '/usr/share/nginx/html/digital-human/js/ui/plugin-image.js'])
            if self.file.read_bytes() != updated:
                raise RuntimeError('切换期间配置被其他操作修改，已停止。')
            self.restart([SERVER])
            self.wait_ready(SERVER)
        except BaseException:
            print('更新未完成，尝试恢复原应用镜像和配置。', file=sys.stderr, flush=True)
            try:
                restore(backup)
            except BaseException as restore_error:
                print('自动恢复未完成：{}。回滚命令：{}'.format(restore_error, rollback_command),
                      file=sys.stderr, flush=True)
            raise
        docker([*self.compose, 'ps', SERVER, WEB], capture=False)
        print('更新完成。Ctrl+F5 刷新智控台，进入“插件中心”。备份：' + str(backup), flush=True)


def restore(backup):
    backup = Path(backup).resolve()
    state = json.loads((backup / 'rollback-state.json').read_text(encoding='utf-8'))
    installation = Installation(state['project'], state['file'])
    if digest(installation.file.read_bytes()) not in state['allowed_hashes']:
        raise RuntimeError('配置后来被修改，已停止自动覆盖；请结合备份人工恢复。')
    atomic_write(installation.file, (backup / 'compose.rollback.json').read_bytes())
    docker([*installation.compose, 'config', '--quiet'])
    installation.restart([WEB, SERVER])
    installation.wait_ready(WEB, plugins=False)
    installation.wait_ready(SERVER, plugins=False)
    print('已恢复原应用镜像；数据库备份保留，未自动覆盖数据库。', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--apply', action='store_true')
    mode.add_argument('--rollback', metavar='BACKUP_DIRECTORY')
    parser.add_argument('--project')
    parser.add_argument('--file', dest='config_file')
    args = parser.parse_args()
    if not args.rollback and (not args.project or not args.config_file):
        parser.error('需要 --project 和 --file')
    os.umask(0o077)
    if args.apply or args.rollback:
        if not hasattr(os, 'geteuid') or os.geteuid() != 0:
            parser.error('更新和回滚需要 root，请使用 sudo python3。')
        import fcntl
        lock = open('/var/lock/xiaozhi-server-install.lock', 'a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('另一个安装或更新任务正在运行。')
        def interrupted(signum, frame):
            raise SystemExit(128 + signum)
        signal.signal(signal.SIGTERM, interrupted)
    try:
        if args.rollback:
            restore(args.rollback)
        else:
            installation = Installation(args.project, args.config_file)
            if args.apply:
                installation.apply()
            else:
                info = installation.inspect()
                print('项目：' + args.project)
                print('配置：' + str(installation.file))
                for service in (SERVER, WEB, DB):
                    print('{}：{}'.format(service, info['containers'][service]['Name'].lstrip('/')))
                print('检查通过。将保留原有端口、启动参数、网络和数据卷；未修改服务。')
    except (RuntimeError, ValueError, OSError, KeyError) as error:
        print('[xiaozhi] ' + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
