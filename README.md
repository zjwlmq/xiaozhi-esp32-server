# xiaozhi-esp32-server 兼容增强版

本仓库基于
[xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)
维护，只说明本仓库额外增加的功能。官方项目介绍、硬件要求和基础使用文档请直接查看
[官方原版仓库](https://github.com/xinnan-tech/xiaozhi-esp32-server)。

## 本仓库增加了什么

### 1. 火山双向流式 TTS 新认证

- 支持新版 `X-Api-Key` 请求头。
- 未填写 API Key 时，保留旧版 AppID/Access Token 认证作为回退。
- 支持 `seed-tts-1.0` 与 `seed-tts-2.0`。
- 智控台可配置 API Key。
- 音色列表区分“湾湾小何”（1.0）和“小何 2.0”（2.0）。

### 2. Anthropic Messages 原生协议

- 直接调用 `/v1/messages`，支持 `x-api-key` 与 Bearer 认证。
- 支持自定义中转站地址、模型名称和 User-Agent。
- 严格按 UTF-8 解析流式 SSE。
- 只把 `text_delta` 发送给字幕和 TTS，不朗读隐藏思考内容。
- 正确处理 `thinking_delta`、`signature_delta`、`redacted_thinking` 和 `ping`。
- 工具续轮时保存并回传思考签名。
- 为工具调用建立独立连续序号，并拒绝损坏或不完整的工具参数。

### 3. 版本化 Docker 部署

- 提供 CentOS Stream 9 与 Ubuntu 22.04/24.04 部署入口。
- 火山与 Anthropic 补丁可以单独使用，也可以使用组合版。
- 安装脚本保留已有数据库和配置，并提供迁移说明。
- 固定分支和候选标签，方便更换服务器后复现同一版本。

## 版本选择

| 版本 | 分支 | 用途 |
| --- | --- | --- |
| 组合版（推荐） | [`release/volc-anthropic`](https://github.com/zjwlmq/xiaozhi-esp32-server/tree/release/volc-anthropic) | 同时使用火山 TTS 新认证与 Anthropic Messages |
| Anthropic 单独版 | [`feat/anthropic-messages`](https://github.com/zjwlmq/xiaozhi-esp32-server/tree/feat/anthropic-messages) | 只增加 Anthropic 原生协议 |
| 火山单独版 | [`feat/volcengine-tts-api-key`](https://github.com/zjwlmq/xiaozhi-esp32-server/tree/feat/volcengine-tts-api-key) | 只增加火山 TTS API Key |
| 官方原版 | [上游仓库](https://github.com/xinnan-tech/xiaozhi-esp32-server) | 不需要本仓库兼容功能 |

完整差异见
[版本选择说明](https://github.com/zjwlmq/xiaozhi-esp32-server/blob/release/volc-anthropic/CUSTOM_VERSIONS.md)。

## 固定候选版本

- 组合版：[`volc-anthropic-v1.0.0-rc.4`](https://github.com/zjwlmq/xiaozhi-esp32-server/releases/tag/volc-anthropic-v1.0.0-rc.4)
- Anthropic 单独版：[`anthropic-messages-v1.0.0-rc.1`](https://github.com/zjwlmq/xiaozhi-esp32-server/tree/anthropic-messages-v1.0.0-rc.1)
- 火山单独版：[`volc-api-key-v1.0.0-rc.1`](https://github.com/zjwlmq/xiaozhi-esp32-server/tree/volc-api-key-v1.0.0-rc.1)

## 配置与部署

- [Anthropic Messages 配置说明](https://github.com/zjwlmq/xiaozhi-esp32-server/blob/release/volc-anthropic/docs/anthropic-messages.md)
- [CentOS Stream 9 部署](https://github.com/zjwlmq/xiaozhi-esp32-server/blob/release/volc-anthropic/deploy/centos-stream-9/README.md)
- [Ubuntu 部署](https://github.com/zjwlmq/xiaozhi-esp32-server/blob/release/volc-anthropic/deploy/ubuntu/README.md)
- [服务器迁移说明](https://github.com/zjwlmq/xiaozhi-esp32-server/blob/release/volc-anthropic/deploy/MIGRATION.md)

组合版已通过 30 个 Python 单元测试、Python 3.10 语法检查、YAML、Compose
和安装脚本检查。仓库不保存任何用户 API Key；所有密钥均应在部署后通过智控台填写。

## 开源许可

本仓库沿用上游项目的 [MIT License](./LICENSE)。感谢官方项目及所有贡献者。
