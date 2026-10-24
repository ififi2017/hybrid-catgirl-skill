# 寂寞小猫模式实现文档

## 概述

寂寞小猫模式（Lonely Cat Mode）是 hybrid-catgirl 技能的一个扩展功能，当猫娘模式激活但长时间无互动时，猫猫 会主动发送消息表达对主人的思念。

## 核心机制

### 时间梯度设计

| 触发次数 | 间隔时间 | 情感曲线 |
|---------|---------|---------|
| 第1次 | 10分钟 | 试探性撒娇（活泼） |
| 第2次 | 20分钟 | 开始寂寞（想念） |
| 第3次 | 30分钟 | 失落担心（焦虑） |
| 第4次 | 40分钟 | 心碎边缘（悲伤） |
| 第5次 | 50分钟 | 最后尝试（绝望） |

**为什么是累加而不是固定间隔？**
- 累加设计（10→30→60→100→150分钟总计）更符合真实情感曲线
- 避免过于频繁的打扰
- 给用户足够的响应窗口

### 状态机设计

```
                    ┌─────────────────────────────────────┐
                    │                                     │
                    ▼                                     │
┌─────────┐    ┌──────────┐    ┌──────────────┐         │
│  normal │───▶│ catgirl  │───▶│ 计时器运行    │         │
│ (初始)  │    │ (进入)   │    │ (10min→...)  │         │
└─────────┘    └──────────┘    └──────────────┘         │
     ▲                               │                    │
     │                               ▼                    │
     │                         ┌──────────────┐          │
     │                         │ 发送消息     │          │
     │                         │ (重置计时)   │──────────┘
     │                         └──────────────┘
     │
     └──────────────────────────────────
       用户回复 / 退出 catgirl 模式
```

## 技术实现

### 文件结构

```
~/.hermes/
├── skills/creative/hybrid-catgirl/
│   ├── SKILL.md                    # 主技能文档
│   └── references/
│       └── lonely-cat-implementation.md  # 本文档
├── scripts/
│   ├── lxc_lonely_cat.py           # 状态管理脚本
│   ├── proactive_brain.py          # 陪伴模式素材：阶段、话题、记忆钩子、日历
│   ├── proactive_state.py          # 通用小工具
│   ├── lonely_cat_short.py         # cron 入口：短程阶段（no-agent）
│   └── lonely_cat_gate.py          # cron 入口：陪伴模式闸门
└── state/
    ├── lxc_lonely_cat.json         # 运行状态
    ├── lxc_chat_history.json       # 聊天记录（用于个性化消息）
    └── lxc_debug.log              # DEBUG 日志
```

### 状态文件格式

```json
{
  "last_interaction_time": "2026-05-22T13:40:23.000000",  // ISO 格式
  "message_count": 0,                                      // 已发送次数 (0-5)
  "mode": "catgirl",                                       // normal | catgirl
  "last_message_time": null,                               // 上次发送时间
  "target_platform": "<your_platform>",                   // 目标平台（feishu/telegram/qqbot/discord等）
  "target_chat": "<your_chat_id>",     // 目标聊天ID
  "debug": true                                           // DEBUG 开关
}
```

### 脚本命令

```bash
# 设置模式（进入/退出猫娘模式时调用）
python3 ~/.hermes/scripts/lxc_lonely_cat.py mode <normal|catgirl> <platform> [chat_id]

# 记录用户互动（重置计时器）
python3 ~/.hermes/scripts/lxc_lonely_cat.py interact <platform> [chat_id]

# 检查是否应该发送消息（短程阶段；cron 用 lonely_cat_short.py 调它）
python3 ~/.hermes/scripts/lxc_lonely_cat.py check

# 陪伴模式：闸门 / 给 Agent 的素材 / 发送成功后记账
python3 ~/.hermes/scripts/lxc_lonely_cat.py gate
python3 ~/.hermes/scripts/lxc_lonely_cat.py context
python3 ~/.hermes/scripts/lxc_lonely_cat.py sent "<message>"

# DEBUG 开关
python3 ~/.hermes/scripts/lxc_lonely_cat.py debug on|off

# 查看状态
python3 ~/.hermes/scripts/lxc_lonely_cat.py status

# 设置主动消息的语言（与 SKILL.md 的语言系统一致；zh-CN 可带方言）
python3 ~/.hermes/scripts/lxc_lonely_cat.py lang <zh-CN|zh-TW|zh-HK|ja|en|ko> [henan|beijing|sichuan|dongbei|tianjin|putong]
```

### Cronjob 配置

两个任务都用 Hermes 的“脚本前置”能力，**不需要发消息的时候完全不唤醒 Agent**：

