# 版本选择说明

本仓库是
[xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)
的兼容版本仓库。官方代码和各项兼容功能使用独立分支，互不覆盖。

## 应该选择哪个版本

| 版本 | 分支 | 适合人群 |
| --- | --- | --- |
| 官方原版 | [`main`](https://github.com/zjwlmq/xiaozhi-esp32-server/tree/main) | 希望完全跟随官方代码，不需要新增兼容功能 |
| 火山 API Key 兼容版 | [`feat/volcengine-tts-api-key`](https://github.com/zjwlmq/xiaozhi-esp32-server/tree/feat/volcengine-tts-api-key) | 只需要火山双向流式 TTS 的新版 `X-Api-Key` 认证 |
| Anthropic Messages 兼容版 | [`feat/anthropic-messages`](https://github.com/zjwlmq/xiaozhi-esp32-server/tree/feat/anthropic-messages) | 只需要原生 `/v1/messages`、思考块和工具调用适配 |
| 火山 + Anthropic 组合版（推荐） | [`release/volc-anthropic`](https://github.com/zjwlmq/xiaozhi-esp32-server/tree/release/volc-anthropic) | 同时需要湾湾小何/小何 2.0、Anthropic 中转协议和版本化 Docker 部署 |

> `main` 保留官方代码。组合版包含前两个兼容补丁，CentOS Stream 9 与 Ubuntu
> 使用同一套程序，只是部署入口不同。

## 固定版本下载

- 火山 API Key：`volc-api-key-v1.0.0-rc.1`
- Anthropic Messages：`anthropic-messages-v1.0.0-rc.1`
- 组合版：`volc-anthropic-v1.0.0-rc.1`

不熟悉 Git 时，可打开标签页面下载 Source code 压缩包；服务器部署建议直接使用
组合版安装脚本。

## 克隆指定分支

```bash
# 官方原版
git clone --branch main --single-branch \
  https://github.com/zjwlmq/xiaozhi-esp32-server.git

# 只要火山 API Key
git clone --branch feat/volcengine-tts-api-key --single-branch \
  https://github.com/zjwlmq/xiaozhi-esp32-server.git

# 只要 Anthropic Messages
git clone --branch feat/anthropic-messages --single-branch \
  https://github.com/zjwlmq/xiaozhi-esp32-server.git

# 同时包含两项补丁（推荐）
git clone --branch release/volc-anthropic --single-branch \
  https://github.com/zjwlmq/xiaozhi-esp32-server.git
```

## 火山 API Key 兼容内容

- 填写 `api_key` 时使用新版请求头 `X-Api-Key`。
- `api_key` 留空时继续使用旧版 AppID/Access Token 请求头。
- 支持 `seed-tts-1.0` 与 `seed-tts-2.0`。
- 智控台可配置 API Key，并区分“湾湾小何”（1.0）与“小何 2.0”（2.0）。

## Anthropic Messages 兼容内容

- 直接调用 Anthropic `/v1/messages`，也可连接兼容该协议的中转站。
- 流式解析 UTF-8 SSE，只把 `text_delta` 送给字幕和 TTS。
- 过滤 `thinking_delta`、`signature_delta` 与 `ping`，并在工具续轮时按协议保存和回传思考签名。
- 为工具调用建立独立、连续的工具序号，不直接使用 Anthropic 内容块序号。
- 默认关闭并行工具调用，遇到不完整工具结果或损坏 JSON 时安全终止该轮。

详细字段和部署方式见 [Anthropic Messages 使用说明](./docs/anthropic-messages.md)。

## Docker 部署

组合版提供以下固定镜像：

- `ghcr.io/zjwlmq/xiaozhi-esp32-server:server_volc-anthropic-1.0.0-rc.1`
- `ghcr.io/zjwlmq/xiaozhi-esp32-server:web_volc-anthropic-1.0.0-rc.1`

部署入口：

- [CentOS Stream 9](./deploy/centos-stream-9/README.md)
- [Ubuntu 22.04/24.04](./deploy/ubuntu/README.md)
- [更换服务器与数据迁移](./deploy/MIGRATION.md)

API Key、应用 ID 和访问令牌均应在部署后通过智控台填写，不要写入提交、Issue、
截图、Compose 或公开配置文件。

## 更新原则

1. `main` 用于同步官方仓库。
2. 单项补丁分别在 `feat/volcengine-tts-api-key` 与 `feat/anthropic-messages` 维护。
3. `release/volc-anthropic` 合并两项补丁并维护 CentOS/Ubuntu 部署文件。
4. 固定候选版本使用对应的 `*-v1.0.0-rc.1` 标签发布，避免分支继续更新后无法复现。
