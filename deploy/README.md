# Docker 部署入口

本目录用于部署“火山 API Key + Anthropic Messages 组合版”。两个系统使用相同的程序镜像，只在宿主机
安装方式和 SELinux 挂载设置上有所区别。

| 系统 | 部署说明 | Compose 文件 |
| --- | --- | --- |
| CentOS Stream 9 | [查看说明](./centos-stream-9/README.md) | [docker-compose.yml](./centos-stream-9/docker-compose.yml) |
| Ubuntu 22.04/24.04 | [查看说明](./ubuntu/README.md) | [docker-compose.yml](./ubuntu/docker-compose.yml) |

两个 Compose 文件固定使用本仓库发布的 `1.0.0-rc.7` 候选镜像：

- `ghcr.io/zjwlmq/xiaozhi-esp32-server:server_volc-anthropic-1.0.0-rc.7`
- `ghcr.io/zjwlmq/xiaozhi-esp32-server:web_volc-anthropic-1.0.0-rc.7`

安装脚本位于 [`install.sh`](./install.sh)。脚本不会删除已有的 MySQL、配置文件或
上传文件；检测到已有数据时会保留并备份部署配置。

更换服务器时请按 [数据迁移说明](./MIGRATION.md) 使用 `mysqldump` 导出和恢复，
不要在 MySQL 运行时直接复制物理数据目录。

## 重要数据

迁移或升级前必须备份：

- `mysql/data`
- `data/.config.yaml`
- `uploadfile`
- `.env`

火山 API Key、Anthropic/中转站 API Key、应用 ID、访问令牌等密钥不得提交到 GitHub。

该版本已经通过请求头、Anthropic SSE 协议、Python、YAML 和部署脚本静态测试。由于真实双向语音调用
会使用用户自己的付费密钥，发布时标记为 Pre-release；生产使用前请用已轮换的新
API Key 分别测试 1.0 与 2.0 音色。
