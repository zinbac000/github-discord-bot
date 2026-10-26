---
phase: 13
title: "Ask for missing details"
status: code done, live check pending
priority: P2
effort: "4h"
dependencies: [12]
---

# Phase 13: Ask for missing details

## Contract

- **Outcome:** when a thread draft lacks something a good issue needs, the bot says exactly what is missing and lets the user fill it in before creating. It never invents the missing part.
- **Constraints:** no extra Groq call. Missing items are computed in code, and the user's answers go straight into the draft. The phase reuses the phase 12 preview view.
- **Non-goals:** a back-and-forth chat, asking in the public thread, re-drafting with the model after the user edits.
- **Acceptance:**
  1. The preview lists what is missing, from these checks: type (unresolved), description (empty), steps to reproduce (type is bug and none given), game (unresolved).
  2. The user fills the gaps with the type select and game select (phase 9) and an "Add details" button that opens a form with these fields, prefilled from the draft: title, description, steps (one per line), expected and actual. A form allows 5 fields, so these fit.
  3. Submitting the form rebuilds the body in code, refreshes the preview and the missing list.
  4. Type and description are required: Confirm stays disabled until both exist. Steps and game are advised, not required: the warning stays but Confirm works. Skipping the game creates the issue with no game label.
  5. Only the person who started the flow can use the select, the button and the form.
  6. The form's text goes through the same mention neutralising as the thread text.
  7. `/ask` creates use the same missing-details preview. When the user did not say whether it is a bug or an idea ("tạo issue: login lỗi"), the type stays empty, the model's guess is not used, and Confirm waits for the type select.

## Design rules

- `missing(draft, names)` in `thread_draft.py` returns a list of keys (`kind`, `description`, `steps`, `game`). The labels for these keys come from `MESSAGES` in both languages.
- `DraftView` extends `ConfirmView`: Confirm enabled only if `kind` and `description` are set; a method `refresh(interaction)` rebuilds `self.intent` (`title`, `body`, `labels`) and edits the preview message.
- The discord.py Modal timeout and the View timeout are both 5 minutes for drafts (a person may need time to write steps). Confirm timeout is reset by `refresh`.
- For `/ask` creates there is no thread text, so the draft is just the title and body the user wrote: description is the body, and only the kind and game selects apply. The form is offered, but steps and expected/actual stay out of the body unless the user writes them.

## Tasks

1. `thread_draft.py`: `missing()` and `apply_form(draft, fields)`. Verify: `uv run pytest tests/test_thread_draft.py -q` exits 0.
2. `ask.py`: `DraftView`, the form (`discord.ui.Modal`), Confirm gating, refresh, `MESSAGES` strings (`en`, `vi`). Verify: `uv run pytest tests/test_ask.py -q` exits 0.
3. Wire `/ask` create to `DraftView` when type is unresolved. Verify: `uv run pytest tests/test_ask.py tests/test_commands.py -q` exits 0.
4. Full suite. Verify: `uv run pytest -q` exits 0.

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
