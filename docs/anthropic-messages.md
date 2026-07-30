# Anthropic Messages 原生协议接入

本文说明如何让 xiaozhi-esp32-server 直接调用 Anthropic Messages API（`POST /v1/messages`）。该适配器不依赖 OpenAI 兼容接口，也不需要在服务器上额外运行 CC Switch。

适用范围：

- 普通文字对话和流式回复；
- Anthropic 原生 `tool_use` / `tool_result` 工具调用；
- 带 `thinking` 内容块的模型；
- 使用 `x-api-key` 或 Bearer 认证的兼容中转站。

暂不包括图片、文件上传、Anthropic 服务端工具和提示词缓存。

## 1. 接入前烟测

`/v1/models` 或 `/v1/chat/completions` 可用，不代表中转站一定开放了 `/v1/messages`。先在部署服务器上测试原生 Messages 端点。

以下命令不会把密钥写入 Shell 历史。示例地址和模型名必须换成中转站实际提供的值：

```bash
export ANTHROPIC_MESSAGES_URL='https://relay.example.com/v1/messages'
export ANTHROPIC_MODEL='your-model-name'
read -s -p 'API Key: ' ANTHROPIC_API_KEY
echo
export ANTHROPIC_API_KEY

curl -i -N "$ANTHROPIC_MESSAGES_URL" \
  -H "x-api-key: ${ANTHROPIC_API_KEY}" \
  -H 'anthropic-version: 2023-06-01' \
  -H 'content-type: application/json' \
  -H 'user-agent: curl/8.5.0' \
  -d "{
    \"model\": \"${ANTHROPIC_MODEL}\",
    \"max_tokens\": 128,
    \"stream\": true,
    \"messages\": [
      {\"role\": \"user\", \"content\": \"只回复OK\"}
    ]
  }"

unset ANTHROPIC_API_KEY
```

成功时会看到 `HTTP 200`，并依次收到类似事件：

```text
message_start
content_block_start
content_block_delta
message_stop
```

最终正文位于 `text_delta.text`。常见错误：

| 结果 | 含义与处理 |
|---|---|
| `401 Invalid token` | 当前 Shell 中的密钥为空、错误，或者认证方式不匹配。先检查 `${#ANTHROPIC_API_KEY}` 是否大于 0 |
| Bearer 才能认证 | 将请求头改成 `Authorization: Bearer ...`，配置里的 `auth_type` 改成 `bearer` |
| `404` / `405` | 中转站没有开放 `/v1/messages`，需联系供应方或继续使用 OpenAI 兼容接口 |
| `Your request was blocked` | 中转站的 WAF 在拦截请求特征；确认它允许的 User-Agent 后再填写 `user_agent` |

不要把真实 API Key 写入 Git、截图、Issue 或聊天记录。

## 2. 本地配置

在 `main/xiaozhi-server/data/.config.yaml` 中增加以下内容；使用源码运行时也可以在 `config.yaml` 中配置。`api_key` 必须换成自己的密钥：

```yaml
selected_module:
  LLM: AnthropicMessagesLLM

LLM:
  AnthropicMessagesLLM:
    type: anthropic_messages
    base_url: https://relay.example.com
    model_name: your-model-name
    api_key: 你的Anthropic协议API密钥
    auth_type: x-api-key
    anthropic_version: "2023-06-01"
    user_agent: "curl/8.5.0"
    max_tokens: 1024
    temperature: 0.7
    top_p: 1
    timeout: 300
    disable_parallel_tool_use: true
    thinking_cache_ttl: 900
    thinking_cache_max_sessions: 256
```

配置说明：

| 字段 | 说明 |
|---|---|
| `base_url` | 可填写服务根地址、以 `/v1` 结尾的地址或完整 `/v1/messages` 地址，适配器会统一规范化 |
| `model_name` | 中转站在 Anthropic Messages 协议下实际接受的模型 ID |
| `auth_type` | `x-api-key`、`x_api_key` 或 `bearer`；默认是 `x-api-key` |
| `anthropic_version` | 默认 `2023-06-01`；请使用字符串，避免 YAML 将其解析成日期 |
| `anthropic_beta` | 可选。仅在服务端明确要求时配置，不要随意开启 Beta 功能 |
| `user_agent` | 默认使用小智自身标识；只有中转站明确按 User-Agent 放行时才配置成它要求的值 |
| `max_tokens` | Anthropic 的必填参数；隐藏思考也计入额度，思考模型建议从 1024 或更高开始 |
| `timeout` | 可填总秒数，也可填 `pool`、`connect`、`write`、`read` 组成的字典 |
| `disable_parallel_tool_use` | 默认 `true`，让工具按轮次串行执行，避免小智只续接部分并行工具结果；只有确认所有工具结果都会完整回写时才关闭 |
| `thinking_cache_ttl` | 工具调用续接所需隐藏内容的内存缓存时长，单位秒，默认 900 |
| `thinking_cache_max_sessions` | 隐藏内容同时缓存的最大会话数，默认 256 |

细粒度超时示例：

```yaml
timeout:
  pool: 2
  connect: 10
  write: 30
  read: 300
```

如果使用官方 Anthropic API，通常不需要自定义 `user_agent`。如果中转站要求 `Authorization: Bearer`，只需把 `auth_type` 改成 `bearer`，其他协议字段保持不变。

## 3. 智控台配置

全模块部署时，可以在智控台的“模型配置”中新增或选择“Anthropic Messages（原生）”供应器：

