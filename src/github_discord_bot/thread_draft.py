"""An issue draft: what the preview shows and what GitHub receives, built in code.

Text from a Discord thread (or typed into the details form) is untrusted: it only ever fills
the fields of a `Draft`. The body is assembled here, never taken from model prose.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace

from .labels import match_game, resolve_kind
from .render import clip

MAX_TITLE = 256
MAX_DESCRIPTION = 4000
MAX_STEP = 500
MAX_STEPS = 20
MAX_EXPECTED = 1000

HEADINGS = {
    "en": {
        "description": "Description",
        "steps": "Steps to reproduce",
        "expected": "Expected",
        "actual": "Actual",
        "source": "Source",
    },
    "vi": {
        "description": "Mô tả",
        "steps": "Các bước tái hiện",
        "expected": "Kết quả mong đợi",
        "actual": "Kết quả thực tế",
        "source": "Nguồn",
    },
}
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


@dataclass(frozen=True)
class Draft:
    title: str
    kind: str = ""  # "bug", "enhancement" or "" (not decided yet)
    game: str = ""  # a `game:*` label that exists on the repo, or ""
    description: str = ""
    steps: tuple[str, ...] = ()
    expected: str = ""
    actual: str = ""
    lang: str = "en"
    source_url: str = ""
    from_thread: bool = False
    read: int = 0  # messages read from the thread
    total: int = 0  # messages the thread has


def neutralise_mentions(text: str) -> str:
    """Stop `@name` from pinging a real GitHub user when the issue is created."""
    return re.sub(r"@(?=\w)", "@​", text)


def build_body(draft: Draft) -> str:
    h = HEADINGS[draft.lang if draft.lang in HEADINGS else "en"]
    description = draft.description.strip()
    structured = draft.kind == "bug" and (draft.steps or draft.expected.strip() or draft.actual.strip())
    parts: list[str] = []
    if not structured:
        if description:
            parts.append(description)
    else:
        if description:
            parts.append(f"## {h['description']}\n{description}")
        if draft.steps:
            numbered = "\n".join(f"{n}. {step}" for n, step in enumerate(draft.steps, 1))
            parts.append(f"## {h['steps']}\n{numbered}")
        if draft.expected.strip():
            parts.append(f"## {h['expected']}\n{draft.expected.strip()}")
        if draft.actual.strip():
            parts.append(f"## {h['actual']}\n{draft.actual.strip()}")
    if draft.source_url:
        parts.append(f"---\n{h['source']}: {draft.source_url}")
    return "\n\n".join(parts)


def missing(draft: Draft, game_exists: bool) -> list[str]:
    """What a good issue still lacks: any of `kind`, `description`, `steps`, `game`."""
    gaps = []
    if not draft.kind:
        gaps.append("kind")
    if draft.from_thread and not draft.description.strip():
        gaps.append("description")
    if draft.kind == "bug" and not draft.steps:
        gaps.append("steps")
    if game_exists and not draft.game:
        gaps.append("game")
    return gaps


def blocking(draft: Draft) -> list[str]:
    """The gaps that stop Confirm: the type always, the description for a thread draft."""
    return [g for g in missing(draft, game_exists=False) if g in ("kind", "description")]


def _lines(text: str) -> tuple[str, ...]:
    lines = (_BULLET.sub("", line).strip() for line in text.splitlines())
    return tuple(clip(neutralise_mentions(line), MAX_STEP) for line in lines if line)[:MAX_STEPS]


def apply_form(
    draft: Draft, *, title: str, description: str, steps: str, expected: str, actual: str
) -> Draft:
    """The draft after the details form: what the user typed replaces what was there."""
    title = neutralise_mentions(title.strip())
    return replace(
        draft,
        title=clip(title, MAX_TITLE) if title else draft.title,
        description=clip(neutralise_mentions(description.strip()), MAX_DESCRIPTION),
        steps=_lines(steps),
        expected=clip(neutralise_mentions(expected.strip()), MAX_EXPECTED),
        actual=clip(neutralise_mentions(actual.strip()), MAX_EXPECTED),
    )


def _text(value: object, limit: int) -> str:
    return clip(neutralise_mentions(value.strip()), limit) if isinstance(value, str) else ""


def parse_draft(
    args: dict,
    *,
    thread_name: str,
    names: list[str],
    url: str,
    read: int,
    total: int,
) -> Draft:
    """A Draft from the model's `draft_issue` arguments. Every field is checked, none trusted."""
    steps = args.get("steps")
    steps_in: Iterable = steps if isinstance(steps, list) else []
    lang = args.get("lang")
    return Draft(
        title=_text(args.get("title"), MAX_TITLE) or _text(thread_name, MAX_TITLE),
        kind=resolve_kind(str(args.get("kind") or "")),
        game=match_game(str(args.get("game") or ""), names),
        description=_text(args.get("description"), MAX_DESCRIPTION),
        steps=tuple(s for s in (_text(x, MAX_STEP) for x in steps_in) if s)[:MAX_STEPS],
        expected=_text(args.get("expected"), MAX_EXPECTED),
        actual=_text(args.get("actual"), MAX_EXPECTED),
        lang=lang if lang in HEADINGS else "en",
        source_url=url,
        from_thread=True,
        read=read,
        total=total,
    )


