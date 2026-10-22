---
phase: 6
title: "/ask command, mentions and confirmation"
status: in-progress
priority: P2
effort: "4h"
dependencies: [5]
---

# Phase 6: /ask command, mentions and confirmation

## Goal
Users reach the Groq parser two ways, `/ask <text>` and tagging the bot in a message. Reads run immediately. Writes show a code-built preview with a single-use Confirm button.

## Rules the executor must follow
- The preview is built in code from the validated `Intent`. Never show text written by the model.
- Permissions are checked in code on the resolved action, once before the preview and again when Confirm is pressed.
- Confirm is single-use: after the first press the buttons are disabled and a second press does nothing.
- Only the user who asked may press Confirm or Cancel.
- Existing `/issue ...` commands must keep working unchanged. If `GROQ_API_KEY` is unset, `/ask` is not registered and the bot does not read message content.
- Replies use the language in `intent.lang` (`vi` or `en`) from a fixed message table in code.
- Visibility: every `/ask` reply is ephemeral (after a defer, Discord fixes the visibility of the first reply, so public and private cannot be mixed). A mention cannot reply ephemerally, so mention replies are plain replies to the message.

## Files
- Create: `src/github_discord_bot/render.py`, `src/github_discord_bot/ask.py`
- Modify: `src/github_discord_bot/bot.py`, `src/github_discord_bot/__main__.py` (only if needed), `README.md`, `.env.example`
- Create: `tests/test_ask.py`

### Task 6.1 - Extract shared rendering (regression gate)
- Goal: list and view embeds are built by functions both the `/issue` commands and `/ask` can call, with no behavior change.
- Target files: `src/github_discord_bot/render.py` (new), `src/github_discord_bot/bot.py`.
- Steps:
  1. Move `_clip`, `_line`, and the embed construction for list and view out of `bot.py` into `render.py` as `clip`, `issue_line`, `list_embed(issues, state)`, `view_embed(issue)`.
  2. Update `bot.py` to import and call them. Do not change any command's behavior or text.
- Success criteria: the full existing suite still passes unchanged.
- Verify: `uv run pytest -q` exits 0, prints `passed` with no `failed`, and the passed count is not lower than before the change.

### Task 6.2 - Message table and action runner
- Goal: one place that describes and executes a validated intent.
- Target files: `src/github_discord_bot/ask.py` (new). Symbols: `MESSAGES`, `describe`, `run_read`, `run_write`.
- Steps:
  1. `MESSAGES`: a dict keyed `vi` and `en` with the fixed strings: preview header, confirm and cancel labels, "done", "cancelled", "expired", "not allowed", "busy", "already handled", "not your request", "empty mention hint". Write natural Vietnamese and English for each.
  2. `describe(gh, intent) -> str`: build the preview text from the validated fields only. For `create`: title and full body. For `close`: the issue number and its current title fetched with `gh.get_issue` (a `GitHubError` propagates). For `comment`: the issue number, its title, and the full comment text.
  3. `run_read(gh, intent)` returns `(content, embed)`: `list` calls `gh.list_issues(state, label, limit=10)` and `list_embed`, or a "no issues" text when empty; `view` calls `gh.get_issue` and `view_embed`.
  4. `run_write(gh, intent)` returns a result string: `create` calls `gh.create_issue(title, body)`, `close` calls `gh.close_issue(number)`, `comment` calls `gh.comment(number, body)`. Result strings contain the issue link.
- Success criteria: no function here touches Discord objects.
- Verify: no verification needed here, because Task 6.5 tests these functions.

### Task 6.3 - Confirmation view
- Goal: a single-use, owner-only Confirm and Cancel with a 120 second timeout.
- Target files: `src/github_discord_bot/ask.py`. Symbol: `ConfirmView(discord.ui.View)`.
- Steps:
  1. Constructor takes `gh`, `intent`, `owner_id`, `role_id`, and `reply_lang`, sets `timeout=120`, and a `consumed` flag set to `False`.
  2. Override `interaction_check`: if `interaction.user.id != owner_id`, reply ephemerally with the "not your request" message and return `False`.
  3. Confirm button: if `consumed`, reply ephemerally "already handled" and return. Set `consumed = True` first, before any `await` on GitHub. Re-check the role (`any(r.id == role_id for r in interaction.user.roles)`); on failure show "not allowed" and disable the buttons. Otherwise run `run_write`, then edit the message with the result and disable the buttons. A `GitHubError` is shown as its `.message`.
  4. Cancel button: set `consumed = True`, edit the message to "cancelled", disable buttons.
  5. `on_timeout`: disable the buttons and edit the message to "expired" if not consumed. Ignore `discord.HTTPException`.
- Success criteria: two simultaneous Confirm presses result in exactly one GitHub call.
- Verify: no verification needed here, because Task 6.5 tests this view.

