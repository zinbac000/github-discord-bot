---
phase: 9
title: "Type and game labels"
status: code done, live check pending
priority: P2
effort: "3h"
dependencies: [8]
---

# Phase 9: Type and game labels

Part of the issue #42 extension (oornasp/zuiwe.space). See "Issue #42 extension" in `plan.md`.

## Contract

- **Outcome:** an issue created through `/issue create`, `/ask` or a mention carries a type label and, when known, a game label. The user can fix both in the preview before confirming.
- **Constraints:** only labels that already exist on the repo are ever sent. The bot never creates labels. The label lists are read from the repo at runtime, not hard-coded, except the two type names.
- **Facts verified on the repo (2026-10-25):** type labels are `bug` and `enhancement`; there is no `idea` label. Game labels are the ones starting with `game:` (today only `game:clash-of-saigon`). Decided with the user: the word "idea" counts as `enhancement`.
- **Non-goals:** priority labels (`P0`, `P1`), area labels, labels on `/bulk create`, relabelling existing issues.
- **Acceptance:**
  1. "tạo issue: game crash khi vào trận, game clash of saigon" previews labels `bug` and `game:clash-of-saigon`. Confirm creates the issue with exactly those labels.
  2. "idea: thêm chế độ tối" previews `enhancement` (never `idea`).
  3. A game the model names that matches no `game:*` label on the repo gives no game label (it never invents one).
  4. The preview has a type select and a game select. Changing either changes the labels sent on Confirm. Only the asker can use them.
  5. `/issue create` accepts optional `kind` and `game` (game with autocomplete from the repo's `game:*` labels) and stays a direct create.
  6. If the repo's label list cannot be read, the issue is still created, without labels, and the reply says so.

## Design rules

- `kind` from the model is one of `bug`, `idea`, `enhancement`, or empty. Code maps `idea` to `enhancement`. Anything else becomes empty.
- `game` from the model is free text copied from the user. Code matches it against the repo's `game:*` labels after normalising (lowercase, drop a `game:` prefix, treat `-`, `_` and spaces alike). No match gives an empty game. The model is never sent the label list.
- The repo's label names are cached in `GitHubClient` for 10 minutes. Labels are re-validated against that list at write time, so a label deleted on GitHub cannot break the create.
- The label list is paged (`per_page=100`, follow `Link: next`), because the repo already has more than 30 labels.

## Tasks

1. `github.py`: `list_labels()` (paged, 10 minute cache). Verify: `uv run pytest tests/test_github.py -q` exits 0.
2. New `labels.py`: `TYPE_LABELS`, `resolve_kind(raw)`, `game_labels(names)`, `match_game(raw, names)`, `final_labels(kind, game, names)`. Verify: `uv run pytest tests/test_labels.py -q` exits 0.
3. `intent.py`: `kind` and `game` on the `create_issue` tool and on `Intent`, plus `labels: tuple[str, ...] = ()`. Prompt line: copy the type word and the game words the user wrote, never guess. Verify: `uv run pytest tests/test_intent.py -q` exits 0.
4. `ask.py`: resolve labels in `submit()` for create, show them in the preview text, pass them in `run_write`, add the type select and game select to `ConfirmView` for create only (selects update `self.intent`). New `MESSAGES` strings in `en` and `vi`. Verify: `uv run pytest tests/test_ask.py -q` exits 0.
5. `bot.py`: `kind` choice and `game` autocomplete on `/issue create`; label failure handling (design rule above, acceptance 6). Verify: `uv run pytest tests/test_commands.py -q` exits 0.
6. Full suite. Verify: `uv run pytest -q` exits 0.

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
