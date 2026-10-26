---
phase: 10
title: "Create anti-spam"
status: code done, live check pending
priority: P2
effort: "2h"
dependencies: [9]
---

# Phase 10: Create anti-spam

## Contract

- **Outcome:** every way of creating an issue is limited per user, not only `/ask` and mentions.
- **Constraints:** in memory only (no database), reset on restart. Role check still comes first: a user without the role is refused before any limit is looked at.
- **Facts:** today `Limiter` (5 second cooldown per user, 30 calls per minute overall) is used only by `handle_text`. `/issue create` and `/bulk` never touch it.
- **Non-goals:** limits on close, comment, assign; persistent counters; per-channel limits.
- **Acceptance:**
  1. `/issue create` and `/bulk create` obey the same 5 second per-user cooldown and 30 per minute global cap as `/ask`. Rejection is a short ephemeral message, nothing is created.
  2. A per-user hourly cap on created issues (`CREATE_LIMIT_PER_HOUR`, default 20, `0` means no cap). Bulk create counts one per title.
  3. The cap is checked when the preview is built (the user sees "you can create N more this hour" instead of a doomed Confirm) and consumed when Confirm is pressed, so abandoned previews cost nothing.
  4. A bulk create that needs more than the user has left is refused whole, with the number remaining. It is never trimmed.
  5. Rejection by cooldown, cap or role is written to the audit log.

## Design rules

- New `quota.py` with `CreateQuota(limit, window=3600, clock)`: `remaining(user_id)`, `consume(user_id, n)`. Sliding window of timestamps per user, pruned on use.
- `/ask`, mentions and the thread flow already pass `Limiter.check` in `handle_text`; do not count them twice. Add the `Limiter.check` call only in the `/issue create` and `/bulk` handlers.
- `submit()` takes a `quota` argument and applies the preview-time check for `create`. `ConfirmView` receives the quota and calls `consume` inside `confirm` after the role check and before the write. A create that fails on GitHub does not refund (keeps the rule simple and spam-safe).
- `CREATE_LIMIT_PER_HOUR` is optional in `.env`, validated as a non-negative integer in `config.py` with the same error style as the other variables.

## Tasks

1. `config.py` and `.env.example`: `CREATE_LIMIT_PER_HOUR`. Verify: `uv run pytest tests/test_config.py -q` exits 0.
2. `quota.py`. Verify: `uv run pytest tests/test_quota.py -q` exits 0.
3. `bot.py`: build one `CreateQuota`, call `limiter.check` in `/issue create` and `/bulk`, pass quota to `submit`. Verify: `uv run pytest tests/test_commands.py -q` exits 0.
4. `ask.py`: preview-time check and Confirm-time consume, new `MESSAGES` strings (`en`, `vi`). Verify: `uv run pytest tests/test_ask.py tests/test_bulk.py -q` exits 0.
5. Full suite. Verify: `uv run pytest -q` exits 0.

## Failure Protocol
If any Verify step does not meet its stated pass condition, STOP this phase.
Do not improvise a fix, retry blindly, or reason around the failure.
Spawn the `kongming` subagent for next-step counsel and pass:
- the phase and task id,
- what you attempted (the steps you ran),
- the exact command and its full output,
- the pass condition it failed to meet.
Apply kongming's guidance, then re-run the Verify step.
If `kongming` cannot be spawned in this environment, STOP and report the same
failure evidence to the user. Never continue by self-reasoning.
