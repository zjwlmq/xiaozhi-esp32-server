# 火山 API Key 兼容版 v1.0.0 RC1

基于官方 `xinnan-tech/xiaozhi-esp32-server` 的 `de45f73e` 提交制作。

## 新增功能

- 火山双向流式 TTS 支持新版 `X-Api-Key` 鉴权。
- 未填写 API Key 时继续兼容旧版 AppID + Access Token。
- 智控台增加 API Key 密码字段及数据库迁移。
- 提供 `seed-tts-1.0` 与 `seed-tts-2.0` 配置。
- 音色列表明确区分“湾湾小何”（1.0）与“小何2.0”（2.0）。
- 提供 CentOS Stream 9 和 Ubuntu 22.04/24.04 Docker Compose 部署入口。
- 发布固定版本的 server/web Docker 镜像。

## 音色示例

- 湾湾小何 1.0：`seed-tts-1.0` /
  `zh_female_wanwanxiaohe_moon_bigtts`
- 小何 2.0：`seed-tts-2.0` /
  `zh_female_xiaohe_uranus_bigtts`

已有配置使用 `volc.service_type.10029` 且运行正常时可以保持不变。

## 验证状态

以下检查已经通过：

- API Key 优先与旧鉴权回退单元测试。
- 两条 WebSocket 建连路径共用同一请求头构造方法。
- Python 语法、YAML、数据库迁移 JSON 与 Git 差异检查。
- CentOS/Ubuntu Compose 与安装脚本静态检查。

真实双向语音调用需要使用用户自己的付费密钥，因此本版本先标记为 Pre-release。
生产使用前，请使用已轮换的新 API Key 分别测试 1.0 和 2.0 音色。

## 部署与升级

- [版本选择](https://github.com/zjwlmq/xiaozhi-esp32-server/blob/volc-api-key-v1.0.0-rc.1/CUSTOM_VERSIONS.md)
- [CentOS Stream 9 部署](https://github.com/zjwlmq/xiaozhi-esp32-server/blob/volc-api-key-v1.0.0-rc.1/deploy/centos-stream-9/README.md)
- [Ubuntu 部署](https://github.com/zjwlmq/xiaozhi-esp32-server/blob/volc-api-key-v1.0.0-rc.1/deploy/ubuntu/README.md)
- [更换服务器与数据迁移](https://github.com/zjwlmq/xiaozhi-esp32-server/blob/volc-api-key-v1.0.0-rc.1/deploy/MIGRATION.md)

升级或迁移前必须备份：

- MySQL 数据库（使用 `mysqldump` 逻辑备份）
- `data/.config.yaml`
- `uploadfile`
- `.env`

API Key、应用 ID、访问令牌和数据库备份均属于敏感数据，不要上传到 GitHub。
