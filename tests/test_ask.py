import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from github_discord_bot.ask import (
    BUSY,
    HINT,
    ConfirmView,
    Limiter,
    handle_text,
)
from github_discord_bot.bot import IssueBot
from github_discord_bot.config import Settings
from github_discord_bot.github import GitHubError, Issue
from github_discord_bot.intent import AIError, Intent

ROLE = 111
OWNER = 7


def issue(number=3, title="Login bug", state="open"):
    return Issue(number, title, state, f"https://github.com/o/r/issues/{number}", ["bug"], "alice", "body")


@pytest.fixture
def gh():
    return MagicMock(
        create_issue=AsyncMock(return_value=issue(5, "New")),
        list_issues=AsyncMock(return_value=[issue(1), issue(2)]),
        get_issue=AsyncMock(return_value=issue(3)),
        close_issue=AsyncMock(return_value=issue(3, state="closed")),
        comment=AsyncMock(return_value="https://github.com/o/r/issues/3#c"),
    )


def groq_returning(intent=None, error=None):
    parse = AsyncMock(return_value=intent, side_effect=error)
    return SimpleNamespace(parse=parse)


async def run(gh, groq, *, roles=(ROLE,), user=OWNER, limiter=None):
    reply = AsyncMock(return_value=SimpleNamespace(edit=AsyncMock()))
    await handle_text(
        text="whatever",
        user_id=user,
        role_ids=roles,
        role_id=ROLE,
        gh=gh,
        groq=groq,
        limiter=limiter or Limiter(),
        reply=reply,
    )
    return reply


