# 火山 API Key + Anthropic Messages v1.0.0-rc.5

`volc-anthropic-v1.0.0-rc.5` 是组合版候选发布，包含火山双向流式 TTS API Key 兼容和 Anthropic Messages 原生协议适配。

## 本次修复

小智可能在首个用户消息之前播放本地欢迎语，并把它保存成 assistant 历史消息。此前适配器检测到第一条对话是 assistant 后，会在发送请求前报出“对话必须从 user 消息开始”，用户随后只能看到系统忙碌提示。

rc.5 调整了对话转换规则：

- 只忽略首个 user 消息之前、没有工具调用的前导 assistant 文本；
- 不伪造 user 消息；
- 不删除首个 user 消息之后的正常 assistant 回复；
- 前导 assistant 消息一旦包含工具调用，仍会安全报错，不会丢弃可能关联 `tool_result` 或思考签名的协议内容。

本次不修改数据库结构、智控台字段或用户保存的模型配置。

## 发布镜像

```text
ghcr.io/zjwlmq/xiaozhi-esp32-server:server_volc-anthropic-1.0.0-rc.5
ghcr.io/zjwlmq/xiaozhi-esp32-server:web_volc-anthropic-1.0.0-rc.5
```

Server 与 Web 应使用同一个候选版本。不要只升级其中一个镜像。

## 升级

先确认 GitHub Actions 已完成两个 rc.5 多架构镜像的发布，再在服务器执行升级。以下示例使用默认安装目录 `/opt/xiaozhi-server`；自定义目录请同步替换。

```bash
cd /opt/xiaozhi-server
cp .env ".env.before-rc.5"
cp docker-compose.yml "docker-compose.yml.before-rc.5"
cp data/.config.yaml "data/.config.yaml.before-rc.5"
docker inspect --format '{{.Config.Image}}' xiaozhi-esp32-server
docker inspect --format '{{.Config.Image}}' xiaozhi-esp32-server-web

curl -fL \
  https://raw.githubusercontent.com/zjwlmq/xiaozhi-esp32-server/volc-anthropic-v1.0.0-rc.5/deploy/install.sh \
  -o /tmp/xiaozhi-install-rc.5.sh
less /tmp/xiaozhi-install-rc.5.sh
sudo env XIAOZHI_INSTALL_DIR=/opt/xiaozhi-server \
  bash /tmp/xiaozhi-install-rc.5.sh
```

安装脚本会更新 `.env` 中的 Server/Web 镜像并保留现有 MySQL、上传文件和应用配置。API Key 继续由智控台或私有配置保存，不要写入命令、截图或 GitHub。

## 验证

先确认两个容器实际使用 rc.5：

```bash
docker inspect --format '{{.Config.Image}}' xiaozhi-esp32-server
docker inspect --format '{{.Config.Image}}' xiaozhi-esp32-server-web
```

再实时观察关键日志：

```bash
docker logs -f --since 30s xiaozhi-esp32-server 2>&1 \
  | grep --line-buffered -E '初始化组件: llm|大模型收到用户消息|Anthropic Messages|LLM stream processing error|发送第一段语音'
```

打开一个新的数字人会话，让小智先播放本地欢迎语，再发送“只回复 OK”。正常结果应包含：

1. `初始化组件: llm成功`；
2. `大模型收到用户消息: 只回复 OK`；
3. `发送第一段语音`；
4. 没有 `Anthropic Messages request failed` 或 `LLM stream processing error`。

如使用“大模型自主函数调用”，再测试一次天气等真实工具，确认工具结果能够继续回传并生成最终正文。隐藏思考、签名和 `ping` 不应出现在字幕或 TTS 中。

## 回滚

本次没有数据库迁移，回滚镜像时不需要恢复 MySQL。先在智控台把智能体主语言模型切回升级前可用的 LLM，然后恢复升级前备份的部署文件：

```bash
cd /opt/xiaozhi-server
cp ".env.before-rc.5" .env
cp "docker-compose.yml.before-rc.5" docker-compose.yml
docker compose --env-file .env -f docker-compose.yml pull
docker compose --env-file .env -f docker-compose.yml up -d --force-recreate \
  xiaozhi-esp32-server xiaozhi-esp32-server-web
docker logs --since 5m xiaozhi-esp32-server
```

不要为了回滚本次修复而覆盖 MySQL、上传文件或整份 `data/.config.yaml`。如果升级后另外修改过模型配置，应按需逐项恢复，而不是整体覆盖。

## 发布前检查

该候选版本应通过 34 项 Python 单元测试，以及安装脚本和两套 Compose 静态检查：

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
bash -n deploy/install.sh
MYSQL_ROOT_PASSWORD=release-check \
  docker compose -f deploy/centos-stream-9/docker-compose.yml config --quiet
MYSQL_ROOT_PASSWORD=release-check \
  docker compose -f deploy/ubuntu/docker-compose.yml config --quiet
```
