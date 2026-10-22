import httpx
import pytest
import respx

from github_discord_bot.github import GitHubClient, GitHubError

REPO = "o/r"
TOKEN = "ghp_supersecret"
BASE = f"https://api.github.com/repos/{REPO}"


def raw_issue(number=1, title="t", state="open", **extra):
    return {
        "number": number,
        "title": title,
        "state": state,
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "labels": [{"name": "bug"}],
        "user": {"login": "alice"},
        "body": "details",
        **extra,
    }


@pytest.fixture
async def client():
    c = GitHubClient(TOKEN, REPO)
    yield c
    await c.aclose()


@respx.mock
async def test_create_issue(client):
    route = respx.post(f"{BASE}/issues").respond(201, json=raw_issue(7, "Hello"))
    issue = await client.create_issue("Hello", "body")
    assert (issue.number, issue.title, issue.labels, issue.author) == (7, "Hello", ["bug"], "alice")
    assert route.calls[0].request.headers["authorization"] == f"Bearer {TOKEN}"


@respx.mock
async def test_list_issues_filters_pull_requests_and_applies_params(client):
    route = respx.get(f"{BASE}/issues").respond(
        200, json=[raw_issue(1), raw_issue(2, pull_request={"url": "x"}), raw_issue(3)]
    )
    issues = await client.list_issues(state="closed", label="bug")
    assert [i.number for i in issues] == [1, 3]
    params = route.calls[0].request.url.params
    assert params["state"] == "closed" and params["labels"] == "bug"


@respx.mock
async def test_list_issues_respects_limit(client):
    respx.get(f"{BASE}/issues").respond(200, json=[raw_issue(n) for n in range(1, 6)])
    assert len(await client.list_issues(limit=2)) == 2


@respx.mock
async def test_get_close_comment(client):
    respx.get(f"{BASE}/issues/4").respond(200, json=raw_issue(4))
    patch = respx.patch(f"{BASE}/issues/4").respond(200, json=raw_issue(4, state="closed"))
    respx.post(f"{BASE}/issues/4/comments").respond(
        201, json={"html_url": "https://github.com/o/r/issues/4#c1"}
    )
    assert (await client.get_issue(4)).number == 4
    assert (await client.close_issue(4)).state == "closed"
    assert b'"closed"' in patch.calls[0].request.content
    assert (await client.comment(4, "hi")).endswith("#c1")


@pytest.mark.parametrize(
    "status,fragment",
    [
        (401, "invalid or expired"),
        (403, "permission"),
        (404, "not found"),
        (422, "rejected that input"),
        (500, "HTTP 500"),
    ],
)
@respx.mock
async def test_error_statuses_are_mapped(client, status, fragment):
    respx.get(f"{BASE}/issues/1").respond(status, json={"message": f"leak {TOKEN}"})
    with pytest.raises(GitHubError) as exc:
        await client.get_issue(1)
    assert fragment in exc.value.message
    assert exc.value.status == status
    assert TOKEN not in exc.value.message


@respx.mock
async def test_network_failure_is_mapped(client):
    respx.get(f"{BASE}/issues/1").mock(side_effect=httpx.ConnectTimeout("boom"))
    with pytest.raises(GitHubError, match="Could not reach GitHub") as exc:
        await client.get_issue(1)
    assert TOKEN not in exc.value.message


@respx.mock
async def test_pull_requests_are_refused_and_never_closed(client):
    respx.get(f"{BASE}/issues/9").respond(200, json=raw_issue(9, pull_request={"url": "x"}))
    patch = respx.patch(f"{BASE}/issues/9").respond(200, json=raw_issue(9, state="closed"))
    with pytest.raises(GitHubError, match="pull request"):
        await client.get_issue(9)
    with pytest.raises(GitHubError, match="pull request"):
        await client.close_issue(9)
    assert not patch.called
