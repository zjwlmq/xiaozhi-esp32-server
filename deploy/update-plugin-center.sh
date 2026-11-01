#!/usr/bin/env bash
# Update an existing deploy/install.sh installation from this source checkout.
set -Eeuo pipefail
umask 077

mode=${1:---check}
[[ "$mode" == --check || "$mode" == --apply ]] || { printf '用法：bash %s --check|--apply\n' "$0" >&2; exit 2; }
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
server=xiaozhi-esp32-server
web=xiaozhi-esp32-server-web
db=xiaozhi-esp32-server-db
die() {
    printf '[xiaozhi] %s\n' "$*" >&2
    if [[ "${changed:-0}" == 1 ]]; then on_failure 1; fi
    exit 1
}
for executable in docker python3 gzip flock; do
    command -v "$executable" >/dev/null || die "缺少命令：$executable"
done
docker compose version >/dev/null
[[ -f "$source_dir/main/xiaozhi-server/core/plugins/catalog.json" ]] || die '源码不完整，请下载整个提交的源码包。'

if [[ "$mode" == --apply ]]; then
    [[ "$EUID" == 0 ]] || die '更新时请使用 sudo。'
    exec 9>/var/lock/xiaozhi-server-install.lock
    flock -n 9 || die '另一个安装或更新任务正在运行。'
fi