def press(user_id=OWNER, role_ids=(ROLE,)):
    return SimpleNamespace(
        user=SimpleNamespace(id=user_id, roles=[SimpleNamespace(id=i) for i in role_ids]),
        response=SimpleNamespace(edit_message=AsyncMock(), send_message=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


def view_from(reply):
    return reply.await_args.kwargs["view"]


CREATE = Intent("create", title="Login lỗi", body="trên Safari", lang="vi")


async def test_read_runs_immediately_without_view(gh):
    reply = await run(gh, groq_returning(Intent("list", state="closed", label="bug")))
    gh.list_issues.assert_awaited_once_with(state="closed", label="bug", limit=10)
    assert "view" not in reply.await_args.kwargs
    assert reply.await_args.kwargs["embed"] is not None


async def test_empty_list_says_so(gh):
    gh.list_issues.return_value = []
    reply = await run(gh, groq_returning(Intent("list")))
    assert "No open issues" in reply.await_args.kwargs["content"]


async def test_create_shows_code_built_preview_and_calls_nothing(gh):
    reply = await run(gh, groq_returning(CREATE))
    embed = reply.await_args.kwargs["embed"]
    assert "Login lỗi" in embed.description and "trên Safari" in embed.description
    assert "Tạo issue này?" in embed.description
    assert isinstance(view_from(reply), ConfirmView)
    assert reply.await_args.kwargs["ephemeral"] is True
    gh.create_issue.assert_not_awaited()


async def test_confirm_creates_exactly_once_even_when_pressed_twice(gh):
    view = view_from(await run(gh, groq_returning(CREATE)))
    first, second = press(), press()
    await asyncio.gather(view.confirm.callback(first), view.confirm.callback(second))
    gh.create_issue.assert_awaited_once_with("Login lỗi", "trên Safari")
    assert "Đã tạo" in first.edit_original_response.await_args.kwargs["content"]
    second.response.send_message.assert_awaited_once()
    assert all(item.disabled for item in view.children)


async def test_other_user_cannot_press(gh):
    view = view_from(await run(gh, groq_returning(CREATE)))
    stranger = press(user_id=999)
    assert await view.interaction_check(stranger) is False
    stranger.response.send_message.assert_awaited_once()
    gh.create_issue.assert_not_awaited()
    assert await view.interaction_check(press()) is True


async def test_role_is_rechecked_on_confirm(gh):
    view = view_from(await run(gh, groq_returning(CREATE)))
    lost_role = press(role_ids=())
    await view.confirm.callback(lost_role)
    gh.create_issue.assert_not_awaited()
    assert "role" in lost_role.response.edit_message.await_args.kwargs["content"]


async def test_write_without_role_is_refused_before_preview(gh):
    reply = await run(gh, groq_returning(CREATE), roles=())
    assert "role" in reply.await_args.kwargs["content"]
    assert "view" not in reply.await_args.kwargs
    gh.get_issue.assert_not_awaited()


async def test_close_preview_shows_real_issue_title(gh):
    reply = await run(gh, groq_returning(Intent("close", number=3)))
    gh.get_issue.assert_awaited_once_with(3)
    assert "#3: Login bug" in reply.await_args.kwargs["embed"].description


async def test_close_confirm_closes(gh):
    view = view_from(await run(gh, groq_returning(Intent("close", number=3))))
    interaction = press()
    await view.confirm.callback(interaction)
    gh.close_issue.assert_awaited_once_with(3)


async def test_github_error_on_confirm_is_shown(gh):
    gh.create_issue.side_effect = GitHubError("token expired")
    view = view_from(await run(gh, groq_returning(CREATE)))
    interaction = press()
    await view.confirm.callback(interaction)
    assert interaction.edit_original_response.await_args.kwargs["content"] == "token expired"


async def test_github_error_while_building_preview(gh):
    gh.get_issue.side_effect = GitHubError("Repository or issue not found.")
    reply = await run(gh, groq_returning(Intent("close", number=99)))
    assert "not found" in reply.await_args.kwargs["content"]
    assert "view" not in reply.await_args.kwargs


async def test_cancel_and_timeout(gh):
    view = view_from(await run(gh, groq_returning(CREATE)))
    interaction = press()
    await view.cancel.callback(interaction)
    assert "huỷ" in interaction.response.edit_message.await_args.kwargs["content"].lower()
    gh.create_issue.assert_not_awaited()

    view2 = view_from(await run(gh, groq_returning(CREATE)))
    view2.message = SimpleNamespace(edit=AsyncMock())
    await view2.on_timeout()
    assert "hết hạn" in view2.message.edit.await_args.kwargs["content"]
    assert view2.consumed


async def test_clarify_takes_no_action(gh):
    reply = await run(gh, groq_returning(Intent("clarify", question="Which issue?")))
    assert reply.await_args.kwargs["content"] == "Which issue?"
    gh.close_issue.assert_not_awaited()


async def test_ai_error_is_reported_not_raised(gh):
    reply = await run(gh, groq_returning(error=AIError("The AI is busy right now.")))
    assert "busy" in reply.await_args.kwargs["content"]


def test_limiter_cooldown_and_global_cap():
    now = [0.0]
    limiter = Limiter(cooldown=5, global_cap=3, window=60, clock=lambda: now[0])
    assert limiter.check(1) is True
    assert limiter.check(1) is False  # inside the cooldown
    now[0] = 6
    assert limiter.check(1) is True
    assert limiter.check(2) is True
    assert limiter.check(3) is False  # global cap of 3 reached
    now[0] = 70
    assert limiter.check(3) is True  # window passed


async def test_limited_call_replies_busy_and_skips_ai(gh):
    groq = groq_returning(Intent("list"))
    limiter = Limiter()
    await run(gh, groq, limiter=limiter)
    reply = await run(gh, groq, limiter=limiter)
    assert reply.await_args.kwargs["content"] == BUSY
    assert groq.parse.await_count == 1


async def test_each_request_is_audited_once(gh, caplog):
    with caplog.at_level(logging.INFO, logger="github_discord_bot.ask"):
        await run(gh, groq_returning(Intent("list")))
    records = [r for r in caplog.records if r.name == "github_discord_bot.ask"]
    assert len(records) == 1
    assert "user=7" in records[0].getMessage() and "outcome=ok" in records[0].getMessage()


def settings(key="gsk_secret"):
    return Settings("d", "g", "o/r", ROLE, None, key)


async def make_bot(key="gsk_secret"):
    bot = IssueBot(settings(key))
    bot._connection.user = SimpleNamespace(id=999)
    return bot


def message(content, *, mentions=True, bot_author=False, bot=None):
    return SimpleNamespace(
        author=SimpleNamespace(bot=bot_author, id=OWNER, roles=[]),
        mentions=[bot._connection.user] if mentions else [],
        content=content,
        reply=AsyncMock(),
    )


async def test_mention_with_only_the_tag_replies_with_hint():
    bot = await make_bot()
    msg = message("<@999> ", bot=bot)
    await bot.on_message(msg)
    assert msg.reply.await_args.args[0] == HINT
    await bot.close()


async def test_mention_runs_the_read_flow_and_strips_the_tag():
    bot = await make_bot()
    bot.groq.parse = AsyncMock(return_value=Intent("clarify", question="Which?"))
    msg = message("<@!999> list bugs", bot=bot)
    await bot.on_message(msg)
    bot.groq.parse.assert_awaited_once_with("list bugs")
    assert msg.reply.await_args.kwargs["content"] == "Which?"
    assert msg.reply.await_args.kwargs["mention_author"] is False
    await bot.close()


async def test_bot_authors_and_untagged_messages_are_ignored():
    bot = await make_bot()
    bot.groq.parse = AsyncMock()
    for msg in (message("<@999> hi", bot_author=True, bot=bot), message("hi", mentions=False, bot=bot)):
        await bot.on_message(msg)
        msg.reply.assert_not_awaited()
    bot.groq.parse.assert_not_awaited()
    await bot.close()


async def test_without_groq_key_there_is_no_ask_command_and_no_message_content():
    bot = await make_bot(key=None)
    names = [c.name for c in bot.tree.get_commands(guild=None)]
    assert "ask" not in names
    assert bot.intents.message_content is False
    msg = message("<@999> hi", bot=bot)
    await bot.on_message(msg)
    msg.reply.assert_not_awaited()
    await bot.close()


async def test_with_groq_key_ask_is_registered_and_mentions_never_ping():
    bot = await make_bot()
    assert bot.tree.get_command("ask") is not None
    assert bot.allowed_mentions.everyone is False and bot.allowed_mentions.users is False
    await bot.close()


async def test_failed_confirm_edit_does_not_raise(gh):
    view = view_from(await run(gh, groq_returning(CREATE)))
    interaction = press()
    interaction.edit_original_response.side_effect = discord.HTTPException(
        SimpleNamespace(status=404, reason="gone"), "gone"
    )
    await view.confirm.callback(interaction)
    gh.create_issue.assert_awaited_once()


def test_limiter_prunes_idle_users():
    now = [0.0]
    limiter = Limiter(cooldown=5, clock=lambda: now[0])
    for user in range(10):
        limiter.check(user)
    now[0] = 10
    limiter.check(99)
    assert set(limiter._last) == {99}


async def test_mention_failure_still_replies():
    bot = await make_bot()
    bot.groq.parse = AsyncMock(side_effect=RuntimeError("boom"))
    msg = message("<@999> hi", bot=bot)
    await bot.on_message(msg)
    assert "wrong" in msg.reply.await_args.args[0]
    await bot.close()
