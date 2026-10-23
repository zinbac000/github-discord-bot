import pytest

from github_discord_bot.config import ConfigError, load_settings

VALID = {
    "DISCORD_TOKEN": "d-token",
    "GITHUB_TOKEN": "g-token",
    "GITHUB_REPO": "zinbac000/github-discord-bot",
    "ALLOWED_ROLE_ID": "123",
}


def test_valid_without_guild():
    s = load_settings(VALID)
    assert s.github_repo == "zinbac000/github-discord-bot"
    assert s.allowed_role_id == 123
    assert s.discord_guild_id is None


def test_valid_with_guild():
    assert load_settings({**VALID, "DISCORD_GUILD_ID": "42"}).discord_guild_id == 42


@pytest.mark.parametrize("name", VALID)
def test_each_required_variable_missing(name):
    env = {k: v for k, v in VALID.items() if k != name}
    with pytest.raises(ConfigError, match=f"{name} is missing"):
        load_settings(env)


def test_all_problems_reported_together():
    with pytest.raises(ConfigError) as exc:
        load_settings({})
    for name in VALID:
        assert name in str(exc.value)


@pytest.mark.parametrize("repo", ["justaname", "a/b/c", "a b/c"])
def test_bad_repo_format(repo):
    with pytest.raises(ConfigError, match="owner/name"):
        load_settings({**VALID, "GITHUB_REPO": repo})


@pytest.mark.parametrize("name", ["ALLOWED_ROLE_ID", "DISCORD_GUILD_ID"])
def test_non_numeric_ids(name):
    with pytest.raises(ConfigError, match=f"{name} must be a number"):
        load_settings({**VALID, name: "abc"})


def test_groq_defaults_when_unset():
    s = load_settings(VALID)
    assert s.groq_api_key is None
    assert s.groq_model == "llama-3.3-70b-versatile"
    assert s.groq_fallback_model is None


def test_groq_values_are_read():
    s = load_settings({**VALID, "GROQ_API_KEY": "k", "GROQ_MODEL": "m", "GROQ_FALLBACK_MODEL": "f"})
    assert (s.groq_api_key, s.groq_model, s.groq_fallback_model) == ("k", "m", "f")


def test_empty_groq_key_means_disabled():
    assert load_settings({**VALID, "GROQ_API_KEY": "  "}).groq_api_key is None


def test_user_map_is_parsed():
    s = load_settings({**VALID, "GITHUB_USER_MAP": "111=zinbac000, 222=@octocat"})
    assert s.github_user_map == {111: "zinbac000", 222: "octocat"}
    assert load_settings(VALID).github_user_map == {}


@pytest.mark.parametrize("raw", ["abc=zinbac000", "111", "111=", "111=bad login", "111=../x"])
def test_malformed_user_map_is_rejected(raw):
    with pytest.raises(ConfigError, match="GITHUB_USER_MAP"):
        load_settings({**VALID, "GITHUB_USER_MAP": raw})
