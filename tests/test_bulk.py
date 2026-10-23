import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from github_discord_bot import bulk
from github_discord_bot.ask import MESSAGES, ConfirmView, submit
from github_discord_bot.bot import IssueBot
from github_discord_bot.config import Settings
from github_discord_bot.github import GitHubError, Issue
from github_discord_bot.intent import Intent, validate_intent
from github_discord_bot.targets import BulkInputError, expand_tokens, parse_numbers

M = MESSAGES["en"]
ROLE = 111
OWNER = 7


def issue(n, title="Bug", state="open", assignees=()):
    return Issue(n, title, state, f"https://github.com/o/r/issues/{n}", [], "alice", "", list(assignees))


def make_gh(issues):
    """A fake client over a mutable dict of issues. A title starting with 'PR:' is a pull request."""
    gh = MagicMock()

    async def get_issue(n):
        if n not in issues:
            raise GitHubError("Repository or issue not found.", 404)
        if issues[n].title.startswith("PR:"):
            raise GitHubError(f"#{n} is a pull request, not an issue.")
        return issues[n]

    async def close_issue(n):
        issues[n] = issue(n, issues[n].title, "closed")
        return issues[n]

    gh.aclose = AsyncMock()
    gh.get_issue = AsyncMock(side_effect=get_issue)
    gh.close_issue = AsyncMock(side_effect=close_issue)
    gh.comment = AsyncMock(return_value="https://github.com/o/r/issues/1#c")
    gh.assign = AsyncMock(side_effect=lambda n, who: issues[n])
    gh.unassign = AsyncMock(side_effect=lambda n, who: issues[n])
    gh.assignable_login = AsyncMock(return_value="Zinbac000")
    gh.create_issue = AsyncMock(side_effect=lambda title, body="": issue(100 + len(title), title))
    return gh


def close_intent(*numbers):
    return Intent("close", numbers=tuple(numbers))


# ---- reading numbers

def test_parse_numbers_lists_ranges_and_dedupe():
    assert parse_numbers("close 12, 15 and 20-22") == [12, 15, 20, 21, 22]
    assert parse_numbers("12 12 12") == [12]
    assert parse_numbers("12 - 14") == [12, 13, 14]


def test_digits_in_words_and_mention_ids_are_not_numbers():
    assert parse_numbers("e2e v2 build <@123456789> user-42") == []


@pytest.mark.parametrize("bad", ["20-12", "1-99999", "2024-10-22"])
def test_bad_ranges_are_rejected_before_expanding(bad):
    with pytest.raises(BulkInputError):
        parse_numbers(bad)


def test_expand_tokens():
    assert expand_tokens(["12", "15-17", "12"]) == [12, 15, 16, 17]
    with pytest.raises(BulkInputError):
        expand_tokens(["abc"])


# ---- intent validation

def test_model_numbers_must_match_what_the_user_typed_exactly():
    ok = validate_intent(close_intent(12, 15, 20), "close 12, 15 and 20")
    assert ok.action == "close" and ok.numbers == (12, 15, 20) and ok.number is None
    assert validate_intent(close_intent(12, 15), "close 12, 15 and 20").action == "clarify"  # dropped one
    assert validate_intent(close_intent(12, 15, 99), "close 12 and 15").action == "clarify"  # invented one
    assert validate_intent(Intent("close", number=15), "close 12 not 15").action == "clarify"


def test_ranges_are_expanded_by_code():
    out = validate_intent(close_intent(12, 13, 14), "close 12-14")
    assert out.numbers == (12, 13, 14)


def test_a_single_number_stays_a_single_intent():
    out = validate_intent(Intent("close", numbers=(12,)), "close 12")
    assert out.number == 12 and out.numbers == ()


def test_bulk_create_titles_must_appear_in_the_users_text():
    text = "create issues: fix login; add dark mode"
    out = validate_intent(Intent("create", titles=("fix login", "add dark mode")), text)
    assert out.titles == ("fix login", "add dark mode") and out.title == ""
    assert validate_intent(Intent("create", titles=("fix login", "invented")), text).action == "clarify"
    one = validate_intent(Intent("create", titles=("fix login",)), text)
    assert one.title == "fix login" and one.titles == ()


