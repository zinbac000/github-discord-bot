import discord

from .github import GitHubClient, GitHubError
from .render import list_embed

PAGE_TIMEOUT = 180

_TEXT = {
    "en": {"not_yours": "Only the person who ran this can change pages.", "empty": "No issues on this page."},
    "vi": {"not_yours": "Chỉ người đã chạy lệnh mới đổi trang được.", "empty": "Trang này không có issue nào."},
}


class ListView(discord.ui.View):
    """Previous and next buttons for a list of issues. Only the person who asked can use them."""

    def __init__(
        self,
        *,
        gh: GitHubClient,
        state: str,
        label: str | None,
        owner_id: int,
        page: int = 1,
        has_next: bool = False,
        lang: str = "en",
    ):
        super().__init__(timeout=PAGE_TIMEOUT)
        self.gh = gh
        self.state = state
        self.label = label
        self.owner_id = owner_id
        self.page = page
        self.has_next = has_next
        self.lang = lang if lang in _TEXT else "en"
        self.message: discord.Message | None = None
        self._sync()

    def _sync(self) -> None:
        self.previous.disabled = self.page <= 1
        self.next.disabled = not self.has_next

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(_TEXT[self.lang]["not_yours"], ephemeral=True)
            return False
        return True

    async def _go(self, interaction: discord.Interaction, page: int) -> None:
        await interaction.response.defer()
        try:
            issues, has_next = await self.gh.list_issues(self.state, self.label, page=page)
        except GitHubError as exc:
            await interaction.followup.send(exc.message, ephemeral=True)
            return
        self.page, self.has_next = page, has_next
        self._sync()
        embed = list_embed(issues, self.state, page, has_next, self.lang)
        content = None if issues else _TEXT[self.lang]["empty"]
        await interaction.edit_original_response(content=content, embed=embed, view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go(interaction, max(1, self.page - 1))

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._go(interaction, self.page + 1)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


async def first_page(
    gh: GitHubClient,
    state: str,
    label: str | None,
    owner_id: int,
    no_issues: str,
    lang: str = "en",
) -> tuple[str | None, discord.Embed | None, ListView | None]:
    """(content, embed, view) for the first page. A view only exists when there is more to see."""
    issues, has_next = await gh.list_issues(state, label, page=1)
    if not issues:
        return no_issues, None, None
    embed = list_embed(issues, state, 1, has_next, lang)
    view = ListView(
        gh=gh, state=state, label=label, owner_id=owner_id, has_next=has_next, lang=lang
    ) if has_next else None
    return None, embed, view
