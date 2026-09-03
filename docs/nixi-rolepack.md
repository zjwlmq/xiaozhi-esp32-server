# 《逆袭》角色包接入小智

本功能把经过证据校订的 `nixi-roleplay` Claude Code Skill 编译为随
`xiaozhi-server` 部署的语音角色包。运行服务器不需要安装 Claude Code，
也不需要访问作者电脑上的 `H:` 盘。

## 为什么采用角色包

- 智控台的角色介绍输入框限制为 2000 字，完整人物规则无法直接粘贴。
- Claude Code Skill 含命令、调试和证据审计规则，不能原样塞给语音模型。
- 编译后的角色包只保留运行期需要的人物底色、初始阶段、关系与安全规则。
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

这里的 `canon` 是兼容既有指令的选项名，运行时只把它当作“人物底色来源”。
`stage` 也只是新生活开始时的关系状态，不是故事停止的时间点。角色在开始交互后按
服务器当前日期继续生活，后来由用户确认的经历不会被小说或剧版材料否定。

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

## 持续生活记忆

如需让三个人物随着长期交流越来越了解用户，请在智控台分别打开吴所畏、池骋和双人
智能体，把“记忆模式”都选为 **《逆袭》持续生活记忆**。三个智能体必须属于同一个
智控台账号；服务端会用账号 ID 共享同一条家庭时间线，而不是按设备或智能体各存一份。

记忆遵循以下状态：

- 用户明确说已经发生的事，才能记为共同经历。
- 人物自己提出、用户尚未接受的安排，只记为“待确认”。
- 用户接受未来安排后记为“计划中”；日期到了也不会自动冒充已经完成。
- 用户确认已经发生、取消或改期后，才更新相应状态。
- 吴所畏单人模式只能读取家庭共享记忆和吴所畏私有记忆；池骋同理；双人模式只读取和
  写入家庭共享记忆，不能借双人模型偷看任何一方的私密内容。

角色回复会在进入字幕和 TTS 前经过最后一道过滤。正常扮演不会用角色声音说“原作没写”、
“证据不足”、“根据小说”等幕后审计话术；对没有确认过的往事，会自然地否认、表示
不记得、追问，或者把它转成今后的邀请。

记忆在一次会话关闭时提取并原子写入：

```text
main/xiaozhi-server/data/nixi_life_memory/<账号ID>/nixi-family.json
```

Docker 部署使用现有 `data` 挂载，因此重建容器不会丢失。当前第一版已经支持持久化、
计划状态和三模式共享/隔离，但还没有智控台里的记忆查看、纠错、置顶和删除页面；在该
页面完成前不要直接手改运行中的 JSON 文件。

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

- 不修改小说/剧版证据库；角色包材料只塑造人物，新的生活由持续记忆单独保存。
- 不会在生产环境读取小说正文、证据库或 `.claude/skills`。
- 当前 `stage` 是初始关系配置；已经产生持续生活记忆后，不要靠切换 `stage` 回滚时间线。
- 持续记忆必须配合有效的《逆袭》角色包和账号授权上下文；普通智能体即使误选该记忆
  模型也会 fail closed，不会创建家庭记忆文件。
- 角色包加载失败时会退回中性错误提示，不会拿半截提示继续扮演。

## 验证

```powershell
python -m unittest discover -s tests -p "test_nixi_rolepack.py" -v
python -m unittest discover -s tests -p "test_nixi_life_memory.py" -v
python -m unittest discover -s tests -v
```

测试覆盖短指令解析、三模式展开、canon/stage 隔离、私有心理关闭、文件指纹防漂移、
构建确定性、动态日期、幕后措辞的流式拦截、记忆证据校验、计划状态以及共享/私有记忆
隔离。人物自然度、记忆提取质量与真实设备听感仍需在智控台分别绑定音色后做人工语音验收。
