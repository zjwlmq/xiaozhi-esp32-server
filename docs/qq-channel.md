# QQ 接入 API（SnowLuma / NapCat，OneBot v11）

QQ → OneBot → 小智 QQ 接口 → 已绑定智能体 → 原有模型、人格、记忆、插件 → OneBot → QQ。

这一版内置在小智 Python 服务中，使用现有 HTTP 端口（默认 8003），无需 DSH，也不单独创建一套聊天模型。参考同工作区 qq-bridge 的 OneBot HTTP 收发和正向 WebSocket 事件协议；不依赖它的 DSH Cookie 或私有会话协议。此适配器支持 OneBot v11，不是腾讯官方机器人开放平台的 AppID / AppSecret 接口。

## 已接入的能力

| 能力 | 行为 / 前置条件 |
| --- | --- |
| 私聊 | 只处理 routes 中明确配置的 QQ 号 |
| 群聊 | 只处理配置的群，默认需要 @机器人，可限制 members |
| 人格与工具 | 虚拟设备绑定到智控台智能体，复用原聊天函数、模型配置和工具调用 |
| 会话与时间 | 按机器人＋私聊对象／群分开设备和上下文；把 QQ 事件的原始时间传给时间感知插件 |
| 图片、图片表情包 | 调用该智能体的 VLLM 识别后进入聊天；需要配置视觉模型。动画的理解程度取决于视觉模型，不保证逐帧分析 |
| QQ 内置表情 | 输入保留表情 ID；发送接口支持 face 段，不把陌生 ID 编成假含义 |
| 生图 | 打开智能体的生图插件后，生成结果直接发回本会话；需要支持工具调用的聊天模型 |
| 语音输入 | OneBot get_record 转换后，经 ffmpeg → 当前智能体的文件 ASR → 正常聊天 |
| 语音输出 | reply_mode: voice 或 both 使用当前 TTS，汇总 Opus 为 WAV 后交给 OneBot 发语音 |
| 主动消息 | 复用插件中心；只在已有在线会话中工作，实际 QQ 发送成功后才计数 |

默认 `reply_mode: text`，不调用语音合成，保留文字和 emoji。`voice` 发语音，`both` 同时发文字和语音。输出语音需要 OneBot 支持发送 WAV/base64；输入语音需要 get_record 返回可访问的转换后 URL 或 base64（标准接口允许只返回 OneBot 本机路径，这种情况不能跨容器直接读取，需要网关提供受限媒体 URL）。某些仅支持实时流的 ASR 没有文件识别能力，需改选支持文件识别的 ASR。真实 QQ 和模型联调仍取决于你的网关、模型配置。

人格 skill、原始聊天记录 JSON、表情包库不会因为开启此渠道自动导入。这版完成传输和智能体对接；自动挑选自建表情包库需要再接对应工具。短期会话和插件时间记录按设备隔离；智控台同一智能体的长期摘要可能共享，私聊和群聊需要不同长期记忆时应绑定不同智能体。

## 首次配置

新配置放在持久卷内 `data/.qq-bridge.yaml`，修改后重启 Python 服务。默认不启用、不自动接管任何 QQ。`qq-bridge.example.yaml` 是完整示例。

先确认 OneBot 的 **HTTP API、正向 WebSocket、Access Token**。现有 qq-bridge 的对应配置为 `snowluma.httpUrl / wsUrl / accessToken`。WebUI 端口（例如 5099）不等于 OneBot API 端口；3000 / 3001 也只是常见示例，以实际配置为准。消息上报选择数组格式。

容器之间必须互通：小智与 SnowLuma 加入同一个 Docker 网络后才能使用 `qqfish-snowluma` 这个名称。宿主机 `127.0.0.1:5099` 在小智容器里不是宿主机地址。不要为了此功能停止数据库或重建数据卷。

在小智服务的工作目录运行（Docker 部署可通过 `docker exec -it 容器名 python tools/qq_bridge.py ...`）：

```bash
python tools/qq_bridge.py init \
  --self-id 机器人QQ号 --peer-id 你的测试QQ号 \
  --http-url http://qqfish-snowluma:3000 \
  --ws-url ws://qqfish-snowluma:3001
```

工具会提示输入 OneBot token，输入不回显，并生成随机 API 密钥和 webhook secret，只写入私有配置文件；已有文件不会覆盖。重启 Python 服务后：

```bash
python tools/qq_bridge.py check
python tools/qq_bridge.py status
python tools/qq_bridge.py prepare --route friend
```

`check` 验证 OneBot HTTP 登录账号；`prepare` 通过现有 OTA 注册虚拟设备并返回 `activation_code`。到智控台选中目标智能体 → 添加／绑定设备 → 输入激活码。随后从已放行的测试 QQ 给机器人发一句话。以上三个工具命令本身都不会发送 QQ 消息。

在智能体插件中心打开“时间感知”（时区 Asia/Shanghai），并按需启用记忆优化、生图等。主动消息建议在正常回复和人格效果确认后再打开。

现有 qqfish-app 若仍监听同一测试 QQ，两边可能各回复一次。测试时将这个会话交给小智处理，并从旧桥的处理范围排除；其他会话继续留在旧桥。这里不会改动另一个项目的配置。

## API

