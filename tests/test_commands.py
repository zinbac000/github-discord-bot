from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from github_discord_bot.bot import NotAllowed, make_issue_group, on_command_error
from github_discord_bot.github import GitHubError, Issue

ROLE = 111


def issue(number=1, title="Bug", state="open"):
    return Issue(number, title, state, f"https://github.com/o/r/issues/{number}", ["bug"], "alice", "body")


def interaction(role_ids=(ROLE,), done=False):
    return SimpleNamespace(
        user=SimpleNamespace(id=7, roles=[SimpleNamespace(id=i) for i in role_ids]),
        response=SimpleNamespace(
            defer=AsyncMock(), send_message=AsyncMock(), is_done=MagicMock(return_value=done)
        ),
        followup=SimpleNamespace(send=AsyncMock()),
    )


@pytest.fixture
def gh():
    return MagicMock(
        create_issue=AsyncMock(return_value=issue(5, "New")),
        list_issues=AsyncMock(return_value=([issue(1), issue(2, "Other")], False)),
        get_issue=AsyncMock(return_value=issue(3)),
        close_issue=AsyncMock(return_value=issue(3, state="closed")),
        comment=AsyncMock(return_value="https://github.com/o/r/issues/3#c"),
        list_labels=AsyncMock(return_value=["bug", "enhancement", "game:clash-of-saigon"]),
        search_issues=AsyncMock(return_value=[]),
    )


@pytest.fixture
def group(gh):
    return make_issue_group(gh, ROLE)


def cmd(group, name):
    return group.get_command(name)


async def passes_checks(command, i):
    return [await check(i) for check in command.checks]


async def test_create_replies_with_link(group, gh):
    i = interaction()
    await cmd(group, "create").callback(i, "New", "details")
    gh.create_issue.assert_awaited_once_with("New", "details", None)
    i.response.defer.assert_awaited_once()
    assert "issues/5" in i.followup.send.await_args.args[0]


async def test_list_defaults_and_filters(group, gh):
    i = interaction()
    await cmd(group, "list").callback(i, "closed", "bug")
    gh.list_issues.assert_awaited_once_with("closed", "bug", page=1)
    embed = i.followup.send.await_args.kwargs["embed"]
    assert "#1" in embed.description and "#2" in embed.description


async def test_list_empty(group, gh):
    gh.list_issues.return_value = ([], False)
    i = interaction()
    await cmd(group, "list").callback(i, "open", None)
    assert "No open issues" in i.followup.send.await_args.kwargs["content"]


async def test_view(group, gh):
    i = interaction()
    await cmd(group, "view").callback(i, 3)
    embed = i.followup.send.await_args.kwargs["embed"]
    assert embed.title == "#3 Bug"


@pytest.mark.parametrize("name", ["create", "close", "comment"])
async def test_write_commands_deny_without_role(group, name):
    with pytest.raises(NotAllowed):
        await passes_checks(cmd(group, name), interaction(role_ids=(999,)))


@pytest.mark.parametrize("name", ["create", "close", "comment"])
async def test_write_commands_allow_with_role(group, name):
    assert await passes_checks(cmd(group, name), interaction()) == [True]


@pytest.mark.parametrize("name", ["list", "view"])
def test_read_commands_have_no_role_gate(group, name):
    assert cmd(group, name).checks == []


async def test_close_and_comment(group, gh):
    i = interaction()
    await cmd(group, "close").callback(i, 3)
    assert "Closed" in i.followup.send.await_args.args[0]
    await cmd(group, "comment").callback(i, 3, "thanks")
    gh.comment.assert_awaited_once_with(3, "thanks")


async def test_error_handler_not_allowed_is_ephemeral():
    i = interaction()
    await on_command_error(i, NotAllowed())
    assert i.response.send_message.await_args.kwargs["ephemeral"] is True


async def test_error_handler_shows_github_message_after_defer():
    i = interaction(done=True)
    wrapped = SimpleNamespace(original=GitHubError("token expired"))
    await on_command_error(i, wrapped)
    assert i.followup.send.await_args.args[0] == "token expired"


async def test_error_handler_swallows_unexpected_errors():
    i = interaction()
    await on_command_error(i, RuntimeError("boom"))
    assert "went wrong" in i.response.send_message.await_args.args[0]


@pytest.mark.parametrize("name", ["assign", "unassign"])
async def test_assign_commands_are_role_gated(group, name):
    with pytest.raises(NotAllowed):
        await passes_checks(cmd(group, name), interaction(role_ids=(999,)))
    assert await passes_checks(cmd(group, name), interaction()) == [True]


async def test_assign_and_unassign_reply_with_the_person(group, gh):
    gh.assign = AsyncMock(return_value=issue(3))
    gh.unassign = AsyncMock(return_value=issue(3))
    i = interaction()
    await cmd(group, "assign").callback(i, 3, "@zinbac000")
    gh.assign.assert_awaited_once_with(3, "zinbac000")
    assert "Assigned zinbac000" in i.followup.send.await_args.args[0]
    await cmd(group, "unassign").callback(i, 3, "zinbac000")
    assert "Unassigned zinbac000" in i.followup.send.await_args.args[0]


MAP = {7: "zinbac000", 8: "octocat"}


async def test_assign_with_a_discord_mention_goes_through_the_user_map(gh):
    group = make_issue_group(gh, ROLE, MAP)
    gh.assign = AsyncMock(return_value=issue(3))
    gh.unassign = AsyncMock(return_value=issue(3))
    i = interaction()
    await cmd(group, "assign").callback(i, 3, "<@8>")
    gh.assign.assert_awaited_once_with(3, "octocat")
    assert "Assigned octocat" in i.followup.send.await_args.args[0]
    await cmd(group, "unassign").callback(i, 3, "<@!8>")
    gh.unassign.assert_awaited_once_with(3, "octocat")


async def test_assign_to_me_uses_the_callers_entry_in_the_map(gh):
    group = make_issue_group(gh, ROLE, MAP)
    gh.assign = AsyncMock(return_value=issue(3))
    await cmd(group, "assign").callback(interaction(), 3, "me")
    gh.assign.assert_awaited_once_with(3, "zinbac000")


async def test_a_mention_or_me_missing_from_the_map_explains_how_to_fix_it(gh):
    group = make_issue_group(gh, ROLE, MAP)
    gh.assign = AsyncMock()
    for who in ("<@999>", "<@!999>"):
        with pytest.raises(GitHubError, match="GITHUB_USER_MAP"):
            await cmd(group, "assign").callback(interaction(), 3, who)
    with pytest.raises(GitHubError, match="GITHUB_USER_MAP"):
        await make_issue_group(gh, ROLE, {}).get_command("assign").callback(interaction(), 3, "me")
    gh.assign.assert_not_awaited()


async def test_a_plain_login_still_works_with_or_without_the_map(gh):
    gh.assign = AsyncMock(return_value=issue(3))
    await cmd(make_issue_group(gh, ROLE), "assign").callback(interaction(), 3, "@someone")
    gh.assign.assert_awaited_once_with(3, "someone")
