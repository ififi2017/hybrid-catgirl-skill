# Proactive Messaging Cost Control

Proactive messaging can consume substantial model tokens even when no message is sent. The expensive part is the scheduled Agent invocation: every run loads the full system prompt, skills, tools, memory, and session context before the checker decides `send: false`. A checker that wakes an Agent every 10 minutes runs 144 times a day; in practice almost all of those runs end in "not yet".

## Don't wake the Agent unless a message is due

Hermes cron supports two ways to keep the Agent asleep:

1. **No-agent jobs** (`--no-agent --script <file>`): the script *is* the job. Its stdout is delivered verbatim; empty stdout is a silent tick; a non-zero exit sends an error alert. No model, no tokens. Use this when the message text is fully determined by the script — the Lonely Cat short-range stage (template messages) is exactly this.

   ```bash
   hermes cron create "every 5m" --no-agent --script lonely_cat_short.py \
     --deliver <platform>:<chat_id> --name lonely-cat-short
   ```

2. **Gate scripts** (`--script <file>` on an Agent job): the script runs first. If its last stdout line is `{"wakeAgent": false}` the scheduler skips the Agent run entirely; otherwise the script output is injected into the Agent's prompt. Use this when the Agent must write the message (the companion stage) but most ticks have nothing to do.

   ```bash
   hermes cron create "0 * * * *" --script lonely_cat_gate.py \
     --prompt "$(cat templates/proactive-message.prompt.md)" --deliver local --name lonely-cat-companion
   ```

The gate must be **read-only**: it must not consume a send slot, or a tick that wakes an Agent which then fails will silently lose a message.

Because both stay cheap when idle, the schedule can be as frequent as the behaviour needs (every 5 minutes for the short-range stage) without paying for empty runs. Scripts must live in `~/.hermes/scripts/`; the subprocess environment is sanitized, so scripts that need credentials should read them from a local file rather than inheriting the gateway's environment.

## Count a message only after it is sent

Earlier versions reserved the slot (incremented the daily count, set the next send time) *before* asking the Agent to write the message. If the Agent then failed — provider error, out of credits, timeout — the slot was gone and nothing was sent.

Instead:

1. When the checker decides a message may be sent, take a short **pending lock** (e.g. 50 minutes) so an overlapping tick doesn't start a second message. Don't touch the counters.
2. After the message is actually delivered, record it: append to the history, increment the count, schedule the next time.
3. If sending fails, the lock simply expires and the next tick retries.

`lxc_lonely_cat.py` implements this as `context` (lock + material) and `sent` (record).

## Back off when the user doesn't reply

A fixed interval keeps sending at the same rate to someone who isn't answering. Track the **unanswered streak** — proactive messages sent since the user's last real activity — and lengthen the interval as it grows (4h → 6h → 8h → 12h → 24h in `proactive_brain.py`), then stop after a cap and wait for the user. This both reduces cost and keeps the character from feeling pushy.

## Recent-activity source

Read the user's last real activity from Hermes's session store rather than file timestamps: `state.db` → `sessions.last_activity_at` for the target `chat_id`, excluding `cron` sessions, opened read-only. Session JSON/JSONL files lag behind and their directory can contain tens of thousands of cron files, which makes scanning them slow. Combine it with the timestamp your own `interact` command records and take the newer one.

A practical "just chatted" threshold is 75 minutes (60 + 15 safety buffer).

## Privacy and portability

Do not commit platform credentials, app secrets, private chat IDs, internal cron job IDs, or machine-specific paths. Read credentials from environment variables or a local secret file, and let users provide their own scheduler and target chat configuration. When feeding memory into proactive messages, filter out technical notes and anything intimate before it reaches the model (see `_TECH`, `_META`, `_INTIMATE` in `proactive_brain.py`).

## Estimating savings

If one Agent wake-up costs approximately `T` input tokens and the checker runs `N` times per day:

```text
estimated_daily_input = T × N
```

With a gate, `N` becomes the number of messages actually sent (a few per day at most) instead of the number of ticks. For example, 144 ticks/day × ~25k tokens ≈ 3.6M input tokens/day, versus 3–4 real sends × 25k ≈ 0.1M. Actual billing depends on the provider's prompt-cache and plan rules, so verify with usage data rather than treating this as an exact invoice calculation.
