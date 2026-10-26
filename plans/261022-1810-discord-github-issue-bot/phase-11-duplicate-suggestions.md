---
phase: 11
title: "Duplicate suggestions"
status: code done, live check pending
priority: P2
effort: "3h"
dependencies: [9]
---

# Phase 11: Duplicate suggestions

## Contract

- **Outcome:** before a create is confirmed, the user sees up to 3 existing issues that look like the new one, and decides.
- **Constraints:** keyword search through GitHub's search API, no LLM matching in this phase. A search failure never blocks creating an issue.
- **Non-goals:** semantic or embedding matching, auto-closing duplicates, adding the `duplicate` label, checks on `/bulk create`.
- **Acceptance:**
  1. Previews of a create (from `/ask`, mentions, and later the thread flow) show a "Similar issues" list of at most 3 entries: number, state (open or closed), title, link. Pull requests never appear.
  2. When there are matches the Confirm button reads "Create anyway" (`Vẫn tạo`). Cancel is "use an existing one": it closes the preview and the links stay in the message.
  3. No matches: the preview is unchanged.
  4. GitHub search errors, 422, rate limit (search is 30 per minute) or timeout: the preview is shown without the list, the reason goes to the log, creation works.
  5. `/issue create` stays a direct create when nothing similar exists. When something similar exists it shows the same preview, so the user chooses.

## Design rules

- Query is built in code from the title: lowercase, drop punctuation and a short Vietnamese and English stopword list, keep words of 3 or more characters, at most 6 words. If fewer than 2 words are left, skip the search.
- Request: `GET /search/issues?q=repo:<owner/name> is:issue <words>&per_page=5&sort=best-match`. Take the first 3 after dropping any pull request. Open and closed issues both count.
- Titles come from GitHub: clip and escape them exactly as `render.issue_line` already does.
- The search lives in `github.py` (`search_issues`) so tests can mock it with `respx` like the rest.

## Tasks

1. `similar.py`: `keywords(title)`. Verify: `uv run pytest tests/test_similar.py -q` exits 0.
2. `github.py`: `search_issues(title, limit=3)`, errors map to `GitHubError`. Verify: `uv run pytest tests/test_github.py -q` exits 0.
3. `ask.py`: call the search in `describe()` for create (inside try, degrade on `GitHubError`), add the list to the preview, switch the Confirm label, new `MESSAGES` strings (`en`, `vi`). Verify: `uv run pytest tests/test_ask.py -q` exits 0.
4. `bot.py`: `/issue create` searches first; direct create if empty, shared preview if not. Verify: `uv run pytest tests/test_commands.py -q` exits 0.
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
