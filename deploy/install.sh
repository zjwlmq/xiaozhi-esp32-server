#!/usr/bin/env bash
set -Eeuo pipefail

RELEASE_TAG="${XIAOZHI_RELEASE_TAG:-volc-anthropic-v1.0.0-rc.6}"
REPOSITORY="${XIAOZHI_REPOSITORY:-zjwlmq/xiaozhi-esp32-server}"
INSTALL_DIR="${XIAOZHI_INSTALL_DIR:-/opt/xiaozhi-server}"
BACKUP_ROOT_INPUT="${XIAOZHI_BACKUP_DIR:-}"
IMAGE_VERSION="${XIAOZHI_IMAGE_VERSION:-${RELEASE_TAG#volc-anthropic-v}}"
INSTALL_DOCKER="${INSTALL_DOCKER:-0}"
OPEN_FIREWALL="${OPEN_FIREWALL:-0}"
SKIP_DATABASE_BACKUP="${SKIP_DATABASE_BACKUP:-0}"
STARTUP_TIMEOUT="${XIAOZHI_STARTUP_TIMEOUT:-300}"
RAW_BASE="https://raw.githubusercontent.com/${REPOSITORY}/${RELEASE_TAG}"
MODEL_URL="https://modelscope.cn/models/iic/SenseVoiceSmall/resolve/master/model.pt"
SERVER_IMAGE="ghcr.io/${REPOSITORY}:server_volc-anthropic-${IMAGE_VERSION}"
WEB_IMAGE="ghcr.io/${REPOSITORY}:web_volc-anthropic-${IMAGE_VERSION}"

log() {
    printf '[xiaozhi] %s\n' "$*"
}

die() {
    printf '[xiaozhi] 错误：%s\n' "$*" >&2
    exit 1
}

require_root() {
    if [[ "${EUID}" -ne 0 ]]; then
        die "请使用 root 执行，或在命令前加 sudo。"
    fi
}

