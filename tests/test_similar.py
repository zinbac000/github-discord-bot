import pytest

from github_discord_bot.similar import keywords


def test_keeps_the_meaningful_words_lowercase():
    assert keywords("Login crash on Safari") == "login crash safari"


def test_drops_punctuation_stopwords_and_short_words():
    assert keywords("Fix: the login, and the logout!") == "login logout"
    assert keywords("tạo issue lỗi đăng nhập trên Safari") == "đăng nhập safari"


def test_at_most_six_distinct_words():
    words = keywords("alpha beta gamma delta epsilon zeta eta theta alpha")
    assert words == "alpha beta gamma delta epsilon zeta"


@pytest.mark.parametrize("title", ["", "bug", "fix it", "ab cd", "Fix bug"])
def test_vague_titles_do_not_search(title):
    assert keywords(title) == ""
