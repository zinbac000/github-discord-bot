import logging
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import replace

import discord

from . import bulk
from .github import GitHubClient, GitHubError
from .intent import WRITE_ACTIONS, AIError, GroqClient, Intent
from .listing import first_page
from .render import clip, issue_line, view_embed

log = logging.getLogger(__name__)

CONFIRM_TIMEOUT = 120
BULK_CONFIRM_TIMEOUT = 300
PREVIEW_BODY_LIMIT = 3000
_MENTION = re.compile(r"<@!?(\d+)>")

MESSAGES = {
    "en": {
        "create": "**Create this issue?**\n**Title:** {title}\n**Body:**\n{body}",
        "close": "**Close this issue?**\n#{number}: {title}",
        "comment": "**Comment on this issue?**\n#{number}: {title}\n**Comment:**\n{body}",
        "shortened": "\n_(preview shortened, the full text is submitted)_",
        "confirm": "Confirm",
        "cancel": "Cancel",
        "working": "Working on it…",
        "cancelled": "Cancelled.",
        "expired": "This request expired. Ask again.",
        "denied": "You need the allowed role to do that.",
        "already": "This request was already handled.",
        "not_yours": "Only the person who asked can use these buttons.",
        "no_issues": "No {state} issues found.",
        "failed": "Something went wrong. Check the bot's logs.",
        "created": "Created {line}",
        "closed": "Closed {line}",
        "commented": "Commented on #{number}: {url}",
        "assign": "**Assign this issue?**\n#{number}: {title}\n**Assign to:** {login}\n**Already assigned:** {current}",
        "unassign": "**Unassign this issue?**\n#{number}: {title}\n**Remove:** {login}\n**Currently assigned:** {current}",
        "assigned": "Assigned {login} to {line}",
        "unassigned": "Unassigned {login} from {line}",
        "unmapped": "I don't know which GitHub account that is. Please give a GitHub username.",
        "nobody": "nobody",
        "bulk_create": "**Create {n} issues?**",
        "bulk_close": "**Close {n} issues?**",
        "bulk_comment": "**Comment on {n} issues?**\n**Comment:** {body}",
        "bulk_assign": "**Assign {login} to {n} issues?**",
        "bulk_unassign": "**Unassign {login} from {n} issues?**",
        "bulk_view": "**{n} issues**",
        "bulk_not_run": "({n} will not run)",
        "bulk_shortened": "_(list shortened, the full list is attached)_",
        "bulk_nothing": "Nothing to do: every listed issue is skipped or cannot run.",
        "report": "**Done:** {ok} ok, {skipped} skipped, {failed} failed, {unknown} unknown, {not_attempted} not attempted.",
        "report_more": "...and {n} more problems (see the attached report)",
        "report_retry": "Retry: {items}",
    },
    "vi": {
        "create": "**Tạo issue này?**\n**Tiêu đề:** {title}\n**Nội dung:**\n{body}",
        "close": "**Đóng issue này?**\n#{number}: {title}",
        "comment": "**Bình luận vào issue này?**\n#{number}: {title}\n**Bình luận:**\n{body}",
        "shortened": "\n_(bản xem trước đã rút gọn, nội dung đầy đủ vẫn được gửi)_",
        "confirm": "Xác nhận",
        "cancel": "Huỷ",
        "working": "Đang xử lý…",
        "cancelled": "Đã huỷ.",
        "expired": "Yêu cầu đã hết hạn. Hãy hỏi lại.",
        "denied": "Bạn cần có role được phép để làm việc này.",
        "already": "Yêu cầu này đã được xử lý.",
        "not_yours": "Chỉ người đã hỏi mới dùng được các nút này.",
        "no_issues": "Không có issue {state} nào.",
        "failed": "Có lỗi xảy ra. Hãy xem log của bot.",
        "created": "Đã tạo {line}",
        "closed": "Đã đóng {line}",
        "commented": "Đã bình luận vào #{number}: {url}",
        "assign": "**Gán issue này?**\n#{number}: {title}\n**Gán cho:** {login}\n**Đang được gán:** {current}",
        "unassign": "**Bỏ gán issue này?**\n#{number}: {title}\n**Bỏ:** {login}\n**Đang được gán:** {current}",
        "assigned": "Đã gán {login} cho {line}",
        "unassigned": "Đã bỏ gán {login} khỏi {line}",
        "unmapped": "Mình chưa biết đó là tài khoản GitHub nào. Hãy nêu tên tài khoản GitHub.",
        "nobody": "chưa có ai",
        "bulk_create": "**Tạo {n} issue?**",
        "bulk_close": "**Đóng {n} issue?**",
        "bulk_comment": "**Bình luận vào {n} issue?**\n**Bình luận:** {body}",
        "bulk_assign": "**Gán {login} cho {n} issue?**",
        "bulk_unassign": "**Bỏ gán {login} khỏi {n} issue?**",
        "bulk_view": "**{n} issue**",
        "bulk_not_run": "({n} issue sẽ không chạy)",
        "bulk_shortened": "_(danh sách đã rút gọn, danh sách đầy đủ nằm trong file đính kèm)_",
        "bulk_nothing": "Không có gì để làm: mọi issue đã nêu đều bị bỏ qua hoặc không chạy được.",
        "report": "**Xong:** {ok} thành công, {skipped} bỏ qua, {failed} lỗi, {unknown} không rõ, {not_attempted} chưa thực hiện.",
        "report_more": "...và {n} vấn đề nữa (xem báo cáo đính kèm)",
        "report_retry": "Thử lại: {items}",
    },
}

