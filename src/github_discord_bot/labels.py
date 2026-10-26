import re

TYPE_LABELS = ("bug", "enhancement")
GAME_PREFIX = "game:"
_ENHANCEMENT_WORDS = {"idea", "enhancement"}


def resolve_kind(raw: str) -> str:
    """`bug` or `enhancement`, or "" when unclear. An idea counts as an enhancement."""
    word = raw.strip().lower()
    if word == "bug":
        return "bug"
    return "enhancement" if word in _ENHANCEMENT_WORDS else ""


def game_labels(names: list[str]) -> list[str]:
    return sorted(n for n in names if n.lower().startswith(GAME_PREFIX))


def _norm(text: str) -> str:
    text = text.strip().lower().removeprefix(GAME_PREFIX)
    return " ".join(re.sub(r"[-_\s]+", " ", text).split())


def match_game(raw: str, names: list[str]) -> str:
    """The repo's `game:*` label the words in `raw` name, or "". Never invents a label."""
    wanted = _norm(raw)
    if not wanted:
        return ""
    for label in game_labels(names):
        name = _norm(label)
        if name and (name == wanted or re.search(rf"(?<!\w){re.escape(name)}(?!\w)", wanted)):
            return label
    return ""


def _canonical(name: str, names: list[str]) -> str:
    return next((n for n in names if n.lower() == name.lower()), "")


def final_labels(kind: str, game: str, names: list[str]) -> tuple[str, ...]:
    """The labels to send: the type and the game, each only if the repo really has it."""
    labels = []
    if kind in TYPE_LABELS:
        labels.append(_canonical(kind, names))
    if game.lower().startswith(GAME_PREFIX):
        labels.append(_canonical(game, names))
    return tuple(label for label in labels if label)
