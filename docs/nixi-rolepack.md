# 《逆袭》角色包接入小智

本功能把经过证据校订的 `nixi-roleplay` Claude Code Skill 编译为随
`xiaozhi-server` 部署的语音角色包。运行服务器不需要安装 Claude Code，
也不需要访问作者电脑上的 `H:` 盘。

## 为什么采用角色包

- 智控台的角色介绍输入框限制为 2000 字，完整人物规则无法直接粘贴。
- Claude Code Skill 含命令、调试和证据审计规则，不能原样塞给语音模型。
- 编译后的角色包只保留运行期需要的 canon、阶段、人物、关系与安全规则。
- 每个运行文件都有 SHA-256；文件被手改后加载器会拒绝启用该角色。
- 普通角色介绍不受影响；只有首个非空行是 `@rolepack` 时才进入角色包逻辑。

## 智控台配置

建议新建三个独立智能体。LLM 选择 `anthropic_messages`；吴所畏和池骋分别选择合适的
TTS 音色。把下面对应内容完整填入“角色介绍”。

吴所畏：

```text
@rolepack nixi/wu
canon=novel
stage=S7
audience=participant
psychology=off
```

池骋：

```text
@rolepack nixi/chi
canon=novel
stage=S7
audience=participant
psychology=off
```

双人模式：

```text
@rolepack nixi/duo
canon=novel
stage=S7
audience=observer
psychology=off
```

双人模式当前仍通过一个 TTS 实例输出，因此会朗读“吴所畏说”和“池骋说”来区分
声道，并不是真正的双音色。真正双音色需要在第二阶段增加按说话人拆句和 TTS 路由。

## 可用选项

| 选项 | 取值 | 说明 |
| --- | --- | --- |
| `canon` | `novel` / `drama` | 默认小说；两层不混用 |
| `stage` | 小说 `S1`–`S8`；剧版 `D1`–`D6` | 默认小说 S7、剧版 D6 |
| `audience` | `participant` / `observer` | 单人默认参与者，双人默认旁观者 |
| `psychology` | 只允许 `off` | TTS v1 不朗读私有心理 |
| `voice` | `default` / `novel` | 剧版使用 `novel` 时显式借用小说语气 |

剧版中性语言示例：

```text
@rolepack nixi/wu
canon=drama
stage=D6
voice=default
audience=participant
psychology=off
```

剧版大纲没有台词材料。`voice=default` 使用中性口语；`voice=novel` 只是跨层借用小说
语言规则，两者都不能声称生成内容是剧中原台词。

## 构建与更新

仓库内已经提交编译后的运行包：

```text
main/xiaozhi-server/rolepacks/nixi/
```

当权威 Skill 确认更新后，在仓库根目录执行：

```powershell
python tools/nixi_rolepack/build_nixi_rolepack.py `
  --skill-root "<nixi-roleplay目录>"
```

构建器先逐文件校验 `tools/nixi_rolepack/source_manifest.json` 中的源文件指纹，任何漂移
都会停止。需要先人工审核新 Skill、更新模板和源指纹，再重新构建，不能跳过审核直接继承。

## 运行边界

- v1 不写角色状态文件，也不修改证据库；新场景只存在于当前对话。
- 不会在生产环境读取小说正文、证据库或 `.claude/skills`。
- 当前 `stage` 是智能体配置，切阶段时修改角色介绍并新建会话，避免旧对话污染时间线。
- 测试阶段建议关闭长期记忆，确认人物稳定后再决定是否接入独立的会话记忆层。
- 角色包加载失败时会退回中性错误提示，不会拿半截提示继续扮演。

## 验证

```powershell
python -m unittest discover -s tests -p "test_nixi_rolepack.py" -v
python -m unittest discover -s tests -v
```

测试覆盖短指令解析、三模式展开、canon/stage 隔离、私有心理关闭、文件指纹防漂移、
构建确定性以及关键人物防串线规则。人物自然度与真实设备听感仍需在智控台分别绑定音色后
做人工语音验收。