# ---- /bulk input

def test_build_intent_for_each_action():
    assert bulk.build_intent("close", "12, 15-16", "").numbers == (12, 15, 16)
    assert bulk.build_intent("close", "12", "").number == 12
    assert bulk.build_intent("create", "a; b\nc", "").titles == ("a", "b", "c")
    assert bulk.build_intent("comment", "1,2", "hello").body == "hello"
    assert bulk.build_intent("assign", "1,2", "@zinbac000").assignee == "zinbac000"
    for action, targets, value in [("comment", "1,2", ""), ("assign", "1,2", "../x"), ("close", "none", ""), ("create", " ; ", "")]:
        with pytest.raises(BulkInputError):
            bulk.build_intent(action, targets, value)


# ---- preparing and previewing

async def test_prepare_skips_closed_refuses_prs_and_reports_missing():
    gh = make_gh({1: issue(1), 2: issue(2, state="closed"), 3: issue(3, "PR: x")})
    items = await bulk.prepare(gh, close_intent(1, 2, 3, 4))
    assert [(i.key, i.state) for i in items] == [("#1", "todo"), ("#2", "skip"), ("#3", "error"), ("#4", "error")]
    assert "pull request" in items[2].note and "not found" in items[3].note


async def test_prepare_assign_and_unassign_rules():
    gh = make_gh({1: issue(1, assignees=["Zinbac000"]), 2: issue(2)})
    intent = Intent("assign", numbers=(1, 2), assignee="zinbac000", assignee_kind="login")
    assert [i.state for i in await bulk.prepare(gh, intent)] == ["skip", "todo"]
    intent = Intent("unassign", numbers=(1, 2), assignee="zinbac000", assignee_kind="login")
    assert [i.state for i in await bulk.prepare(gh, intent)] == ["todo", "skip"]
    gh.assignable_login.return_value = None
    with pytest.raises(GitHubError, match="cannot be assigned"):
        await bulk.prepare(gh, Intent("assign", numbers=(1, 2), assignee="x", assignee_kind="login"))


async def test_preview_states_the_count_first_and_escapes_untrusted_titles():
    gh = make_gh({1: issue(1, "@everyone **bold** " + "x" * 200), 2: issue(2, state="closed")})
    items = await bulk.prepare(gh, close_intent(1, 2))
    text, full, todo = bulk.preview(close_intent(1, 2), items, M)
    assert text.startswith("**Close 1 issues?**") and "(1 will not run)" in text and todo == 1
    assert "@everyone" not in text and "\\*\\*bold\\*\\*" in text
    assert full is None
    assert max(len(line) for line in text.splitlines()) < 120  # titles are cut


async def test_a_long_list_is_shortened_and_the_full_list_goes_in_a_file():
    issues = {n: issue(n, "t" * 60) for n in range(1, 300)}
    intent = close_intent(*issues)
    items = await bulk.prepare(make_gh(issues), intent)
    text, full, todo = bulk.preview(intent, items, M)
    assert todo == 299 and len(text) <= 4000 and full is not None
    assert M["bulk_shortened"] in text and "#299" in full and "#299" not in text


# ---- executing

async def run(gh, intent, items=None, **kw):
    items = items if items is not None else await bulk.prepare(gh, intent)
    sleeps = []

    async def sleep(seconds):
        sleeps.append(seconds)

    outcomes = await bulk.execute(gh, intent, items, sleep=sleep, **kw)
    return outcomes, sleeps


async def test_items_run_in_order_with_a_pause_between_writes():
    issues = {n: issue(n) for n in (1, 2, 3)}
    gh = make_gh(issues)
    outcomes, sleeps = await run(gh, close_intent(1, 2, 3))
    assert [c.args[0] for c in gh.close_issue.await_args_list] == [1, 2, 3]
    assert [o.status for o in outcomes] == ["ok"] * 3
    assert sleeps == [0.5, 0.5]  # between items, none after the last


