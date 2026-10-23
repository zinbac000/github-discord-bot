# github-discord-bot

A Discord bot that manages issues in one GitHub repo. Use slash commands, or write in plain Vietnamese or English and let the bot work out what you mean.

The bot connects out to Discord, so it needs no open ports and runs fine behind home NAT.

## Using the bot

"Role" below means members of the Discord role set in `ALLOWED_ROLE_ID`. Anyone else can only read.

### Slash commands

| Command | Who | What it does |
|---|---|---|
| `/issue create title [body]` | role | Creates an issue and replies with its link |
| `/issue list [state] [label]` | everyone | Lists issues, 20 per page, with ◀ ▶ buttons when there is more. `state` is `open` (default), `closed` or `all`. `label` filters by label |
| `/issue view number` | everyone | Shows one issue: title, state, author, labels and the start of its description |
| `/issue close number` | role | Closes an issue |
| `/issue comment number body` | role | Adds a comment to an issue |
| `/issue assign number user` | role | Assigns a GitHub user to an issue (adds them, existing assignees stay) |
| `/issue unassign number user` | role | Removes a GitHub user from an issue |

Examples:

```
/issue create title: Login fails on Safari  body: Happens after the 2.3 update
/issue list state: closed  label: bug
/issue view number: 12
/issue close number: 12
/issue comment number: 12  body: Fixed in the next release
/issue assign number: 12  user: zinbac000
/issue unassign number: 12  user: zinbac000
```

`user` is a GitHub username that the repo can assign. The bot checks that, and only says "assigned" once GitHub confirms the person is on the issue (GitHub itself silently ignores people it cannot assign).

Pull requests are not issues: the bot skips them in lists and refuses to view or close them.

Long lists are paged: 20 issues per page, newest first. When there are more, the page footer says so and ◀ ▶ buttons appear under it. Only the person who ran the command can use the buttons, and they stop working after 3 minutes (run the command again). The same goes for "list open bugs" in plain language.

### Several issues at once

`/bulk action targets [value]` works on many issues in one go, and so does plain language ("close 12, 15 and 20-22"). There is no limit on how many issues you can name.

| `action` | `targets` | `value` |
|---|---|---|
| `view` | issue numbers | |
| `create` | titles separated by `;` | |
| `close` | issue numbers | |
| `comment` | issue numbers | the comment text |
| `assign` / `unassign` | issue numbers | a GitHub username |

Numbers can be a list, a range, or both: `12, 15, 20-22`. `view` is open to everyone, every other action needs the role.

```
/bulk action: close  targets: 12, 15, 20-22
/bulk action: create  targets: Fix login; Add dark mode; Write the README
/bulk action: assign  targets: 3-6  value: zinbac000
@bot gán issue 10, 11 và 12 cho zinbac000
```

How it behaves:

- You always get **one preview** that starts with the count and the action ("Close 7 issues?"), then lists every issue with its real title. Nothing changes until you press **Confirm** once. This applies to slash commands too.
- The bot runs exactly the list you saw, one issue at a time with a short pause, and re-checks each issue just before changing it. An issue that is already in the wanted state (for example already closed) or is now a pull request is skipped and reported.
- If one issue fails, the rest still run. At the end you get a summary (ok, skipped, failed, unknown, not attempted) and, for the failures, a list of numbers to retry. Long previews and reports come as an attached file.
- If GitHub rate limits or refuses the bot, the run stops and the remaining issues are marked "not attempted".
- Creating is never retried: if a create times out, the bot says the outcome is unknown, because the issue may exist. Check the issue list before creating it again.
- The numbers must be written by you. In plain language, if the AI's list differs in any way from what you typed (one more, one fewer), the bot asks instead of guessing. There is no "all issues with label X" yet.
- A very long run takes about one second per issue. Discord only lets the bot edit its reply for 15 minutes after the command, so after roughly 900 issues the final summary may not be shown. The bot logs every item either way.

### Plain language (needs a Groq key, see [Natural language](#natural-language-groq))

Use `/ask`, or tag the bot in any message:

```
/ask text: liệt kê issue đang mở
/ask text: tạo issue login lỗi trên Safari
@bot list closed bugs
@bot đóng issue 12
@bot comment on 12: fixed in the next release
@bot gán issue 12 cho zinbac000
@bot assign 12 to me
@bot assign 12 to @teammate
@bot bỏ gán 12 cho zinbac000
```

"Me" and `@mention` only work for people listed in `GITHUB_USER_MAP` (see below). For anyone else, type their GitHub username. The bot never guesses who you mean.

- Reading (list, view) happens right away.
- Writing (create, close, comment) first shows a preview with **Confirm** and **Cancel** buttons. Nothing changes on GitHub until you press Confirm. Only you can press the buttons, they work once, and they expire after 2 minutes.
- Say the issue number yourself ("close 12"). If you don't, the bot asks which one you mean instead of guessing.
- If you need a role you don't have, the bot says so and does nothing.

## Setup

### 1. Discord application

