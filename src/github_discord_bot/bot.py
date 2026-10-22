import logging
import re
from typing import Literal

import discord
from discord import app_commands

from .ask import HINT, Limiter, handle_text
from .config import Settings
from .github import GitHubClient, GitHubError
from .intent import GroqClient
from .render import issue_line, list_embed, view_embed

log = logging.getLogger(__name__)

LIST_LIMIT = 10


class NotAllowed(app_commands.CheckFailure):
    """The user lacks the role required for write commands."""


def role_gate(role_id: int):
    """Decorator limiting a command to members holding the role with `role_id`."""

    async def predicate(interaction: discord.Interaction) -> bool:
        roles = getattr(interaction.user, "roles", [])
        if any(role.id == role_id for role in roles):
            return True
        raise NotAllowed()

    return app_commands.check(predicate)


def make_issue_group(gh: GitHubClient, role_id: int) -> app_commands.Group:
    group = app_commands.Group(name="issue", description="Manage GitHub issues")
    write = role_gate(role_id)

    @group.command(name="create", description="Create an issue")
    @app_commands.describe(title="Issue title", body="Issue description")
    @write
    async def create(interaction: discord.Interaction, title: str, body: str = ""):
        await interaction.response.defer()
        issue = await gh.create_issue(title, body)
        await interaction.followup.send(f"Created {issue_line(issue)}")

    @group.command(name="list", description="List issues")
    @app_commands.describe(state="Which issues to show", label="Only issues with this label")
    async def list_issues(
        interaction: discord.Interaction,
        state: Literal["open", "closed", "all"] = "open",
        label: str | None = None,
    ):
        await interaction.response.defer()
        issues = await gh.list_issues(state=state, label=label, limit=LIST_LIMIT)
        if not issues:
            await interaction.followup.send(f"No {state} issues found.")
            return
        await interaction.followup.send(embed=list_embed(issues, state))

    @group.command(name="view", description="Show one issue")
    @app_commands.describe(number="Issue number")
    async def view(interaction: discord.Interaction, number: int):
        await interaction.response.defer()
        issue = await gh.get_issue(number)
        await interaction.followup.send(embed=view_embed(issue))

    @group.command(name="close", description="Close an issue")
    @app_commands.describe(number="Issue number")
    @write
    async def close(interaction: discord.Interaction, number: int):
        await interaction.response.defer()
        issue = await gh.close_issue(number)
        await interaction.followup.send(f"Closed {issue_line(issue)}")

    @group.command(name="comment", description="Comment on an issue")
    @app_commands.describe(number="Issue number", body="Comment text")
    @write
    async def comment(interaction: discord.Interaction, number: int, body: str):
        await interaction.response.defer()
        url = await gh.comment(number, body)
        await interaction.followup.send(f"Commented on #{number}: {url}")

    return group


async def on_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Turn any command failure into a Discord reply. Never lets the bot die."""
    cause = getattr(error, "original", error)
    if isinstance(error, NotAllowed):
        message = "You need the allowed role to use this command."
    elif isinstance(cause, GitHubError):
        message = cause.message
    else:
        log.error("Unhandled command error", exc_info=error)
        message = "Something went wrong. Check the bot's logs."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        log.exception("Could not deliver error message")


def _send_kwargs(content, embed, view) -> dict:
    """Only pass what is set: discord.py rejects some explicit Nones."""
    given = {"content": content, "embed": embed, "view": view}
    return {key: value for key, value in given.items() if value is not None}


class IssueBot(discord.Client):
    def __init__(self, settings: Settings):
        intents = discord.Intents.default()
        if settings.groq_api_key:
            intents.message_content = True  # needed to read tagged messages
        # Echoed user text must never ping anyone.
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self._settings = settings
        self.github = GitHubClient(settings.github_token, settings.github_repo)
        self.groq: GroqClient | None = None
        self.limiter = Limiter()
        self.tree = app_commands.CommandTree(self)
        self.tree.add_command(
            make_issue_group(self.github, settings.allowed_role_id),
            guild=self._guild(),
        )
        self.tree.error(on_command_error)
        if settings.groq_api_key:
            self.groq = GroqClient(
                settings.groq_api_key, settings.groq_model, settings.groq_fallback_model
            )
            self._add_ask_command()

    def _guild(self) -> discord.Object | None:
        guild_id = self._settings.discord_guild_id
        return discord.Object(id=guild_id) if guild_id else None

    def _add_ask_command(self) -> None:
        # Every /ask reply is private to the asker: after a defer Discord fixes the
        # visibility of the first reply, so public and private cannot be mixed.
        @self.tree.command(
            name="ask", description="Manage issues in plain language", guild=self._guild()
        )
        @app_commands.describe(text="What you want to do, in Vietnamese or English")
        async def ask(interaction: discord.Interaction, text: str):
            await interaction.response.defer(ephemeral=True)

            async def reply(content=None, embed=None, view=None, ephemeral=False):
                return await interaction.followup.send(
                    **_send_kwargs(content, embed, view), ephemeral=True
                )

            await handle_text(
                text=text,
                user_id=interaction.user.id,
                role_ids=[role.id for role in getattr(interaction.user, "roles", [])],
                role_id=self._settings.allowed_role_id,
                gh=self.github,
                groq=self.groq,
                limiter=self.limiter,
                reply=reply,
            )

    async def setup_hook(self) -> None:
        await self.tree.sync(guild=self._guild())

    async def on_ready(self) -> None:
        log.info("Logged in as %s, managing %s", self.user, self._settings.github_repo)

    async def on_message(self, message: discord.Message) -> None:
        if self.groq is None or message.author.bot or self.user not in message.mentions:
            return
        text = re.sub(rf"<@!?{self.user.id}>", "", message.content).strip()
        if not text:
            await message.reply(HINT, mention_author=False)
            return

        async def reply(content=None, embed=None, view=None, ephemeral=False):
            # A message reply cannot be ephemeral.
            return await message.reply(**_send_kwargs(content, embed, view), mention_author=False)

        try:
            await handle_text(
                text=text,
                user_id=message.author.id,
                role_ids=[role.id for role in getattr(message.author, "roles", [])],
                role_id=self._settings.allowed_role_id,
                gh=self.github,
                groq=self.groq,
                limiter=self.limiter,
                reply=reply,
            )
        except Exception:
            log.exception("Unhandled error while handling a mention")
            try:
                await message.reply(
                    "Something went wrong. / Có lỗi xảy ra.", mention_author=False
                )
            except discord.HTTPException:
                pass

    async def close(self) -> None:
        await self.github.aclose()
        if self.groq:
            await self.groq.aclose()
        await super().close()


def run(settings: Settings) -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    IssueBot(settings).run(settings.discord_token, log_handler=None)
