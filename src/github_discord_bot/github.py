from dataclasses import dataclass, field

import httpx

API = "https://api.github.com"


class GitHubError(Exception):
    """A GitHub failure with a message that is safe to show in Discord."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Issue:
    number: int
    title: str
    state: str
    url: str
    labels: list[str] = field(default_factory=list)
    author: str = ""
    body: str = ""


def _issue(data: dict) -> Issue:
    return Issue(
        number=data["number"],
        title=data["title"],
        state=data["state"],
        url=data["html_url"],
        labels=[label["name"] for label in data.get("labels", [])],
        author=(data.get("user") or {}).get("login", ""),
        body=data.get("body") or "",
    )


def _error_for(status: int) -> GitHubError:
    if status == 401:
        return GitHubError("GitHub rejected the bot's token. It is invalid or expired.", status)
    if status == 403:
        return GitHubError(
            "GitHub refused the request: the token lacks permission, or the rate limit was hit.",
            status,
        )
    if status in (404, 410):
        return GitHubError("Repository or issue not found.", status)
    if status == 422:
        return GitHubError("GitHub rejected that input.", status)
    return GitHubError(f"GitHub returned an unexpected error (HTTP {status}).", status)


class GitHubClient:
    def __init__(self, token: str, repo: str, *, timeout: float = 15.0):
        self._repo = repo
        self._http = httpx.AsyncClient(
            base_url=API,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "github-discord-bot",
            },
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, **kwargs):
        try:
            response = await self._http.request(method, f"/repos/{self._repo}{path}", **kwargs)
        except httpx.HTTPError:
            raise GitHubError("Could not reach GitHub. Try again in a moment.") from None
        if response.is_error:
            raise _error_for(response.status_code)
        return response.json()

    async def create_issue(
        self, title: str, body: str = "", labels: list[str] | None = None
    ) -> Issue:
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        return _issue(await self._request("POST", "/issues", json=payload))

    async def list_issues(
        self, state: str = "open", label: str | None = None, limit: int = 10
    ) -> list[Issue]:
        params: dict = {"state": state, "per_page": 100}
        if label:
            params["labels"] = label
        data = await self._request("GET", "/issues", params=params)
        # The issues endpoint also returns pull requests; they carry a "pull_request" key.
        issues = [_issue(item) for item in data if "pull_request" not in item]
        return issues[:limit]

    async def get_issue(self, number: int) -> Issue:
        data = await self._request("GET", f"/issues/{number}")
        if "pull_request" in data:
            raise GitHubError(f"#{number} is a pull request, not an issue.")
        return _issue(data)

    async def close_issue(self, number: int) -> Issue:
        await self.get_issue(number)  # refuses pull requests before anything is closed
        return _issue(await self._request("PATCH", f"/issues/{number}", json={"state": "closed"}))

    async def comment(self, number: int, body: str) -> str:
        data = await self._request("POST", f"/issues/{number}/comments", json={"body": body})
        return data["html_url"]
