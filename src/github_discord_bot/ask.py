import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable

import discord

from .github import GitHubClient, GitHubError
from .intent import WRITE_ACTIONS, AIError, GroqClient, Intent
from .render import clip, issue_line, list_embed, view_embed

log = logging.getLogger(__name__)

CONFIRM_TIMEOUT = 120
PREVIEW_BODY_LIMIT = 3000

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
        if intent.action == "close":
            text = m["close"].format(number=issue.number, title=clip(issue.title, 200))
        else:
            text = m["comment"].format(
                number=issue.number,
                title=clip(issue.title, 200),
                body=clip(body, PREVIEW_BODY_LIMIT),
            )
    return text + (m["shortened"] if shortened else "")


async def run_read(gh: GitHubClient, intent: Intent) -> tuple[str | None, discord.Embed | None]:
    m = MESSAGES[intent.lang]
    if intent.action == "list":
        issues = await gh.list_issues(state=intent.state, label=intent.label, limit=10)
        if not issues:
            return m["no_issues"].format(state=intent.state), None
        return None, list_embed(issues, intent.state)
    return None, view_embed(await gh.get_issue(intent.number))


async def run_write(gh: GitHubClient, intent: Intent) -> str:
    m = MESSAGES[intent.lang]
    if intent.action == "create":
        issue = await gh.create_issue(intent.title, intent.body)
        return m["created"].format(line=issue_line(issue))
    if intent.action == "close":
        issue = await gh.close_issue(intent.number)
        return m["closed"].format(line=issue_line(issue))
    url = await gh.comment(intent.number, intent.body)
    return m["commented"].format(number=intent.number, url=url)


class ConfirmView(discord.ui.View):
    """Single-use Confirm and Cancel for a write intent. Only the asker may press."""

    def __init__(self, *, gh: GitHubClient, intent: Intent, owner_id: int, role_id: int):
        super().__init__(timeout=CONFIRM_TIMEOUT)
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
        try:
            result = await run_write(self.gh, self.intent)
        except GitHubError as exc:
            result = exc.message
        except Exception:
            log.exception("Confirmed action failed")
            result = self._m["failed"]
        try:
            await interaction.edit_original_response(content=result, view=None)
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
            f"{intent.action} number={intent.number} title={clip(intent.title, 60)!r} "
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

    m = MESSAGES[intent.lang]
    is_write = intent.action in WRITE_ACTIONS
    if is_write and role_id not in set(role_ids):
        _audit(user_id, text, intent, "denied")
        await reply(content=m["denied"], ephemeral=True)
        return

    try:
        if not is_write:
            content, embed = await run_read(gh, intent)
            _audit(user_id, text, intent, "ok")
            await reply(content=content, embed=embed)
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
