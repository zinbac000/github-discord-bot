import logging
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import replace

import discord

from . import bulk
from .github import GitHubClient, GitHubError, Issue
from .intent import WRITE_ACTIONS, AIError, GroqClient, Intent
from .labels import final_labels, game_labels, match_game
from .listing import first_page
from .quota import CreateQuota
from .render import clip, issue_line, view_embed
from .similar import keywords
from .thread_draft import (
    Draft,
    apply_form,
    blocking,
    build_body,
    collect,
    missing,
    parse_draft,
)

log = logging.getLogger(__name__)

CONFIRM_TIMEOUT = 120
BULK_CONFIRM_TIMEOUT = 300
DRAFT_TIMEOUT = 300
MAX_SELECT_OPTIONS = 25
NO_GAME = "none"  # a select option value cannot be empty
PREVIEW_BODY_LIMIT = 3000
_MENTION = re.compile(r"<@!?(\d+)>")

MESSAGES = {
    "en": {
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
        "create_head": "**Create this issue?**",
        "labels": "**Labels:** {labels}",
        "title_line": "**Title:** {title}",
        "body_line": "**Body:**\n{body}",
        "required": "**Needed before Confirm:** {items}",
        "advised": "**Still missing (advised):** {items}",
        "miss_kind": "type (pick Bug or Enhancement)",
        "miss_description": "description",
        "miss_steps": "steps to reproduce",
        "miss_game": "game",
        "similar": "**Similar issues, check before creating:**",
        "similar_item": "• {line} ({state})",
        "read_note": "_Read {read} of {total} messages from the thread._",
        "create_anyway": "Create anyway",
        "use_existing": "Use an existing one",
        "add_details": "Add details",
        "kind_placeholder": "Type",
        "kind_bug": "Bug",
        "kind_enhancement": "Enhancement (idea or feature)",
        "game_placeholder": "Game",
        "game_none": "No game",
        "no_labels": "\n_(Labels could not be checked, so the issue was created without labels.)_",
        "form_title": "Issue details",
        "f_title": "Title",
        "f_description": "Description",
        "f_steps": "Steps to reproduce (one per line)",
        "f_expected": "Expected",
        "f_actual": "Actual",
        "unknown_game": "There is no game label with that name on the repo. Pick one from the list.",
        "capped": "You have reached the hourly limit for creating issues. Try again later.",
        "cap_left": "You can create {left} more issue(s) this hour, but this needs {need}.",
        "need_thread": "Run this inside a thread.",
        "thread_empty": "This thread has nothing to draft an issue from.",
        "thread_perm": "I cannot read or post in this thread. I need View Channel, Read Message History and Send Messages in Threads.",
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
        "create_head": "**Tạo issue này?**",
        "labels": "**Nhãn:** {labels}",
        "title_line": "**Tiêu đề:** {title}",
        "body_line": "**Nội dung:**\n{body}",
        "required": "**Cần có trước khi Xác nhận:** {items}",
        "advised": "**Còn thiếu (nên bổ sung):** {items}",
        "miss_kind": "loại (chọn Bug hoặc Enhancement)",
        "miss_description": "mô tả",
        "miss_steps": "các bước tái hiện",
        "miss_game": "game",
        "similar": "**Issue giống, hãy xem trước khi tạo:**",
        "similar_item": "• {line} ({state})",
        "read_note": "_Đã đọc {read} trên {total} tin nhắn của thread._",
        "create_anyway": "Vẫn tạo",
        "use_existing": "Dùng issue cũ",
        "add_details": "Bổ sung",
        "kind_placeholder": "Loại",
        "kind_bug": "Bug",
        "kind_enhancement": "Enhancement (ý tưởng hoặc tính năng)",
        "game_placeholder": "Game",
        "game_none": "Không có game",
        "no_labels": "\n_(Không kiểm tra được nhãn nên issue được tạo không có nhãn.)_",
        "form_title": "Chi tiết issue",
        "f_title": "Tiêu đề",
        "f_description": "Mô tả",
        "f_steps": "Các bước tái hiện (mỗi dòng một bước)",
        "f_expected": "Kết quả mong đợi",
        "f_actual": "Kết quả thực tế",
        "unknown_game": "Repo không có nhãn game nào tên như vậy. Hãy chọn một game trong danh sách.",
        "capped": "Bạn đã dùng hết giới hạn tạo issue trong một giờ. Hãy thử lại sau.",
        "cap_left": "Bạn còn tạo được {left} issue trong giờ này, nhưng yêu cầu này cần {need}.",
        "need_thread": "Hãy chạy lệnh này bên trong một thread.",
        "thread_empty": "Thread này chưa có nội dung để soạn issue.",
        "thread_perm": "Mình không đọc hoặc đăng được trong thread này. Mình cần quyền View Channel, Read Message History và Send Messages in Threads.",
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


async def label_names(gh: GitHubClient) -> list[str] | None:
    """The repo's label names, or None when GitHub cannot be asked right now."""
    try:
        return await gh.list_labels()
    except GitHubError as exc:
        log.warning("Could not read the repo's labels: %s", exc.message)
        return None


async def _writable_labels(gh: GitHubClient, labels: tuple[str, ...]) -> tuple[tuple[str, ...], bool]:
    """`labels` that still exist on the repo, and whether the repo could be checked.

    Checked again at write time: a label deleted since the preview must not fail the create.
    """
    if not labels:
        return (), True
    names = await label_names(gh)
    if names is None:
        return (), False
    lowered = {n.lower(): n for n in names}
    return tuple(lowered[x.lower()] for x in labels if x.lower() in lowered), True


async def run_write(gh: GitHubClient, intent: Intent) -> str:
    m = MESSAGES[intent.lang]
    if intent.action == "create":
        labels, checked = await _writable_labels(gh, intent.labels)
        issue = await gh.create_issue(intent.title, intent.body, list(labels) or None)
        return m["created"].format(line=issue_line(issue)) + ("" if checked else m["no_labels"])
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


_SELF_WORDS = {"me", "myself", "tôi", "tui", "mình"}


def resolve_person(raw: str, user_id: int, user_map: dict[int, str]) -> str:
    """The GitHub login for what someone typed in a slash command option.

    That can be a GitHub login ("zinbac000" or "@zinbac000"), "me", or a Discord mention:
    Discord sends a picked user as "<@123>", which GitHub knows nothing about, so it goes
    through GITHUB_USER_MAP. Raises GitHubError when a mention or "me" has no entry.
    """
    raw = raw.strip()
    mention = re.fullmatch(r"<@!?(\d+)>", raw)
    if mention:
        login = user_map.get(int(mention.group(1)))
    elif raw.lstrip("@").lower() in _SELF_WORDS:
        login = user_map.get(user_id)
    else:
        return raw.lstrip("@")
    if login is None:
        raise GitHubError(
            "I don't know which GitHub account that is. Type their GitHub username, "
            "or add them to GITHUB_USER_MAP."
        )
    return login


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
        quota: CreateQuota | None = None,
        cost: int = 0,
        announce: Callable[[str], Awaitable[object]] | None = None,
    ):
        super().__init__(timeout=timeout)
        self.quota = quota  # counted at Confirm, so an abandoned preview costs nothing
        self.cost = cost
        self.announce = announce  # posts a created issue's link where everyone can see it
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

    def not_ready(self) -> str | None:
        """Why Confirm must not run yet, or None. A disabled button is not a guard on its own."""
        return None

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
        problem = self.not_ready()
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        self.consumed = True  # before any await, so a double-click cannot run twice
        self._disable()
        self.stop()

        roles = getattr(interaction.user, "roles", [])
        if not any(role.id == self.role_id for role in roles):
            await interaction.response.edit_message(content=self._m["denied"], embed=None, view=None)
            return

        if self.quota is not None and self.cost and not self.quota.consume(self.owner_id, self.cost):
            await interaction.response.edit_message(content=self._m["capped"], embed=None, view=None)
            return

        await interaction.response.edit_message(content=self._m["working"], embed=None, view=self)
        file = None
        created = False
        try:
            if self.items is not None:
                outcomes = await bulk.execute(self.gh, self.intent, self.items)
                result, full = bulk.report(outcomes, self._m)
                file = bulk.as_file(full, "bulk-report.txt") if full else None
            else:
                result = await run_write(self.gh, self.intent)
                created = self.intent.action == "create"
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
        if created and self.announce is not None:
            try:
                await self.announce(result)
            except discord.HTTPException:
                log.exception("Could not post the created issue where it was asked for")

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


class _Pick(discord.ui.Select):
    """A select that sets one field of the draft (the type or the game)."""

    def __init__(self, field: str, placeholder: str, options: list[discord.SelectOption], row: int):
        super().__init__(placeholder=placeholder, options=options, min_values=1, max_values=1, row=row)
        self.field = field

    async def callback(self, interaction: discord.Interaction):
        view: CreateView = self.view
        value = self.values[0]
        view.draft = replace(view.draft, **{self.field: "" if value == NO_GAME else value})
        await view.refresh(interaction)


class DetailsModal(discord.ui.Modal):
    """The form for the parts of a draft that the thread (or the sentence) did not give."""

    def __init__(self, view: "CreateView"):
        m = view._m
        draft = view.draft
        super().__init__(title=m["form_title"], timeout=DRAFT_TIMEOUT)
        self.target = view

        def field(key: str, value: str, limit: int, *, long: bool = True, required: bool = False):
            item = discord.ui.TextInput(
                label=clip(m[key], 45),
                default=clip(value, limit) or None,
                max_length=limit,
                required=required,
                style=discord.TextStyle.paragraph if long else discord.TextStyle.short,
            )
            self.add_item(item)
            return item

        self.title_in = field("f_title", draft.title, 256, long=False, required=True)
        self.description = field("f_description", draft.description, 4000)
        self.steps = field("f_steps", "\n".join(draft.steps), 1000)
        self.expected = field("f_expected", draft.expected, 1000)
        self.actual = field("f_actual", draft.actual, 1000)

    async def on_submit(self, interaction: discord.Interaction):
        view = self.target
        view.draft = apply_form(
            view.draft,
            title=self.title_in.value,
            description=self.description.value,
            steps=self.steps.value,
            expected=self.expected.value,
            actual=self.actual.value,
        )
        await view.refresh(interaction)


class CreateView(ConfirmView):
    """The preview of a new issue: what will be sent, what is missing, what looks like a duplicate.

    The title, body and labels are rebuilt from `draft` on every change, so what the preview shows
    is exactly what Confirm sends.
    """

    def __init__(
        self,
        *,
        gh: GitHubClient,
        draft: Draft,
        owner_id: int,
        role_id: int,
        names: list[str] | None,
        similar: list[Issue] | None = None,
        quota: CreateQuota | None = None,
        announce: Callable[[str], Awaitable[object]] | None = None,
    ):
        super().__init__(
            gh=gh,
            intent=Intent("create", title=draft.title, lang=draft.lang),
            owner_id=owner_id,
            role_id=role_id,
            timeout=DRAFT_TIMEOUT,
            quota=quota,
            cost=1,
            announce=announce,
        )
        self.draft = draft
        self.names = names
        self.similar = similar or []
        self._games = game_labels(names or [])[:MAX_SELECT_OPTIONS]
        m = self._m

        self.kind_select = _Pick(
            "kind",
            m["kind_placeholder"],
            [
                discord.SelectOption(label=m["kind_bug"], value="bug"),
                discord.SelectOption(label=m["kind_enhancement"], value="enhancement"),
            ],
            row=1,
        )
        self.add_item(self.kind_select)
        self.game_select = None
        if self._games:
            options = [discord.SelectOption(label=m["game_none"], value=NO_GAME)]
            options += [
                discord.SelectOption(label=clip(g.split(":", 1)[1] or g, 100), value=g)
                for g in self._games[: MAX_SELECT_OPTIONS - 1]
            ]
            self.game_select = _Pick("game", m["game_placeholder"], options, row=2)
            self.add_item(self.game_select)

        details = discord.ui.Button(label=m["add_details"], style=discord.ButtonStyle.primary, row=0)
        details.callback = self._open_form
        self.add_item(details)
        self._sync()

    async def _open_form(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DetailsModal(self))

    def _sync(self) -> None:
        draft, m = self.draft, self._m
        if self.names is None:  # labels could not be read: ask for them anyway, they are checked at write time
            labels = tuple(x for x in (draft.kind, draft.game) if x)
        else:
            labels = final_labels(draft.kind, draft.game, self.names)
        self.intent = replace(
            self.intent, title=draft.title, body=build_body(draft), labels=labels, lang=draft.lang
        )
        self.confirm.disabled = bool(blocking(draft))
        self.confirm.label = m["create_anyway"] if self.similar else m["confirm"]
        self.cancel.label = m["use_existing"] if self.similar else m["cancel"]
        for select, current in ((self.kind_select, draft.kind), (self.game_select, draft.game)):
            if select is not None:
                for option in select.options:
                    option.default = bool(current) and option.value == current

    def not_ready(self) -> str | None:
        needed = [self._m[f"miss_{g}"] for g in blocking(self.draft)]
        return self._m["required"].format(items=", ".join(needed)) if needed else None

    def embed(self) -> discord.Embed:
        return discord.Embed(description=clip(create_text(self.draft, self.intent, self.similar, self._m, bool(self._games)), 4000))

    async def refresh(self, interaction: discord.Interaction) -> None:
        self._sync()
        await interaction.response.edit_message(embed=self.embed(), view=self)


def create_text(
    draft: Draft, intent: Intent, similar: list[Issue], m: dict, game_exists: bool
) -> str:
    """Preview of a new issue, built from the draft and the checked labels only."""
    body = intent.body
    lines = [
        m["create_head"],
        m["title_line"].format(title=draft.title),
        m["labels"].format(labels=", ".join(intent.labels) or "-"),
        m["body_line"].format(body=clip(body, PREVIEW_BODY_LIMIT) or "-"),
    ]
    gaps = missing(draft, game_exists)
    needed = [m[f"miss_{g}"] for g in gaps if g in blocking(draft)]
    advised = [m[f"miss_{g}"] for g in gaps if g not in blocking(draft)]
    if needed:
        lines.append(m["required"].format(items=", ".join(needed)))
    if advised:
        lines.append(m["advised"].format(items=", ".join(advised)))
    if draft.total > draft.read:
        lines.append(m["read_note"].format(read=draft.read, total=draft.total))
    if similar:
        lines.append(m["similar"])
        lines += [m["similar_item"].format(line=issue_line(i), state=i.state) for i in similar]
    return "\n".join(lines) + (m["shortened"] if len(body) > PREVIEW_BODY_LIMIT else "")


async def find_similar(gh: GitHubClient, title: str) -> list[Issue]:
    """Up to 3 existing issues like `title`. A search that fails just means no suggestions."""
    query = keywords(title)
    if not query:
        return []
    try:
        return await gh.search_issues(query)
    except GitHubError as exc:
        log.warning("Duplicate search failed: %s", exc.message)
        return []


async def within_quota(
    quota: CreateQuota | None, user_id: int, need: int, m: dict, reply: Reply
) -> bool:
    """False, after telling the user, when creating `need` issues now would pass their hourly cap."""
    left = quota.remaining(user_id) if quota is not None else None
    if left is None or left >= need:
        return True
    text = m["cap_left"].format(left=left, need=need) if left else m["capped"]
    await reply(content=text, ephemeral=True)
    return False


async def present_create(
    *,
    gh: GitHubClient,
    draft: Draft,
    names: list[str] | None,
    similar: list[Issue],
    user_id: int,
    role_id: int,
    reply: Reply,
    quota: CreateQuota | None = None,
    announce: Callable[[str], Awaitable[object]] | None = None,
    text: str = "",
) -> None:
    view = CreateView(
        gh=gh, draft=draft, owner_id=user_id, role_id=role_id, names=names,
        similar=similar, quota=quota, announce=announce,
    )
    _audit(user_id, text, view.intent, "preview")
    view.message = await reply(embed=view.embed(), view=view, ephemeral=True)


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
    quota: CreateQuota | None = None,
    thread: "discord.Thread | None" = None,
    announce: Callable[[str], Awaitable[object]] | None = None,
) -> None:
    """Shared flow for `/ask` and mentions. `reply(content=, embed=, view=, ephemeral=)`.

    `thread` is the thread the message was sent in, if any, and `announce` posts a created
    issue's link there when `reply` is private.
    """
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

    if intent.action == "thread":
        _audit(user_id, text, intent, "thread")
        await handle_thread(
            thread=thread,
            user_id=user_id,
            role_ids=role_ids,
            role_id=role_id,
            gh=gh,
            groq=groq,
            reply=reply,
            quota=quota,
            announce=announce,
            lang=intent.lang,
        )
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
        quota=quota,
        announce=announce,
    )


