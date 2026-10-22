---
phase: 3
title: "Discord commands"
status: in-progress
priority: P2
effort: "3h"
dependencies: [2]
---

# Phase 3: Discord commands

## Goal
The `/issue` command group works end to end, with role-gated writes and friendly errors.

## Files to Create / Modify
- Create: `src/github_discord_bot/bot.py`
- Modify: `src/github_discord_bot/__main__.py` (start the bot)
- Create: `tests/test_commands.py`

## Tasks & Steps
1. Client with default intents (no privileged intents needed for slash commands). `setup_hook` syncs the command tree to `DISCORD_GUILD_ID` if set, otherwise globally.
2. `app_commands.Group("issue")` with, in this order:
   - `create(title, body="")`: write, role-gated. Replies with issue number, title and link.
   - `list(state="open", label=None)`: read. Embed of up to 10 issues (number, title, link). `state` is a choice of open, closed, all. Says so plainly when there are none.
   - `view(number)`: read. Embed with title, state, labels, author, truncated body, link.
   - `close(number)`: write, role-gated.
   - `comment(number, body)`: write, role-gated.
3. Role gate: `app_commands.checks.has_role(allowed_role_id)` on write commands only. Responses to failures are ephemeral.
4. Defer every command (`interaction.response.defer()`) before calling GitHub so slow responses do not hit the 3 second limit.
5. Tree error handler: `MissingRole` gives "You need the <role> role", `GitHubError` gives its message, anything else is logged with traceback and answered with a generic ephemeral message. The bot process never exits on a command error.
6. Logging to stdout with timestamps, so launchd and the Windows task can capture it.
7. Tests with a fake `GitHubClient` and fake interactions: create success, list with and without filters, empty list, role denial on each write command, `GitHubError` surfaced as a message, unexpected exception does not propagate.

## Verification
- `uv run pytest` passes.
- Manual in a test server: `/issue create` makes a real issue with a working link, `/issue list` shows it, an account without the role is refused on create and close, an invalid PAT in `.env` gives a clear error and the bot stays online.