MAX_THREAD_MESSAGES = 60
HEAD_MESSAGES = 3
MAX_MESSAGE_CHARS = 1500
MAX_THREAD_CHARS = 12000


@dataclass(frozen=True)
class Collected:
    text: str
    read: int  # messages read
    total: int  # messages the thread has


def _line(message) -> str:
    text = (message.clean_content or "").strip()
    attachments = " ".join(f"[attachment: {a.filename}]" for a in message.attachments)
    body = clip(" ".join(part for part in (text, attachments) if part), MAX_MESSAGE_CHARS)
    return f"{message.author.display_name}: {body}" if body else ""


def _fit(lines: list[str], limit: int) -> list[str]:
    """Keep the first few lines and as many of the latest as fit, saying how many were left out."""
    if sum(len(x) + 1 for x in lines) <= limit:
        return lines
    head, rest = lines[:HEAD_MESSAGES], lines[HEAD_MESSAGES:]
    budget = limit - sum(len(x) + 1 for x in head)
    tail: list[str] = []
    for line in reversed(rest):
        if len(line) + 1 > budget:
            break
        tail.insert(0, line)
        budget -= len(line) + 1
    left_out = len(rest) - len(tail)
    return head + ([f"[... {left_out} messages left out ...]"] if left_out else []) + tail


async def collect(thread) -> Collected:
    """The thread as plain text: its title, its starter post and up to 60 messages.

    When the thread is longer, the first 3 messages and the latest ones are kept. Bot messages
    are skipped and author names are display names, never ids. Raises discord.HTTPException when
    the bot may not read the thread.
    """
    starter = None
    if getattr(thread.parent, "fetch_message", None) and not hasattr(thread.parent, "available_tags"):
        try:  # a thread opened from a message: that message lives in the parent channel
            starter = await thread.parent.fetch_message(thread.id)
        except Exception:  # missing, deleted or not readable: the thread itself still counts
            starter = None
    head = [m async for m in thread.history(limit=HEAD_MESSAGES, oldest_first=True)]
    tail = [m async for m in thread.history(limit=MAX_THREAD_MESSAGES - HEAD_MESSAGES)]
    tail.reverse()
    seen: dict[int, object] = {}
    for message in [*([starter] if starter else []), *head, *tail]:
        seen.setdefault(message.id, message)
    messages = list(seen.values())
    lines = [_line(m) for m in messages if not m.author.bot]
    lines = [line for line in lines if line]
    total = max(len(messages), getattr(thread, "message_count", 0) or 0)
    text = "\n".join([f"Thread title: {thread.name}", *_fit(lines, MAX_THREAD_CHARS)])
    return Collected(text=text if lines else "", read=len(messages), total=total)
