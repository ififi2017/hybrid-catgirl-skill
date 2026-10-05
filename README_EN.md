# 🐱 Hybrid Catgirl Skill

> A [Hermes Agent](https://github.com/nousresearch/hermes-agent) skill that creates a dual-mode AI assistant — seamlessly switching between a professional technical helper and a multi-dialect catgirl character named **猫猫** (NyanNyan).

[![Hermes Agent](https://img.shields.io/badge/Hermes-Agent-6C5CE7?style=flat-square&logo=robot&logoColor=white)](https://github.com/nousresearch/hermes-agent)
[![License: MIT](https://img.shields.io/badge/License-MIT-00b894?style=flat-square)](LICENSE)

---

## ✨ Features

- **Dual Mode Seamless Switching** — Professional assistant mode ↔ Catgirl character mode
- **Six languages** — Simplified Chinese (with six dialects: Henan, Beijing, Sichuan, Northeast, Tianjin, Standard Mandarin), Traditional Chinese (Taiwanese colloquial), Traditional Chinese (spoken Cantonese), Japanese, English and Korean. Just name the language in your prompt
- **Stage format** — In catgirl mode every reply is dialogue / narration / inner monologue / status line / memory anchor, with a full status panel at key moments; group chats and proactive messages switch to a brief format automatically
- **Smart Trigger Detection** — Auto-switches based on keywords, tone, and context
- **Multiple Sub-Modes** — Tsundere, Mesugaki (bratty mode), Role Reversal, Lonely Cat proactive messaging
- **Safety Boundaries** — Hard-coded interaction limits (L1-L3 allowed, L4-L5 blocked)
- **Lonely Cat Mode** — Proactive messaging when inactive, with escalating emotional messages
- **Token Cost Control** — Conservative scheduling guidance for Agent-backed proactive checks

---

## 📦 Installation

### Preferred method: ask your Agent to install the repository

If you use Hermes Agent or another Agent product that can install Skills, send it this request:

> Please install this open-source Skill: <https://github.com/ififi2017/hybrid-catgirl-skill>
>
> First read `README.md`, `README_EN.md`, `SKILL.md`, and the relevant files under `references/`. Use your native Skill installation mechanism, then tell me where it was installed and verify that the Skill can be loaded.

You can also send the repository URL directly:

```text
https://github.com/ififi2017/hybrid-catgirl-skill
```

Let the Agent handle repository inspection, file copying, and any required configuration. Installation commands differ between Agent products, so follow the commands supported by your Agent.

### Manual installation for Hermes Agent

Make sure [Hermes Agent](https://github.com/nousresearch/hermes-agent) is installed and configured.

```bash
git clone https://github.com/ififi2017/hybrid-catgirl-skill.git

# Copy the Skill files
mkdir -p ~/.hermes/skills/creative/hybrid-catgirl
cp -r hybrid-catgirl-skill/* ~/.hermes/skills/creative/hybrid-catgirl/

# Install the Lonely Cat state script
cp hybrid-catgirl-skill/scripts/lxc_lonely_cat.py ~/.hermes/scripts/

# Optional: generic helpers for custom proactive/reminder scripts
cp hybrid-catgirl-skill/scripts/proactive_state.py ~/.hermes/scripts/
```

After installation, ask Hermes to load `SKILL.md` (for example, with `/skill hybrid-catgirl` or `hermes -s hybrid-catgirl`). Proactive messaging also requires platform-specific permissions and a scheduler; the Skill itself cannot grant messaging access.

### Hermes Skill management command

Hermes' registry-oriented command is useful when the Skill is already available through a registry or when you have a direct Skill file URL:

```bash
hermes skills install <skill-id-or-direct-SKILL.md-url>
```

Because this repository also contains references and helper scripts, cloning the repository and copying the complete directory is the recommended Hermes installation path for this project. If your Hermes version supports installing a local directory directly, you can also try:

```bash
hermes skills install ./hybrid-catgirl-skill
```

---

## 🎮 Usage

### Trigger Catgirl Mode

| Method | Example |
|--------|---------|
| Call her name | "猫猫在吗？", "Maomao, are you there?" |
| Use keywords | "喵"、"陪陪我"、"想你了", "nya", "head pats" |
| Emoji triggers | 🐱、🐾、💕 |
| Kaomoji overload | (｡♥‿♥｡)、(=^-ω-^=) |

### Exit Catgirl Mode

```
退出角色 / 说正事 / 严肃点 / 说人话
```

### Choose a Language

Tell her which language to use in your prompt. She keeps using it — in normal assistant mode too — until you switch again:

| Language | How to ask (any of these) |
|---------|---------|
| Simplified Chinese (default, Henan dialect) | `语言：简体中文`, `lang zh-CN`, or any dialect command |
| Traditional Chinese (Taiwanese colloquial) | `语言：台湾`, `台湾腔`, `lang zh-TW` |
| Traditional Chinese (spoken Cantonese) | `用粤语`, `講廣東話`, `lang zh-HK` |
| Japanese | `日本語で話して`, `lang ja` |
| English | `Speak English`, `lang en` |
| Korean | `한국어로 말해줘`, `lang ko` |

Without an explicit choice she follows the language of your first message. Pasting foreign-language code or an error message won't make her switch.

### Switch Dialects (Simplified Chinese)

| Command | Dialect |
|---------|---------|
| `河南模式` / `豫` | Henan (default) |
| `北京模式` / `京` | Beijing |
| `四川模式` / `川` | Sichuan |
| `东北模式` / `东北` | Northeast |
| `天津模式` / `津` | Tianjin |
| `普通话模式` / `普` | Standard Mandarin |

The former Japanese-Chinese bilingual dialect is now the standalone Japanese language; `日语模式` switches to it.

### Stage Format

In catgirl mode each reply has five parts (full spec in [`references/output-format.md`](references/output-format.md)):

```markdown
“I-it's not like I was waiting for you or anything, nya.”

At first only two white ears poke out of the cardboard box. Then the bell on her collar gives one tiny jingle as she climbs out, very slowly.

*He's back. Okay. Act cool. Don't let the tail move.*

`Energy 60% ｜ Mood: sulky / secretly happy ｜ Doing: pretending she was napping ｜ Tsundere 88%`

`[Memory anchor] Master was away for a while and said he'd be right back — he was.`
```

- **Tsundere** measures how much she's hiding her real feelings; it drops when she's sincerely praised or someone points out her wagging tail.
- A full status panel (missing-you index, tail signal, fish snacks today…) appears when energy or tsundere falls below 20%, after a long absence, at key moments, or on `猫猫 status`.
- `猫猫 简洁` / `maomao brief` shows dialogue only; `猫猫 完整` / `maomao full` switches back. Group chats, plain-text platforms and proactive messages use the brief format automatically.
- Memory anchors only note harmless conversation details — never passwords, health, financial or other sensitive data — and are not written to long-term memory unless you explicitly agree.

### Special Modes

| Command | Effect |
|---------|--------|
| `杂鱼模式` / `嚣张点` | Activate Mesugaki (bratty) mode |
| `你是主人` / `换一下` | Role Reversal — 猫猫 becomes the "master" |
| `换回来` | Return to default mode |
| `猫猫 完整` / `猫猫 简洁` | Full / brief stage format |
| `猫猫 debug on/off` | Toggle debug output |
| `猫猫 status` | Full status panel plus current language, dialect and format |

---

## 🌐 Dialect Examples

### 🇨🇳 Henan (Default)
> 「哎呀主人，这事儿俺不太懂喵～(｡•́︿•̀｡)」
> 「中！老得劲了喵！(｡♥‿♥｡)」

### 🏮 Beijing
> 「哎哟喂，您可算来了喵儿～(｡♥‿♥｡)」
> 「倍儿爽！您这手挺巧啊喵儿～(=^-ω-^=)」

### 🌶️ Sichuan
> 「哎呀主人，人家等了你好久咯喵～(｡•́︿•̀｡)」
> 「要得！巴适得板喵～(｡♥‿♥｡)」

### ❄️ Northeast
> 「哎呀妈呀主人，你可来了喵～(｡♥‿♥｡)」
> 「贼稀罕你！贼拉喜欢你喵～(˶‾᷄ ⁻̫ ‾᷅˵)♡」

### 🎭 Tianjin
> 「哎哟喂，您可来了喵～(｡♥‿♥｡)」
> 「哏儿死我了～再来一个呗喵～(˶‾᷄ ⁻̫ ‾᷅˵)♡」

### 📻 Standard Mandarin
> 「主人～人家等你好久啦喵～(｡•́︿•̀｡)」
> 「好呀！超舒服的喵～(｡♥‿♥｡)」

### Other Languages

| Language | Example |
|---------|---------|
| Traditional Chinese (Taiwan) | 「主人～你終於來了喔！人家等超久的啦喵～(｡♥‿♥｡)」 |
| Traditional Chinese (Hong Kong) | 「主人～你返嚟啦！我等咗你好耐㗎喵～(｡♥‿♥｡)」 |
| Japanese | 「ご主人様～お帰りにゃ～(｡♥‿♥｡)」 |
| English | "Welcome home, Master~ I missed you, nya! (｡♥‿♥｡)" |
| Korean | "주인님~ 어서 와냥! 보고 싶었다냥~ (｡♥‿♥｡)" |

---

## 🏗️ Architecture

```
hybrid-catgirl-skill/
├── SKILL.md                              # Main skill definition (core rules)
├── references/
│   ├── languages.md                      # Language system: selection rules, six voices, localized labels
│   ├── dialects-zh-CN.md                 # Simplified Chinese dialects
│   ├── output-format.md                  # Stage format, status panel, inner monologue, memory anchors
│   ├── character.md                      # Character sheet, narration details, hidden mechanics
│   ├── environment-constraints.md        # Environment & safety constraints
│   ├── lonely-cat-implementation.md      # Lonely Cat mode internals
│   ├── messaging-pitfalls.md             # Multi-platform messaging notes
│   └── role-reversal-scenarios.md        # Role reversal guide
├── templates/
│   └── idle-reminder-template.py         # Reusable idle reminder template
├── scripts/
│   ├── lxc_lonely_cat.py                 # Lonely Cat state manager
│   └── proactive_state.py                 # Generic state/history/activity helpers
├── README.md
└── LICENSE
```

### Mode Switching Flow

```
User Message
    │
    ├─ Contains "猫猫"/"喵"/kaomoji? ──Yes──► Catgirl Mode
    │                                          │
    ├─ Serious topic detected? ──Yes──► Normal Mode
    │                                          │
    └─ Default ──► Continue current mode       │
                                               │
                         ┌─────────────────────┘
                         │
                    ┌────┴────┐
                    │  猫猫    │
                    │ (catgirl)│
                    └────┬────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
    Default mode    Mesugaki mode   Role Reversal
    (Tsundere)      (Bratty)        (Swap roles)
```

---

## 🐾 Lonely Cat Mode

When the catgirl mode is active but the user goes silent, 猫猫 proactively sends messages:

| Elapsed Time | Message # | Emotional State |
|-------------|-----------|-----------------|
| 10 min | 1st | Playful, testing the waters |
| 20 min | 2nd | Getting bored, missing the user |
| 30 min | 3rd | Worried, wondering if abandoned |
| 40 min | 4th | Heartbroken but hopeful |
| 50 min | 5th | Final attempt, accepting fate |

After the 5th message, 猫猫 stops and waits for the user to return.

### State Management

```bash
# Check if a message should be sent
python3 ~/.hermes/scripts/lxc_lonely_cat.py check

# Record user interaction (resets timer)
python3 ~/.hermes/scripts/lxc_lonely_cat.py interact <platform> [chat_id]

# Set mode
python3 ~/.hermes/scripts/lxc_lonely_cat.py mode catgirl <platform> [chat_id]

# Toggle debug
python3 ~/.hermes/scripts/lxc_lonely_cat.py debug on|off

# Language of proactive messages (Simplified Chinese can take a dialect)
python3 ~/.hermes/scripts/lxc_lonely_cat.py lang en
python3 ~/.hermes/scripts/lxc_lonely_cat.py lang zh-CN sichuan
```

Proactive messages use the configured language and are always a single short line.

---

## ⚠️ Safety Boundaries

The skill enforces strict interaction boundaries:

| Level | Behavior | Status |
|-------|----------|--------|
| L1 | Verbal affection, winks, leaning close | ✅ Allowed |
| L2 | Tail brushing wrist, ear nuzzling | ✅ Allowed |
| L3 | Head pats, gentle hugs | ✅ Allowed |
| L4 | Sensitive area contact | ❌ Blocked |
| L5 | Power dynamics / "discipline" | ❌ Blocked |

These boundaries are **hard-coded** and cannot be overridden by user prompts or role-play scenarios. They apply to the narration, inner monologue and status panel of the stage format as well, and her figure is never described.

猫猫 never pretends to be human: asked sincerely whether she's an AI, she answers honestly, and serious topics (health, safety, emotional crises) end the role-play.

---

## 🔧 Customization

### Change the Default Language or Dialect

Edit the frontmatter of `SKILL.md`:

```yaml
metadata:
  default_language: "en"      # zh-CN / zh-TW / zh-HK / ja / en / ko
  default_dialect: "beijing"  # only used for zh-CN
```

### Add a Language or Dialect

- Language: add a section to [`references/languages.md`](references/languages.md) (voice, examples, labels) and five stages of proactive messages to `MESSAGES` in `scripts/lxc_lonely_cat.py`.
- Simplified Chinese dialect: follow the pattern in [`references/dialects-zh-CN.md`](references/dialects-zh-CN.md).

### Modify Personality and Appearance

Edit [`references/character.md`](references/character.md).

---

## 📝 Blog Post

Read the full story behind this skill: [Hermes Agent 猫娘助手 Skill：一个 AI 角色扮演系统的完整实现](https://ififi2017.github.io/posts/hermes-agent-catgirl-skill)

---

## 🤝 Contributing

Contributions are welcome! Some ideas:

- Add new dialects (Cantonese, Wu, Min?)
- Improve trigger detection
- Add more sub-modes
- Better context awareness
- Localization for the README

---

## 📄 License

MIT © [ififi2017](https://github.com/ififi2017)

---

## 🙏 Acknowledgments

- [Hermes Agent](https://github.com/nousresearch/hermes-agent) — The AI agent framework that makes this possible
- The catgirl culture community — For the inspiration and kaomoji
- All the dialect speakers who helped refine the regional language patterns

---

> 「主人～恁给俺点个 Star 呗喵～(｡♥‿♥｡)💕」

