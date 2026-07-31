# Messaging Pitfalls

Reference for messaging issues encountered during lonely cat mode operation across different platforms.

## General Issue: send_message Tool Fails in Cron Context

### Symptom

The `send_message` tool may fail when running inside a cron job, regardless of platform. This is a common issue across all messaging integrations (QQ Bot, Feishu, Telegram, Discord, etc.).

### Common Error Pattern

```json
{"error":"No home channel set for <platform> to determine where to send the message.
Either specify a channel directly with '<platform>:CHANNEL_NAME',
or set a home channel via: hermes config set <PLATFORM>_HOME_CHANNEL <channel_id>"}
```

### Attempted Fixes That May NOT Work

1. **Setting config via CLI**:
   ```bash
   # May not take effect in cron context
   hermes config set <PLATFORM>_HOME_CHANNEL <channel_id>
   # Config updated but send_message still fails in cron
   ```

2. **Using different target formats**:
   - `platform:<channel_id>` - may fail with same error
   - `platform:group:<channel_id>` - may fail (invalid target format)
   - Bare `platform` - may fail even with home channel set

3. **Environment variable**:
   ```bash
   export <PLATFORM>_HOME_CHANNEL=<channel_id>
   # May have no effect on send_message tool in cron context
   ```

### Working Alternatives

Since `send_message` tool may have issues in cron job contexts, current workarounds:

1. **Output DEBUG info in the final response** - When running as a scheduled cron job, the final response IS the output mechanism. Include DEBUG messages in the response body.

2. **Direct API call** (if platform HTTP API is available):
   ```bash
   # Example: Generic webhook approach (adapt to your platform)
   curl -X POST <platform_api_endpoint> \
     -H "Content-Type: application/json" \
     -d '{"target": "<chat_id>", "message": "your message"}'
   ```

### Current State

The lonely checker script outputs JSON with `debug_messages` array when DEBUG mode is on. The cron job handler should:

1. Parse the script output
2. If `send: false` but has `debug_messages`, output them in the response
3. If `send: true`, output both DEBUG messages and the actual catgirl message

Example response format:
```
## 📋 猫猫 寂寞小猫模式检查报告

**检查时间**: 2026-05-22 13:50:05

### DEBUG 输出
```
[🐱 DEBUG 13:50:05] 检查中 - 模式: catgirl, 已发送: 0次, 经过: 9.4分钟
[🐱 DEBUG 13:50:05] 条件不满足 - 还需等待 0.6 分钟
```

### 状态摘要
- DEBUG 模式: 开启
- 猫娘消息: 未发送 (条件不满足)
- 下次联络: 还需 0.6 分钟
```

### Script Output Format (Example)

When DEBUG mode is enabled, the script outputs DEBUG lines followed by JSON:

```
[🐱 DEBUG 13:55:29] 检查中 - 模式: catgirl, 已发送: 0次, 经过: 14.8分钟
[🐱 DEBUG 13:55:29] ✅ 触发条件满足 - 准备发送第 1 次消息 (已等待 14.8 分钟)
{
  "send": true,
  "message": "主人～俺还想被rua喵...(｡•́︿•̀｡) 恁的手老得劲了...再来呗喵～(｡♥‿♥｡)",
  "target_platform": "<your_platform>",
  "target_chat": "<your_chat_id>",
  "debug_messages": [
    "[🐱 DEBUG 13:55:29] 检查中 - 模式: catgirl, 已发送: 0次, 经过: 14.8分钟",
    "[🐱 DEBUG 13:55:29] ✅ 触发条件满足 - 准备发送第 1 次消息 (已等待 14.8 分钟)"
  ]
}
```

**Parsing notes:**
- DEBUG lines are printed to stdout before the JSON
- Parse by splitting on newlines and finding the JSON object (starts with `{`)
- The `debug_messages` array contains the same DEBUG lines for easy output

### General Reliability Fixes

The proactive path should apply these rules regardless of the messaging platform:

1. **Reserve state before returning a send decision**. Update the counter and next-send timestamp before an Agent or separate sender handles the message. This prevents duplicate sends when checks overlap.
2. **Record the proactive message in chat history immediately**. Otherwise the next user reply lacks the message that prompted it.
3. **Bound chat history**. Keep a fixed number of recent entries so the local context file cannot grow without limit.
4. **Normalize escaped formatting**. Convert command-line `\\n` and `\\t` to real newlines and tabs before sending.

The repository's `scripts/proactive_state.py` provides dependency-free helpers for these operations:

```python
from proactive_state import append_message, normalize_message, reserve_slot

state = reserve_slot(state, interval_minutes=240)
history = append_message(history, "assistant", message)
message = normalize_message(message)
```

For Hermes gateway activity, prefer the newest non-cron `session_*.json` mtime and fall back to non-cron `.jsonl` files when the live JSON session is unavailable. See `proactive_state.latest_user_activity()`.

### Script Interface Reference

```bash
# Check if message should be sent (returns JSON)
python3 ~/.hermes/scripts/lxc_lonely_cat.py check

# Output format:
# {"send": false, "debug_messages": [...]}  - no message needed, but has debug
# {"send": true, "message": "...", "debug_messages": [...]}  - send message
# {}  - no action needed

# Get current status
python3 ~/.hermes/scripts/lxc_lonely_cat.py status

# Control DEBUG mode
python3 ~/.hermes/scripts/lxc_lonely_cat.py debug on
python3 ~/.hermes/scripts/lxc_lonely_cat.py debug off
```

### Platform-Specific Configuration

Each platform has its own configuration approach. Set the home channel in `~/.hermes/config.yaml`:

```yaml
# Replace <PLATFORM> with your platform name (QQBOT, FEISHU, TELEGRAM, DISCORD, etc.)
<PLATFORM>_HOME_CHANNEL: <channel_id>
```

Channel directory: `~/.hermes/channel_directory.json`
```json
{
  "platforms": {
    "<platform_name>": [
      {
        "id": "<channel_id>",
        "name": "<channel_name>",
        "type": "group"
      }
    ]
  }
}
```

**Note**: Despite channels being registered in channel_directory.json, the send_message tool may still fail in cron contexts. This appears to be a limitation of the tool when running non-interactively.

State files:
- `~/.hermes/state/lxc_lonely_cat.json` - Current mode, counters, timestamps
- `~/.hermes/state/lxc_chat_history.json` - Recent chat context
- `~/.hermes/state/lxc_debug.log` - DEBUG log history
