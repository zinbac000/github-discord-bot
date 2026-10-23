"""Reading issue numbers out of text. Pure code, so the AI never decides what was meant."""

import re
from collections.abc import Iterable

MAX_RANGE = 10_000  # sanity bound for one "a-b" range, not a limit on how many issues you can name

_MENTION_ID = re.compile(r"<[@#&!]*\d+>")
_TOKEN = re.compile(r"(?<![\w-])(\d+)(?:\s*-\s*(\d+))?(?!\w)")
_ONE = re.compile(r"(\d+)(?:\s*-\s*(\d+))?")


class BulkInputError(ValueError):
    """The targets could not be understood. The message is safe to show."""


def _expand(start: str, end: str | None) -> range:
    a = int(start)
    b = int(end) if end else a
    if b < a:
        raise BulkInputError(f"{start}-{end} is a backwards range.")
    if b - a + 1 > MAX_RANGE:
        raise BulkInputError(f"{start}-{end} is too large a range.")
    return range(a, b + 1)


def parse_numbers(text: str) -> list[int]:
    """Issue numbers written in `text` (lists and a-b ranges), deduplicated, in order.

    Digits glued to letters ("e2e", "v2") and Discord mention ids are not issue numbers.
    """
    seen: dict[int, None] = {}
    for match in _TOKEN.finditer(_MENTION_ID.sub("", text)):
        for n in _expand(match.group(1), match.group(2)):
            seen.setdefault(n, None)
    return list(seen)


def expand_tokens(tokens: Iterable[str]) -> list[int]:
    """Expand model-supplied tokens such as "12" or "12-15" the same way."""
    seen: dict[int, None] = {}
    for token in tokens:
        match = _ONE.fullmatch(str(token).strip())
        if not match:
            raise BulkInputError(f"{token!r} is not an issue number.")
        for n in _expand(match.group(1), match.group(2)):
            seen.setdefault(n, None)
    return list(seen)
