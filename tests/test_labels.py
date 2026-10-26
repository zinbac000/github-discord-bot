import pytest

from github_discord_bot.labels import final_labels, game_labels, match_game, resolve_kind

NAMES = ["bug", "enhancement", "docs", "game:clash-of-saigon", "game:Pho-Run"]


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("bug", "bug"),
        (" Bug ", "bug"),
        ("idea", "enhancement"),  # the repo has no "idea" label: an idea is an enhancement
        ("enhancement", "enhancement"),
        ("feature", ""),
        ("", ""),
        ("P0", ""),
    ],
)
def test_resolve_kind(raw, expected):
    assert resolve_kind(raw) == expected


def test_game_labels_only_the_prefixed_ones_sorted():
    assert game_labels(NAMES) == ["game:Pho-Run", "game:clash-of-saigon"]
    assert game_labels(["bug", "docs"]) == []


@pytest.mark.parametrize(
    "raw",
    [
        "clash of saigon",
        "Clash-Of-Saigon",
        "clash_of_saigon",
        "game:clash-of-saigon",
        "tôi chơi clash of saigon hôm qua",
    ],
)
def test_match_game_finds_the_repo_label(raw):
    assert match_game(raw, NAMES) == "game:clash-of-saigon"


@pytest.mark.parametrize("raw", ["", "   ", "tetris", "clash", "saigon", "pho"])
def test_match_game_never_invents_a_label(raw):
    assert match_game(raw, NAMES) == ""


def test_match_game_needs_whole_words():
    assert match_game("phoenix", ["game:pho"]) == ""
    assert match_game("a pho run", ["game:pho"]) == "game:pho"


def test_final_labels_type_then_game():
    assert final_labels("bug", "game:clash-of-saigon", NAMES) == ("bug", "game:clash-of-saigon")
    assert final_labels("enhancement", "", NAMES) == ("enhancement",)
    assert final_labels("", "", NAMES) == ()


def test_final_labels_drop_what_the_repo_does_not_have():
    assert final_labels("bug", "game:gone", ["docs"]) == ()
    assert final_labels("bug", "game:clash-of-saigon", ["bug"]) == ("bug",)


def test_final_labels_use_the_repos_own_casing():
    assert final_labels("bug", "game:pho-run", ["Bug", "game:Pho-Run"]) == ("Bug", "game:Pho-Run")


def test_final_labels_refuse_a_game_without_the_prefix():
    assert final_labels("", "docs", NAMES) == ()
    assert final_labels("P0", "", ["P0"]) == ()
