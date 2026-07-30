# 火山 API Key + Anthropic Messages v1.0.0-rc.6

`volc-anthropic-v1.0.0-rc.6` 是组合版候选发布，包含火山双向流式 TTS API Key 兼容、Anthropic Messages 原生协议适配，以及天气工具调用死路修复。

## 本次修复

此前基础提示词假定本地未来 7 天天气一定已经预取成功，并要求本地天气问题绝不调用 `get_weather`。当预取超时、接口失败、城市无效或缓存中只有失败文本时，模型既没有可用天气事实，又被禁止调用工具，最终可能直接猜测、拒答或停在工具调用前。

rc.6 将规则改为按天气上下文的实际状态处理：

- 只有上下文中存在有效、未过期，并且覆盖所问地点和日期范围的本地天气时，才允许直接回答；
- 用户明确说出地点时，即使该地点与设备本地城市相同，也调用 `get_weather`；
- 预取缺失、失败、超时、已过期，或地点、日期范围不匹配时，必须调用 `get_weather`；
- 空值、“请求失败”、“未找到相关城市”等失败结果不再作为天气事实写入提示词，无效缓存会被清理；
- 用户没有提供地点时，工具可省略 `location`，由客户端 IP 或默认地点补全；
- `lang` 不再是调用方必须显式提供的参数，未提供时继续使用 `zh_CN`。

这项修改不会改变天气供应商、API Key 保存位置或正常天气缓存格式，也不修改数据库结构、智控台字段和用户保存的模型配置。

## 发布镜像

```text
ghcr.io/zjwlmq/xiaozhi-esp32-server:server_volc-anthropic-1.0.0-rc.6
ghcr.io/zjwlmq/xiaozhi-esp32-server:web_volc-anthropic-1.0.0-rc.6
```

Server 与 Web 应使用同一个候选版本，不要只升级其中一个镜像。

## 升级

先确认 GitHub Actions 已完成两个 rc.6 多架构镜像的发布。以下示例使用默认安装目录 `/opt/xiaozhi-server`；自定义目录请同步替换。

```bash
cd /opt/xiaozhi-server
cp .env ".env.before-rc.6"
cp docker-compose.yml "docker-compose.yml.before-rc.6"
cp data/.config.yaml "data/.config.yaml.before-rc.6"
docker inspect --format '{{.Config.Image}}' xiaozhi-esp32-server
docker inspect --format '{{.Config.Image}}' xiaozhi-esp32-server-web

curl -fL \
  https://raw.githubusercontent.com/zjwlmq/xiaozhi-esp32-server/volc-anthropic-v1.0.0-rc.6/deploy/install.sh \
  -o /tmp/xiaozhi-install-rc.6.sh
less /tmp/xiaozhi-install-rc.6.sh
sudo env XIAOZHI_INSTALL_DIR=/opt/xiaozhi-server \
  bash /tmp/xiaozhi-install-rc.6.sh
```

安装脚本会更新 `.env` 中的 Server/Web 镜像，并保留现有 MySQL、上传文件和应用配置。天气、火山 TTS 与 LLM 的 API Key 继续由智控台或私有配置保存，不要写入命令、截图或 GitHub。

## 验证

先确认两个容器实际使用 rc.6：

```bash
docker inspect --format '{{.Config.Image}}' xiaozhi-esp32-server
docker inspect --format '{{.Config.Image}}' xiaozhi-esp32-server-web
```

实时观察天气预取与工具调用日志：

```bash
docker logs -f --since 30s xiaozhi-esp32-server 2>&1 \
  | grep --line-buffered -E '初始化组件: llm|大模型收到用户消息|function_name=get_weather|获取天气信息失败|天气工具未返回有效天气信息|发送第一段语音|LLM stream processing error'
```

在智控台为智能体选择“大模型自主函数调用”，确认 `get_weather` 已启用，然后依次测试：

1. 天气预取成功后询问“明天天气怎么样”，不指定地点。若上下文确实覆盖明天，应直接根据有效本地天气回答。
2. 询问“广州明天天气怎么样”。即使设备位置也是广州，也应调用 `get_weather`，再根据工具结果回答。
3. 在天气预取缺失或失败的环境询问“明天天气怎么样”。模型应调用 `get_weather`，并在未指定地点时省略 `location`，由工具使用客户端 IP 或默认地点。
4. 询问另一个城市或超出上下文日期范围的天气。模型应调用 `get_weather`，不应使用不匹配的本地天气猜测。

正常结果应生成最终文字和语音；日志中不应出现 `LLM stream processing error`。如果天气接口本身不可用，可以返回明确的工具失败结果，但模型不应再因提示词禁止调用而停在没有数据的死路。

## 回滚

本次没有数据库迁移，回滚镜像时不需要恢复 MySQL。先在智控台把智能体主语言模型切回升级前可用的 LLM，再恢复升级前备份的部署文件：

```bash
cd /opt/xiaozhi-server
cp ".env.before-rc.6" .env
cp "docker-compose.yml.before-rc.6" docker-compose.yml
docker compose --env-file .env -f docker-compose.yml pull
docker compose --env-file .env -f docker-compose.yml up -d --force-recreate \
  xiaozhi-esp32-server xiaozhi-esp32-server-web
docker logs --since 5m xiaozhi-esp32-server
```

不要为了回滚本次修复而覆盖 MySQL、上传文件或整份 `data/.config.yaml`。如果升级后另外修改过天气插件或模型配置，应按需逐项恢复，而不是整体覆盖。

## 发布前检查

该候选版本应通过 40 项 Python 单元测试，以及安装脚本和两套 Compose 静态检查：

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
bash -n deploy/install.sh
MYSQL_ROOT_PASSWORD=release-check \
  docker compose -f deploy/centos-stream-9/docker-compose.yml config --quiet
MYSQL_ROOT_PASSWORD=release-check \
  docker compose -f deploy/ubuntu/docker-compose.yml config --quiet
```
