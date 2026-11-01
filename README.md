# 猫猫 · Hermes Agent Skill 与插件

本仓库提供猫猫的公共人设、Skill 和 Hermes Agent 插件。**插件仅适用于 Hermes Agent**：它们使用 Hermes 的插件注册、消息网关、模型工具及会话钩子，不能直接安装到其他 Agent 框架。

## 包含什么

- `SKILL.md`：功能使用指南；[persona.md](plugins/maomao-companion/persona.md) 是角色与聊天语气的唯一编辑来源。
- `maomao-companion`：人设注入、分气泡规则、显式语音授权、普通记忆、语义检索和可选的后台阅读组件。
- `maomao-qq`：独立 QQ 连接器、分群图片描述与表情图库、发送额度与恢复去重。
- `maomao-private`：飞书和 Telegram 私聊适配器封装及可选的普通私聊图库；名称表示私聊渠道。
- `scripts/`：旧版主动联系脚本，是否适配现有网关和定时器须自行验证。插件不会自动建立主动消息定时器。

这是从实际运行环境整理出的公共组件。不同 Hermes 版本的插件 API 可能有差异，请先在测试配置中验证。仓库不包含运行状态、账号绑定、聊天记录、媒体图库或 API Key。

## 安装

先安装并完成 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 的平台和模型配置。以下在当前 `HERMES_HOME`（默认 `~/.hermes`）安装，插件目录名必须与示例一致：

```bash
git clone https://github.com/ififi2017/hybrid-catgirl-skill.git
cd hybrid-catgirl-skill
HERMES_PROFILE="${HERMES_HOME:-$HOME/.hermes}"
mkdir -p "$HERMES_PROFILE/plugins" "$HERMES_PROFILE/skills/creative/hybrid-catgirl"
cp -R plugins/maomao-companion "$HERMES_PROFILE/plugins/"
cp SKILL.md "$HERMES_PROFILE/skills/creative/hybrid-catgirl/"
cp -R references "$HERMES_PROFILE/skills/creative/hybrid-catgirl/"
# 可选：按实际渠道安装；先看下文的前置条件。
cp -R plugins/maomao-qq "$HERMES_PROFILE/plugins/"
cp -R plugins/maomao-private "$HERMES_PROFILE/plugins/"
```

在该 profile 的 `config.yaml` 的现有 `plugins.enabled` 列表中**合并**要启用的插件，不要覆盖已有项。例如：

```yaml
plugins:
  enabled:
    - maomao-companion
    # 仅在对应 profile 使用：
    # - maomao-qq
    # - maomao-private
```

重启对应 Hermes 网关，检查日志中插件是否成功加载。`maomao-companion` 在模型调用前加载公共人设，即使平台设置了跳过 SOUL 文件扫描；避免在 SOUL 或其他 Skill 再写一套相互冲突的语气规则。多个 profile 需要分别安装，并在修改人设后同步、重启。

## 模型与密钥

使用 `hermes model` 交互式选择主要模型和提供商，或按所用 Hermes 版本修改 `config.yaml`：

```yaml
model:
  provider: openrouter
  default: your-provider/your-chat-model
```

把占位值换成你的提供商支持的聊天模型，并按 Hermes 官方方法配置凭据；不要把真实密钥写入仓库。图片理解模型通过 Hermes 的 `auxiliary.vision` 配置，须选择**支持图片输入**的模型；Embedding 模型不能当聊天模型或识图模型。

插件自己的普通模型白名单是 `$HERMES_PROFILE/state/maomao-companion/config.json` 中的 `context.allowed_models`。更改主模型后同步修改白名单，否则受保护的记忆、表情判断和梗搜索提示可能不会启用。无配置时，这些功能默认不启动，人设仍会注入。下面仅是结构示例，标识符请从自己平台的可信配置中获取，**不要提交填好的文件**：

```json
{
  "enabled": true,
  "authorization": {"mode": "standalone"},
  "target": {"platform": "feishu", "chat_type": "dm", "chat_id": "YOUR_CHAT_ID", "user_id": "YOUR_USER_ID"},
  "context": {
    "enabled": true,
    "allowed_models": ["your-provider/your-chat-model"],
    "embedding": {"enabled": false, "model": "qwen/qwen3-embedding-8b", "query_seconds": 2, "threshold": 0.5, "daily_limit": 200}
  },
  "channels": [],
  "life": {"enabled": false},
  "background": {"enabled": false}
}
```

创建 `state/maomao-companion` 后将配置保存为 `config.json`，设置适当的文件访问权限。`authorization.mode: standalone` 明确开启公开版的私聊授权：只有 Hermes 已准入、与 `target` 的平台、私聊和用户 ID 均匹配的消息才获得 5 分钟的进程内授权；模型白名单与当前会话匹配仍须同时通过。授权不会在进程重启后保留，也不能通过聊天正文取得。移除该选项即回到默认关闭。外部模型处理应先获得参与者授权。

独立授权只用于没有其他会话授权扩展的独立公开 profile；如果当前 profile 已存在 `state/maomao-companion/session-policy.json`，独立授权会保持关闭，避免覆盖宿主的已有隔离策略。不要通过删除该文件绕过现有策略。