管理 API 使用 `Authorization: Bearer <qq_bridge.api_key>`；该密钥保留在服务端。公网访问使用 HTTPS 反向代理。OneBot HTTP 上报可改用 `X-Signature: sha1=<HMAC-SHA1(webhook_secret, 原始请求体)>`，不需要把管理 API 密钥填到 QQ 消息中。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/xiaozhi/qq/status` | 路由、设备编号、队列长度、最近错误及出错阶段 |
| POST | `/xiaozhi/qq/bindings/{route_id}/prepare` | 查询绑定状态／生成控制台激活码，不发到 QQ |
| POST | `/xiaozhi/qq/events` | 接收 OneBot 消息事件，202 返回 event_id |
| GET | `/xiaozhi/qq/events/{event_id}` | 查询处理结果：queued / processing / completed / failed / interrupted |
| POST | `/xiaozhi/qq/send` | 向已配置会话发 text / image / face / record 消息 |

正向 WS 模式会自动订阅 OneBot 事件，不需要额外调用 `/events`。使用 HTTP POST 上报时，留空 websocket_url，配置 OneBot 上报地址为 `/xiaozhi/qq/events` 以及相同的 webhook_secret。

事件请求示例（time 必须是当前真实 Unix 秒，修改 message_id 才是一条新消息）：

```json
{
  "time": 1793505600,
  "post_type": "message",
  "self_id": 100001,
  "message_type": "private",
  "user_id": 200001,
  "message_id": 123456,
  "message": [{"type": "text", "data": {"text": "今天星期几？"}}]
}
```

发送接口请求示例（只有你调用该接口时才会发送）：

```json
{
  "route_id": "friend",
  "message": [
    {"type": "text", "data": {"text": "在呢 🙂"}},
    {"type": "face", "data": {"id": "14"}}
  ]
}
```

图片／图片表情包用 `{"type":"image","data":{"file":"base64://..."}}`；语音用 `record`。也可在 data.url 传可访问的 HTTPS URL。下载最多 5 MiB、输入语音最多 90 秒；不接受客户端传来的本地文件路径，不跟随 HTTP 跳转。只有管理员设置的 `media_allowed_origins` 精确地址可以使用 HTTP 或内网媒体服务，不提供通配符。

文字型 `[CQ:...]` 按字面文字处理；图片、@、表情等请使用消息段数组。任意第三方调用者不能在请求里指定 agent_id、设备编号或陌生 QQ 目标。

每个会话顺序处理，最多排队 16 条，满时返回 429。重复事件在 SQLite 中去重，重启后仍有效。默认丢弃超过 300 秒或未来超过 60 秒的事件，避免重连重放旧话。完成意味着本轮已经结束且所有实际发出的消息都得到 OneBot 确认，不代表对方已读。失败可能已发出部分内容；不要盲目重发。主动消息、普通回复和 `/send` 都不会在发送超时后自动重试。

事件库只记录事件 ID、路由、状态、时间和错误类型，不保存消息正文；聊天记录仍沿用小智原有存储配置。队列中的正文在内存里，进程崩溃后标记 interrupted，不重新播放。只部署一个渠道实例读取此事件库。

## 当前迁移 Docker Compose 部署

你目前的 Compose 文件是 `/root/migration/live/prepared/apps/xiaozhi/compose.json`，项目名 `migration-live-20260923-xiaozhi`。更新代码可沿用本仓库的 `deploy/update-plugin-compose-json.py --check / --apply`；它保留迁移后的端口、CPU 基础镜像、启动参数和数据卷。此次渠道无需额外 SQL 迁移，但该现有更新器会一并重建 Web 镜像。

取得包含此功能的新源码后：

```bash
python3 "$QQ_SRC/deploy/update-plugin-compose-json.py" --check \
  --project migration-live-20260923-xiaozhi \
  --file /root/migration/live/prepared/apps/xiaozhi/compose.json
python3 "$QQ_SRC/deploy/update-plugin-compose-json.py" --apply \
  --project migration-live-20260923-xiaozhi \
  --file /root/migration/live/prepared/apps/xiaozhi/compose.json
```

在服务器更新后，可以用以下命令只读检查工具是否随镜像安装：

```bash
docker compose -p migration-live-20260923-xiaozhi \
  -f /root/migration/live/prepared/apps/xiaozhi/compose.json \
  exec xiaozhi-esp32-server python tools/qq_bridge.py --help
```

再执行前面的 init / check / prepare 流程。API 返回 404 通常意味着尚未加载启用的 `.qq-bridge.yaml` 或仍运行旧镜像；`binding_required` 表示还没绑定设备；`recognizing_image` 阶段报错先查媒体地址、VLLM；`recognizing_voice` 阶段报错先查 get_record、ffmpeg、ASR；`waiting_for_reply` 报错查模型、TTS 和 OneBot 发消息能力。

## 验证

`python -m unittest discover -s tests -p 'test_qq_bridge.py' -v`

测试使用本地 aiohttp 假 OneBot 和假模型，执行实际 ConnectionHandler.chat 方法、QQ HTTP 接口、媒体边界与文字输出队列，不连接真实 QQ、不调用付费模型。真实语音编码、模型效果和实际 SnowLuma/NapCat 配置仍需上线后联调。

协议依据：[OneBot v11 API](https://github.com/botuniverse/onebot-11/blob/master/api/public.md)、[HTTP 上报](https://github.com/botuniverse/onebot-11/blob/master/communication/http-post.md)、[正向 WebSocket](https://github.com/botuniverse/onebot-11/blob/master/communication/ws.md)、[消息段](https://github.com/botuniverse/onebot-11/blob/master/message/segment.md)。