### Task 6.4 - Entry points, rate limiting and audit log
- Goal: `/ask` and mention both call one shared handler.
- Target files: `src/github_discord_bot/ask.py` (symbols `Limiter`, `handle_text`), `src/github_discord_bot/bot.py` (class `IssueBot`).
- Steps:
  1. `Limiter`: in-memory. A per-user cooldown of 5 seconds and a global cap of 30 calls per minute (a `deque` of timestamps). `check(user_id) -> bool`. When it returns `False`, the reply is the "busy" message.
  2. `handle_text(*, text, user_id, roles, settings, gh, groq, limiter, reply)`: where `reply` is an async callable `reply(content=None, embed=None, view=None, ephemeral=False)`. Flow: limiter check; `groq.parse(text)` (`AIError` becomes its message); if `clarify`, reply with `intent.question`; if the action is in `WRITE_ACTIONS` and the role check fails, reply "not allowed" and stop; reads call `run_read` and reply; writes call `describe`, then reply with the preview and a `ConfirmView`. Every call ends with one log line from logger `github_discord_bot.ask`: user id, text clipped to 200 characters, action and arguments, outcome (`ok`, `clarify`, `denied`, `ai_error`, `github_error`, `limited`).
  3. In `IssueBot.__init__`, only when `settings.groq_api_key` is set: create `GroqClient` and `Limiter`; request `intents.message_content = True`; register the `/ask` command (`text` parameter, defer then followup; `reply` maps `ephemeral` to `followup.send(ephemeral=...)`).
  4. Add `IssueBot.on_message`: ignore authors that are bots; ignore messages where `self.user` is not in `message.mentions`; strip the mention text (`<@id>` and `<@!id>`); if nothing remains, reply with the "empty mention hint"; otherwise call `handle_text` with `reply` implemented as `message.reply(...)` (ignore `ephemeral`).
  5. Close `GroqClient` in `IssueBot.close`.
- Success criteria: with `GROQ_API_KEY` unset, `bot.tree` contains no `ask` command and `intents.message_content` is `False`.
- Verify: no verification needed here, because Task 6.5 tests these paths.

### Task 6.5 - Tests
- Goal: the whole `/ask` and mention flow is tested with mocked Groq and fake Discord objects.
- Target files: `tests/test_ask.py` (new).
- Steps: write tests for:
  1. A read intent (`list`) calls `list_issues` and replies without a view.
  2. A `create` intent replies with a preview containing the exact title and body and a `ConfirmView`, and calls nothing on GitHub yet.
  3. Pressing Confirm calls `create_issue` exactly once, even when Confirm is pressed twice concurrently (`asyncio.gather`).
  4. Pressing Confirm as a different user is refused and does not call GitHub.
  5. The role is re-checked on Confirm: a user who loses the role between preview and Confirm is refused.
  6. A write intent from a user without the role is refused before any preview is built.
  7. `close` preview contains the issue's real title fetched through `get_issue`.
  8. `clarify` replies with the question and takes no action.
  9. An `AIError` (429) replies with the busy message and the bot's `/issue` commands still work.
  10. The `Limiter` blocks a second call within 5 seconds and the 31st call within a minute.
  11. A mention containing only the bot tag replies with the hint; a mention from a bot author is ignored; a message without a mention is ignored.
  12. Each handled call emits one log record on `github_discord_bot.ask` (use `caplog`) and none contains the API key.
  13. With `groq_api_key=None`, `IssueBot` has no `ask` command.
- Success criteria: all pass with no network access.
- Verify: `uv run pytest -q` exits 0 and prints `passed` with no `failed`.

### Task 6.6 - Docs
- Goal: README explains the AI feature and its privacy implication.
- Target files: `README.md`, `.env.example`.
- Steps: add a section "Natural language (Groq)" covering: set `GROQ_API_KEY` (and `GROQ_MODEL`; mention `GROQ_FALLBACK_MODEL`); enable **Message Content Intent** in the Developer Portal under Bot to allow tagging; usage examples in Vietnamese and English for `/ask` and for tagging the bot; that writes always ask for confirmation; that the text of each `/ask` or mention is sent to Groq (a third party); that the bot logs every request; and that models get retired, so update `GROQ_MODEL` if you see "AI model unavailable". Add the new section to the commands table.
- Success criteria: README mentions every new environment variable and the Message Content Intent.
- Verify: `grep -c -E "GROQ_API_KEY|GROQ_MODEL|GROQ_FALLBACK_MODEL|Message Content" README.md` prints a number of at least 4.

## Phase verification
- `uv run pytest -q` exits 0 and prints `passed` with no `failed`.
- Live check (needs real keys, run by the user): `/ask` with "tạo issue test Groq" shows a preview; Confirm creates a real issue; a second click does nothing; tagging the bot with "liệt kê issue đang mở" replies with the list.

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
