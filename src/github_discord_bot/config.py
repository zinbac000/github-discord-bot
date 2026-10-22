import os
import re
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import dotenv_values

_REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")
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
    )
