# CentOS Stream 9 部署

该部署入口运行“火山 API Key + Anthropic Messages 组合版”，适用于 CentOS Stream 9 的
`x86_64` 和 `aarch64` 服务器。

## 特点

- 使用 Docker Compose v2。
- 使用本仓库发布的固定版本镜像，不会意外切回官方镜像。
- Bind mount 添加 `:Z` 标签，兼容 SELinux Enforcing。
- 不会默认关闭 SELinux。
- 不会默认修改 firewalld。
- 已有配置与数据不会被脚本删除。
- 智控台 `8002` 默认只监听本机，避免第一个管理员被公网抢注。

## 快速部署

下载并检查脚本：

```bash
curl -fL \
  https://raw.githubusercontent.com/zjwlmq/xiaozhi-esp32-server/volc-anthropic-v1.0.0-rc.2/deploy/install.sh \
  -o /tmp/xiaozhi-install.sh

less /tmp/xiaozhi-install.sh
```

已经安装 Docker：

```bash
sudo bash /tmp/xiaozhi-install.sh
```

没有安装 Docker，并希望脚本按照 Docker 官方 RPM 仓库安装：

```bash
sudo env INSTALL_DOCKER=1 bash /tmp/xiaozhi-install.sh
```

如果需要同时开放本机 firewalld 的 `8000`、`8002`、`8003` TCP 端口：

```bash
sudo env OPEN_FIREWALL=1 bash /tmp/xiaozhi-install.sh
```

云服务器还需要在云平台安全组中开放所需端口。不要向公网开放 MySQL `3306` 和
Redis `6379`。首次注册管理员前不要向所有公网地址开放 `8002`。

Docker 发布端口可能不完全受 firewalld 的常规 INPUT 规则限制，公网暴露范围应以
云安全组或 `DOCKER-USER` 链再次限制。需要仅监听内网或本机时，可修改 `.env` 中的
`SERVER_BIND_ADDRESS`。

## 安装目录

默认安装到 `/opt/xiaozhi-server`：

```text
/opt/xiaozhi-server
├── .env
├── docker-compose.yml
├── data
│   └── .config.yaml
├── models
│   └── SenseVoiceSmall
│       └── model.pt
├── mysql
│   └── data
└── uploadfile
```

首次注册管理员时，在自己的电脑建立 SSH 隧道：

```bash
ssh -L 8002:127.0.0.1:8002 root@服务器IP
```

随后打开 `http://127.0.0.1:8002`。注册完成后，如确需公网访问，将服务器
`/opt/xiaozhi-server/.env` 中的 `MANAGER_BIND_ADDRESS` 改为 `0.0.0.0`，
并在云安全组中限制允许访问的来源 IP。

更换目录：

```bash
sudo env XIAOZHI_INSTALL_DIR=/data/xiaozhi-server \
  bash /tmp/xiaozhi-install.sh
```

## 已有服务器升级

升级时 `XIAOZHI_INSTALL_DIR` 必须指向旧版
`docker-compose_all.yml`、`mysql/data`、`data` 所在的同一个安装目录。若旧版不在默认
`/opt/xiaozhi-server`，请显式指定，例如：

```bash
sudo env XIAOZHI_INSTALL_DIR=/root/xiaozhi-server \
  bash /tmp/xiaozhi-install.sh
```

升级前至少备份：

```text
/opt/xiaozhi-server/data/.config.yaml
/opt/xiaozhi-server/uploadfile
/opt/xiaozhi-server/.env
```

数据库正常迁移应使用 [`mysqldump` 备份与恢复流程](../MIGRATION.md)，不要在线复制
`mysql/data`。

新安装固定使用 MySQL 8.4。若已有 MySQL 数据，脚本会：

1. 尝试读取旧 `docker-compose_all.yml` 中的 `MYSQL_ROOT_PASSWORD`。
2. 固定当前 MySQL 镜像的 digest，避免意外跨大版本升级。
3. 在旧数据库容器运行时创建 `mysqldump` 逻辑备份。

无法确定密码、原镜像或无法完成逻辑备份时，脚本会停止，不会用新环境覆盖旧数据。
只有已经确认拥有可用冷备份时，才可以设置
`SKIP_DATABASE_BACKUP=1` 跳过在线逻辑备份。

备份空间不足时，可将备份写入另一块磁盘：

```bash
sudo env XIAOZHI_BACKUP_DIR=/data/xiaozhi-backup \
  bash /tmp/xiaozhi-install.sh
```

## 查看状态

```bash
cd /opt/xiaozhi-server
docker compose --env-file .env -f docker-compose.yml ps
docker compose --env-file .env -f docker-compose.yml logs -f
```

## API Key

API Key 不写入 Compose 或源码。部署完成后，在智控台的火山双向流式 TTS 模型中
填写。曾经公开在聊天、截图或日志中的密钥应先在火山控制台重置。