validate_install_dir() {
    local canonical_dir
    local canonical_backup_root

    command -v realpath >/dev/null 2>&1 ||
        die "系统缺少 realpath（通常由 coreutils 提供）。"
    [[ "${INSTALL_DIR}" == /* ]] ||
        die "XIAOZHI_INSTALL_DIR 必须是绝对路径。"

    canonical_dir="$(realpath -m -- "${INSTALL_DIR}")"
    case "${canonical_dir}" in
        / | /boot | /boot/* | /dev | /dev/* | /etc | /etc/* | /home | /opt | \
        /proc | /proc/* | /root | /run | /run/* | /sys | /sys/* | /usr | /usr/* | \
        /var)
            die "安装目录范围过大，请使用专用子目录，例如 /opt/xiaozhi-server。"
            ;;
    esac
    INSTALL_DIR="${canonical_dir}"

    if [[ -n "${BACKUP_ROOT_INPUT}" ]]; then
        [[ "${BACKUP_ROOT_INPUT}" == /* ]] ||
            die "XIAOZHI_BACKUP_DIR 必须是绝对路径。"
        canonical_backup_root="$(realpath -m -- "${BACKUP_ROOT_INPUT}")"
    else
        canonical_backup_root="${INSTALL_DIR}/backup"
    fi

    case "${canonical_backup_root}" in
        / | /boot | /boot/* | /dev | /dev/* | /etc | /etc/* | /home | /opt | \
        /proc | /proc/* | /root | /run | /run/* | /sys | /sys/* | /usr | /usr/* | \
        /var)
            die "备份目录范围过大，请使用专用子目录。"
            ;;
    esac
    BACKUP_ROOT="${canonical_backup_root}"

    [[ "${REPOSITORY}" =~ ^[0-9A-Za-z_.-]+/[0-9A-Za-z_.-]+$ ]] ||
        die "XIAOZHI_REPOSITORY 格式无效。"
    [[ "${RELEASE_TAG}" =~ ^[0-9A-Za-z][0-9A-Za-z._-]*$ ]] ||
        die "XIAOZHI_RELEASE_TAG 格式无效。"
    [[ "${IMAGE_VERSION}" =~ ^[0-9A-Za-z][0-9A-Za-z._-]*$ ]] ||
        die "XIAOZHI_IMAGE_VERSION 格式无效。"
    [[ "${STARTUP_TIMEOUT}" =~ ^[1-9][0-9]*$ ]] ||
        die "XIAOZHI_STARTUP_TIMEOUT 必须是正整数秒。"
}

acquire_lock() {
    command -v flock >/dev/null 2>&1 ||
        die "系统缺少 flock（通常由 util-linux 提供）。"
    exec 9> /var/lock/xiaozhi-server-install.lock
    flock -n 9 || die "另一个小智安装或升级任务正在运行。"
}

detect_profile() {
    [[ -r /etc/os-release ]] || die "无法读取 /etc/os-release。"
    # shellcheck disable=SC1091
    source /etc/os-release

    case "${ID:-}" in
        centos)
            [[ "${VERSION_ID%%.*}" == "9" ]] ||
                die "CentOS 部署入口仅支持 CentOS Stream 9。"
            PROFILE="centos-stream-9"
            ;;
        ubuntu)
            case "${VERSION_ID:-}" in
                22.04 | 24.04) PROFILE="ubuntu" ;;
                *) die "Ubuntu 部署入口仅验证过 22.04 和 24.04。" ;;
            esac
            ;;
        *)
            die "当前仅支持 CentOS Stream 9、Ubuntu 22.04/24.04。"
            ;;
    esac

    case "$(uname -m)" in
        x86_64 | aarch64) ;;
        *) die "当前镜像不支持架构：$(uname -m)。" ;;
    esac
}

install_prerequisites() {
    local missing=()
    command -v curl >/dev/null 2>&1 || missing+=(curl)
    command -v openssl >/dev/null 2>&1 || missing+=(openssl)

    if (( ${#missing[@]} == 0 )); then
        return
    fi

    if [[ "${PROFILE}" == "centos-stream-9" ]]; then
        dnf -y install ca-certificates "${missing[@]}"
    else
        apt-get update
        DEBIAN_FRONTEND=noninteractive apt-get install -y ca-certificates "${missing[@]}"
    fi
}

install_docker_on_centos() {
    log "按照 Docker 官方 RPM 仓库安装 Docker Engine 与 Compose v2。"
    dnf -y install dnf-plugins-core
    dnf config-manager --add-repo \
        https://download.docker.com/linux/centos/docker-ce.repo
    dnf -y install \
        docker-ce \
        docker-ce-cli \
        containerd.io \
        docker-buildx-plugin \
        docker-compose-plugin
    systemctl enable --now docker
}

ensure_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        if [[ "${PROFILE}" == "centos-stream-9" && "${INSTALL_DOCKER}" == "1" ]]; then
            install_docker_on_centos
        else
            die "没有检测到 Docker。请先安装 Docker，或在 CentOS 上设置 INSTALL_DOCKER=1 后重试。"
        fi
    fi

    if docker --version 2>&1 | grep -qi 'podman'; then
        die "检测到 podman-docker 兼容命令。该部署仅验证 Docker Engine，请先移除兼容包装并安装 Docker CE。"
    fi

    if ! docker compose version >/dev/null 2>&1; then
        if [[ "${PROFILE}" == "centos-stream-9" && "${INSTALL_DOCKER}" == "1" ]]; then
            install_docker_on_centos
        else
            die "没有检测到 Docker Compose v2（docker compose）。"
        fi
    fi

    if ! docker info >/dev/null 2>&1; then
        if command -v systemctl >/dev/null 2>&1; then
            systemctl enable --now docker
        fi
        docker info >/dev/null 2>&1 || die "Docker 服务未运行。"
    fi
}

download() {
    local url="$1"
    local destination="$2"
    curl \
        --fail \
        --location \
        --retry 3 \
        --connect-timeout 20 \
        --output "${destination}" \
        "${url}"
}

prepare_directories() {
    install -d -m 0755 \
        "${INSTALL_DIR}" \
        "${INSTALL_DIR}/data" \
        "${INSTALL_DIR}/models/SenseVoiceSmall" \
        "${INSTALL_DIR}/uploadfile" \
        "${INSTALL_DIR}/mysql/data"
    install -d -m 0700 "${BACKUP_ROOT}"
}

read_previous_mysql_password() {
    local previous_compose="${INSTALL_DIR}/docker-compose_all.yml"
    local candidate=""

    if [[ -f "${previous_compose}" ]]; then
        candidate="$(
            sed -n \
                's/^[[:space:]]*-[[:space:]]*MYSQL_ROOT_PASSWORD=//p' \
                "${previous_compose}" |
                head -n 1
        )"
    fi

    if [[ "${candidate}" =~ ^[0-9A-Za-z._-]+$ ]]; then
        PREVIOUS_MYSQL_PASSWORD="${candidate}"
    else
        PREVIOUS_MYSQL_PASSWORD=""
    fi
}

detect_existing_mysql_data() {
    MYSQL_DATA_EXISTS=0
    if [[ -n "$(find "${INSTALL_DIR}/mysql/data" -mindepth 1 -print -quit)" ]]; then
        MYSQL_DATA_EXISTS=1
    fi
}

resolve_existing_mysql_image() {
    local image_id=""
    local image_digest=""

    if docker inspect xiaozhi-esp32-server-db >/dev/null 2>&1; then
        image_id="$(
            docker inspect \
                --format '{{.Image}}' \
                xiaozhi-esp32-server-db
        )"
    fi

    if [[ -n "${image_id}" ]]; then
        image_digest="$(
            docker image inspect \
                --format '{{if .RepoDigests}}{{index .RepoDigests 0}}{{end}}' \
                "${image_id}"
        )"
    fi

    [[ -n "${image_digest}" ]] ||
        die "检测到已有 MySQL 数据，但无法确定原镜像摘要。请先备份并在 .env 中手工设置 MYSQL_IMAGE。"
    EXISTING_MYSQL_IMAGE="${image_digest}"
}

upsert_environment_value() {
    local env_file="$1"
    local key="$2"
    local value="$3"
    local staged_file="${env_file}.new"
    local temporary_file

    temporary_file="$(mktemp)"
    TEMPORARY_FILES+=("${temporary_file}")
    TEMPORARY_FILES+=("${staged_file}")
    awk -v key="${key}" -v value="${value}" '
        BEGIN { updated = 0 }
        index($0, key "=") == 1 {
            if (!updated) {
                print key "=" value
                updated = 1
            }
            next
        }
        { print }
        END {
            if (!updated) {
                print key "=" value
            }
        }
    ' "${env_file}" > "${temporary_file}"
    install -m 0600 "${temporary_file}" "${staged_file}"
    mv -f "${staged_file}" "${env_file}"
}

read_environment_value() {
    local env_file="$1"
    local key="$2"

    awk -v key="${key}" '
        index($0, key "=") == 1 {
            print substr($0, length(key) + 2)
            exit
        }
    ' "${env_file}"
}

prepare_environment_file() {
    local env_file="${INSTALL_DIR}/.env"
    local mysql_image="mysql:8.4"
    local password=""
    local staged_file="${env_file}.new"
    local temporary_file

    detect_existing_mysql_data
    if [[ -f "${env_file}" ]]; then
        password="$(read_environment_value "${env_file}" MYSQL_ROOT_PASSWORD)"
        [[ -n "${password}" ]] ||
            die "${env_file} 中的 MYSQL_ROOT_PASSWORD 不能为空。"
        if [[ "${MYSQL_DATA_EXISTS}" == "1" ]]; then
            mysql_image="$(read_environment_value "${env_file}" MYSQL_IMAGE)"
            [[ -n "${mysql_image}" ]] ||
                die "已有 MySQL 数据时，${env_file} 必须填写固定的 MYSQL_IMAGE。"
            [[ "${mysql_image}" != *:latest ]] ||
                die "已有 MySQL 数据时不能使用 MYSQL_IMAGE=:latest，请填写原来的固定版本或镜像摘要。"
        fi
        chmod 0600 "${env_file}"
        upsert_environment_value \
            "${env_file}" \
            XIAOZHI_SERVER_IMAGE \
            "${SERVER_IMAGE}"
        upsert_environment_value \
            "${env_file}" \
            XIAOZHI_WEB_IMAGE \
            "${WEB_IMAGE}"
        return
    fi

    read_previous_mysql_password
    if [[ -n "${PREVIOUS_MYSQL_PASSWORD}" ]]; then
        password="${PREVIOUS_MYSQL_PASSWORD}"
        log "沿用旧 Compose 中的 MySQL 密码。"
    elif [[ "${MYSQL_DATA_EXISTS}" == "1" ]]; then
        die "检测到已有 MySQL 数据但无法确定密码。请先创建 ${env_file}，写入 MYSQL_ROOT_PASSWORD=原密码。"
    else
        password="$(openssl rand -hex 16)"
        log "已为新安装生成随机 MySQL 密码。"
    fi

    if [[ "${MYSQL_DATA_EXISTS}" == "1" ]]; then
        resolve_existing_mysql_image
        mysql_image="${EXISTING_MYSQL_IMAGE}"
        log "已固定沿用现有 MySQL 镜像摘要，避免跨版本升级。"
    fi

    umask 077
    temporary_file="$(mktemp)"
    TEMPORARY_FILES+=("${temporary_file}")
    TEMPORARY_FILES+=("${staged_file}")
    {
        printf 'MYSQL_ROOT_PASSWORD=%s\n' "${password}"
        printf 'MYSQL_IMAGE=%s\n' "${mysql_image}"
        printf 'XIAOZHI_SERVER_IMAGE=%s\n' "${SERVER_IMAGE}"
        printf 'XIAOZHI_WEB_IMAGE=%s\n' "${WEB_IMAGE}"
        printf 'SERVER_BIND_ADDRESS=0.0.0.0\n'
        printf 'MANAGER_BIND_ADDRESS=127.0.0.1\n'
    } > "${temporary_file}"
    install -m 0600 "${temporary_file}" "${staged_file}"
    mv -f "${staged_file}" "${env_file}"
}

backup_deployment_files() {
    local timestamp
    local backup_dir
    local path

    timestamp="$(date +%Y%m%d-%H%M%S)"
    backup_dir="${BACKUP_ROOT}/${timestamp}"
    BACKUP_DIR="${backup_dir}"
    install -d -m 0700 "${backup_dir}"

    for path in \
        "${INSTALL_DIR}/docker-compose.yml" \
        "${INSTALL_DIR}/docker-compose_all.yml" \
        "${INSTALL_DIR}/data/.config.yaml" \
        "${INSTALL_DIR}/.env"; do
        if [[ -f "${path}" ]]; then
            cp -a "${path}" "${backup_dir}/"
        fi
    done
}

ensure_backup_space() {
    local available_bytes
    local database_bytes
    local required_bytes

    database_bytes="$(
        du -sb "${INSTALL_DIR}/mysql/data" |
            awk '{print $1}'
    )"
    available_bytes="$(
        df -P -B1 "${BACKUP_ROOT}" |
            awk 'NR == 2 {print $4}'
    )"
    [[ "${database_bytes}" =~ ^[0-9]+$ && "${available_bytes}" =~ ^[0-9]+$ ]] ||
        die "无法检查数据库备份所需磁盘空间。"

    required_bytes=$((database_bytes + 536870912))
    if (( available_bytes < required_bytes )); then
        die "备份空间不足。请清理磁盘，或通过 XIAOZHI_BACKUP_DIR 指定其他磁盘上的目录。"
    fi
}

backup_running_database() {
    local password
    local running_container
    local backup_file
    local partial_file

    [[ "${MYSQL_DATA_EXISTS}" == "1" ]] || return 0

    running_container="$(
        docker ps \
            --filter name='^/xiaozhi-esp32-server-db$' \
            --format '{{.Names}}'
    )"
    if [[ "${running_container}" != "xiaozhi-esp32-server-db" ]]; then
        if [[ "${SKIP_DATABASE_BACKUP}" == "1" ]]; then
            log "警告：已按要求跳过 MySQL 逻辑备份。"
            return
        fi
        die "已有 MySQL 数据但数据库容器未运行。请先启动旧服务完成备份，或确认已有冷备份后设置 SKIP_DATABASE_BACKUP=1。"
    fi

    password="$(
        read_environment_value "${INSTALL_DIR}/.env" MYSQL_ROOT_PASSWORD
    )"
    [[ -n "${password}" ]] || die "无法读取 MySQL 密码用于备份。"

    ensure_backup_space
    install -d -m 0700 "${BACKUP_DIR}"
    backup_file="${BACKUP_DIR}/xiaozhi_esp32_server.sql.gz"
    partial_file="${backup_file}.partial"
    TEMPORARY_FILES+=("${partial_file}")
    log "正在创建 MySQL 逻辑备份。"
    docker exec \
        -e MYSQL_PWD="${password}" \
        xiaozhi-esp32-server-db \
        mysqldump \
        --user=root \
        --single-transaction \
        --routines \
        --events \
        --databases xiaozhi_esp32_server |
        gzip > "${partial_file}"

    [[ -s "${partial_file}" ]] ||
        die "MySQL 逻辑备份为空，已停止升级。"
    mv "${partial_file}" "${backup_file}"
    log "数据库备份完成：${backup_file}"
}

install_compose_file() {
    local staged_file="${INSTALL_DIR}/.docker-compose.yml.new"
    local temporary_file

    temporary_file="$(mktemp)"
    TEMPORARY_FILES+=("${temporary_file}")
    TEMPORARY_FILES+=("${staged_file}")

    download \
        "${RAW_BASE}/deploy/${PROFILE}/docker-compose.yml" \
        "${temporary_file}"
    docker compose \
        --env-file "${INSTALL_DIR}/.env" \
        --project-directory "${INSTALL_DIR}" \
        -f "${temporary_file}" \
        config \
        --quiet
    install -m 0644 "${temporary_file}" "${staged_file}"
    mv -f "${staged_file}" "${INSTALL_DIR}/docker-compose.yml"
}

prepare_config() {
    local config_file="${INSTALL_DIR}/data/.config.yaml"
    local rendered_file
    local staged_file="${config_file}.new"
    local temporary_file

    if [[ -d "${config_file}" ]]; then
        die "${config_file} 当前是目录而不是配置文件。请先将该目录移出安装路径后重试。"
    fi
    [[ -f "${config_file}" && -s "${config_file}" ]] && return

    temporary_file="$(mktemp)"
    rendered_file="$(mktemp)"
    TEMPORARY_FILES+=("${temporary_file}")
    TEMPORARY_FILES+=("${rendered_file}")
    TEMPORARY_FILES+=("${staged_file}")
    download \
        "${RAW_BASE}/main/xiaozhi-server/config_from_api.yaml" \
        "${temporary_file}"
    sed \
        's#url: http://127.0.0.1:8002/xiaozhi#url: http://xiaozhi-esp32-server-web:8002/xiaozhi#' \
        "${temporary_file}" > "${rendered_file}"
    grep -q \
        'url: http://xiaozhi-esp32-server-web:8002/xiaozhi' \
        "${rendered_file}" ||
        die "生成的配置文件缺少 Docker 内部管理端地址。"
    grep -q 'secret:' "${rendered_file}" ||
        die "生成的配置文件缺少 manager-api.secret。"
    install -m 0640 "${rendered_file}" "${staged_file}"
    mv -f "${staged_file}" "${config_file}"
}

prepare_model() {
    local model_file="${INSTALL_DIR}/models/SenseVoiceSmall/model.pt"
    local partial_file="${model_file}.part"

    if [[ -d "${model_file}" ]]; then
        die "${model_file} 当前是目录而不是模型文件。请先将该目录移出安装路径后重试。"
    fi
    [[ -f "${model_file}" && -s "${model_file}" ]] && return

    log "正在下载 SenseVoiceSmall 模型，文件较大，请耐心等待。"
    rm -f "${partial_file}"
    download "${MODEL_URL}" "${partial_file}"
    if [[ "$(stat -c '%s' "${partial_file}")" -lt 1048576 ]]; then
        die "模型文件下载结果异常（小于 1 MiB）。"
    fi
    mv "${partial_file}" "${model_file}"
}

configure_firewall() {
    local port

    [[ "${PROFILE}" == "centos-stream-9" ]] || return 0
    command -v firewall-cmd >/dev/null 2>&1 || return 0
    firewall-cmd --state >/dev/null 2>&1 || return 0

    if [[ "${OPEN_FIREWALL}" == "1" ]]; then
        for port in 8000 8002 8003; do
            firewall-cmd --permanent --add-port="${port}/tcp"
        done
        firewall-cmd --reload
        log "已开放 TCP 端口 8000、8002、8003。"
    else
        log "firewalld 正在运行，但脚本未自动开放端口。"
        log "确认安全组后，可设置 OPEN_FIREWALL=1 重新运行脚本。"
    fi
}

compose_command() {
    docker compose \
        --env-file "${INSTALL_DIR}/.env" \
        --project-directory "${INSTALL_DIR}" \
        -f "${INSTALL_DIR}/docker-compose.yml" \
        "$@"
}

config_needs_manager_secret() {
    local manager_secret

    manager_secret="$(
        awk '
            /^manager-api:[[:space:]]*$/ {
                in_manager_api = 1
                next
            }
            in_manager_api && /^[^[:space:]#]/ {
                exit
            }
            in_manager_api && /^[[:space:]]*secret:[[:space:]]*/ {
                sub(/^[[:space:]]*secret:[[:space:]]*/, "")
                print
                exit
            }
        ' "${INSTALL_DIR}/data/.config.yaml"
    )"
    [[ -z "${manager_secret}" || "${manager_secret}" == *你* ]]
}

wait_for_manager_api() {
    local deadline=$((SECONDS + STARTUP_TIMEOUT))
    local url="http://127.0.0.1:8002/xiaozhi/user/captcha?uuid=xiaozhi-release-check"

    log "等待智控台后端与数据库迁移完成。"
    while (( SECONDS < deadline )); do
        if curl \
            --fail \
            --silent \
            --max-time 3 \
            --output /dev/null \
            "${url}"; then
            return
        fi
        sleep 3
    done

    compose_command ps || true
    die "智控台未在 ${STARTUP_TIMEOUT} 秒内就绪。部署文件备份位于 ${BACKUP_DIR}。"
}

wait_for_xiaozhi_server() {
    local deadline=$((SECONDS + STARTUP_TIMEOUT))
    local response

    log "等待小智 WebSocket 服务就绪。"
    while (( SECONDS < deadline )); do
        response="$(
            curl \
                --fail \
                --silent \
                --show-error \
                --max-time 3 \
                http://127.0.0.1:8000/ 2>/dev/null ||
                true
        )"
        if [[ "${response}" == *"Server is running"* ]]; then
            return
        fi
        sleep 3
    done

    compose_command ps || true
    die "小智服务未在 ${STARTUP_TIMEOUT} 秒内就绪。请检查 .config.yaml 和容器日志；备份位于 ${BACKUP_DIR}。"
}

