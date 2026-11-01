# 插件中心

智控台顶部新增“插件中心”。选择智能体，打开所需插件，再填写它的配置；设置按智能体保存。开启节假日感知或主动消息时，会同时启用时间感知。

| 插件 | 当前能力 | 使用条件 |
| --- | --- | --- |
| 时间感知 | 每轮更新日期、星期和时区；区分实际间隔与跨日；按时间顺序理解历史 | 默认时区 Asia/Shanghai |
| 节假日感知 | 公历、农历节日和近期节日；指定日期的放假或调休安排 | 放假安排在界面选择日期、休息日或工作日；没有安排的日期保持未知 |
| 主动消息 | 安静一段时间后生成简短消息；免打扰时段、每日次数、跳过无合适话题的尝试 | 设备持续在线，已有真实互动，LLM 和发送通道可用；间隔及每日上限按设备会话计算 |
| 记忆优化 | 按话题选择记忆段落、去重、控制本轮长度，保留原文日期和否定信息 | 作用于记忆模块返回给模型的文本；超长段落可能被排除 |
| 生成图片 | 调用兼容 OpenAI 的 images/generations 接口，将图片发送到聊天窗口 | 配置完整地址、密钥、模型；使用函数调用模式；客户端支持图片消息 |

插件初始均关闭。绿色“已启用”来自设备报告，并要求报告与最新配置版本一致。仅保存设置时显示“待生效”或“待连接”；缺少配置、缺少客户端能力和运行错误分别显示原因。界面显示最近报告状态的设备，不代表该智能体绑定的所有设备同时就绪。

主动消息通过现有 TTS 队列发送。生成期间收到新消息或检测到用户语音，会取消本次主动消息；关闭插件或断开连接也会阻止待生成结果发送。没有首次真实互动时不会主动开场。模型可返回 `[SKIP]` 跳过本轮；不会把后台任务文本写成用户发言。间隔和次数保存在 SQLite，重连后继续累计。已进入传输过程的消息可能已经送达。

时间记录位于 Python 服务工作目录下的 `data/plugin-center/live.sqlite3`，保存时间元数据及主动消息尝试状态。智控台模式按用户、智能体、设备隔离；本地配置模式按设备隔离。导入的旧微信聊天日期不会被当作当前会话的最后联系时间。该目录需要随服务数据持久化。

生图服务返回的图片带有 `origin: generated` 标记。数字人页面已声明 `plugin_images` 能力并显示 `plugin_image` 消息。其他客户端需实现同样的能力声明和消息显示；QQ 官方机器人、NapCat 的账号接入和消息适配还需实现。当前生图适配器使用 JSON 图片生成协议；参考图、images/edits 以及现有 Dafeiyu 预设需要另加适配。

普通生图地址要求公网 HTTPS。请求固定到已验证的 IP，保留原始 Host 和 TLS 域名校验，禁止重定向。若服务端管理员确实使用本机或局域网图片服务，可在服务端 `data/.config.yaml` 添加精确的允许来源：

```yaml
plugin_center_image_allowed_origins:
  - "http://127.0.0.1:8188"
```

此配置只能由服务端管理员设置，包含协议、主机和非默认端口，不填写路径；不能由智能体的插件配置修改。密钥在数据库中持久化，普通读取接口只返回“已保存”的标记；密钥输入留空会保留原值，勾选“清除已保存的密钥”才清除。

部署时需要一并更新 `manager-api`、`xiaozhi-server`、`manager-web`；使用数字人收图时也更新 `digital-human` 静态资源。Java 服务通过 Liquibase 变更 `202611011200` 新建 `ai_agent_extension_config` 表。Python 服务从新接口读取配置，约每 15 秒刷新；用户发起对话时也会刷新。旧版 API 未提供接口时，插件保持等待状态，普通聊天仍使用原有流程。配置服务暂时不可用时暂停主动发送和生图操作。

对已有的一键 Docker Compose 安装，可下载本次提交的完整源码，在源码目录执行 `sudo bash deploy/update-plugin-center.sh --check`。脚本从运行中的容器识别部署目录；要求单份 Compose 文件、`.env` 和 `XIAOZHI_SERVER_IMAGE` / `XIAOZHI_WEB_IMAGE` 变量。检查通过后，执行 `sudo bash deploy/update-plugin-center.sh --apply`：在服务器构建两个镜像，备份数据库和配置，再更新管理端及 Python 服务，检查插件表和服务端口。应用服务重建时需要重新连接聊天客户端。

脚本沿用现有数据目录、MySQL 和 Redis 服务，备份及回滚脚本保存在检测到的部署目录下的 `backups/plugin-center-*`。回滚脚本恢复应用镜像和配置；数据库备份保留供单独恢复，不自动覆盖数据库。固定镜像、多份 Compose 文件、无 Compose 标签等布局会停止检查，需要按实际部署方式调整命令。

纯本地配置模式可以在 `data/.config.yaml` 中使用：

```yaml
plugin_center:
  revision: 1
  plugins:
    time-awareness:
      enabled: true
      settings:
        timezone: Asia/Shanghai
    holiday-awareness:
      enabled: true
      settings:
        lookahead_days: 3
        calendar: []
```

智控台模式下，插件设置以智控台数据库为准。本地配置模式修改后需要重启服务。

开发入口如下：

- `main/manager-web/src/views/PluginCenter.vue`：界面、开关、配置及状态。
- `main/manager-api/.../agent/service/PluginCatalog.java`：字段验证、依赖及密钥隐藏。
- `main/manager-api/.../agent/service/PluginCenterService.java`：所有权校验、配置版本与运行报告。
- `main/xiaozhi-server/core/plugins/runtime.py`：生命周期、时间上下文、记忆处理、主动消息及生图执行。
- 两端的 `plugin-center/catalog.json` / `core/plugins/catalog.json`：相同插件清单；测试校验一致性。

新增插件需要登记清单及配置字段、实现运行逻辑和状态报告，再增加对应验证。已有工具调用系统仍负责由模型主动调用的功能，插件中心还支持时间上下文和后台调度等行为。DSH 的插件包不能直接安装到这套 Python 运行器中。

验证命令：

```text
# 仓库根目录，使用项目的 Python 依赖环境
python -m unittest discover -s tests -p test_plugin_center.py -v

# main/manager-web
node --test tests/pluginCenter.test.mjs
npm run build

# main/manager-api，JDK 21
mvn -DskipTests=false -Dtest=PluginCatalogTest,PluginCenterServiceTest,ConfigServiceImplTest test
```

已通过 28 项 Python 检查、7 项前端逻辑检查和 13 项 Java 检查，完成前端生产构建。使用本地模拟 API 对生产构建检查了页面开关、角色隔离、配置保存、无效日期提示、失败反馈、密钥隐藏和桌面／手机布局，并验证数字人图片组件能加载图片、拒绝无效地址。真实数据库迁移、在线设备、外部生图和语音服务仍需部署环境联调；这些验证不会发送真实 QQ 消息或调用付费图片服务。
