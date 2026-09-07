本文档是开发类文档，如需部署小智服务端，[点击这里查看部署教程](../../README.md#%E9%83%A8%E7%BD%B2%E6%96%87%E6%A1%A3)

如需查看一体机数字人落地部署、Kiosk 全屏启动和系统环境配置，[点击这里查看一体机部署指南](../../docs/all-in-one-digital-human-setup.md)

如需查看唤醒词模型下载、运行时配置和详细使用说明，[点击这里查看唤醒词专题文档](../../docs/digital-human-wakeword.md)

# 项目介绍

digital-human 是独立的数字人测试模块，负责提供本地测试页面、前端交互资源、唤醒词运行时和事件桥能力，用于联调整个数字人交互链路。

# 快速启动

## 无硬件声音调节版

使用电脑或手机浏览器即可进行文字、麦克风对话，无需 ESP32。已部署智控台的环境可通过 `/digital-human/` 访问；首次连接按页面提示将浏览器设备绑定到智能体。麦克风需要 HTTPS 或本机 localhost。

左上角“声音设置”提供模型、生成配置、语种、语速（0.5～2.0 倍）和音调（−12～12 半音）。选择后点击“应用设置”，收到确认后从下一次回复生效。偏好保存在当前浏览器，重连时自动发送；“恢复默认”回到智能体配置。参数只影响当前网页连接。

服务端需同时更新 Python 服务与本目录的静态资源。绑定智能体需使用 `huoshan_double_stream` 及 `S_` 开头的复刻音色，继续使用服务端保存的密钥。旧服务端、不支持的音色、未配置的训练版本或合成失败会在面板提示。

生成配置按火山实际接口区分：

- 复刻 2.0：标准版对应 `seed-tts-2.0-standard`，表现力增强版对应 `seed-tts-2.0-expressive`；后一项仍需音色训练版本支持。
- 复刻 1.0：“跟随音色训练”使用绑定的音色；标准版、还原版使用各自已训练的 DiT 音色，需先关联。选择菜单不会重新训练音色。
- “还原版”与“表现力增强版”是不同能力，不能互相替代；切换 1.0／2.0 也需要音色和账号具备相应权限。

若已有 1.0 标准版／还原版音色，在该 TTS 模型的服务端配置内增加以下映射（用实际音色 ID 替换占位符）。映射以智能体当前绑定的音色为键，每个智能体只能选取该音色下的配置。没有映射时选择对应生成版本会明确报错，保留上一次有效设置。

```yaml
browser_voice_variants:
  S_BOUND_VOICE_ID:
    standard: S_TRAINED_DIT_STANDARD_ID
    restoration: S_TRAINED_DIT_RESTORATION_ID
```

接口实现采用 `hello.features.voice_settings` 协商能力，后续 `voice_settings` 消息只接受上述界面参数；服务端通过 `request_id` 确认。模型切换在下一次 TTS 会话开始时重新设置资源 ID，必要时重建上游连接。

参考：[火山双向流式接口](https://docs.volcengine.com/docs/6561/1329505?lang=zh)、[复刻训练版本说明](https://docs.volcengine.com/docs/6561/1305191?lang=zh)。

## 本地唤醒词运行时

安装依赖：

```bash
pip install -r wakeword_runtime/requirements.txt
```

启动模块：

```bash
python start.py
```

# 访问地址

启动后可访问：

- 页面地址：http://127.0.0.1:8006/index.html
- 事件桥地址：ws://127.0.0.1:8006/wakeword-ws
- 健康检查：http://127.0.0.1:8006/health

# 目录说明

- `start.py`：模块启动入口
- `index.html`：数字人测试页面入口
- `wakeword_runtime`：本地唤醒词运行时与配置目录
- `js`、`css`：页面前端脚本与样式
- `images`、`resources`：页面资源文件

# 相关文档

- 一体机部署指南：适用于 x86 设备整机落地部署、Kiosk 展示和开机自启动配置
	[../../docs/all-in-one-digital-human-setup.md](../../docs/all-in-one-digital-human-setup.md)
- 唤醒词专题文档：适用于唤醒词模型下载、运行时配置和本地调试说明
	[../../docs/digital-human-wakeword.md](../../docs/digital-human-wakeword.md)