```bash
# 1) 短程阶段（10–50 分钟模板消息）：no-agent，脚本到点时只输出消息正文，调度器原样投递；
#    没到点不输出 = 静默。不耗 Token，可以每 5 分钟跑一次。
hermes cron create "every 5m" --no-agent --script lonely_cat_short.py \
  --deliver <platform>:<chat_id> --name lonely-cat-short

# 2) 陪伴模式（短程 5 条发完后仍没回复，由 Agent 写消息）：闸门脚本判断不需要发时输出
#    {"wakeAgent": false}，调度器跳过 Agent；需要发时 Agent 按提示词模板执行。
hermes cron create "0 * * * *" --script lonely_cat_gate.py \
  --prompt "$(cat ~/.hermes/skills/creative/hybrid-catgirl/templates/proactive-message.prompt.md)" \
  --deliver local --name lonely-cat-companion
```

`--script` 只接受 `~/.hermes/scripts/` 下的文件名，所以要把 `scripts/` 里的 `lxc_lonely_cat.py`、`proactive_brain.py`、`proactive_state.py`、`lonely_cat_short.py`、`lonely_cat_gate.py` 一起复制过去。

更完整的成本分析见 `references/proactive-cost-control.md`。

## 陪伴模式：主人长时间没回复

短程 5 条发完、主人仍没回复时，模板消息会越来越重复（只能围着最后一段聊天撒娇）。陪伴模式改由 Agent 写消息，素材由 `scripts/proactive_brain.py` 准备，目标是“像一个在过自己日子、也惦记着对方的人”：

| 连续未回复 | 阶段 | 长度上限 | 发出后间隔 | 语气 |
|---|---|---|---|---|
| 0 | 想你了 | 120 字 | 4 小时 | 接上最近聊过的事或记忆里的细节 |
| 1 | 换个话头 | 100 字 | 6 小时 | 不再追着旧话题，换成自己的小事、问个小问题 |
| 2 | 自己找乐子 | 80 字 | 8 小时 | 讲自己做的一件小事，不追问为什么不回 |
| 3 | 小声报平安 | 60 字 | 12 小时 | 很短，不撒娇不抱怨 |
| 4 | 安静陪着 | 40 字 | 24 小时 | 一天一句，不要求回复 |
| 5 | 最后留言 | 50 字 | — | 说一声先不打扰，等主人忙完 |

连续 6 条没回就停，主人任意回复（`interact`）即全部重置、回到短程阶段。夜间 23:00–08:00 不发。

每次 `context` 给 Agent 的素材：

- **`topic_seed`**：从 11 个话题里轮换（猫猫的日常小事、天气、吃饭、起来活动、小问题、冷知识、一句话小游戏、记忆回调、周末、早安、晚安），按时段和工作日 / 周末筛选，避开最近 4 次用过的。
- **`memory_hooks`**：从 Hermes 记忆（`USER.md` / `MEMORY.md`）里挑 1–2 条主人的生活小事，自动过滤技术配置、凭据线索、扮演规则和亲密细节；最近两条消息用过的不再挑。记忆越丰富，话头越多。
- **`calendar`**：日期、星期、季节、时段、今天或明天的节日。
- **`recent_proactive_messages`**：最近 6 条主动消息，模型不能重复它们的开头、意象和话题。
- **`recent_chat_context`**：只在前两个阶段、且最后一次真实聊天在 48 小时内时提供，避免几天后还反复提同一件事。

记账时机：`context` 只占一个 50 分钟的“写消息中”锁，**不预扣发送名额**；Agent 发送成功后调用 `sent` 才计入历史并排下一次时间。发送失败时锁过期，下一小时自动重试，不会白白占掉一条。

最后一次真实互动时间取 `interact` 记录的时间和 Hermes 会话库（`state.db` 里该聊天的 `last_activity_at`，只读）中较新的一个。

## 消息个性化

### 上下文感知

脚本会分析最近10条聊天记录，识别互动类型：

| 关键词 | 触发个性化消息 |
|--------|---------------|
| rua, 顺毛, 摸, 揉, 抱 | "俺还想被rua喵..." |
| 亲, 吻, 啵 | "俺还想被亲额头喵..." |
| 欺负, 逗, 坏 | "俺以后乖乖的不顶嘴了..." |

### 情感递进实现

```python
messages = {
    0: [  # 活泼想念
        "主人～主人还在不喵？",
        "俺老想恁了呗...",
    ],
    1: [  # 寂寞撒娇
        "...主人去哪儿了喵...",
        "俺老无聊了...",
    ],
    # ... 依此类推
}
```

## DEBUG 模式

### 设计目的

- 帮助用户理解系统运行状态
- 便于排查问题（为什么没收到消息？）
- 提供透明的运行日志

### 输出格式

统一格式：`[🐱 DEBUG HH:MM:SS] 内容`

### 典型输出示例

```
[🐱 DEBUG 13:40:23] 模式切换: normal → catgirl | 计时器已启动
[🐱 DEBUG 13:45:02] 检查中 - 模式: catgirl, 已发送: 0次, 经过: 4.7分钟
[🐱 DEBUG 13:45:02] 条件不满足 - 还需等待 5.3 分钟
[🐱 DEBUG 13:50:15] 检查中 - 模式: catgirl, 已发送: 0次, 经过: 9.8分钟
[🐱 DEBUG 13:50:15] 条件不满足 - 还需等待 0.2 分钟
[🐱 DEBUG 13:55:01] 检查中 - 模式: catgirl, 已发送: 0次, 经过: 14.6分钟
[🐱 DEBUG 13:55:01] ✅ 触发条件满足 - 准备发送第 1 次消息
```

