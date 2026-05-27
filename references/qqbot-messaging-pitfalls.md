# QQ Bot Messaging Pitfalls

Session-specific reference for QQ bot messaging issues encountered during lonely cat mode operation.

## Issue: send_message Tool Fails with QQ Bot

### Symptom
```
{"error":"No home channel set for qqbot to determine where to send the message. 
Either specify a channel directly with 'qqbot:CHANNEL_NAME', 
or set a home channel via: hermes config set QQBOT_HOME_CHANNEL <channel_id>"}
```

### Attempted Fixes That Did NOT Work

1. **Setting config via CLI**:
   ```bash
   hermes config set QQBOT_HOME_CHANNEL 500844CE96B9EB6EA0ED397FA0569BE6
   # Result: Config updated in ~/.hermes/config.yaml (line 415) but send_message still fails
   # Error persists: "No home channel set for qqbot..."
   ```

2. **Using different target formats**:
   - `qqbot:500844CE96B9EB6EA0ED397FA0569BE6` - fails with same error
   - `qqbot:group:500844CE96B9EB6EA0ED397FA0569BE6` - fails (invalid target format)
   - Bare `qqbot` - fails even with QQBOT_HOME_CHANNEL set in config.yaml

3. **Environment variable**:
   ```bash
   export QQBOT_HOME_CHANNEL=500844CE96B9EB6EA0ED397FA0569BE6
   # Result: No effect on send_message tool in cron context
   ```

4. **HTTP API call**:
   ```python
   # Attempted direct POST to localhost:3000/send_group_msg
   # Result: Connection refused (qqbot service not running on expected port)
   ```

### Working Alternatives

Since `send_message` tool has issues with QQ bot in cron job contexts, the current workaround is:

1. **Output DEBUG info in the final response** - When running as a scheduled cron job, the final response IS the output mechanism. Include DEBUG messages in the response body.

2. **Direct API call** (if qqbot HTTP API is available):
   ```bash
   curl -X POST http://localhost:8080/send_group_msg \
     -H "Content-Type: application/json" \
     -d '{
       "group_id": "GROUP_ID",
       "message": "your message"
     }'
   ```

### Current State (2025-05-22)

The lonely cat checker script outputs JSON with `debug_messages` array when DEBUG mode is on. The cron job handler should:

1. Parse the script output
2. If `send: false` but has `debug_messages`, output them in the response
3. If `send: true`, output both DEBUG messages and the actual catgirl message

Example response format:
```
## 📋 LXC 寂寞小猫模式检查报告

**检查时间**: 2025-05-22 13:50:05

### DEBUG 输出
```
[🐱 DEBUG 13:50:05] 检查中 - 模式: catgirl, 已发送: 0次, 经过: 9.4分钟
[🐱 DEBUG 13:50:05] 条件不满足 - 还需等待 0.6 分钟 (目标: 10分钟, 已过: 9.4分钟)
```

### 状态摘要
- DEBUG 模式: 开启
- 猫娘消息: 未发送 (条件不满足)
- 下次联络: 还需 0.6 分钟
```

### Script Output Format (Real Example)

When DEBUG mode is enabled, the script outputs DEBUG lines followed by JSON:

```
[🐱 DEBUG 13:55:29] 检查中 - 模式: catgirl, 已发送: 0次, 经过: 14.8分钟
[🐱 DEBUG 13:55:29] ✅ 触发条件满足 - 准备发送第 1 次消息 (已等待 14.8 分钟)
{
  "send": true,
  "message": "主人～俺还想被rua喵...(｡•́︿•̀｡) 恁的手老得劲了...再来呗喵～(｡♥‿♥｡)",
  "target_platform": "qqbot",
  "target_chat": "500844CE96B9EB6EA0ED397FA0569BE6",
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

### Related Configuration

Config location: `~/.hermes/config.yaml`
```yaml
# Line 415 (may vary)
QQBOT_HOME_CHANNEL: 500844CE96B9EB6EA0ED397FA0569BE6
```

Channel directory: `~/.hermes/channel_directory.json`
```json
{
  "platforms": {
    "qqbot": [
      {
        "id": "500844CE96B9EB6EA0ED397FA0569BE6",
        "name": "500844CE96B9EB6EA0ED397FA0569BE6",
        "type": "group"
      }
    ]
  }
}
```

**Note**: Despite the channel being registered in channel_directory.json and QQBOT_HOME_CHANNEL being set in config.yaml, the send_message tool still fails in cron contexts. This appears to be a limitation of the tool when running non-interactively.

State files:
- `~/.hermes/state/lxc_lonely_cat.json` - Current mode, counters, timestamps
- `~/.hermes/state/lxc_chat_history.json` - Recent chat context
- `~/.hermes/state/lxc_debug.log` - DEBUG log history