async def test_one_failure_does_not_stop_the_rest():
    gh = make_gh({1: issue(1), 2: issue(2), 3: issue(3)})
    original = gh.close_issue.side_effect

    async def flaky(n):
        if n == 2:
            raise GitHubError("GitHub rejected that input.", 422)
        return await original(n)

    gh.close_issue.side_effect = flaky
    outcomes, _ = await run(gh, close_intent(1, 2, 3))
    assert [o.status for o in outcomes] == ["ok", "failed", "ok"]


async def test_a_rate_limit_stops_the_run_and_marks_the_rest_not_attempted():
    gh = make_gh({n: issue(n) for n in (1, 2, 3, 4)})
    original = gh.close_issue.side_effect

    async def limited(n):
        if n == 2:
            raise GitHubError("GitHub refused the request: rate limit.", 403)
        return await original(n)

    gh.close_issue.side_effect = limited
    outcomes, sleeps = await run(gh, close_intent(1, 2, 3, 4))
    assert [o.status for o in outcomes] == ["ok", "failed", "not_attempted", "not_attempted"]
    assert gh.close_issue.await_count == 2


async def test_state_that_drifted_after_the_preview_is_skipped_not_rewritten():
    issues = {1: issue(1), 2: issue(2)}
    gh = make_gh(issues)
    intent = close_intent(1, 2)
    items = await bulk.prepare(gh, intent)
    issues[2] = issue(2, state="closed")  # someone closed it after the preview
    issues[1] = issue(1, "PR: now a pull request")
    outcomes, _ = await run(gh, intent, items)
    assert [(o.key, o.status) for o in outcomes] == [("#1", "failed"), ("#2", "skipped")]
    gh.close_issue.assert_not_awaited()


async def test_create_is_never_retried_and_an_unclear_failure_is_reported_as_unknown():
    gh = make_gh({})
    gh.create_issue.side_effect = [issue(1, "a"), GitHubError("Could not reach GitHub."), issue(3, "c")]
    intent = Intent("create", titles=("a", "b", "c"))
    outcomes, sleeps = await run(gh, intent)
    assert [o.status for o in outcomes] == ["ok", "unknown", "ok"]
    assert gh.create_issue.await_count == 3
    assert sleeps == [1.0, 1.0]


async def test_comment_assign_unassign_execute_per_item():
    gh = make_gh({1: issue(1), 2: issue(2)})
    await run(gh, Intent("comment", numbers=(1, 2), body="hi"))
    assert gh.comment.await_count == 2
    await run(gh, Intent("assign", numbers=(1, 2), assignee="zinbac000", assignee_kind="login"))
    assert gh.assign.await_count == 2
    gh2 = make_gh({1: issue(1, assignees=["zinbac000"]), 2: issue(2, assignees=["zinbac000"])})
    await run(gh2, Intent("unassign", numbers=(1, 2), assignee="zinbac000", assignee_kind="login"))
    assert gh2.unassign.await_count == 2


def test_report_counts_lists_problems_and_a_retry_list():
    outcomes = [bulk.Outcome("#1", "ok"), bulk.Outcome("#2", "skipped", "already closed"),
                bulk.Outcome("#3", "failed", "boom"), bulk.Outcome("#4", "not_attempted", "stopped")]
    summary, full = bulk.report(outcomes, M)
    assert "1 ok, 1 skipped, 1 failed, 0 unknown, 1 not attempted" in summary
    assert "#3: boom" in summary and "Retry: 3, 4" in summary and full is None


def test_a_big_report_goes_in_a_file_but_the_summary_stays_short():
    outcomes = [bulk.Outcome(f"#{n}", "failed", "boom") for n in range(1, 60)]
    summary, full = bulk.report(outcomes, M)
    assert len(summary) <= 1900 and full is not None and "#59" in full


# ---- through submit(): gating, preview, confirm

def press(user_id=OWNER, role_ids=(ROLE,)):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, roles=[SimpleNamespace(id=i) for i in role_ids]),
        response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


async def go(gh, intent, *, roles=(ROLE,), text="close"):
    reply = AsyncMock(return_value=SimpleNamespace(edit=AsyncMock()))
    await submit(intent=intent, text=text, user_id=OWNER, role_ids=roles, role_id=ROLE, gh=gh, reply=reply)
    return reply


