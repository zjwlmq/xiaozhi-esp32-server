# 火山 API Key + Anthropic Messages 组合版

当前分支为本仓库的推荐组合版，基于
[xiaozhi-esp32-server 官方原版](https://github.com/xinnan-tech/xiaozhi-esp32-server)
增加以下兼容功能。官方项目介绍和基础使用方法请查看上游仓库。

## 新增功能

### 火山双向流式 TTS

- 支持新版 `X-Api-Key`，同时保留旧 AppID/Access Token 回退。
- 支持 `seed-tts-1.0` 与 `seed-tts-2.0`。
- 智控台可配置 API Key。
- 区分“湾湾小何”（1.0）与“小何 2.0”（2.0）。

### Anthropic Messages

- 原生 `/v1/messages`，支持 `x-api-key`、Bearer 和自定义 User-Agent。
- 严格 UTF-8 SSE 解析，只把 `text_delta` 发送给字幕和 TTS。
- 隐藏思考内容，安全保存并回传思考签名。
- 独立连续的工具序号，拒绝损坏或不完整的工具参数与结果。
- 智控台可新增并选择 `anthropic_messages` 类型模型。

### 部署

- 支持 CentOS Stream 9 与 Ubuntu 22.04/24.04。
- 固定版本镜像、升级备份和服务器迁移说明。
- 不在容器内临时打补丁，容器重建后功能仍然保留。

## 使用入口

- [版本选择说明](./CUSTOM_VERSIONS.md)
- [Anthropic Messages 配置说明](./docs/anthropic-messages.md)
- [CentOS Stream 9 部署](./deploy/centos-stream-9/README.md)
- [Ubuntu 部署](./deploy/ubuntu/README.md)
- [服务器迁移](./deploy/MIGRATION.md)

固定候选标签：
[`volc-anthropic-v1.0.0-rc.3`](https://github.com/zjwlmq/xiaozhi-esp32-server/tree/volc-anthropic-v1.0.0-rc.3)。

本组合版已通过 30 个单元测试及 Python 3.10、YAML、Compose、安装脚本检查。
API Key 只应在部署后通过智控台填写，不得提交到 GitHub。

本仓库沿用上游项目的 [MIT License](./LICENSE)。
