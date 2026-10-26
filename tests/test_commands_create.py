"""/issue create, /issue from-thread and /bulk create: labels, duplicates and spam limits."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from github_discord_bot.ask import BUSY, Limiter
from github_discord_bot.bot import IssueBot, NotAllowed, make_issue_group
from github_discord_bot.config import Settings
from github_discord_bot.github import GitHubError, Issue
from github_discord_bot.quota import CreateQuota

ROLE = 111
LABELS = ["bug", "enhancement", "docs", "game:clash-of-saigon"]


def issue(number=1, title="Bug", state="open"):
    return Issue(number, title, state, f"https://github.com/o/r/issues/{number}", ["bug"], "alice", "body")


def interaction(role_ids=(ROLE,), channel=None):
    return SimpleNamespace(
        user=SimpleNamespace(id=7, roles=[SimpleNamespace(id=i) for i in role_ids]),
        response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock(), is_done=MagicMock(return_value=False)),
        followup=SimpleNamespace(send=AsyncMock(return_value=SimpleNamespace(edit=AsyncMock()))),
        channel=channel,
    )


@pytest.fixture
def gh():
    return MagicMock(
        create_issue=AsyncMock(return_value=issue(5, "New")),
        list_labels=AsyncMock(return_value=list(LABELS)),
        search_issues=AsyncMock(return_value=[]),
    )


def cmd(group, name):
    return group.get_command(name)


def sent(i):
    return i.followup.send.await_args


async def test_create_sends_the_type_and_game_labels(gh):
    group = make_issue_group(gh, ROLE)
    i = interaction()
    await cmd(group, "create").callback(i, "Crash on start", "details", "bug", "game:clash-of-saigon")
    gh.create_issue.assert_awaited_once_with("Crash on start", "details", ["bug", "game:clash-of-saigon"])
    assert "issues/5" in sent(i).args[0]


async def test_an_idea_is_filed_as_an_enhancement(gh):
    group = make_issue_group(gh, ROLE)
    await cmd(group, "create").callback(interaction(), "Dark mode please", "", "idea", None)
    assert gh.create_issue.await_args.args[2] == ["enhancement"]


async def test_game_names_are_matched_loosely_but_must_exist(gh):
    group = make_issue_group(gh, ROLE)
    await cmd(group, "create").callback(interaction(), "Crash on start", "", None, "Clash of Saigon")
    assert gh.create_issue.await_args.args[2] == ["game:clash-of-saigon"]

    gh.create_issue.reset_mock()
    i = interaction()
    await cmd(group, "create").callback(i, "Crash on start", "", None, "tetris")
    gh.create_issue.assert_not_awaited()
    assert "no game label" in sent(i).args[0].lower()


async def test_create_still_works_when_labels_cannot_be_read(gh):
    gh.list_labels.side_effect = GitHubError("Could not reach GitHub.")
    group = make_issue_group(gh, ROLE)
    i = interaction()
    await cmd(group, "create").callback(i, "Crash on start", "", "bug", None)
    gh.create_issue.assert_awaited_once_with("Crash on start", "", None)
    assert "without labels" in sent(i).args[0]


async def test_game_autocomplete_lists_only_game_labels(gh):
    group = make_issue_group(gh, ROLE)
    param = cmd(group, "create")._params["game"]
    choices = await param.autocomplete(interaction(), "clash")
    assert [(c.name, c.value) for c in choices] == [("game:clash-of-saigon", "game:clash-of-saigon")]
    assert [c.value for c in await param.autocomplete(interaction(), "")] == ["game:clash-of-saigon"]
    assert await param.autocomplete(interaction(), "zzz") == []


async def test_similar_issue_turns_the_direct_create_into_a_preview(gh):
    gh.search_issues.return_value = [issue(8, "Crash on start of the game", "closed")]
    group = make_issue_group(gh, ROLE)
    i = interaction()
    await cmd(group, "create").callback(i, "Crash on start", "details", "bug", None)
    gh.create_issue.assert_not_awaited()
    kwargs = sent(i).kwargs
    assert "[#8]" in kwargs["embed"].description and kwargs["view"].confirm.label == "Create anyway"
    assert "ephemeral" not in kwargs  # a followup after a public defer cannot be private
    gh.search_issues.assert_awaited_once_with("crash start")


async def test_no_similar_issue_creates_straight_away(gh):
    group = make_issue_group(gh, ROLE)
    i = interaction()
    await cmd(group, "create").callback(i, "Crash on start", "", None, None)
    gh.create_issue.assert_awaited_once()
    assert "view" not in sent(i).kwargs


async def test_a_failing_search_does_not_stop_a_create(gh):
    gh.search_issues.side_effect = GitHubError("rate limit")
    group = make_issue_group(gh, ROLE)
    await cmd(group, "create").callback(interaction(), "Crash on start", "", None, None)
    gh.create_issue.assert_awaited_once()


async def test_create_obeys_the_per_user_cooldown(gh):
    group = make_issue_group(gh, ROLE, limiter=Limiter())
    first, second = interaction(), interaction()
    await cmd(group, "create").callback(first, "Crash on start", "", None, None)
    await cmd(group, "create").callback(second, "Another crash", "", None, None)
    assert gh.create_issue.await_count == 1
    second.response.send_message.assert_awaited_once_with(BUSY, ephemeral=True)
    second.response.defer.assert_not_awaited()


async def test_create_obeys_the_hourly_cap_and_spends_one(gh):
    quota = CreateQuota(2)
    group = make_issue_group(gh, ROLE, quota=quota)
    for title in ("Crash one", "Crash two", "Crash three"):
        await cmd(group, "create").callback(interaction(), title, "", None, None)
    assert gh.create_issue.await_count == 2
    assert quota.remaining(7) == 0


async def test_capped_user_is_told_before_any_work(gh):
    quota = CreateQuota(1)
    quota.consume(7)
    group = make_issue_group(gh, ROLE, quota=quota)
    i = interaction()
    await cmd(group, "create").callback(i, "Crash on start", "", None, None)
    assert "hourly limit" in i.response.send_message.await_args.args[0]
    gh.list_labels.assert_not_awaited()
    gh.search_issues.assert_not_awaited()


async def test_create_still_needs_the_role(gh):
    group = make_issue_group(gh, ROLE)
    for check in cmd(group, "create").checks:
        with pytest.raises(NotAllowed):
            await check(interaction(role_ids=()))
        assert await check(interaction()) is True


# --- /issue from-thread


def test_from_thread_exists_only_when_groq_is_configured(gh):
    assert cmd(make_issue_group(gh, ROLE), "from-thread") is None
    assert cmd(make_issue_group(gh, ROLE, groq=SimpleNamespace()), "from-thread") is not None


async def test_from_thread_outside_a_thread_says_so(gh):
    group = make_issue_group(gh, ROLE, groq=SimpleNamespace(draft=AsyncMock()))
    i = interaction(channel=SimpleNamespace())
    await cmd(group, "from-thread").callback(i)
    assert sent(i).kwargs["content"] == "Run this inside a thread."
    assert sent(i).kwargs["ephemeral"] is True


async def test_from_thread_needs_the_role(gh):
    group = make_issue_group(gh, ROLE, groq=SimpleNamespace(draft=AsyncMock()))
    for check in cmd(group, "from-thread").checks:
        with pytest.raises(NotAllowed):
            await check(interaction(role_ids=()))
        assert await check(interaction()) is True


async def test_from_thread_obeys_the_cooldown(gh):
    group = make_issue_group(gh, ROLE, limiter=Limiter(), groq=SimpleNamespace(draft=AsyncMock()))
    await cmd(group, "from-thread").callback(interaction(channel=SimpleNamespace()))
    second = interaction(channel=SimpleNamespace())
    await cmd(group, "from-thread").callback(second)
    second.response.send_message.assert_awaited_once_with(BUSY, ephemeral=True)


async def test_from_thread_drafts_privately_and_posts_the_link_in_the_thread(gh, monkeypatch):
    class FakeThread:
        id = 42
        name = "Crash on start"
        jump_url = "https://discord.com/channels/1/42"
        message_count = 1
        parent = SimpleNamespace()
        send = AsyncMock()

        def history(self, limit=None, oldest_first=False):
            async def gen():
                yield SimpleNamespace(
                    id=1, author=SimpleNamespace(bot=False, display_name="An"),
                    clean_content="the game crashes on start", attachments=[],
                )

            return gen()

    monkeypatch.setattr("discord.Thread", FakeThread)
    groq = SimpleNamespace(
        draft=AsyncMock(return_value={"title": "Game crashes", "kind": "bug", "description": "It crashes", "lang": "en"})
    )
    group = make_issue_group(gh, ROLE, groq=groq)
    thread = FakeThread()
    i = interaction(channel=thread)
    await cmd(group, "from-thread").callback(i)
    i.response.defer.assert_awaited_once_with(ephemeral=True)
    view = sent(i).kwargs["view"]
    assert sent(i).kwargs["ephemeral"] is True

    press = SimpleNamespace(
        user=SimpleNamespace(id=7, roles=[SimpleNamespace(id=ROLE)]),
        response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
        edit_original_response=AsyncMock(),
    )
    await view.confirm.callback(press)
    gh.create_issue.assert_awaited_once()
    thread.send.assert_awaited_once()
    assert "issues/5" in thread.send.await_args.args[0]


# --- the bot wiring


def settings(**kw):
    return Settings("d", "g", "o/r", ROLE, None, "gsk_secret", **kw)


async def test_the_bot_builds_the_cap_from_settings():
    bot = IssueBot(settings(create_limit_per_hour=3))
    assert bot.quota.limit == 3
    assert bot.tree.get_command("issue").get_command("from-thread") is not None
    await bot.close()


async def test_without_groq_there_is_no_from_thread():
    bot = IssueBot(Settings("d", "g", "o/r", ROLE))
    assert bot.tree.get_command("issue").get_command("from-thread") is None
    await bot.close()


async def test_bulk_create_obeys_the_cooldown_but_other_bulk_actions_do_not():
    bot = IssueBot(settings())
    bulk = bot.tree.get_command("bulk")
    bot.limiter.check(7)  # the caller just used up their slot

    busy = interaction()
    await bulk.callback(busy, "create", "a; b", "")
    busy.response.send_message.assert_awaited_once_with(BUSY, ephemeral=True)
    busy.response.defer.assert_not_awaited()

    bot.github = MagicMock(get_issue=AsyncMock(return_value=issue(1)), aclose=AsyncMock())
    view = interaction()
    await bulk.callback(view, "view", "1, 2", "")
    view.response.send_message.assert_not_awaited()
    view.response.defer.assert_awaited_once()
    await bot.close()