如需让同一人的飞书和 Telegram **共享普通记忆与私聊图库**，在配置中增加 `private_members`，分别填写两条平台可信身份（每项包含 `platform`、`chat_type: dm`、`chat_id`、`user_id`）。`target` 仍作为共享作用域的主绑定；不应把不同人的账号绑定到同一作用域。QQ 群和 QQ 私聊不会加入这个作用域。QQ 分群记忆另由 `channels` 指定可信平台、群 ID 和类型。后台浏览仍有独立开关和调度前提，不因启用私聊记忆而自动启动。

可先完成平台配对并发一条测试消息，再在自己的 Hermes profile 的 `sessions/sessions.json` 中查找该会话的 `origin`，核对 `platform`、`chat_type`、`chat_id`、`user_id`；以实际运行版本提供的可信平台元数据为准。这些标识及该文件属于运行数据，保留在本机，不要上传仓库或发进群聊。公开版普通记忆独立保存在当前 profile 的 `state/maomao-companion/` 下。

Embedding 默认关闭。当前实现只接受 `qwen/qwen3-embedding-8b` 或 `baai/bge-m3`、1024 维，使用 OpenRouter 上固定的 DeepInfra 路由；改成不受支持的模型不会生效。启用前确认供应商可用、成本、数据处理约定和相关参与者授权。

提供的语音适配器名为 `maomao-gemini`，图像适配器名为 `maomao-google`，从运行环境读取 `GEMINI_API_KEY` 或 `GOOGLE_API_KEY`。在 `config.yaml` 选择提供商：

```yaml
tts:
  provider: maomao-gemini
  auto_tts: false
image_gen:
  provider: maomao-google
```

当前这两个适配器的模型 ID（分别为 `gemini-3.8-flash-tts`、`gemini-nano-banana-2.1`）及语音 `Aoede` 写在 `plugins/maomao-companion/maomao_companion/providers.py` 中，**不是任意模型/音色的配置入口**。如要更换，需修改适配器并验证目标 API 与协议；也可以改用 Hermes 自带的其他提供商。语音回复要求当前用户明确请求，或符合插件识别到的明确后续请求。

## QQ 和私聊接入

QQ 使用独立 profile 和网关，只启用一个 QQ 连接器，不能同时运行内置 QQ 连接器。群内希望各成员共享一段对话，可在该独立 QQ profile 的 `config.yaml` 顶层设置 `group_sessions_per_user: false`；不同群和私聊仍应保持隔离。迁移既有会话前备份配置及状态，核对来源和身份。

先按 Hermes 的 QQ 平台配置方式设置应用凭据（`QQ_APP_ID`、`QQ_CLIENT_SECRET`）、群访问策略及允许的群。QQ 机器人还需要有接收群全部消息的权限，并实际收到 `GROUP_MESSAGE_CREATE`；仅收到 @ 事件时无法判断未 @ 消息。只有取得群内参与者同意后才启用主动判断，因为近期群消息片段会发送给配置的模型：

```json
{
  "autonomous": {
    "enabled": true,
    "group_messages_to_model": true,
    "groups": ["YOUR_GROUP_OPENID"]
  },
  "vision_enabled": false,
  "collect_enabled": false,
  "embedding_enabled": false
}
```

将上面的文件保存为该 QQ profile 的 `state/maomao-qq/config.json`。默认不主动接话；三个条件（启用、明确允许发给模型、群在白名单）缺一不可。新话题每群间隔至少 10 分钟、每小时最多 3 次；同一成员对猫猫近期回复的追问可更快判断。为控制模型调用，每群每小时最多判断 60 次（重启后计数重置）。模型判断失败、消息已过时或群里已有进行中的回复时跳过。@ 消息正常进入回复流程。关闭可将 `enabled` 改为 `false`。

QQ 连接器对已准入的群消息会在本地按群保留近期文本观察记录（最多 1000 条、7 天），用于对话上下文；停止主动判断不会自动删除这些记录。请按群内约定管理该 profile 的 `state/maomao-qq/` 数据。

可在 QQ profile 的受保护环境中设置 `QQ_OWNER_OPENID` 为平台提供的主人**成员 openid**，区分主人和群友；这是机器人收到的成员标识，不是可由聊天内容证明的身份。留空时不识别主人。插件在每轮使用准入事件的当前发送者，拒绝仅凭昵称或正文冒充主人；群会话共享时也不复用上一位发言人的身份。

图片识别、收藏、Embedding 分别在 QQ profile 的 `state/maomao-qq/config.json` 中使用 `vision_enabled`、`collect_enabled`、`embedding_enabled` 控制，默认关闭。开始前须配置识图服务、获取参与者授权，并为图库和群聊数据制定保留策略。

`maomao-private` 封装的是已配置的 Hermes 飞书和 Telegram 连接器；要启用其普通私聊图库，须启用上面的独立授权，并正确绑定对应账号。不要重复启动同一账号的连接器。授权缺失或过期时，私聊图库和相关记忆功能保持关闭。

## 验证与限制

```bash
python3 -m unittest discover -s plugins/maomao-companion/tests -q
python3 -m unittest discover -s plugins/maomao-qq/tests -q
```

部分 QQ 测试需要 Pillow；原生网关集成测试还需要与目标部署匹配的 Hermes Python 环境。测试使用合成数据，不会连接平台或发送消息。联网搜索由模型按提示决定，颜文字约四次回复一次也是提示词目标，二者均不是严格概率或每轮保证。

## 许可证

仓库采用 [MIT](LICENSE)。QQ 传输代码保留 [Hermes 上游许可](plugins/maomao-qq/LICENSE.hermes)。
