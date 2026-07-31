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
│   └── lxc_lonely_cat.py           # 状态管理脚本
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

# 检查是否应该发送消息（cronjob 调用）
python3 ~/.hermes/scripts/lxc_lonely_cat.py check

# DEBUG 开关
python3 ~/.hermes/scripts/lxc_lonely_cat.py debug on|off

# 查看状态
python3 ~/.hermes/scripts/lxc_lonely_cat.py status
```

### Cronjob 配置

```yaml
name: lxc-lonely-cat-checker
schedule: "0 * * * *"  # 每小时检查一次（推荐）
```

**为什么使用每小时检查？**
- Agent-backed 检查即使返回“不发送”也会消耗模型 Token
- 每小时检查可显著减少空检查的上下文开销
- 实际消息间隔由状态文件继续控制，避免影响发送节奏
- 如果使用纯本地脚本且不唤醒 Agent，可以按需提高检查频率

更完整的成本分析和状态预留策略见 `references/proactive-cost-control.md`。

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

## Token 成本控制

如果由 Agent 执行定时检查，检查本身也会消耗模型 Token，即使最终返回“不发送”。因此不应只调整消息间隔，还要降低调度唤醒频率。

推荐将 Agent-backed 检查从每几分钟改为每小时一次，并将实际主动消息间隔设为更保守的值，例如 4 小时。详细原因、状态预留、防重复发送、实时 Session mtime 和隐私注意事项见 `references/proactive-cost-control.md`。