start_stack() {
    compose_command config --quiet
    compose_command pull

    if config_needs_manager_secret; then
        FIRST_RUN_NEEDS_SECRET=1
        if ! compose_command up -d \
            xiaozhi-esp32-server-db \
            xiaozhi-esp32-server-redis \
            xiaozhi-esp32-server-web; then
            compose_command ps || true
            die "智控台启动失败；原部署文件已备份到 ${BACKUP_DIR}。"
        fi
        compose_command stop xiaozhi-esp32-server >/dev/null 2>&1 || true
    else
        FIRST_RUN_NEEDS_SECRET=0
        if ! compose_command up -d; then
            compose_command ps || true
            die "服务启动失败；原部署文件已备份到 ${BACKUP_DIR}。"
        fi
    fi

    wait_for_manager_api
    if [[ "${FIRST_RUN_NEEDS_SECRET}" == "0" ]]; then
        wait_for_xiaozhi_server
    else
        log "智控台已经就绪；小智服务将在填写 server.secret 后启动。"
    fi
    compose_command ps
}

print_next_steps() {
    cat <<EOF

部署文件已安装到：${INSTALL_DIR}

下一步：
1. 为避免首个管理员被抢注，8002 默认只监听 127.0.0.1；首次安装时小智服务会先保持停止。
2. 在自己电脑建立 SSH 隧道：
   ssh -L 8002:127.0.0.1:8002 root@服务器IP
3. 打开 http://127.0.0.1:8002 并注册第一个管理员。
4. 在参数管理中复制 server.secret。
5. 编辑 ${INSTALL_DIR}/data/.config.yaml，填写该 secret。
6. 如需公网访问智控台，将 ${INSTALL_DIR}/.env 中
   MANAGER_BIND_ADDRESS 改为 0.0.0.0，并限制云安全组来源 IP。
7. 在智控台模型配置中填写火山 API Key；如需使用 Anthropic Messages，再新增
   Anthropic 协议模型并填写中转站地址、模型名和密钥。任何密钥都不要提交到 GitHub。
8. 重启服务：
   cd ${INSTALL_DIR}
   docker compose --env-file .env -f docker-compose.yml up -d
9. 验证小智服务：
   curl http://127.0.0.1:8000/

正常迁移数据库请使用 mysqldump，不要在线复制 mysql/data。
完整迁移步骤请查看仓库 deploy/MIGRATION.md。
EOF
}

cleanup() {
    local path
    for path in "${TEMPORARY_FILES[@]:-}"; do
        [[ -n "${path}" ]] && rm -f "${path}"
    done
}

main() {
    TEMPORARY_FILES=()
    trap cleanup EXIT

    require_root
    validate_install_dir
    umask 077
    acquire_lock
    detect_profile
    install_prerequisites
    ensure_docker
    prepare_directories
    backup_deployment_files
    prepare_environment_file
    backup_running_database
    install_compose_file
    prepare_config
    prepare_model
    configure_firewall
    start_stack
    print_next_steps
}

main "$@"