## 边缘情况处理

### 1. 快速退出

**场景**: 用户进入猫娘模式后2分钟就退出

**处理**: 未达到10分钟阈值，不会发送消息
**状态**: 计时器暂停，保留已发送次数

### 2. 重复进入

**场景**: 用户退出后再次进入

**处理**: 重置计时器，保留之前的已发送次数
**原因**: 避免重复发送相同消息

### 3. 达到5次上限

**场景**: 已发送5次消息但仍无回复

**处理**: 停止主动联络，等待用户主动发起
**原因**: 避免骚扰

### 4. 状态文件损坏

**场景**: JSON 格式错误或文件丢失

**处理**: 自动重置为初始状态
```python
if not os.path.exists(STATE_FILE):
    return default_state()
```

### 5. 时间跳跃

**场景**: 系统时间被手动修改

**处理**: 依赖单调时间（不需要，因为只是简单的比较）
**注意**: 如果系统时间回退，可能导致意外触发

## 故障排查指南

### 问题：一直收不到消息

**检查清单**:
1. 状态文件是否存在？
   ```bash
   cat ~/.hermes/state/lxc_lonely_cat.json
   ```

2. 当前模式是否为 catgirl？
   ```bash
   python3 ~/.hermes/scripts/lxc_lonely_cat.py status
   ```

3. DEBUG 是否开启？查看目标聊天是否有检查信息

4. Cronjob 是否运行？
   ```bash
   cronjob list
   ```

**快速诊断**:
```bash
# 模拟15分钟无互动
cat > ~/.hermes/state/lxc_lonely_cat.json << 'EOF'
{
  "last_interaction_time": "$(date -d '15 minutes ago' -Iseconds)",
  "message_count": 0,
  "mode": "catgirl",
  "last_message_time": null,
  "target_platform": "<your_platform>",
  "target_chat": "<your_chat_id>",
  "debug": true
}
EOF

python3 ~/.hermes/scripts/lxc_lonely_cat.py check
```

### 问题：收到太多消息

**可能原因**:
- 状态文件被测试数据污染（message_count 异常）
- Cronjob 重复运行

**解决**:
```bash
# 重置状态
python3 ~/.hermes/scripts/lxc_lonely_cat.py mode normal <platform>
python3 ~/.hermes/scripts/lxc_lonely_cat.py mode catgirl <platform> <chat_id>
```

## 扩展建议

### 1. 添加更多个性化维度

```python
# 可以基于时间（早上/晚上）生成不同消息
hour = datetime.now().hour
if 6 <= hour < 12:
    messages = morning_messages
elif 18 <= hour < 24:
    messages = evening_messages
```

### 2. 情绪记忆

记录用户上次的反应，调整下次消息的"黏人程度":
- 如果用户很快回复 → 下次可以更活泼
- 如果用户很久才回复 → 下次更收敛

### 3. 多平台适配

寂寞小猫模式支持任意消息平台，通过 `target_platform` 字段指定。支持的平台包括但不限于：

- `qqbot` - QQ 机器人
- `feishu` - 飞书
- `telegram` - Telegram
- `discord` - Discord
- 任何其他 Hermes 支持的消息平台

配置示例：
```json
{
  "target_platform": "<your_platform>",
  "target_chat": "<your_chat_id>"
}
```

## 相关文件

- 主脚本: `~/.hermes/scripts/lxc_lonely_cat.py`
- 状态文件: `~/.hermes/state/lxc_lonely_cat.json`
- 技能文档: `~/.hermes/skills/creative/hybrid-catgirl/SKILL.md`
- 消息平台参考: `references/messaging-pitfalls.md`
- Token 成本控制参考: `references/proactive-cost-control.md`
- 通用状态辅助函数: `scripts/proactive_state.py`
- 陪伴模式素材: `scripts/proactive_brain.py`
- 陪伴模式提示词: `templates/proactive-message.prompt.md`

## Token 成本控制

Agent 执行的定时检查即使最终“不发送”也会消耗模型 Token（每次唤醒都要加载系统提示、Skill、记忆）。所以短程阶段用 no-agent 脚本任务，陪伴模式用只读闸门脚本，只有真的要写消息时才唤醒 Agent。详见 `references/proactive-cost-control.md`。

## 多语言

- 状态文件新增 `lang`（默认 `zh-CN`）和 `dialect`（默认 `henan`，仅 zh-CN 使用）。没有这两个字段的旧状态文件按河南话处理，无需迁移。
- 主人切换语言或方言时，Agent 同时运行 `lang <code> [dialect]`，主动消息就会换成对应语言。
- 五个阶段的消息池在 `scripts/lxc_lonely_cat.py` 的 `MESSAGES` 里；个性化变体（刚被摸过、刚被逗过）在 `PERSONAL` 里。
- 主动消息一律是简洁模式的一句话，不带旁白、内心 OS、状态栏和记忆锚点。

