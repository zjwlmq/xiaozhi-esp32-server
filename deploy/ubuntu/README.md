# Ubuntu 部署

该部署入口运行“火山 API Key + Anthropic Messages 组合版”，适用于安装了 Docker Engine 与 Docker
Compose v2 的 Ubuntu 22.04/24.04 服务器。

## 快速部署

```bash
curl -fL \
  https://raw.githubusercontent.com/zjwlmq/xiaozhi-esp32-server/volc-anthropic-v1.0.0-rc.6/deploy/install.sh \
  -o /tmp/xiaozhi-install.sh

less /tmp/xiaozhi-install.sh
sudo bash /tmp/xiaozhi-install.sh
```

脚本不会安装 Ubuntu 的 Docker。未安装时，请先按照
[Docker 官方 Ubuntu 安装文档](https://docs.docker.com/engine/install/ubuntu/)
安装 Docker Engine 与 Compose plugin。

默认目录、升级备份和部署后的配置步骤与
[CentOS Stream 9 部署说明](../centos-stream-9/README.md)相同。Ubuntu Compose
文件不添加 SELinux `:Z` 标签。

火山与 LLM 的 API Key 都应在部署完成后通过智控台填写，不要写入 GitHub、Compose 或公开配置。
