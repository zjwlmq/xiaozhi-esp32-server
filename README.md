# Anthropic Messages 原生协议兼容版

当前分支基于
[xiaozhi-esp32-server 官方原版](https://github.com/xinnan-tech/xiaozhi-esp32-server)
只增加 Anthropic Messages 兼容功能。官方项目介绍和基础使用方法请查看上游仓库。

## 新增功能

- 直接调用 `/v1/messages`。
- 支持 `x-api-key`、Bearer、自定义中转站地址和 User-Agent。
- 严格 UTF-8 SSE 流式解析。
- 只把 `text_delta` 发送给字幕和 TTS。
- 过滤 `thinking_delta`、`signature_delta` 与 `ping`。
- 工具续轮时保存并回传思考、签名与 `redacted_thinking`。
- 工具调用使用独立连续序号。
- 拒绝损坏 JSON、未闭合内容块和不完整工具结果。
- 智控台可新增并选择 `anthropic_messages` 类型模型。

## 使用说明

- [配置、协议与回滚说明](./docs/anthropic-messages.md)
- 固定候选标签：
  [`anthropic-messages-v1.0.0-rc.1`](https://github.com/zjwlmq/xiaozhi-esp32-server/tree/anthropic-messages-v1.0.0-rc.1)
- 同时需要火山 TTS API Key 时，请使用
  [组合版](https://github.com/zjwlmq/xiaozhi-esp32-server/tree/release/volc-anthropic)。

本分支通过 26 个 Anthropic 协议与提供商测试。API Key 不会保存到仓库。

本仓库沿用上游项目的 [MIT License](./LICENSE)。