1. 填写基础 URL、模型名称和 API Key；
2. 按烟测结果选择 `x-api-key` 或 `bearer`；
3. 仅在中转站确实拦截默认请求头时填写自定义 User-Agent；
4. 保存并启用模型；
5. 在智能体配置中把主语言模型切换到该模型。

如果需要天气、音乐或设备控制等工具，将意图识别选择为“大模型自主函数调用”。普通聊天可以继续使用“不使用意图识别”。

### 首轮本地欢迎语

小智可能在用户第一次说话前播放欢迎语，并把它保存成 assistant 历史消息。这段内容是本地提示，不是 Anthropic 返回的模型轮次；如果直接发送，服务端会因对话没有从 user 消息开始而拒绝请求。

从 `volc-anthropic-v1.0.0-rc.5` 开始，适配器只忽略首个 user 消息之前、没有工具调用的前导 assistant 文本。它不会伪造 user 消息，也不会删除首个 user 之后的正常 assistant 回复。若前导 assistant 消息包含工具调用，适配器仍会报错，不会静默丢弃可能关联工具结果或思考签名的协议内容。

## 4. 思考内容为什么不会被朗读

Anthropic 流可能同时返回以下内容：

```text
thinking_delta   模型隐藏思考
signature_delta  隐藏思考的协议签名
text_delta       给用户的最终正文
ping             连接保活事件
```

适配器不会主动替服务端开启思考模式；是否产生思考块由所选模型和中转站决定。只要响应中已经包含思考块，下面的过滤和续接规则就会生效。

适配器只把 `text_delta` 交给小智字幕和 TTS。`thinking_delta`、`signature_delta` 和 `ping` 不会显示、不会朗读，也不会写入普通 INFO 日志。

当模型发起工具调用时，Anthropic 要求下一次请求带回关联的思考块和签名。适配器会在当前进程内按 `session_id` 暂存这些隐藏块，并在发送 `tool_result` 时原样续接：

```text
隐藏思考 + tool_use
        ↓ 执行天气/音乐/设备工具
隐藏思考 + tool_use + tool_result
        ↓
最终 text_delta → 字幕与 TTS
```

缓存会在最终回答完成、超时或超出会话上限后清理，不同会话不会共用。若容器恰好在工具调用中间重启，内存缓存会丢失；重新发起该问题即可。

Anthropic 内容块的 `index` 同时包含思考、正文和工具块，因此适配器会为工具调用重新生成从 0 开始的连续序号。这是内部兼容处理，不需要用户配置。

适配器默认通过 `tool_choice.disable_parallel_tool_use=true` 要求模型每轮只调用一个客户端工具。如果中转站忽略该设置，而历史里只出现一部分工具结果，适配器会终止该轮，不会把不完整的签名工具链继续发送或执行。

## 5. Docker 发布与部署

不要在运行中的容器里用 `sed` 修改 Python 文件：容器重建后改动就会丢失。应当从包含本补丁的 Git 提交构建并发布镜像。

组合分支的 `.github/workflows/docker-image.yml` 会在发布镜像前执行全部 Python 单元测试。推送
`volc-anthropic-v1.0.0-rc.6` 标签后，工作流发布：

```text
ghcr.io/<owner>/<repository>:server_volc-anthropic-1.0.0-rc.6
ghcr.io/<owner>/<repository>:web_volc-anthropic-1.0.0-rc.6
```

工作流使用 GitHub 自动提供的 `GITHUB_TOKEN` 发布到当前仓库的 Packages，不需要把个人访问令牌写进仓库。

部署前先备份当前配置并记录正在运行的镜像：

```bash
cd /opt/xiaozhi-server
cp data/.config.yaml "data/.config.yaml.before-anthropic"
cp docker-compose_all.yml "docker-compose_all.yml.before-anthropic"
docker inspect --format '{{.Config.Image}}' xiaozhi-esp32-server
docker inspect --format '{{.Config.Image}}' xiaozhi-esp32-server-web
```

把 `docker-compose_all.yml` 中 server 和 web 的镜像改成同一个发布版本，然后执行：

```bash
docker compose -f docker-compose_all.yml pull
docker compose -f docker-compose_all.yml up -d --force-recreate \
  xiaozhi-esp32-server xiaozhi-esp32-server-web

docker logs --since 5m xiaozhi-esp32-server 2>&1 |
  grep -E 'anthropic_messages|初始化组件|ERROR'
```

只部署 Server、没有智控台时，修改 `docker-compose.yml` 中的 server 镜像，并使用：

```bash
docker compose -f docker-compose.yml pull
docker compose -f docker-compose.yml up -d --force-recreate xiaozhi-esp32-server
```

## 6. 回滚

出现问题时，先在智控台把智能体的主语言模型切回升级前的 LLM。随后：

1. 将 Compose 文件中的 server 和 web 镜像恢复为升级前记录的不可变版本标签；
2. 同时回滚 server 和 web，避免管理端与服务端版本不一致；
3. 重新创建容器并检查日志；
4. 只有在确有需要时才逐项恢复旧配置，不要用旧 `.config.yaml` 整体覆盖新版本配置。

```bash
cd /opt/xiaozhi-server
docker compose -f docker-compose_all.yml pull
docker compose -f docker-compose_all.yml up -d --force-recreate \
  xiaozhi-esp32-server xiaozhi-esp32-server-web
docker logs --since 5m xiaozhi-esp32-server
```

新增的 Anthropic 供应器元数据可以保留，不会影响其他 LLM。API Key 应由配置或智控台保存，不要打进镜像。
