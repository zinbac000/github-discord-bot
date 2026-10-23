import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from dotenv import dotenv_values

_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
_LOGIN_RE = re.compile(r"^[A-Za-z0-9-]{1,39}$")
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


class ConfigError(Exception):
    """Raised with one message listing every missing or invalid variable."""


@dataclass(frozen=True)
class Settings:
    discord_token: str
    github_token: str
    github_repo: str
    allowed_role_id: int
    discord_guild_id: int | None = None
    groq_api_key: str | None = None
    groq_model: str = DEFAULT_GROQ_MODEL
    groq_fallback_model: str | None = None
    github_user_map: dict[int, str] = field(default_factory=dict)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Build Settings from `env`, or from `.env` overlaid by the process environment."""
    if env is None:
        env = {**dotenv_values(".env"), **os.environ}

    problems: list[str] = []

    def text(name: str) -> str:
        value = (env.get(name) or "").strip()
        if not value:
            problems.append(f"{name} is missing")
        return value

    def number(name: str, required: bool) -> int | None:
        value = (env.get(name) or "").strip()
        if not value:
            if required:
                problems.append(f"{name} is missing")
            return None
        if not value.isdigit():
            problems.append(f"{name} must be a number, got {value!r}")
            return None
        return int(value)

    discord_token = text("DISCORD_TOKEN")
    github_token = text("GITHUB_TOKEN")
    github_repo = text("GITHUB_REPO")
    if github_repo and not _REPO_RE.match(github_repo):
        problems.append(f"GITHUB_REPO must look like owner/name, got {github_repo!r}")
    allowed_role_id = number("ALLOWED_ROLE_ID", required=True)
    discord_guild_id = number("DISCORD_GUILD_ID", required=False)

    user_map: dict[int, str] = {}
    for pair in filter(None, (p.strip() for p in (env.get("GITHUB_USER_MAP") or "").split(","))):
        discord_id, _, login = pair.partition("=")
        discord_id, login = discord_id.strip(), login.strip().lstrip("@")
        if discord_id.isdigit() and _LOGIN_RE.match(login):
            user_map[int(discord_id)] = login
        else:
            problems.append(f"GITHUB_USER_MAP entry {pair!r} must look like <discord id>=<github login>")

    if problems:
        raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(problems))

    assert allowed_role_id is not None
    return Settings(
        discord_token=discord_token,
        github_token=github_token,
        github_repo=github_repo,
        allowed_role_id=allowed_role_id,
        discord_guild_id=discord_guild_id,
        groq_api_key=(env.get("GROQ_API_KEY") or "").strip() or None,
        groq_model=(env.get("GROQ_MODEL") or "").strip() or DEFAULT_GROQ_MODEL,
        groq_fallback_model=(env.get("GROQ_FALLBACK_MODEL") or "").strip() or None,
        github_user_map=user_map,
    )
