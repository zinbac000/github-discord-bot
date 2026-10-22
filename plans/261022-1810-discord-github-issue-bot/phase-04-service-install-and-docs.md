---
phase: 4
title: "Service install and docs"
status: in-progress
priority: P2
effort: "3.5h"
dependencies: [3]
---

# Phase 4: Service install and docs

## Goal
One command per OS turns a fresh clone plus a filled `.env` into a restart-on-failure, start-on-boot service.

## Files to Create / Modify
- Create: `scripts/install.sh` (macOS)
- Create: `scripts/install.ps1` (Windows)
- Modify: `README.md`

## Tasks & Steps
1. `install.sh`: check `uv` and `.env` exist, run `uv sync --frozen`, write `~/Library/LaunchAgents/com.github-discord-bot.plist` with absolute paths, `RunAtLoad` and `KeepAlive` true, stdout and stderr to `~/Library/Logs/github-discord-bot.log`, then `launchctl bootstrap` (unload any previous copy first so reruns are idempotent). A `--uninstall` flag removes it.
2. `install.ps1`: same preflight, then `Register-ScheduledTask` running `uv run github-discord-bot` in the repo directory, with logon trigger, restart on failure (3 tries, 1 minute apart), no execution time limit, hidden window, output to a log file. Rerun replaces the existing task. `-Uninstall` removes it.
3. Both scripts print the final status, log path, and how to stop or remove the service. Neither prints secrets.
4. README: what it does, create the Discord application and invite URL (scopes `bot` and `applications.commands`), create the fine-grained PAT (Issues read/write on the one repo), fill `.env`, install on macOS and Windows, install over SSH, update (`git pull` then rerun the installer), logs, troubleshooting (commands not appearing, 401 and 403).
5. Verify on a clean path: clone to a new directory, follow the README only.

## Verification
- macOS: after `scripts/install.sh`, `launchctl list | grep github-discord-bot` shows the job, killing the process makes it return, and it runs after reboot.
- Windows: after `scripts/install.ps1`, `Get-ScheduledTask github-discord-bot` shows Ready or Running, and the bot is online after logging out and back in.
- Rerunning either installer changes nothing and causes no duplicate service.
- Acceptance criteria 1 to 5 in `plan.md` all hold.