BUSY = "Too many requests, try again in a moment. / Quá nhiều yêu cầu, thử lại sau giây lát."
HINT = (
    "Tell me what to do with issues, e.g. `@bot list open bugs` or "
    "`@bot tạo issue login lỗi`. / Hãy nói bạn muốn làm gì với issue."
)

Reply = Callable[..., Awaitable["discord.Message | None"]]


async def describe(gh: GitHubClient, intent: Intent) -> str:
    """Preview text for a write intent, built from validated fields only."""
    m = MESSAGES[intent.lang]
    body = intent.body
    shortened = len(body) > PREVIEW_BODY_LIMIT
    if intent.action == "create":
        text = m["create"].format(title=intent.title, body=clip(body, PREVIEW_BODY_LIMIT) or "-")
    else:
        issue = await gh.get_issue(intent.number)
        if intent.action in ("assign", "unassign"):
            current = ", ".join(issue.assignees) or m["nobody"]
            if intent.action == "assign":
                login = await gh.assignable_login(intent.assignee)
                if login is None:
                    raise GitHubError(f"{intent.assignee} cannot be assigned in this repo.")
            else:
                login = next((a for a in issue.assignees if a.lower() == intent.assignee.lower()), None)
                if login is None:
                    raise GitHubError(f"{intent.assignee} is not assigned to #{issue.number}.")
            text = m[intent.action].format(
                number=issue.number, title=clip(issue.title, 200), login=login, current=current
            )
        elif intent.action == "close":
            text = m["close"].format(number=issue.number, title=clip(issue.title, 200))
        else:
            text = m["comment"].format(
                number=issue.number,
                title=clip(issue.title, 200),
                body=clip(body, PREVIEW_BODY_LIMIT),
            )
    return text + (m["shortened"] if shortened else "")


async def run_read(
    gh: GitHubClient, intent: Intent, owner_id: int = 0
) -> tuple[str | None, discord.Embed | None, discord.ui.View | None]:
    m = MESSAGES[intent.lang]
    if intent.action == "list":
        return await first_page(
            gh,
            intent.state,
            intent.label,
            owner_id,
            m["no_issues"].format(state=intent.state),
            lang=intent.lang,
        )
    return None, view_embed(await gh.get_issue(intent.number)), None


async def run_write(gh: GitHubClient, intent: Intent) -> str:
    m = MESSAGES[intent.lang]
    if intent.action == "create":
        issue = await gh.create_issue(intent.title, intent.body)
        return m["created"].format(line=issue_line(issue))
    if intent.action == "close":
        issue = await gh.close_issue(intent.number)
        return m["closed"].format(line=issue_line(issue))
    if intent.action == "assign":
        issue = await gh.assign(intent.number, intent.assignee)
        return m["assigned"].format(login=intent.assignee, line=issue_line(issue))
    if intent.action == "unassign":
        issue = await gh.unassign(intent.number, intent.assignee)
        return m["unassigned"].format(login=intent.assignee, line=issue_line(issue))
    url = await gh.comment(intent.number, intent.body)
    return m["commented"].format(number=intent.number, url=url)


