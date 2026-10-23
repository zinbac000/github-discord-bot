---
phase: 8
title: "Bulk actions"
status: in-progress
priority: P2
effort: "6h"
dependencies: [7]
---

# Phase 8: Bulk actions

## Contract

- **Outcome:** the existing actions work on many issues at once: view, create (several titles), close, comment (same text), assign and unassign. Through `/bulk action targets [value]` and through plain language.
- **Constraints:** every bulk write has one preview (count and action first, then each issue with its real title) and one Confirm, slash commands included. The bot runs exactly the frozen list, re-checking each issue right before writing. Numbers come from the user's own text and are parsed and expanded by code, never by the model.
- **Decided with the user:** filter-based bulk ("close all with label X") is deferred. There is no cap on how many issues can be named.
- **Non-goals:** filter-based bulk, undo, agent loops.
- **Acceptance:** see the README section "Several issues at once". Every behavior listed there has a test in `tests/test_bulk.py`.

## Design rules (from advisory review)

- The frozen list lives in the Confirm view, not in the button. The list is never rebuilt from the message or the model.
- Before each write, re-fetch the issue. Skip it if it is already in the target state, fail it if it became a pull request.
- A rate limit (403 or 429) stops the run. The remaining items are "not attempted". Other failures do not stop the run.
- Create is never retried. A network failure on create is reported as "unknown".
- Titles from GitHub are untrusted: cut to 60 characters, markdown and mentions escaped.
- If the model's numbers differ from the numbers code reads in the text, clarify. This also protects single-issue commands ("close 12 not 15").
- Previews and reports that do not fit in one Discord message are shortened and the full text is attached as a file.

## Tasks

1. `targets.py`: read lists and ranges, reject backwards or absurd ranges. Verify: `uv run pytest tests/test_bulk.py -q` exits 0.
2. `intent.py`: `numbers` and `titles`, exact-match validation. Verify: `uv run pytest tests/test_intent.py -q` exits 0.
3. `bulk.py`: prepare, preview, execute, report, `/bulk` input. Verify: `uv run pytest tests/test_bulk.py -q` exits 0.
4. `ask.py` and `bot.py`: `submit()` shared by AI input and `/bulk`, Confirm view for bulk, `/bulk` command, file attachments. Verify: `uv run pytest -q` exits 0.
5. README. Verify: `grep -c "Several issues at once" README.md` prints 1.

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
