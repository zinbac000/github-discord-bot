import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx

API = "https://api.github.com"
LOGIN_RE = re.compile(r"^[A-Za-z0-9-]{1,39}$")
PAGE_SIZE = 20
FETCH_SIZE = 100  # GitHub items per request while filling a page
MAX_FETCHES = 10  # most GitHub requests spent on one page of results
LABEL_CACHE_SECONDS = 600
MAX_LABEL_PAGES = 10


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
    assignees: list[str] = field(default_factory=list)


def _issue(data: dict) -> Issue:
    return Issue(
        number=data["number"],
        title=data["title"],
        state=data["state"],
        url=data["html_url"],
        labels=[label["name"] for label in data.get("labels", [])],
        author=(data.get("user") or {}).get("login", ""),
        body=data.get("body") or "",
        assignees=[a["login"] for a in data.get("assignees") or []],
    )


def _check_login(login: str) -> str:
    login = login.strip().lstrip("@")
    if not LOGIN_RE.match(login):
        raise GitHubError("That is not a valid GitHub username.")
    return login


def _has(logins: list[str], login: str) -> bool:
    return login.lower() in (name.lower() for name in logins)


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
    def __init__(
        self,
        token: str,
        repo: str,
        *,
        timeout: float = 15.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._repo = repo
        self._clock = clock
        self._labels: list[str] = []
        self._labels_at: float | None = None
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

    async def _call(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            response = await self._http.request(method, url, **kwargs)
        except httpx.HTTPError:
            raise GitHubError("Could not reach GitHub. Try again in a moment.") from None
        if response.is_error:
            raise _error_for(response.status_code)
        return response

    async def _send(self, method: str, path: str, **kwargs) -> httpx.Response:
        return await self._call(method, f"/repos/{self._repo}{path}", **kwargs)

    async def _request(self, method: str, path: str, **kwargs):
        return (await self._send(method, path, **kwargs)).json()

    async def create_issue(
        self, title: str, body: str = "", labels: list[str] | None = None
    ) -> Issue:
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        return _issue(await self._request("POST", "/issues", json=payload))

    async def list_labels(self) -> list[str]:
        """Every label name on the repo. Cached for ten minutes, so one preview costs no request."""
        now = self._clock()
        if self._labels_at is not None and now - self._labels_at < LABEL_CACHE_SECONDS:
            return list(self._labels)
        names: list[str] = []
        for page in range(1, MAX_LABEL_PAGES + 1):
            response = await self._send("GET", "/labels", params={"per_page": 100, "page": page})
            names += [label["name"] for label in response.json()]
            if "next" not in response.links:
                break
        self._labels, self._labels_at = names, now
        return list(names)

    async def search_issues(self, query: str, limit: int = 3) -> list[Issue]:
        """Issues (never pull requests, open or closed) that best match the words in `query`."""
        response = await self._call(
            "GET",
            "/search/issues",
            params={
                "q": f"repo:{self._repo} is:issue {query}",
                "per_page": limit + 2,
                "sort": "best-match",
            },
        )
        items = [i for i in response.json().get("items", []) if "pull_request" not in i]
        return [_issue(i) for i in items[:limit]]

    async def list_issues(
        self,
        state: str = "open",
        label: str | None = None,
        page: int = 1,
        per_page: int = PAGE_SIZE,
    ) -> tuple[list[Issue], bool]:
        """Page `page` of issues (`per_page` each), and whether there are more after it.

        GitHub mixes pull requests into this endpoint (they carry a "pull_request" key), so a
        GitHub page can hold few or no issues. We therefore read GitHub pages until we have
        enough issues to fill ours, instead of paging GitHub directly.
        """
        params: dict = {"state": state, "per_page": FETCH_SIZE}
        if label:
            params["labels"] = label
        start = (page - 1) * per_page
        collected: list[Issue] = []
        more, fetched = True, 0
        while more and fetched < MAX_FETCHES and len(collected) <= start + per_page:
            fetched += 1
            response = await self._send("GET", "/issues", params={**params, "page": fetched})
            collected += [_issue(i) for i in response.json() if "pull_request" not in i]
            more = "next" in response.links
        has_next = len(collected) > start + per_page or more
        return collected[start : start + per_page], has_next

    async def get_issue(self, number: int) -> Issue:
        data = await self._request("GET", f"/issues/{number}")
        if "pull_request" in data:
            raise GitHubError(f"#{number} is a pull request, not an issue.")
        return _issue(data)

    async def close_issue(self, number: int) -> Issue:
        await self.get_issue(number)  # refuses pull requests before anything is closed
        return _issue(await self._request("PATCH", f"/issues/{number}", json={"state": "closed"}))

    async def assignable_login(self, login: str) -> str | None:
        """GitHub's canonical casing of `login` if the repo can assign it, else None."""
        login = _check_login(login)
        users = await self._request("GET", "/assignees", params={"per_page": 100})
        return next((u["login"] for u in users if u["login"].lower() == login.lower()), None)

    async def assign(self, number: int, login: str) -> Issue:
        await self.get_issue(number)  # refuses pull requests
        canonical = await self.assignable_login(login)
        if canonical is None:
            raise GitHubError(f"{login.strip().lstrip('@')} cannot be assigned in this repo.")
        data = await self._request(
            "POST", f"/issues/{number}/assignees", json={"assignees": [canonical]}
        )
        issue = _issue(data)
        # GitHub silently ignores users it cannot assign, so trust the response, not the status.
        if not _has(issue.assignees, canonical):
            raise GitHubError(f"GitHub did not assign {canonical} to #{number}.")
        return issue

    async def unassign(self, number: int, login: str) -> Issue:
        login = _check_login(login)
        issue = await self.get_issue(number)  # refuses pull requests
        current = next((a for a in issue.assignees if a.lower() == login.lower()), None)
        if current is None:
            raise GitHubError(f"{login} is not assigned to #{number}.")
        data = await self._request(
            "DELETE", f"/issues/{number}/assignees", json={"assignees": [current]}
        )
        issue = _issue(data)
        if _has(issue.assignees, current):
            raise GitHubError(f"GitHub did not unassign {current} from #{number}.")
        return issue

    async def comment(self, number: int, body: str) -> str:
        data = await self._request("POST", f"/issues/{number}/comments", json={"body": body})
        return data["html_url"]
