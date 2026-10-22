---
phase: 2
title: "GitHub client"
status: in-progress
priority: P2
effort: "2h"
dependencies: [1]
---

# Phase 2: GitHub client

## Goal
An async client for the fixed repo's issues, with every GitHub failure turned into a `GitHubError` carrying a user-safe message.

## Files to Create / Modify
- Create: `src/github_discord_bot/github.py`
- Create: `tests/test_github.py`

## Tasks & Steps
1. `GitHubError(message, status)`. Mapping: 401 means token invalid or expired, 403 means no permission or rate limited, 404 means repo or issue not found, 422 means GitHub rejected the input, network or timeout means GitHub unreachable. Messages never include the token or raw response bodies.
2. `GitHubClient(token, repo)` wrapping one `httpx.AsyncClient` with `Authorization`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version` headers, and a timeout.
3. Methods: `create_issue(title, body, labels=None)`, `list_issues(state="open", label=None, limit=10)`, `get_issue(number)`, `close_issue(number)`, `comment(number, body)`. Return a small `Issue` dataclass (`number`, `title`, `state`, `url`, `labels`, `author`, `body`).
4. `list_issues` must drop pull requests (GitHub returns PRs in the issues endpoint; they carry a `pull_request` key).
5. `aclose()` for shutdown.
6. Tests with `respx`: success for each method, PRs filtered out, each error status mapped, timeout mapped, token absent from every error string.

## Verification
- `uv run pytest tests/test_github.py` passes.
- Optional manual check with a real PAT: create then list an issue in a scratch repo.
