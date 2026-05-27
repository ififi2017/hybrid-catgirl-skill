# Environment Constraints Reference

Session-specific notes about environment limitations discovered during lxc-lonely-cat debugging (2025-05-22).

## Network Access

**Status**: ❌ No external network access

**Evidence**:
```bash
# All outbound HTTP requests timeout
curl -I https://www.google.com  # Timeout after 50s
wget https://dl.google.com/...   # Connection fails
```

**Impact**:
- Cannot install packages requiring download (Chrome, Chromium via snap)
- Cannot use web search or browser navigation tools
- Cannot fetch external APIs or webpages

**Workaround**:
- Use local tools only
- Pre-install required packages in container image
- User must copy-paste external information

## Browser Installation

**Status**: ❌ No browser available

**Attempted**:
1. `apt install chromium-browser` - Installs snap wrapper, but snap download fails (no network)
2. Download Chrome .deb directly - wget fails (no network)
3. Check for existing Chrome/Chromium - Not found

**Error Pattern**:
```
Auto-launch failed: Chrome exited early
No usable sandbox! 
If you are running on Ubuntu 23.10+ or another Linux distro 
that has disabled unprivileged user namespaces with AppArmor...
```

**Resolution**: Use `--no-sandbox` flag if browser is ever installed (container/VM environment).

## Tool Availability

**Available**:
- `terminal` - Local command execution
- `skill_view`, `skill_manage` - Skill introspection
- `cronjob` - Scheduled tasks (local only)
- `send_message` - Messaging platforms (local only, requires config)

**Not Available**:
- `browser_navigate` - Requires Chrome/Chromium
- Web search - Requires network
- External API calls - Require network

## State Persistence

**Working Directory**: `~/.hermes/`

**State Files** (working):
- `~/.hermes/state/lxc_lonely_cat.json` - JSON state storage ✓
- `~/.hermes/state/lxc_chat_history.json` - Chat context ✓
- `~/.hermes/state/lxc_debug.log` - Debug logging ✓

**Config Files** (working):
- `~/.hermes/config.yaml` - Read/write access ✓
- `~/.hermes/channel_directory.json` - Messaging platform channels ✓

## Cron Job Environment

**Working**:
- Cron jobs can be created and execute
- Local script execution (`python3 ...`)
- Response output as message mechanism

**Limitations**:
- `send_message` tool may not work with messaging platforms in cron context
- Must output content directly in response
- No interactive prompts available

## Implications for Future Sessions

1. **Don't attempt web searches** - Will always fail
2. **Don't try to install browsers** - Will always fail  
3. **Use copy-paste for external info** - User must provide
4. **Prefer local tools** - terminal, file operations work fine
5. **State management works** - Use JSON files for persistence

## Related Notes

- See `messaging-pitfalls.md` for multi-platform messaging issues
- See `lonely-cat-implementation.md` for state machine design
