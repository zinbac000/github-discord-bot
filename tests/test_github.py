import json

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
    issues, has_next = await client.list_issues(state="closed", label="bug")
    assert [i.number for i in issues] == [1, 3] and has_next is False
    params = route.calls[0].request.url.params
    assert params["state"] == "closed" and params["labels"] == "bug"
    assert params["per_page"] == "100" and params["page"] == "1"


@respx.mock
async def test_a_page_is_filled_across_github_pages_that_are_mostly_pull_requests(client):
    nxt = {"Link": f'<{BASE}/issues?page=2>; rel="next"'}

    def serve(request):
        if request.url.params["page"] == "1":  # 90 PRs and only 10 issues
            body = [raw_issue(n, pull_request={"url": "x"}) for n in range(1, 91)]
            body += [raw_issue(n) for n in range(1000, 1010)]
            return httpx.Response(200, json=body, headers=nxt)
        return httpx.Response(200, json=[raw_issue(n) for n in range(2000, 2015)])

    respx.get(f"{BASE}/issues").mock(side_effect=serve)
    first, has_next = await client.list_issues(page=1)
    assert len(first) == 20 and has_next is True  # 25 issues exist, 5 are left over
    second, has_next = await client.list_issues(page=2)
    assert [i.number for i in second] == [2010, 2011, 2012, 2013, 2014] and has_next is False
    assert not {i.number for i in first} & {i.number for i in second}


@respx.mock
async def test_a_short_last_page_has_no_next(client):
    respx.get(f"{BASE}/issues").respond(200, json=[raw_issue(n) for n in range(1, 6)])
    issues, has_next = await client.list_issues()
    assert len(issues) == 5 and has_next is False
    assert await client.list_issues(page=2) == ([], False)


@respx.mock
async def test_filling_a_page_stops_after_a_bounded_number_of_requests(client):
    route = respx.get(f"{BASE}/issues").respond(
        200,
        json=[raw_issue(n, pull_request={"url": "x"}) for n in range(1, 101)],
        headers={"Link": f'<{BASE}/issues?page=2>; rel="next"'},
    )
    issues, has_next = await client.list_issues()
    assert issues == [] and has_next is True  # unknown, so the caller is told there may be more
    assert route.call_count == 10


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


def assignee(login):
    return {"login": login}


@respx.mock
async def test_assign_sends_canonical_casing_and_checks_the_response(client):
    respx.get(f"{BASE}/issues/5").respond(200, json=raw_issue(5))
    respx.get(f"{BASE}/assignees").respond(200, json=[assignee("Zinbac000"), assignee("octocat")])
    post = respx.post(f"{BASE}/issues/5/assignees").respond(
        201, json=raw_issue(5, assignees=[assignee("Zinbac000")])
    )
    issue = await client.assign(5, "@zinbac000")
    assert issue.assignees == ["Zinbac000"]
    assert json.loads(post.calls[0].request.content) == {"assignees": ["Zinbac000"]}


@respx.mock
async def test_assign_reports_failure_when_github_silently_ignores_the_user(client):
    respx.get(f"{BASE}/issues/5").respond(200, json=raw_issue(5))
    respx.get(f"{BASE}/assignees").respond(200, json=[assignee("zinbac000")])
    respx.post(f"{BASE}/issues/5/assignees").respond(201, json=raw_issue(5, assignees=[]))
    with pytest.raises(GitHubError, match="did not assign"):
        await client.assign(5, "zinbac000")


@respx.mock
async def test_assign_refuses_users_the_repo_cannot_assign_without_writing(client):
    respx.get(f"{BASE}/issues/5").respond(200, json=raw_issue(5))
    respx.get(f"{BASE}/assignees").respond(200, json=[assignee("octocat")])
    post = respx.post(f"{BASE}/issues/5/assignees").respond(201, json=raw_issue(5))
    with pytest.raises(GitHubError, match="cannot be assigned"):
        await client.assign(5, "stranger")
    assert not post.called


@pytest.mark.parametrize("bad", ["../x", "a b", "x" * 40, "", "a/b"])
async def test_logins_are_validated_before_any_request(client, bad):
    with pytest.raises(GitHubError, match="valid GitHub username"):
        await client.assignable_login(bad)
    with pytest.raises(GitHubError, match="valid GitHub username"):
        await client.unassign(1, bad)


@respx.mock
async def test_assign_and_unassign_refuse_pull_requests(client):
    respx.get(f"{BASE}/issues/9").respond(200, json=raw_issue(9, pull_request={"url": "x"}))
    with pytest.raises(GitHubError, match="pull request"):
        await client.assign(9, "zinbac000")
    with pytest.raises(GitHubError, match="pull request"):
        await client.unassign(9, "zinbac000")


