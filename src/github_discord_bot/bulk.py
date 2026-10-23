import asyncio
import io
import logging
import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, replace

import discord

from .github import LOGIN_RE, GitHubClient, GitHubError, Issue
from .intent import Intent
from .render import clip
from .targets import BulkInputError, parse_numbers

log = logging.getLogger(__name__)

FETCH_CONCURRENCY = 5
# Pause between writes. GitHub throttles content-creating requests the hardest.
PAUSE = {"create": 1.0, "comment": 1.0, "close": 0.5, "assign": 0.5, "unassign": 0.5}
LINE_TITLE = 60
PREVIEW_BUDGET = 3800
REPORT_LINES = 15


def is_bulk(intent: Intent) -> bool:
    return len(intent.numbers) > 1 or len(intent.titles) > 1


def build_intent(action: str, targets: str, value: str) -> Intent:
    """Build an intent from the /bulk slash command's own fields, with no AI involved."""
    value = value.strip()
    if action == "create":
        titles = tuple(t.strip() for t in re.split(r"[;\n]", targets) if t.strip())
        if not titles:
            raise BulkInputError("Give at least one title, separated by ;")
        return Intent(action="create", titles=titles if len(titles) > 1 else (), title=titles[0] if len(titles) == 1 else "")
    numbers = parse_numbers(targets)
    if not numbers:
        raise BulkInputError("Give at least one issue number, like 12, 15 or 20-22.")
    intent = Intent(
        action=action,
        number=numbers[0] if len(numbers) == 1 else None,
        numbers=tuple(numbers) if len(numbers) > 1 else (),
    )
    if action == "comment":
        if not value:
            raise BulkInputError("A comment needs text in `value`.")
        return replace(intent, body=value)
    if action in ("assign", "unassign"):
        login = value.lstrip("@")
        if not LOGIN_RE.match(login):
            raise BulkInputError("`value` must be a GitHub username.")
        return replace(intent, assignee_kind="login", assignee=login)
    return intent


@dataclass
class Item:
    key: str
    number: int | None
    title: str
    state: str = "todo"  # todo | skip | error
    note: str = ""
    issue: Issue | None = None


@dataclass
class Outcome:
    key: str
    status: str  # ok | skipped | failed | unknown | not_attempted
    detail: str = ""


def _has(logins: list[str], login: str) -> bool:
    return login.lower() in (name.lower() for name in logins)


def _classify(intent: Intent, issue: Issue) -> tuple[str, str]:
    if intent.action == "close" and issue.state == "closed":
        return "skip", "already closed"
    if intent.action == "assign" and _has(issue.assignees, intent.assignee):
        return "skip", "already assigned"
    if intent.action == "unassign" and not _has(issue.assignees, intent.assignee):
        return "skip", "not assigned"
    return "todo", ""


async def prepare(gh: GitHubClient, intent: Intent) -> list[Item]:
    """Fetch every target and decide what would be done. Raises GitHubError for a bad assignee."""
    if intent.action == "create":
        return [Item(key=t, number=None, title=t) for t in intent.titles]
    if intent.action == "assign" and await gh.assignable_login(intent.assignee) is None:
        raise GitHubError(f"{intent.assignee} cannot be assigned in this repo.")

    gate = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def one(n: int) -> Item:
        async with gate:
            try:
                issue = await gh.get_issue(n)  # also refuses pull requests
            except GitHubError as exc:
                return Item(f"#{n}", n, "", "error", exc.message)
        state, note = _classify(intent, issue)
        return Item(f"#{n}", n, issue.title, state, note, issue)

    return list(await asyncio.gather(*(one(n) for n in intent.numbers)))


def _safe(title: str) -> str:
    """Titles come from GitHub, so they are untrusted: no markdown, no pings."""
    return discord.utils.escape_markdown(discord.utils.escape_mentions(clip(title, LINE_TITLE)))


def _line(item: Item) -> str:
    if item.state == "skip":
        return f"↷ {item.key} {item.note}"
    if item.state == "error":
        return f"✗ {item.key} {item.note}"
    return f"• {item.key} {_safe(item.title)}" if item.number else f"• {_safe(item.title)}"


def _fit(header: str, lines: list[str], shortened: str) -> tuple[str, str | None]:
    """The text to show, plus the full text when it did not fit."""
    full = "\n".join([header, *lines])
    if len(full) <= PREVIEW_BUDGET:
        return full, None
    shown, used = [header], len(header)
    for line in lines:
        if used + len(line) + 1 > PREVIEW_BUDGET - len(shortened) - 2:
            break
        shown.append(line)
        used += len(line) + 1
    return "\n".join([*shown, shortened]), full


