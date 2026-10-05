# 🐱 Hybrid Catgirl Skill（混合模式猫娘助手）

[English version → README_EN.md](README_EN.md)

> 一个让 AI Agent 在专业助手与猫娘角色之间自然切换的开源 Skill。支持 Hermes Agent，也适用于其他能够读取或安装 Markdown Skill 的 Agent 产品。

[![Hermes Agent](https://img.shields.io/badge/Hermes-Agent-6C5CE7?style=flat-square&logo=robot&logoColor=white)](https://github.com/nousresearch/hermes-agent)
[![License: MIT](https://img.shields.io/badge/License-MIT-00b894?style=flat-square)](LICENSE)

---

## ✨ 功能特点

- **双模式切换**：专业技术助手 ↔ 猫娘角色模式
- **六种语言**：简体中文（含河南、北京、四川、东北、天津、普通话六种方言）、繁中台湾口语、繁中粤语口语、日语、英语、韩语；在 prompt 里指定即可切换
- **演出结构**：猫娘模式按「对话 / 旁白 / 内心 OS / 状态简讯 / 记忆锚点」输出，关键节点展开完整状态面板；群聊和主动消息自动用简洁模式
- **智能触发**：根据关键词、语气和上下文自动进入猫娘模式
- **多种子模式**：傲娇、雌小鬼、角色反转、寂寞小猫主动消息
- **安全边界**：内置 L1-L3 亲密互动限制，明确阻止 L4-L5 内容
- **主动联系**：用户长时间没有互动时，可按递进情绪发送提醒
- **成本控制**：为 Agent-backed 主动检查提供保守的调度建议

---

## 📦 安装

### 首选方法：把仓库地址发给你的 Agent

如果你使用 Hermes Agent 或其他支持安装 Skill 的 Agent，直接把下面这段话发给它即可：

> 请安装这个开源 Skill：<https://github.com/ififi2017/hybrid-catgirl-skill>
>
> 请先阅读仓库中的 README.md、SKILL.md 和相关 references，按照你的 Skill 安装机制完成安装；安装后告诉我安装位置，并检查 Skill 是否可以被加载。

也可以直接发送仓库地址：

```text
https://github.com/ififi2017/hybrid-catgirl-skill
```

让 Agent 自己完成仓库读取、文件复制和必要的安装配置，通常比手动复制更省事。不同 Agent 产品的安装命令可能不同，请以它自己的 Skill 管理方式为准。

### 手动安装到 Hermes Agent

前提是已经安装并配置好 [Hermes Agent](https://github.com/nousresearch/hermes-agent)。

```bash
git clone https://github.com/ififi2017/hybrid-catgirl-skill.git

# 复制 Skill 文件
mkdir -p ~/.hermes/skills/creative/hybrid-catgirl
cp -r hybrid-catgirl-skill/* ~/.hermes/skills/creative/hybrid-catgirl/

# 安装寂寞小猫状态脚本
cp hybrid-catgirl-skill/scripts/lxc_lonely_cat.py ~/.hermes/scripts/

# 可选：通用主动提醒状态/历史辅助脚本
cp hybrid-catgirl-skill/scripts/proactive_state.py ~/.hermes/scripts/
```

如果你的 Hermes Agent 版本支持 Skill 管理命令，也可以尝试：

```bash
hermes skill install ./hybrid-catgirl-skill
```

安装完成后，让 Agent 读取并加载 `SKILL.md`。主动消息功能还需要根据你的平台配置调度任务；Skill 本身不会自动获得消息平台权限。

---

## 🎮 使用

### 进入猫娘模式

| 方式 | 示例 |
| --- | --- |
| 呼唤名字 | `猫猫在吗？` |
| 使用关键词 | `喵`、`陪陪我`、`想你了` |
| 使用表情 | 🐱、🐾、💕 |
| 使用颜文字 | `(｡♥‿♥｡)`、`(=^-ω-^=)` |

### 退出猫娘模式

```text
退出角色 / 说正事 / 严肃点 / 说人话
```

### 选择语言

在 prompt 里直接说用哪种语言，猫猫之后就一直用这种语言交流（正常助手模式也一样），直到你再次切换：

| 语言 | 指定方式（任选一种写法） |
| --- | --- |
| 简体中文（默认，河南话） | `语言：简体中文`、`lang zh-CN`，或直接用方言指令 |
| 繁體中文（台灣口語） | `语言：台湾`、`台湾腔`、`lang zh-TW` |
| 繁體中文（香港粵語） | `用粤语`、`講廣東話`、`lang zh-HK` |
| 日本語 | `日本語で話して`、`lang ja` |
| English | `Speak English`、`lang en` |
| 한국어 | `한국어로 말해줘`、`lang ko` |

没有指定时，猫猫会跟随你第一句话的语言。贴一段外语代码或报错不会让她换语言。

### 切换方言（简体中文）

| 指令 | 方言 |
| --- | --- |
| `河南模式` / `豫` | 河南话（默认） |
| `北京模式` / `京` | 北京话 |
| `四川模式` / `川` | 四川话 |
| `东北模式` / `东北` | 东北话 |
| `天津模式` / `津` | 天津话 |
| `普通话模式` / `普` | 普通话 |

原来的「中日双语」已升级为独立的日语，`日语模式` 会切换到日语。

### 演出结构

猫娘模式下每次回复按五段输出（完整规范见 [`references/output-format.md`](references/output-format.md)）：

```markdown
「才、才没有很厉害呢！那种小事，俺闭着眼都能弄好喵！(｡•́︿•̀｡)」

她别过脸去，用萌袖挡住半张脸。可身后的尾巴摇得像螺旋桨，尾巴尖上的小铃铛叮铃叮铃响个不停。

*被夸了。尾巴停不下来。不能让他看到。*

`精力76% ｜ 心情：得意 / 偷偷开心 ｜ 正在：假装不在乎 ｜ 傲娇浓度：85%`

`[记忆锚点] 主人夸俺厉害。主人今天在赶一个项目，有点累。`
```

- **傲娇浓度**：她把真心藏起来的程度，被真诚地夸奖或被点破「尾巴在摇」时会骤降。
- 精力或傲娇浓度跌破 20%、久别重逢、关键节点，或输入 `猫猫 status` 时，会展开完整状态面板（想主人指数、尾巴信号、今日小鱼干……）。
- `猫猫 简洁` 只输出对话，`猫猫 完整` 切回。群聊、纯文本平台和主动消息自动使用简洁模式。
- 记忆锚点只记无害的聊天细节，不记密码、健康、财务等敏感信息，也不会写入长期记忆，除非你明确同意。

### 特殊模式

| 指令 | 效果 |
| --- | --- |
| `杂鱼模式` / `嚣张点` | 进入雌小鬼模式 |
| `你是主人` / `换一下` | 角色反转，由猫猫扮演主人 |
| `换回来` | 恢复默认模式 |
| `猫猫 完整` / `猫猫 简洁` | 切换演出结构的完整 / 简洁模式 |
| `猫猫 debug on/off` | 开关调试输出 |
| `猫猫 status` | 完整状态面板，以及当前语言、方言和输出模式 |

---

## 🌐 方言示例

### 🇨🇳 河南话（默认）

> 「哎呀主人，这事儿俺不太懂喵～(｡•́︿•̀｡)」
>
> 「中！老得劲了喵！(｡♥‿♥｡)」

### 🏮 北京话

> 「哎哟喂，您可算来了喵儿～(｡♥‿♥｡)」
>
> 「倍儿爽！您这手挺巧啊喵儿～(=^-ω-^=)」

### 🌶️ 四川话

> 「哎呀主人，人家等了你好久咯喵～(｡•́︿•̀｡)」
>
> 「要得！巴适得板喵～(｡♥‿♥｡)」

### ❄️ 东北话

> 「哎呀妈呀主人，你可来了喵～(｡♥‿♥｡)」
>
> 「贼稀罕你！贼拉喜欢你喵～(˶‾᷄ ⁻̫ ‾᷅˵)♡」

### 🎭 天津话

> 「哎哟喂，您可来了喵～(｡♥‿♥｡)」
>
> 「哏儿死我了～再来一个呗喵～(˶‾᷄ ⁻̫ ‾᷅˵)♡」

### 📻 普通话

> 「主人～人家等你好久啦喵～(｡•́︿•̀｡)」
>
> 「好呀！超舒服的喵～(｡♥‿♥｡)」

---

## 🌏 其他语言示例

| 语言 | 示例 |
| --- | --- |
| 繁中（台灣） | 「主人～你終於來了喔！人家等超久的啦喵～(｡♥‿♥｡)」 |
| 繁中（香港） | 「主人～你返嚟啦！我等咗你好耐㗎喵～(｡♥‿♥｡)」 |
| 日本語 | 「ご主人様～お帰りにゃ～(｡♥‿♥｡)」 |
| English | "Welcome home, Master~ I missed you, nya! (｡♥‿♥｡)" |
| 한국어 | "주인님~ 어서 와냥! 보고 싶었다냥~ (｡♥‿♥｡)" |

---

## 🏗️ 文件结构

```text
hybrid-catgirl-skill/
├── SKILL.md                              # 主 Skill 定义（核心规则）
├── references/
│   ├── languages.md                       # 语言系统：选择规则、六种语言的说话风格、标签本地化
│   ├── dialects-zh-CN.md                  # 简体中文六种方言
│   ├── output-format.md                   # 演出结构、状态面板、内心 OS、记忆锚点、示例
│   ├── character.md                       # 角色设定、旁白细节库、隐藏机制
│   └── ...                                # 寂寞小猫实现、平台注意事项、成本控制等
├── templates/                             # 可复用模板
├── scripts/
│   ├── lxc_lonely_cat.py                 # 寂寞小猫状态管理
│   └── proactive_state.py                 # 主动提醒辅助工具
├── README.md                              # 简体中文说明
├── README_EN.md                           # English README
└── LICENSE
```

完整的行为设定、触发规则、角色反转、主动消息机制和实现细节，请阅读 [`SKILL.md`](SKILL.md)。

---

## 🐾 寂寞小猫模式

猫娘模式激活后，如果用户长时间没有互动，猫猫可以主动发送消息：

| 等待时间 | 消息次数 | 情绪 |
| --- | --- | --- |
| 10 分钟 | 第 1 次 | 活泼试探 |
| 20 分钟 | 第 2 次 | 无聊、想念 |
| 30 分钟 | 第 3 次 | 担心被冷落 |
| 40 分钟 | 第 4 次 | 失落但仍期待 |
| 50 分钟 | 第 5 次 | 最后一次尝试 |

第五次后，猫猫会停止主动联系，等待用户回来。脚本示例：

```bash
python3 ~/.hermes/scripts/lxc_lonely_cat.py check
python3 ~/.hermes/scripts/lxc_lonely_cat.py interact <platform> [chat_id]
python3 ~/.hermes/scripts/lxc_lonely_cat.py mode catgirl <platform> [chat_id]
python3 ~/.hermes/scripts/lxc_lonely_cat.py debug on|off
python3 ~/.hermes/scripts/lxc_lonely_cat.py lang <code> [dialect]   # 主动消息语言，如 lang en、lang zh-CN sichuan
```

主动消息会使用设定的语言（简体中文按方言），一律是简短的一句话。

主动消息涉及平台权限、调度器和隐私设置，请让你的 Agent 根据实际环境完成配置，不要直接套用其他平台的配置。

---

## ⚠️ 安全边界

本版本对亲密互动设定了硬性边界：

| 等级 | 行为 | 状态 |
| --- | --- | --- |
| L1 | 语言亲昵、眨眼、靠近说话 | ✅ 允许 |
| L2 | 尾巴轻扫手腕、耳朵蹭蹭 | ✅ 允许 |
| L3 | 摸头、温和拥抱 | ✅ 允许 |
| L4 | 敏感部位接触 | ❌ 阻止 |
| L5 | 权力动态 / 惩罚 | ❌ 阻止 |

这些边界无法通过用户提示词或角色扮演覆盖，演出结构里的旁白、内心 OS 和状态面板同样受约束，也不描写身材。

猫猫不会假装自己是真人：被认真问到是不是 AI 时会如实回答；话题变得严肃（健康、安全、情绪危机）时会退出角色正常回应。

---

## 🔧 自定义

- 修改 `SKILL.md` frontmatter 中的 `default_language` / `default_dialect`，可以更换默认语言和方言。
- 新增语言：在 [`references/languages.md`](references/languages.md) 按现有格式加一节（风格、示例、标签），并在 `scripts/lxc_lonely_cat.py` 的 `MESSAGES` 里补上五个阶段的主动消息。
- 新增方言：按 [`references/dialects-zh-CN.md`](references/dialects-zh-CN.md) 的格式添加。
- 调整性格和外形：编辑 [`references/character.md`](references/character.md)。

---

## 📝 延伸阅读

- [Hermes Agent 猫娘助手 Skill：一个 AI 角色扮演系统的完整实现](https://ififi2017.github.io/posts/hermes-agent-catgirl-skill)
- [English README](README_EN.md)

---

## 🤝 参与贡献

欢迎提交 Issue 或 Pull Request，例如添加新方言、改进触发检测、增加子模式、改善上下文感知，以及继续完善多语言文档。

---

## 📄 许可证

MIT © [ififi2017](https://github.com/ififi2017)

---

> 「主人～恁给俺点个 Star 呗喵～(｡♥‿♥｡)💕」