async def test_bulk_without_the_role_is_refused_before_anything_is_fetched():
    gh = make_gh({1: issue(1), 2: issue(2)})
    reply = await go(gh, close_intent(1, 2), roles=())
    assert "role" in reply.await_args.kwargs["content"]
    gh.get_issue.assert_not_awaited()


async def test_bulk_preview_then_confirm_runs_exactly_the_frozen_list_once():
    issues = {1: issue(1), 2: issue(2), 3: issue(3, state="closed")}
    gh = make_gh(issues)
    reply = await go(gh, close_intent(1, 2, 3))
    view = reply.await_args.kwargs["view"]
    assert isinstance(view, ConfirmView) and view.timeout == 300
    assert reply.await_args.kwargs["embed"].description.startswith("**Close 2 issues?**")
    gh.close_issue.assert_not_awaited()

    issues[9] = issue(9)  # new issues appearing later change nothing
    first, second = press(), press()
    await asyncio.gather(view.confirm.callback(first), view.confirm.callback(second))
    assert sorted(c.args[0] for c in gh.close_issue.await_args_list) == [1, 2]
    assert "2 ok, 1 skipped" in first.edit_original_response.await_args.kwargs["content"]
    second.response.send_message.assert_awaited_once()


async def test_role_is_rechecked_on_confirm_for_bulk():
    gh = make_gh({1: issue(1), 2: issue(2)})
    view = (await go(gh, close_intent(1, 2))).await_args.kwargs["view"]
    await view.confirm.callback(press(role_ids=()))
    gh.close_issue.assert_not_awaited()


async def test_nothing_to_do_shows_why_and_offers_no_confirm():
    gh = make_gh({1: issue(1, state="closed"), 2: issue(2, state="closed")})
    reply = await go(gh, close_intent(1, 2))
    assert "Nothing to do" in reply.await_args.kwargs["content"]
    assert "view" not in reply.await_args.kwargs


async def test_bulk_view_reads_without_confirm_or_role():
    gh = make_gh({1: issue(1, "One", assignees=["zinbac000"]), 2: issue(2, "Two")})
    reply = await go(gh, Intent("view", numbers=(1, 2)), roles=())
    description = reply.await_args.kwargs["embed"].description
    assert "#1 [open] One - zinbac000" in description and "#2 [open] Two" in description
    assert "view" not in reply.await_args.kwargs


async def test_bulk_create_preview_lists_titles():
    gh = make_gh({})
    reply = await go(gh, Intent("create", titles=("fix login", "add dark mode")))
    description = reply.await_args.kwargs["embed"].description
    assert description.startswith("**Create 2 issues?**") and "fix login" in description
    gh.create_issue.assert_not_awaited()


async def test_a_bad_assignee_refuses_the_whole_bulk_assign():
    gh = make_gh({1: issue(1), 2: issue(2)})
    gh.assignable_login.return_value = None
    intent = Intent("assign", numbers=(1, 2), assignee="stranger", assignee_kind="login")
    reply = await go(gh, intent, text="assign 1, 2 to stranger")
    assert "cannot be assigned" in reply.await_args.kwargs["content"]
    assert "view" not in reply.await_args.kwargs


# ---- the /bulk slash command

async def slash(bot, **options):
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=OWNER, roles=[SimpleNamespace(id=options.pop("role", ROLE))]),
        response=SimpleNamespace(defer=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    await bot.tree.get_command("bulk").callback(interaction, **options)
    return interaction


async def test_slash_bulk_previews_for_a_role_member_and_refuses_others():
    bot = IssueBot(Settings("d", "g", "o/r", ROLE))
    bot._connection.user = SimpleNamespace(id=999)
    gh = make_gh({1: issue(1), 2: issue(2)})
    bot.github = gh
    ok = await slash(bot, action="close", targets="1, 2", value="")
    kwargs = ok.followup.send.await_args.kwargs
    assert isinstance(kwargs["view"], ConfirmView) and kwargs["ephemeral"] is True
    refused = await slash(bot, action="close", targets="1, 2", value="", role=999)
    assert "role" in refused.followup.send.await_args.kwargs["content"]
    bad = await slash(bot, action="close", targets="20-12", value="")
    assert "backwards" in bad.followup.send.await_args.kwargs["content"]
    await bot.close()
