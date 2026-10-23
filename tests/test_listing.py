from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from github_discord_bot.ask import submit
from github_discord_bot.github import GitHubError, Issue
from github_discord_bot.intent import Intent
from github_discord_bot.listing import ListView, first_page
from github_discord_bot.render import list_embed

OWNER = 7


def issue(n):
    return Issue(n, f"Issue {n}", "open", f"https://github.com/o/r/issues/{n}")


def pages(*batches):
    """A fake client whose list_issues serves the given (issues, has_next) pages in order."""
    gh = MagicMock()

    async def list_issues(state="open", label=None, page=1, per_page=20):
        return batches[page - 1]

    gh.list_issues = AsyncMock(side_effect=list_issues)
    return gh


def press(user_id=OWNER):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id),
        response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


async def test_a_single_page_has_no_buttons():
    gh = pages(([issue(1), issue(2)], False))
    content, embed, view = await first_page(gh, "open", None, OWNER, "none")
    assert content is None and view is None and embed.footer.text is None


async def test_more_pages_give_a_view_and_a_footer_saying_so():
    gh = pages(([issue(n) for n in range(1, 21)], True))
    _, embed, view = await first_page(gh, "open", None, OWNER, "none")
    assert isinstance(view, ListView) and "more on the next page" in embed.footer.text
    assert view.previous.disabled and not view.next.disabled


async def test_empty_first_page_returns_the_no_issues_text():
    content, embed, view = await first_page(pages(([], False)), "closed", None, OWNER, "No closed issues found.")
    assert content == "No closed issues found." and embed is None and view is None


async def test_next_and_previous_move_between_pages_and_toggle_the_buttons():
    gh = pages(([issue(1)], True), ([issue(2)], True), ([issue(3)], False))
    _, _, view = await first_page(gh, "open", "bug", OWNER, "none")

    p = press()
    await view.next.callback(p)
    assert view.page == 2 and not view.previous.disabled and not view.next.disabled
    assert "Issue 2" in p.edit_original_response.await_args.kwargs["embed"].description
    gh.list_issues.assert_awaited_with("open", "bug", page=2)

    await view.next.callback(press())
    assert view.page == 3 and view.next.disabled  # no next page left

    p = press()
    await view.previous.callback(p)
    assert view.page == 2 and "Page 2" in p.edit_original_response.await_args.kwargs["embed"].footer.text


async def test_only_the_person_who_ran_it_can_change_pages():
    _, _, view = await first_page(pages(([issue(1)], True)), "open", None, OWNER, "none")
    stranger = press(user_id=999)
    assert await view.interaction_check(stranger) is False
    stranger.response.send_message.assert_awaited_once()
    assert await view.interaction_check(press()) is True


async def test_a_github_error_while_paging_is_shown_privately_and_the_page_stays():
    gh = pages(([issue(1)], True))
    _, _, view = await first_page(gh, "open", None, OWNER, "none")
    gh.list_issues.side_effect = GitHubError("GitHub is down")
    p = press()
    await view.next.callback(p)
    assert p.followup.send.await_args.args[0] == "GitHub is down"
    assert view.page == 1
    p.edit_original_response.assert_not_awaited()


async def test_timeout_removes_the_buttons():
    _, _, view = await first_page(pages(([issue(1)], True)), "open", None, OWNER, "none")
    view.message = SimpleNamespace(edit=AsyncMock())
    await view.on_timeout()
    view.message.edit.assert_awaited_once_with(view=None)


async def test_vietnamese_footer():
    embed = list_embed([issue(1)], "open", page=2, has_next=True, lang="vi")
    assert embed.footer.text == "Trang 2 · còn trang sau"


async def test_ask_list_sends_the_page_view_when_there_is_more():
    gh = pages(([issue(n) for n in range(1, 21)], True))
    reply = AsyncMock(return_value=SimpleNamespace(edit=AsyncMock()))
    await submit(
        intent=Intent("list"), text="list", user_id=OWNER, role_ids=[], role_id=111, gh=gh, reply=reply
    )
    view = reply.await_args.kwargs["view"]
    assert isinstance(view, ListView) and view.owner_id == OWNER and view.message is not None
