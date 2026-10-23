---
phase: 7
title: "Assign and unassign issues"
status: in-progress
priority: P2
effort: "4h"
dependencies: [6]
---

# Phase 7: Assign and unassign issues

## Contract

- **Outcome:** `/issue assign number user` and `/issue unassign number user`, plus the same in plain language ("gán 12 cho zinbac000", "assign 12 to me", "bỏ gán 12 cho @someone") through `/ask` and tagging.
- **Constraints:** both are writes: role required, preview plus Confirm in plain language, role rechecked on Confirm. The assignee is a GitHub login that the repo can assign. Every way of naming the person (typed login, "me", mention) resolves to one login and passes the same checks. Pull requests stay refused.
- **Non-goals:** self-service account linking, stored state, assigning several people at once, a "replace assignee" mode.
- **Semantics (decided with the user):** assign **adds** the person (GitHub's behavior) and the preview lists who is already assigned. Unassign of someone who is not assigned says so and calls no write API.
- **Acceptance:**
  1. `/issue assign 12 zinbac000` assigns, and the bot says "assigned" only when GitHub's response lists that person in `assignees`.
  2. A login the repo cannot assign gives a clear error and writes nothing.
  3. `/issue unassign` removes the person. Unassigning someone not assigned reports it and makes no write call.
  4. Plain language previews show the issue title, the resolved login and the current assignees.
  5. "me" or a mention of someone missing from `GITHUB_USER_MAP` is refused with a request for the GitHub username. The bot never guesses.
  6. Users without the role are refused before any preview.
  7. A mocked 200 response whose `assignees` lacks the person makes the bot report failure.

## Design rules (from advisory review)

- Check the POST/DELETE response, not the HTTP status: GitHub silently ignores users it cannot assign. The assignable-list check is only for earlier, friendlier errors.
- Groq never resolves identity. It emits `assignee_kind` (`login`, `self`, `mention`) and, for `login`, the typed text. Code resolves the person. A typed login must appear literally in the user's message. A mention is read from `<@id>` in the user's message. "me" uses the caller's Discord ID.
- Logins are validated with `^[A-Za-z0-9-]{1,39}$` before use in a URL, compared case-insensitively, and sent with GitHub's canonical casing.
- `GITHUB_USER_MAP` (`<discord id>=<github login>,...` in `.env`) is optional and admin-edited.

## Tasks

1. `github.py`: `Issue.assignees`, `assignable_login`, `assign`, `unassign` with the rules above. Verify: `uv run pytest tests/test_github.py -q` exits 0.
2. `config.py` and `.env.example`: parse `GITHUB_USER_MAP`, reject malformed entries. Verify: `uv run pytest tests/test_config.py -q` exits 0.
3. `intent.py`: `assign` and `unassign` tools, `assignee_kind` and `assignee` on `Intent`, validation. Verify: `uv run pytest tests/test_intent.py -q` exits 0.
4. `ask.py` and `bot.py`: resolution, preview text in Vietnamese and English, `run_write`, `/issue assign` and `/issue unassign`, assignees on the view embed. Verify: `uv run pytest -q` exits 0.
5. README: usage and `GITHUB_USER_MAP`. Verify: `grep -c GITHUB_USER_MAP README.md` prints at least 2.

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