1. In the [Developer Portal](https://discord.com/developers/applications) create an application, then **Bot** > **Reset Token** and copy the token.
2. **OAuth2** > **URL Generator**: scopes `bot` and `applications.commands`, no bot permissions needed. Open the URL to invite the bot to your server.
3. In Discord, enable Developer Mode (Settings > Advanced). Right-click the allowed role (Server Settings > Roles) and **Copy Role ID**. Right-click the server icon and **Copy Server ID**. These are numbers, not names.

### 2. GitHub token

The token must be able to read and write **Issues** on the one repo.

- **Repo owned by the same account that creates the token:** use a [fine-grained token](https://github.com/settings/personal-access-tokens/new) limited to that repo, with **Issues: Read and write**.
- **Private repo owned by someone else's personal account** (you are only a collaborator): a fine-grained token cannot reach it and GitHub answers `404 Not Found`. Either create a [classic token](https://github.com/settings/tokens) with the `repo` scope (it covers every repo you can access, so keep it secret), or ask the owner to create a fine-grained token for that repo.
- **Repo owned by an organization:** use a fine-grained token with the organization as resource owner. The organization may need to approve it.

### 3. Configure

```
cp .env.example .env     # Windows: copy .env.example .env
```

| Variable | Meaning |
|---|---|
| `DISCORD_TOKEN` | Bot token from step 1 |
| `GITHUB_TOKEN` | Token from step 2 |
| `GITHUB_REPO` | The one repo to manage, as `owner/name` |
| `ALLOWED_ROLE_ID` | Role ID (a number) allowed to write |
| `DISCORD_GUILD_ID` | Optional. Your server ID. Without it, new commands can take up to an hour to appear |
| `GROQ_API_KEY`, `GROQ_MODEL`, `GROQ_FALLBACK_MODEL` | Optional, for plain language |
| `GITHUB_USER_MAP` | Optional. Comma-separated `<discord user id>=<github login>` pairs, for example `123456789=zinbac000,987654321=octocat`. Lets people say "assign to me" or tag a teammate. You edit it yourself, there is no self-service linking |

`.env` is ignored by git. Never commit it.

### 4. Run

Needs [uv](https://docs.astral.sh/uv/). To run in the foreground:

```
uv run python -m github_discord_bot
```

When it works you see `Logged in as <bot name>, managing <owner/repo>`. Stop with Ctrl+C.

If the bot exits at once, it prints which `.env` values are missing or invalid.

## Natural language (Groq)

Optional. With a Groq key the bot understands plain language, as described above.

1. Create a key in the [Groq console](https://console.groq.com/keys) and set `GROQ_API_KEY` in `.env`.
2. Groq retires models from time to time. Check the [model list](https://console.groq.com/docs/models) and set `GROQ_MODEL` to a current model that supports tool calling. Optionally set `GROQ_FALLBACK_MODEL`, which the bot retries with when the main model is unavailable.
3. To allow tagging, turn on **Message Content Intent** in the Developer Portal (your app > Bot > Privileged Gateway Intents).
4. Restart the bot. Without `GROQ_API_KEY`, `/ask` is not registered and the bot does not read message content.

Good to know:

- `/ask` replies are visible only to you. Replies to a tag are normal replies in the channel, so a write preview from a tag is visible to everyone there (only you can press its buttons). Use `/ask` for writes if that matters.
- Each message you send this way is sent to Groq, a third party. Issue content is never sent to Groq.
- The bot logs one line per request (who, what they wrote, what it understood, the outcome), which helps when something looks wrong.
- Requests are limited to one every 5 seconds per person and 30 per minute overall.

## Run as a service

### macOS

```
scripts/install.sh
```

This installs a launchd agent that starts at login and restarts on failure. Logs go to `~/Library/Logs/github-discord-bot.log`. For an unattended Mac mini, turn on automatic login (System Settings > Users & Groups), since launchd agents only run while the user is logged in. Remove with `scripts/install.sh --uninstall`.

### Windows

```
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

This registers a scheduled task that starts at logon and restarts on failure. Logs go to `bot.log` in the repo. Remove with `-Uninstall`.

If Windows Application Control blocks `uv run github-discord-bot` (error "An Application Control policy has blocked this file"), run the bot as `uv run python -m github_discord_bot` instead.

### Over SSH

Clone the repo on the target machine, put the `.env` there (for example with `scp`), then run the installer for that OS. On macOS the launchd agent needs a logged-in GUI session for the user, so log in once at the machine (or enable automatic login) before installing over SSH.

## Updating

```
git pull
```

then restart the bot, or run the installer again. It is safe to repeat.

## Troubleshooting

| You see | Cause and fix |
|---|---|
| Commands do not appear | Set `DISCORD_GUILD_ID` and restart. Make sure the invite included the `applications.commands` scope |
| `ALLOWED_ROLE_ID must be a number` | Use the role's numeric ID, not its name |
| "Repository or issue not found" | Wrong `GITHUB_REPO`, a wrong issue number, or the token cannot see a private repo. See [GitHub token](#2-github-token) |
| "GitHub rejected the bot's token" | The token is wrong or expired. Make a new one and update `.env` |
| "GitHub refused the request" | The token lacks Issues write access on that repo, or the rate limit was hit |
| "You need the allowed role" | You do not have the role in `ALLOWED_ROLE_ID` |
| "The AI model is unavailable" | Groq retired the model. Pick a current one and update `GROQ_MODEL` |
| Tagging does nothing | Message Content Intent is off in the Developer Portal, or `GROQ_API_KEY` is empty |
| "X cannot be assigned in this repo" | The person is not a collaborator on the repo. Only collaborators (and the owner) can be assigned |
| "I don't know which GitHub account that is" | "Me" or a mention for someone missing from `GITHUB_USER_MAP`. Type their GitHub username, or add them to the map |
| "#N is a pull request, not an issue" | The number belongs to a pull request. The bot only handles issues |

After changing `.env`, restart the bot.

## Development

```
uv sync
uv run pytest
```
