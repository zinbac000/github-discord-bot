import re

MAX_WORDS = 6
MIN_WORDS = 2
MIN_LENGTH = 3
_STOPWORDS = frozenset(
    """
    the and for with that this from have has not are was were but you your our can when then than into
    onto out all any new add fix bug issue
    cho của và là các một những này khi bị không được trong trên với để có các đã sẽ khi thì mà như
    tạo lỗi thêm sửa
    """.split()
)


def keywords(title: str) -> str:
    """The search words for a title: lowercase, no punctuation or filler, at most six.

    Returns "" when fewer than two useful words are left, so a vague title never searches.
    """
    words = re.findall(r"\w+", title.lower())
    kept: list[str] = []
    for word in words:
        if len(word) >= MIN_LENGTH and word not in _STOPWORDS and word not in kept:
            kept.append(word)
    return " ".join(kept[:MAX_WORDS]) if len(kept) >= MIN_WORDS else ""
