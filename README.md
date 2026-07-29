# 火山双向流式 TTS API Key 兼容版

当前分支基于
[xiaozhi-esp32-server 官方原版](https://github.com/xinnan-tech/xiaozhi-esp32-server)
只增加火山双向流式 TTS 的新版认证与部署兼容。官方项目介绍和基础使用方法请查看上游仓库。

## 新增功能

- 支持新版 `X-Api-Key` 请求头。
- 未配置 API Key 时，继续使用旧 AppID/Access Token 认证。
- 支持 `seed-tts-1.0` 与 `seed-tts-2.0`。
- 智控台模型配置增加 API Key 输入项。
- 音色列表区分“湾湾小何”（1.0）和“小何 2.0”（2.0）。
- 提供 CentOS Stream 9 与 Ubuntu 22.04/24.04 的版本化 Docker 部署文件。
- 提供安装、升级备份和服务器迁移说明。

## 使用入口

- [版本选择说明](./CUSTOM_VERSIONS.md)
- [CentOS Stream 9 部署](./deploy/centos-stream-9/README.md)
- [Ubuntu 部署](./deploy/ubuntu/README.md)
- [服务器迁移](./deploy/MIGRATION.md)
- 固定候选标签：
  [`volc-api-key-v1.0.0-rc.1`](https://github.com/zjwlmq/xiaozhi-esp32-server/tree/volc-api-key-v1.0.0-rc.1)

同时需要 Anthropic Messages 时，请使用
[组合版](https://github.com/zjwlmq/xiaozhi-esp32-server/tree/release/volc-anthropic)。

本分支通过火山请求头、Python、YAML、Compose 与安装脚本检查。API Key 不会保存到仓库。

本仓库沿用上游项目的 [MIT License](./LICENSE)。