@respx.mock
async def test_unassign_removes_the_person(client):
    respx.get(f"{BASE}/issues/5").respond(200, json=raw_issue(5, assignees=[assignee("Zinbac000")]))
    delete = respx.delete(f"{BASE}/issues/5/assignees").respond(200, json=raw_issue(5, assignees=[]))
    issue = await client.unassign(5, "zinbac000")
    assert issue.assignees == []
    assert json.loads(delete.calls[0].request.content) == {"assignees": ["Zinbac000"]}


@respx.mock
async def test_unassign_of_someone_not_assigned_makes_no_write_call(client):
    respx.get(f"{BASE}/issues/5").respond(200, json=raw_issue(5, assignees=[assignee("octocat")]))
    delete = respx.delete(f"{BASE}/issues/5/assignees").respond(200, json=raw_issue(5))
    with pytest.raises(GitHubError, match="is not assigned"):
        await client.unassign(5, "zinbac000")
    assert not delete.called


@respx.mock
async def test_unassign_reports_failure_when_the_person_is_still_assigned(client):
    respx.get(f"{BASE}/issues/5").respond(200, json=raw_issue(5, assignees=[assignee("zinbac000")]))
    respx.delete(f"{BASE}/issues/5/assignees").respond(200, json=raw_issue(5, assignees=[assignee("zinbac000")]))
    with pytest.raises(GitHubError, match="did not unassign"):
        await client.unassign(5, "zinbac000")


def label_page(*names):
    return [{"name": n} for n in names]


@respx.mock
async def test_list_labels_follows_pages_and_is_cached_for_ten_minutes():
    now = [0.0]
    client = GitHubClient(TOKEN, REPO, clock=lambda: now[0])
    route = respx.get(f"{BASE}/labels").mock(
        side_effect=[
            httpx.Response(
                200,
                json=label_page("bug", "game:clash-of-saigon"),
                headers={"Link": f'<{BASE}/labels?page=2>; rel="next"'},
            ),
            httpx.Response(200, json=label_page("enhancement")),
        ]
    )
    assert await client.list_labels() == ["bug", "game:clash-of-saigon", "enhancement"]
    assert route.call_count == 2
    assert route.calls[0].request.url.params["per_page"] == "100"

    now[0] = 599
    await client.list_labels()
    assert route.call_count == 2  # still cached

    now[0] = 601
    route.mock(side_effect=None, return_value=httpx.Response(200, json=label_page("bug")))
    assert await client.list_labels() == ["bug"]
    await client.aclose()


@respx.mock
async def test_list_labels_error_is_a_github_error_and_not_cached(client):
    route = respx.get(f"{BASE}/labels").mock(
        side_effect=[httpx.Response(403), httpx.Response(200, json=label_page("bug"))]
    )
    with pytest.raises(GitHubError):
        await client.list_labels()
    assert await client.list_labels() == ["bug"]
    assert route.call_count == 2


@respx.mock
async def test_create_issue_sends_labels_only_when_given(client):
    route = respx.post(f"{BASE}/issues").respond(201, json=raw_issue(1))
    await client.create_issue("a", "b", ["bug", "game:x"])
    await client.create_issue("c", "d")
    assert json.loads(route.calls[0].request.content)["labels"] == ["bug", "game:x"]
    assert "labels" not in json.loads(route.calls[1].request.content)


@respx.mock
async def test_search_issues_scopes_to_the_repo_and_drops_pull_requests(client):
    route = respx.get("https://api.github.com/search/issues").respond(
        200,
        json={
            "items": [
                raw_issue(1, "first"),
                raw_issue(2, "a pr", pull_request={"url": "x"}),
                raw_issue(3, "third", state="closed"),
                raw_issue(4, "fourth"),
                raw_issue(5, "fifth"),
            ]
        },
    )
    found = await client.search_issues("login crash")
    assert [i.number for i in found] == [1, 3, 4]
    assert found[1].state == "closed"
    params = route.calls[0].request.url.params
    assert params["q"] == f"repo:{REPO} is:issue login crash"
    assert params["sort"] == "best-match"


@respx.mock
@pytest.mark.parametrize("status", [403, 422, 500])
async def test_search_errors_are_github_errors(client, status):
    respx.get("https://api.github.com/search/issues").respond(status)
    with pytest.raises(GitHubError):
        await client.search_issues("login crash")
