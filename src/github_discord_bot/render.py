import discord

from .github import Issue

BODY_LIMIT = 800


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def issue_line(issue: Issue) -> str:
    return f"[#{issue.number}]({issue.url}) {clip(issue.title, 100)}"


def list_embed(issues: list[Issue], state: str) -> discord.Embed:
    return discord.Embed(
        title=f"{state.capitalize()} issues",
        description="\n".join(map(issue_line, issues)),
    )


def view_embed(issue: Issue) -> discord.Embed:
    embed = discord.Embed(
        title=clip(f"#{issue.number} {issue.title}", 256),
        url=issue.url,
        description=clip(issue.body, BODY_LIMIT) or "No description.",
    )
    embed.add_field(name="State", value=issue.state)
    embed.add_field(name="Author", value=issue.author or "unknown")
    if issue.labels:
        embed.add_field(name="Labels", value=", ".join(issue.labels))
    return embed