def preview(intent: Intent, items: list[Item], m: dict[str, str]) -> tuple[str, str | None, int]:
    """(text, full text if long, number of items that would run)."""
    todo = sum(1 for i in items if i.state == "todo")
    header = m[f"bulk_{intent.action}"].format(
        n=todo, login=intent.assignee, body=clip(intent.body, 800)
    )
    extra = len(items) - todo
    if extra:
        header += " " + m["bulk_not_run"].format(n=extra)
    text, full = _fit(header, [_line(i) for i in items], m["bulk_shortened"])
    return text, full, todo


def view_summary(items: list[Item], m: dict[str, str]) -> tuple[str, str | None]:
    lines = []
    for item in items:
        if item.issue is None:
            lines.append(_line(item))
            continue
        i = item.issue
        who = f" - {', '.join(i.assignees)}" if i.assignees else ""
        lines.append(f"{item.key} [{i.state}] {_safe(i.title)}{who}")
    return _fit(m["bulk_view"].format(n=len(items)), lines, m["bulk_shortened"])


Sleep = Callable[[float], Awaitable[None]]


async def _apply(gh: GitHubClient, intent: Intent, item: Item) -> Outcome:
    action = intent.action
    if action == "create":
        issue = await gh.create_issue(item.title, "")
        return Outcome(item.key, "ok", f"#{issue.number}")
    n = item.number
    issue = await gh.get_issue(n)  # re-check right before writing: state may have drifted
    state, note = _classify(intent, issue)
    if state == "skip":
        return Outcome(item.key, "skipped", note)
    if action == "close":
        await gh.close_issue(n)
    elif action == "comment":
        await gh.comment(n, intent.body)
    elif action == "assign":
        await gh.assign(n, intent.assignee)
    else:
        await gh.unassign(n, intent.assignee)
    return Outcome(item.key, "ok")


async def execute(
    gh: GitHubClient,
    intent: Intent,
    items: list[Item],
    *,
    pauses: dict[str, float] | None = None,
    sleep: Sleep = asyncio.sleep,
) -> list[Outcome]:
    """Run exactly the frozen items, in order. A failure never aborts the rest, except a rate limit."""
    pauses = PAUSE if pauses is None else pauses
    outcomes = [
        Outcome(i.key, "skipped" if i.state == "skip" else "failed", i.note)
        for i in items
        if i.state != "todo"
    ]
    todo = [i for i in items if i.state == "todo"]
    halted = False
    for index, item in enumerate(todo):
        if halted:
            outcomes.append(Outcome(item.key, "not_attempted", "stopped after a rate limit"))
            continue
        try:
            outcome = await _apply(gh, intent, item)
        except GitHubError as exc:
            if exc.status in (403, 429):
                halted = True
                outcome = Outcome(item.key, "failed", f"{exc.message} Stopped the run.")
            elif intent.action == "create" and exc.status is None:
                # The request may have gone through: never retry, never claim success.
                outcome = Outcome(item.key, "unknown", "outcome unknown, check the issue list")
            else:
                outcome = Outcome(item.key, "failed", exc.message)
        except Exception:
            log.exception("bulk item crashed: %s", item.key)
            outcome = Outcome(item.key, "failed", "unexpected error")
        outcomes.append(outcome)
        log.info("bulk action=%s item=%s outcome=%s detail=%s", intent.action, item.key, outcome.status, outcome.detail)
        if index < len(todo) - 1 and not halted:
            await sleep(pauses.get(intent.action, 0.5))
    return outcomes


def report(outcomes: list[Outcome], m: dict[str, str]) -> tuple[str, str | None]:
    """(short summary, full per-item report when the summary leaves things out)."""
    count = {s: sum(1 for o in outcomes if o.status == s) for s in
             ("ok", "skipped", "failed", "unknown", "not_attempted")}
    head = m["report"].format(**count)
    problems = [o for o in outcomes if o.status in ("failed", "unknown", "not_attempted")]
    lines = [f"✗ {o.key}: {o.detail}" for o in problems[:REPORT_LINES]]
    if len(problems) > REPORT_LINES:
        lines.append(m["report_more"].format(n=len(problems) - REPORT_LINES))
    if problems:
        retry = ", ".join(o.key.lstrip("#") if o.key.startswith("#") else o.key for o in problems)
        lines.append(m["report_retry"].format(items=clip(retry, 300)))
    summary = clip("\n".join([head, *lines]), 1900)
    full = None
    if len(problems) > REPORT_LINES or len(outcomes) > REPORT_LINES:
        full = "\n".join(f"{o.status:13} {o.key}  {o.detail}".rstrip() for o in outcomes)
    return summary, full


def as_file(text: str, name: str) -> discord.File:
    return discord.File(io.BytesIO(text.encode("utf-8")), filename=name)