def resolve_assignee(
    intent: Intent, text: str, user_id: int, user_map: dict[int, str]
) -> str | None:
    """The GitHub login the user means, or None. The model never decides who this is."""
    if intent.assignee_kind == "login":
        return intent.assignee or None
    if intent.assignee_kind == "self":
        return user_map.get(user_id)
    mentioned = set(_MENTION.findall(text))
    if len(mentioned) != 1:
        return None
    return user_map.get(int(next(iter(mentioned))))


class ConfirmView(discord.ui.View):
    """Single-use Confirm and Cancel for a write intent. Only the asker may press."""

    def __init__(
        self,
        *,
        gh: GitHubClient,
        intent: Intent,
        owner_id: int,
        role_id: int,
        items: list[bulk.Item] | None = None,
        timeout: float = CONFIRM_TIMEOUT,
    ):
        super().__init__(timeout=timeout)
        self.items = items  # the frozen bulk list shown in the preview, never rebuilt
        self.gh = gh
        self.intent = intent
        self.owner_id = owner_id
        self.role_id = role_id
        self.consumed = False
        self.message: discord.Message | None = None
        self._m = MESSAGES[intent.lang]
        self.confirm.label = self._m["confirm"]
        self.cancel.label = self._m["cancel"]

    def _disable(self) -> None:
        for item in self.children:
            item.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(self._m["not_yours"], ephemeral=True)
            return False
        return True

    @discord.ui.button(style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.consumed:
            await interaction.response.send_message(self._m["already"], ephemeral=True)
            return
        self.consumed = True  # before any await, so a double-click cannot run twice
        self._disable()
        self.stop()

        roles = getattr(interaction.user, "roles", [])
        if not any(role.id == self.role_id for role in roles):
            await interaction.response.edit_message(content=self._m["denied"], embed=None, view=None)
            return

        await interaction.response.edit_message(content=self._m["working"], embed=None, view=self)
        file = None
        try:
            if self.items is not None:
                outcomes = await bulk.execute(self.gh, self.intent, self.items)
                result, full = bulk.report(outcomes, self._m)
                file = bulk.as_file(full, "bulk-report.txt") if full else None
            else:
                result = await run_write(self.gh, self.intent)
        except GitHubError as exc:
            result = exc.message
        except Exception:
            log.exception("Confirmed action failed")
            result = self._m["failed"]
        try:
            extra = {"attachments": [file]} if file else {}
            await interaction.edit_original_response(content=result, view=None, **extra)
        except discord.HTTPException:
            log.exception("Could not show the result of a confirmed action: %s", result)

    @discord.ui.button(style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.consumed:
            await interaction.response.send_message(self._m["already"], ephemeral=True)
            return
        self.consumed = True
        self.stop()
        await interaction.response.edit_message(content=self._m["cancelled"], embed=None, view=None)

    async def on_timeout(self) -> None:
        if self.consumed or self.message is None:
            return
        self.consumed = True
        try:
            await self.message.edit(content=self._m["expired"], embed=None, view=None)
        except discord.HTTPException:
            pass


class Limiter:
    """In-memory per-user cooldown plus a global calls-per-window cap."""

    def __init__(
        self,
        *,
        cooldown: float = 5.0,
        global_cap: int = 30,
        window: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._cooldown = cooldown
        self._cap = global_cap
        self._window = window
        self._clock = clock
        self._last: dict[int, float] = {}
        self._calls: deque[float] = deque()

    def check(self, user_id: int) -> bool:
        now = self._clock()
        while self._calls and now - self._calls[0] >= self._window:
            self._calls.popleft()
        self._last = {u: t for u, t in self._last.items() if now - t < self._cooldown}
        last = self._last.get(user_id)
        if (last is not None and now - last < self._cooldown) or len(self._calls) >= self._cap:
            return False
        self._last[user_id] = now
        self._calls.append(now)
        return True


def _audit(user_id: int, text: str, intent: Intent | None, outcome: str) -> None:
    if intent is None:
        what = "-"
    else:
        what = (
            f"{intent.action} number={intent.number} numbers={clip(','.join(map(str, intent.numbers)), 80)} "
            f"titles={len(intent.titles)} title={clip(intent.title, 60)!r} "
            f"state={intent.state} label={intent.label}"
        )
    log.info("ask user=%s text=%r intent=[%s] outcome=%s", user_id, clip(text, 200), what, outcome)


async def handle_text(
    *,
    text: str,
    user_id: int,
    role_ids: Iterable[int],
    role_id: int,
    gh: GitHubClient,
    groq: GroqClient,
    limiter: Limiter,
    reply: Reply,
    user_map: dict[int, str] | None = None,
) -> None:
    """Shared flow for `/ask` and mentions. `reply(content=, embed=, view=, ephemeral=)`."""
    if not limiter.check(user_id):
        _audit(user_id, text, None, "limited")
        await reply(content=BUSY, ephemeral=True)
        return

    try:
        intent = await groq.parse(text)
    except AIError as exc:
        _audit(user_id, text, None, "ai_error")
        await reply(content=exc.message, ephemeral=True)
        return

    if intent.action == "clarify":
        _audit(user_id, text, intent, "clarify")
        await reply(content=intent.question, ephemeral=True)
        return

    await submit(
        intent=intent,
        text=text,
        user_id=user_id,
        role_ids=role_ids,
        role_id=role_id,
        gh=gh,
        reply=reply,
        user_map=user_map,
    )


def _file_kwargs(full: str | None, name: str) -> dict:
    return {"file": bulk.as_file(full, name)} if full else {}


async def submit(
    *,
    intent: Intent,
    text: str,
    user_id: int,
    role_ids: Iterable[int],
    role_id: int,
    gh: GitHubClient,
    reply: Reply,
    user_map: dict[int, str] | None = None,
) -> None:
    """Run a validated intent: gate, preview, confirm. Shared by AI input and /bulk."""
    m = MESSAGES[intent.lang]
    is_write = intent.action in WRITE_ACTIONS
    if is_write and role_id not in set(role_ids):
        _audit(user_id, text, intent, "denied")
        await reply(content=m["denied"], ephemeral=True)
        return

    if intent.action in ("assign", "unassign"):
        login = resolve_assignee(intent, text, user_id, user_map or {})
        if login is None:
            _audit(user_id, text, intent, "unmapped")
            await reply(content=m["unmapped"], ephemeral=True)
            return
        intent = replace(intent, assignee=login, assignee_kind="login")

    if bulk.is_bulk(intent):
        await _submit_bulk(intent, text, user_id, role_id, gh, reply)
        return

    try:
        if not is_write:
            content, embed, page_view = await run_read(gh, intent, user_id)
            _audit(user_id, text, intent, "ok")
            if page_view is None:
                await reply(content=content, embed=embed)
            else:
                page_view.message = await reply(content=content, embed=embed, view=page_view)
            return
        preview = await describe(gh, intent)
    except GitHubError as exc:
        _audit(user_id, text, intent, "github_error")
        await reply(content=exc.message, ephemeral=True)
        return

    view = ConfirmView(gh=gh, intent=intent, owner_id=user_id, role_id=role_id)
    _audit(user_id, text, intent, "preview")
    view.message = await reply(
        embed=discord.Embed(description=clip(preview, 4000)), view=view, ephemeral=True
    )


async def _submit_bulk(
    intent: Intent, text: str, user_id: int, role_id: int, gh: GitHubClient, reply: Reply
) -> None:
    m = MESSAGES[intent.lang]
    try:
        items = await bulk.prepare(gh, intent)
    except GitHubError as exc:
        _audit(user_id, text, intent, "github_error")
        await reply(content=exc.message, ephemeral=True)
        return

    if intent.action == "view":
        shown, full = bulk.view_summary(items, m)
        _audit(user_id, text, intent, "ok")
        await reply(embed=discord.Embed(description=shown), **_file_kwargs(full, "bulk-view.txt"))
        return

    shown, full, todo = bulk.preview(intent, items, m)
    files = _file_kwargs(full, "bulk-preview.txt")
    embed = discord.Embed(description=clip(shown, 4000))
    if todo == 0:
        _audit(user_id, text, intent, "nothing_to_do")
        await reply(content=m["bulk_nothing"], embed=embed, ephemeral=True, **files)
        return

    view = ConfirmView(
        gh=gh, intent=intent, owner_id=user_id, role_id=role_id, items=items,
        timeout=BULK_CONFIRM_TIMEOUT,
    )
    _audit(user_id, text, intent, "preview")
    view.message = await reply(embed=embed, view=view, ephemeral=True, **files)
