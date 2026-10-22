---
phase: 1
title: "Project scaffold and config"
status: in-progress
priority: P2
effort: "1.5h"
dependencies: []
---

# Phase 1: Project scaffold and config

## Goal
A runnable Python package whose settings load from `.env` and fail fast with a clear message when something is missing.

## Files to Create / Modify
- Create: `pyproject.toml` (deps: `discord.py`, `httpx`, `python-dotenv`; dev: `pytest`, `pytest-asyncio`, `respx`; Python >=3.11; script entry `github-discord-bot`)
- Create: `src/github_discord_bot/__init__.py`, `__main__.py`
- Create: `src/github_discord_bot/config.py`
- Create: `.env.example`
- Modify: `.gitignore` (add `.env`, `.venv/`, `__pycache__/`, `*.log`, keep `.claude/`)
- Create: `tests/test_config.py`

## Tasks & Steps
1. Write `pyproject.toml` and run `uv sync` to produce `uv.lock`.
2. `config.py`: frozen dataclass `Settings` with `discord_token`, `github_token`, `github_repo` (validated as `owner/name`), `allowed_role_id` (int), `discord_guild_id` (optional int). `load_settings()` reads `.env` then the environment and raises one `ConfigError` listing every missing or invalid variable.
3. `__main__.py`: load settings, print the `ConfigError` message and exit code 2 if it fails, otherwise start the bot (stub until phase 3).
4. `.env.example` lists all five variables with comments and no real values.
5. Tests: all valid, each variable missing, bad repo format, non-numeric role ID.

## Verification
- `uv run pytest tests/test_config.py` passes.
- `uv run python -m github_discord_bot` with an empty environment exits 2 and names every missing variable.
- `git check-ignore .env` prints `.env`.