project=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$server")
deploy_dir=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$server")
compose_file=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$server")
[[ "$project" =~ ^[a-zA-Z0-9_-]+$ && "$deploy_dir" == /* && -d "$deploy_dir" ]] || die '未识别到现有 Docker Compose 部署；未修改服务。'
[[ "$compose_file" != *,* && -f "$compose_file" && -f "$deploy_dir/.env" ]] || die '检测到多份 Compose 文件或没有 .env；此脚本不适用，未修改服务。'
deploy_dir=$(cd -- "$deploy_dir" && pwd -P)
case "$deploy_dir" in /|/root|/home|/opt|/etc|/var) die '部署目录不是专用子目录，已停止。';; esac
python3 - "$deploy_dir" "$compose_file" <<'PY'
import sys
from pathlib import Path
root=Path(sys.argv[1]).resolve()
for path in (Path(sys.argv[2]), root/'.env'):
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise SystemExit('配置路径不在部署目录内，或使用了符号链接；未修改服务。')
PY
grep -qF '${XIAOZHI_SERVER_IMAGE' "$compose_file" && grep -qF '${XIAOZHI_WEB_IMAGE' "$compose_file" || die 'Compose 使用固定镜像或其他格式；请提供部署检查输出，未修改服务。'
for container in "$server" "$web" "$db"; do
    [[ $(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$container") == "$project" ]] || die "容器不属于同一项目：$container"
    [[ $(docker inspect -f '{{.State.Running}}' "$container") == true ]] || die "请先确认原容器正在运行：$container"
done

cd -- "$deploy_dir"
compose=(docker compose --project-directory "$deploy_dir" -p "$project" --env-file "$deploy_dir/.env" -f "$compose_file")
"${compose[@]}" config --quiet
images=$("${compose[@]}" config --format json | python3 -c '
import json,sys
services=json.load(sys.stdin)["services"]
for name in ("xiaozhi-esp32-server","xiaozhi-esp32-server-web"):
    print(services[name]["image"])
')
mapfile -t old_images <<< "$images"
old_server_id=$(docker inspect -f '{{.Image}}' "$server")
old_web_id=$(docker inspect -f '{{.Image}}' "$web")
[[ $(docker image inspect -f '{{.Id}}' "${old_images[0]}") == "$old_server_id" ]] || die '配置与正在运行的 Python 镜像不同，已停止。'
[[ $(docker image inspect -f '{{.Id}}' "${old_images[1]}") == "$old_web_id" ]] || die '配置与正在运行的管理端镜像不同，已停止。'
printf '已识别部署目录：%s\nCompose：%s\n项目：%s\nPython 镜像：%s\n管理端镜像：%s\n' "$deploy_dir" "$compose_file" "$project" "${old_images[0]}" "${old_images[1]}"
if [[ "$mode" == --check ]]; then
    printf '检查通过，未修改配置或容器。可使用 --apply 构建并更新。\n'
    exit 0
fi

release="plugin-center-$(date -u +%Y%m%d-%H%M%S)-$$"
server_image="xiaozhi-esp32-server:$release"
web_image="xiaozhi-esp32-server-web:$release"
before_config=$("${compose[@]}" config --hash '*')
docker build -f "$source_dir/Dockerfile-server" -t "$server_image" "$source_dir"
docker build -f "$source_dir/Dockerfile-web" -t "$web_image" "$source_dir"
[[ $("${compose[@]}" config --hash '*') == "$before_config" ]] || die '构建期间部署配置已变化；未切换服务，请重新检查。'
[[ $(docker inspect -f '{{.Image}}' "$server") == "$old_server_id" && $(docker inspect -f '{{.Image}}' "$web") == "$old_web_id" ]] || die '构建期间运行版本已变化；未切换服务。'

mkdir -p -- "$deploy_dir/backups"
backup_dir=$(mktemp -d "$deploy_dir/backups/$release-XXXXXX")
cp -p -- "$deploy_dir/.env" "$backup_dir/env.before"
cp -p -- "$compose_file" "$backup_dir/compose.before.yml"
if [[ -f "$deploy_dir/data/.config.yaml" ]]; then
    cp -p -- "$deploy_dir/data/.config.yaml" "$backup_dir/runtime-config.before.yaml"
fi
printf '备份数据库到：%s\n' "$backup_dir/database.sql.gz"
docker exec "$db" sh -c '
set -eu
export MYSQL_PWD="${MYSQL_ROOT_PASSWORD:?数据库容器未提供 MYSQL_ROOT_PASSWORD，备份中止}"
exec mysqldump --user=root --single-transaction --routines --triggers --events \
    --set-gtid-purged=OFF --no-tablespaces --databases "${MYSQL_DATABASE:-xiaozhi_esp32_server}"
' | gzip > "$backup_dir/database.sql.gz"
gzip -t "$backup_dir/database.sql.gz"

docker image tag "$old_server_id" "xiaozhi-esp32-server:rollback-$release"
docker image tag "$old_web_id" "xiaozhi-esp32-server-web:rollback-$release"
cat > "$backup_dir/set_images.py" <<'PY'
import os,re,stat,sys,tempfile
from pathlib import Path
path=Path(sys.argv[1])
original=path.stat()
content=path.read_text(encoding='utf-8')
content=re.sub(r'(?m)^\s*(?:export\s+)?(?:XIAOZHI_SERVER_IMAGE|XIAOZHI_WEB_IMAGE)\s*=.*(?:\n|$)','',content).rstrip('\n')+'\n'
content+=f'XIAOZHI_SERVER_IMAGE={sys.argv[2]}\nXIAOZHI_WEB_IMAGE={sys.argv[3]}\n'
temporary=None
try:
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.env.plugins-',delete=False) as out:
        out.write(content)
        temporary=out.name
    os.chmod(temporary,stat.S_IMODE(original.st_mode))
    os.chown(temporary,original.st_uid,original.st_gid)
    os.replace(temporary,path)
    temporary=None
finally:
    if temporary is not None: os.unlink(temporary)
PY
{
    printf '#!/usr/bin/env bash\nset -Eeuo pipefail\numask 077\n'
    printf 'cp -p -- %q %q\n' "$backup_dir/env.before" "$deploy_dir/.env"
    printf 'python3 %q %q %q %q\n' "$backup_dir/set_images.py" "$deploy_dir/.env" "xiaozhi-esp32-server:rollback-$release" "xiaozhi-esp32-server-web:rollback-$release"
    printf 'export XIAOZHI_SERVER_IMAGE=%q XIAOZHI_WEB_IMAGE=%q\n' "xiaozhi-esp32-server:rollback-$release" "xiaozhi-esp32-server-web:rollback-$release"
    printf '%q ' "${compose[@]}"
    printf 'up -d --no-deps --pull never --force-recreate %q %q\n' "$web" "$server"
    printf 'printf %q\n' '已恢复旧镜像和原配置；数据库备份保留，未自动覆盖数据库。\n'
} > "$backup_dir/rollback.sh"
chmod 700 "$backup_dir/rollback.sh"

changed=0
on_failure() {
    result=$1
    trap - ERR INT TERM
    if [[ "$changed" == 1 ]]; then
        printf '更新未完成，尝试恢复旧镜像。\n' >&2
        bash "$backup_dir/rollback.sh" || printf '请手动执行回滚脚本：%s/rollback.sh\n' "$backup_dir" >&2
    fi
    exit "$result"
}
trap 'on_failure $?' ERR
trap 'on_failure 130' INT
trap 'on_failure 143' TERM
changed=1
python3 "$backup_dir/set_images.py" "$deploy_dir/.env" "$server_image" "$web_image"
export XIAOZHI_SERVER_IMAGE="$server_image" XIAOZHI_WEB_IMAGE="$web_image"
"${compose[@]}" config --quiet
"${compose[@]}" up -d --no-deps --pull never --force-recreate "$web"
api_ready=0
for attempt in {1..60}; do
    if docker exec "$web" wget -q -O /dev/null http://127.0.0.1:8002/xiaozhi/user/pub-config; then
        api_ready=1
        break
    fi
    sleep 5
done
[[ "$api_ready" == 1 ]] || die '管理端未就绪，请查看容器日志。'
table=$(docker exec "$db" sh -c '
set -eu
export MYSQL_PWD="${MYSQL_ROOT_PASSWORD:?}"
exec mysql --user=root --batch --skip-column-names "${MYSQL_DATABASE:-xiaozhi_esp32_server}" \
    -e "SHOW TABLES LIKE '\''ai_agent_extension_config'\'';"
')
[[ "$table" == ai_agent_extension_config ]] || die '插件配置表尚未创建，请检查 Liquibase 日志。'
"${compose[@]}" up -d --no-deps --pull never --force-recreate "$server"
server_ready=0
for attempt in {1..60}; do
    if docker exec "$server" python -c 'import socket; from core.plugins.runtime import PluginRuntime; socket.create_connection(("127.0.0.1",8000),timeout=2).close()' >/dev/null 2>&1; then
        server_ready=1
        break
    fi
    sleep 5
done
[[ "$server_ready" == 1 ]] || die 'Python 服务未就绪，请查看容器日志。'
docker exec "$web" test -s /usr/share/nginx/html/digital-human/js/ui/plugin-image.js
trap - ERR INT TERM
"${compose[@]}" ps "$server" "$web"
printf '\n更新完成。刷新智控台，进入“插件中心”。\n备份：%s\n回滚命令：sudo bash %q/rollback.sh\n' "$backup_dir" "$backup_dir"