async def handle_thread(
    *,
    thread: "discord.Thread | None",
    user_id: int,
    role_ids: Iterable[int],
    role_id: int,
    gh: GitHubClient,
    groq: GroqClient,
    reply: Reply,
    quota: CreateQuota | None = None,
    announce: Callable[[str], Awaitable[object]] | None = None,
    lang: str = "en",
) -> None:
    """Draft an issue from a Discord thread and show the preview. Needs the write role.

    This is the one place Discord content goes to Groq, and only because someone asked for it.
    """
    m = MESSAGES[lang]
    if thread is None:
        await reply(content=m["need_thread"], ephemeral=True)
        return
    if role_id not in set(role_ids):
        _audit(user_id, "from-thread", None, "denied")
        await reply(content=m["denied"], ephemeral=True)
        return
    if not await within_quota(quota, user_id, 1, m, reply):
        return

    try:
        collected = await collect(thread)
    except discord.HTTPException:
        log.warning("Cannot read thread %s", thread.id, exc_info=True)
        await reply(content=m["thread_perm"], ephemeral=True)
        return
    if not collected.text:
        await reply(content=m["thread_empty"], ephemeral=True)
        return

    try:
        args = await groq.draft(collected.text)
    except AIError as exc:
        _audit(user_id, "from-thread", None, "ai_error")
        await reply(content=exc.message, ephemeral=True)
        return

    names = await label_names(gh)
    draft = parse_draft(
        args,
        thread_name=thread.name,
        names=names or [],
        url=thread.jump_url,
        read=collected.read,
        total=collected.total,
    )
    similar = await find_similar(gh, draft.title)
    await present_create(
        gh=gh, draft=draft, names=names, similar=similar, user_id=user_id, role_id=role_id,
        reply=reply, quota=quota, announce=announce, text=f"from-thread {thread.id}",
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
    quota: CreateQuota | None = None,
    announce: Callable[[str], Awaitable[object]] | None = None,
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
        await _submit_bulk(intent, text, user_id, role_id, gh, reply, quota)
        return

    if intent.action == "create":
        if not await within_quota(quota, user_id, 1, m, reply):
            _audit(user_id, text, intent, "capped")
            return
        names = await label_names(gh)
        draft = Draft(
            title=intent.title,
            kind=intent.kind,
            game=match_game(intent.game, names or []),
            description=intent.body,
            lang=intent.lang,
        )
        await present_create(
            gh=gh, draft=draft, names=names, similar=await find_similar(gh, intent.title),
            user_id=user_id, role_id=role_id, reply=reply, quota=quota, announce=announce, text=text,
        )
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
    intent: Intent,
    text: str,
    user_id: int,
    role_id: int,
    gh: GitHubClient,
    reply: Reply,
    quota: CreateQuota | None = None,
) -> None:
    m = MESSAGES[intent.lang]
    if intent.action == "create" and not await within_quota(quota, user_id, len(intent.titles), m, reply):
        _audit(user_id, text, intent, "capped")
        return
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
        timeout=BULK_CONFIRM_TIMEOUT, quota=quota,
        cost=sum(1 for item in items if item.state == "todo") if intent.action == "create" else 0,
    )
    _audit(user_id, text, intent, "preview")
    view.message = await reply(embed=embed, view=view, ephemeral=True, **files)
