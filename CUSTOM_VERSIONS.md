# 版本选择说明

本仓库是
[xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)
的兼容版本仓库。不同版本使用独立分支，互不覆盖。

## 应该选择哪个版本

| 版本 | 分支 | 适合人群 |
| --- | --- | --- |
| 官方原版 | [`main`](https://github.com/zjwlmq/xiaozhi-esp32-server/tree/main) | 希望完全跟随官方代码，不需要新增兼容功能 |
| 火山 API Key 兼容版 | [`feat/volcengine-tts-api-key`](https://github.com/zjwlmq/xiaozhi-esp32-server/tree/feat/volcengine-tts-api-key) | 需要在火山双向流式 TTS 中使用新版 `X-Api-Key`，同时保留旧 AppID/Access Token 配置 |
| CentOS Stream 9 / Ubuntu Docker 部署 | [`feat/volcengine-tts-api-key`](https://github.com/zjwlmq/xiaozhi-esp32-server/tree/feat/volcengine-tts-api-key) | 使用同一兼容版程序，根据系统选择不同 Compose 和安装说明 |

> `main` 保留官方代码。自定义功能只进入对应分支，便于以后继续同步官方更新。

## 下载方法

### 方法一：直接下载固定版本

不熟悉 Git 的用户，建议从
[Releases](https://github.com/zjwlmq/xiaozhi-esp32-server/releases)
页面选择版本并下载 Source code 压缩包。

### 方法二：克隆指定分支

官方原版：

```bash
git clone --branch main --single-branch \
  https://github.com/zjwlmq/xiaozhi-esp32-server.git
```

火山 API Key 兼容版：

```bash
git clone --branch feat/volcengine-tts-api-key --single-branch \
  https://github.com/zjwlmq/xiaozhi-esp32-server.git
```

## 火山 API Key 兼容版说明

兼容版为双向流式 TTS 增加 `api_key` 配置：

- 填写 `api_key` 时，使用新版请求头 `X-Api-Key`。
- `api_key` 留空时，继续使用旧版 AppID/Access Token 请求头。
- 支持 `seed-tts-1.0` 与 `seed-tts-2.0` 资源。
- 智控台模型配置中增加 API Key 输入项。
- 音色列表明确显示“湾湾小何”（1.0）与“小何2.0”（2.0）。

已有配置如果使用 `volc.service_type.10029` 且运行正常，不需要强制修改；新建配置
可按音色版本选择 `seed-tts-1.0` 或 `seed-tts-2.0`。

仓库不会保存用户的 API Key。密钥应在部署完成后通过智控台填写，不要写入提交、
Issue、截图或公开配置文件。

## Docker 部署说明

CentOS 与 Ubuntu 不是两套程序版本。二者使用同一个 API Key 兼容版，只根据宿主机
选择不同部署入口：

- [CentOS Stream 9 部署](./deploy/centos-stream-9/README.md)
- [Ubuntu 22.04/24.04 部署](./deploy/ubuntu/README.md)
- [更换服务器与数据迁移](./deploy/MIGRATION.md)

部署文件固定引用本仓库发布的版本化 Docker 镜像，避免误用官方镜像而缺少
API Key 功能。

## 更新原则

1. `main` 用于同步官方仓库。
2. 通用功能先更新到 `feat/volcengine-tts-api-key`。
3. CentOS 与 Ubuntu 的部署文件在同一兼容分支维护。
4. 固定、可复现的候选版本通过 `volc-api-key-v1.0.0-rc.1` 标签和 GitHub
   Pre-release 发布。
