# 更换服务器与数据迁移

GitHub 只保存程序源码和部署文件，不会保存智控台中的账号、智能体、模型配置、
API Key 或上传文件。这些运行数据必须单独备份。

正常迁移请使用 MySQL 逻辑备份。不要在 MySQL 运行时直接复制 `mysql/data`；
物理数据目录只有在数据库完全停止，并且新旧 MySQL 版本和 CPU 架构兼容时才可能使用。

以下命令假设安装目录是 `/opt/xiaozhi-server`。如果实际目录不同，请先替换命令中的路径。

## 一、在旧服务器创建迁移包

```bash
sudo -i
INSTALL_DIR=/opt/xiaozhi-server
BACKUP_DIR=/root/xiaozhi-migration
install -d -m 0700 "$BACKUP_DIR"

MYSQL_ROOT_PASSWORD="$(
  sed -n 's/^MYSQL_ROOT_PASSWORD=//p' "$INSTALL_DIR/.env"
)"
test -n "$MYSQL_ROOT_PASSWORD"

docker exec \
  -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" \
  xiaozhi-esp32-server-db \
  mysqldump \
  --user=root \
  --single-transaction \
  --routines \
  --events \
  --databases xiaozhi_esp32_server |
  gzip > "$BACKUP_DIR/xiaozhi_esp32_server.sql.gz"

tar -C "$INSTALL_DIR" -czf "$BACKUP_DIR/runtime-files.tar.gz" \
  data uploadfile .env

chmod 0600 "$BACKUP_DIR"/*
sha256sum \
  "$BACKUP_DIR/xiaozhi_esp32_server.sql.gz" \
  "$BACKUP_DIR/runtime-files.tar.gz" \
  > "$BACKUP_DIR/SHA256SUMS"
unset MYSQL_ROOT_PASSWORD
```

确认两个归档不是空文件：

```bash
ls -lh "$BACKUP_DIR"
gzip -t "$BACKUP_DIR/xiaozhi_esp32_server.sql.gz"
tar -tzf "$BACKUP_DIR/runtime-files.tar.gz" | head
sha256sum -c "$BACKUP_DIR/SHA256SUMS"
```

迁移包包含数据库密码、server.secret、API Key 和其他敏感配置。只使用加密或可信通道传输，
不要上传到 GitHub、网盘公开链接或聊天群。

## 二、复制到新服务器

示例：

```bash
scp -r root@旧服务器IP:/root/xiaozhi-migration /root/
```

在新服务器校验：

```bash
cd /root/xiaozhi-migration
sha256sum -c SHA256SUMS
```

## 三、在新服务器恢复

先按对应系统的部署文档安装同一版本。安装器会创建新的 `.env` 和空数据库。
保留新服务器生成的 `.env`，不要用旧 `.env` 覆盖它。

```bash
sudo -i
INSTALL_DIR=/opt/xiaozhi-server
BACKUP_DIR=/root/xiaozhi-migration
cd "$INSTALL_DIR"

docker compose --env-file .env -f docker-compose.yml stop \
  xiaozhi-esp32-server \
  xiaozhi-esp32-server-web

MYSQL_ROOT_PASSWORD="$(
  sed -n 's/^MYSQL_ROOT_PASSWORD=//p' .env
)"
test -n "$MYSQL_ROOT_PASSWORD"

docker compose --env-file .env -f docker-compose.yml exec -T \
  -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" \
  xiaozhi-esp32-server-db \
  mysql --user=root \
  -e 'DROP DATABASE IF EXISTS xiaozhi_esp32_server;'

gunzip -c "$BACKUP_DIR/xiaozhi_esp32_server.sql.gz" |
  docker compose --env-file .env -f docker-compose.yml exec -T \
    -e MYSQL_PWD="$MYSQL_ROOT_PASSWORD" \
    xiaozhi-esp32-server-db \
    mysql --user=root

tar -xzf "$BACKUP_DIR/runtime-files.tar.gz" -C "$INSTALL_DIR" \
  data uploadfile
chmod 0640 "$INSTALL_DIR/data/.config.yaml"
unset MYSQL_ROOT_PASSWORD

docker compose --env-file .env -f docker-compose.yml up -d
```

新版本包含新的数据库迁移时，智控台第一次启动可能需要几分钟。验证：

```bash
curl -f \
  "http://127.0.0.1:8002/xiaozhi/user/captcha?uuid=migration-check" \
  -o /dev/null
curl http://127.0.0.1:8000/
docker compose --env-file .env -f docker-compose.yml ps
```

第二条命令应返回 `Server is running`。登录智控台后，再检查智能体、音色、API Key
和上传文件是否完整。确认无误前不要删除旧服务器和迁移包。
