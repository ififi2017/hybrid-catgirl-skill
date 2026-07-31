# Proactive Messaging Cost Control

Proactive messaging can consume substantial model tokens even when no message is sent. The expensive part is usually the scheduled Agent invocation: every run may load the full system prompt, skills, tools, memory, and session context before the checker returns `send: false`.

## Recommended defaults

Use conservative schedules for an Agent-backed proactive checker:

```yaml
# Run the checker once per hour, rather than every few minutes.
schedule: "0 * * * *"
```

```python
# Keep actual proactive messages at least four hours apart.
MIN_INTERVAL = 240
MAX_INTERVAL = 240
```

The checker should still enforce both guards:

1. The scheduler controls how often an Agent is awakened.
2. The state file controls when a message may actually be reserved/sent.

Changing only the message interval does **not** reduce the cost of repeated no-op Agent runs.

## State reservation before generation

When a check decides that a message may be sent, reserve the slot before asking an Agent to generate text or before handing the result to a separate sender:

```python
new_count = state.get("proactive_count_today", 0) + 1
interval = random.randint(MIN_INTERVAL, MAX_INTERVAL)
next_time = now + timedelta(minutes=interval)
state["proactive_count_today"] = new_count
state["last_proactive_time"] = now.isoformat()
state["next_proactive_time"] = next_time.isoformat()
save_state(state)
```

This prevents a second checker invocation from seeing the same unreserved state and generating a duplicate message.

## Recent-activity guard

Use the most recent real user activity when deciding whether to send. If the gateway updates a live `session_*.json` file while the corresponding `.jsonl` transcript is delayed, prefer the live JSON file's modification time and exclude cron sessions from the scan.

A practical threshold is:

```python
RECENT_CHAT_THRESHOLD = 60
SAFETY_BUFFER = 15
# Skip proactive contact when elapsed minutes < 75.
```

## Privacy and portability

Do not commit platform credentials, app secrets, private chat IDs, internal cron job IDs, or machine-specific paths. Read credentials from environment variables or a local secret store, and let users provide their own scheduler and target chat configuration.

## Estimating savings

If one Agent wake-up costs approximately `T` input tokens and the checker runs `N` times per day:

```text
estimated_daily_input = T × N
```

Moving from every 10 minutes (144 runs/day) to hourly (24 runs/day) reduces the number of wake-ups by about 83%. Actual billing depends on the provider's prompt-cache and plan rules, so verify with usage data rather than treating this as an exact invoice calculation.
