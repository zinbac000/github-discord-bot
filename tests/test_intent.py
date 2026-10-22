import json

import httpx
import pytest
import respx

from github_discord_bot.intent import AIError, GroqClient, Intent, validate_intent

URL = "https://api.groq.com/openai/v1/chat/completions"
KEY = "gsk_supersecret"


def tool_response(name, **args):
    return {
        "choices": [
            {"message": {"tool_calls": [{"function": {"name": name, "arguments": json.dumps(args)}}]}}
        ]
    }


@pytest.fixture
async def groq():
    c = GroqClient(KEY, "main-model", "backup-model")
    yield c
    await c.aclose()


@respx.mock
async def test_vietnamese_create(groq):
    respx.post(URL).respond(
        200, json=tool_response("create_issue", title="Login lỗi", body="Safari", lang="vi")
    )
    intent = await groq.parse("tạo issue login lỗi trên Safari")
    assert (intent.action, intent.title, intent.lang) == ("create", "Login lỗi", "vi")


@respx.mock
async def test_list_filters_pass_through(groq):
    respx.post(URL).respond(200, json=tool_response("list_issues", state="closed", label="bug", lang="en"))
    intent = await groq.parse("closed bugs")
    assert (intent.action, intent.state, intent.label) == ("list", "closed", "bug")


@respx.mock
async def test_close_with_typed_number_passes(groq):
    respx.post(URL).respond(200, json=tool_response("close_issue", number=12, lang="en"))
    intent = await groq.parse("close 12")
    assert (intent.action, intent.number) == ("close", 12)


@respx.mock
async def test_close_without_typed_number_becomes_clarify(groq):
    respx.post(URL).respond(200, json=tool_response("close_issue", number=12, lang="en"))
    assert (await groq.parse("close the login bug")).action == "clarify"


@respx.mock
async def test_number_differing_from_typed_becomes_clarify(groq):
    respx.post(URL).respond(200, json=tool_response("view_issue", number=21, lang="en"))
    assert (await groq.parse("show me issue 12")).action == "clarify"


@respx.mock
async def test_number_must_match_whole_digit_group(groq):
    respx.post(URL).respond(200, json=tool_response("view_issue", number=1, lang="en"))
    assert (await groq.parse("show issue 12")).action == "clarify"


@respx.mock
async def test_empty_title_becomes_clarify(groq):
    respx.post(URL).respond(200, json=tool_response("create_issue", title="  ", lang="vi"))
    intent = await groq.parse("tạo issue")
    assert intent.action == "clarify" and intent.lang == "vi"


@respx.mock
async def test_request_shape_and_truncation(groq):
    route = respx.post(URL).respond(200, json=tool_response("clarify", question="?", lang="en"))
    await groq.parse("x" * 5000)
    sent = json.loads(route.calls[0].request.content)
    assert sent["tool_choice"] == "required" and sent["temperature"] == 0
    assert len(sent["messages"][1]["content"]) == 1000
    assert route.calls[0].request.headers["authorization"] == f"Bearer {KEY}"


@pytest.mark.parametrize(
    "status,fragment",
    [(429, "busy"), (401, "rejected"), (500, "HTTP 500"), (400, "unavailable")],
)
@respx.mock
async def test_error_statuses(status, fragment):
    c = GroqClient(KEY, "main-model")
    respx.post(URL).respond(status, json={"error": {"message": f"leak {KEY}"}})
    with pytest.raises(AIError) as exc:
        await c.parse("hi")
    assert fragment in exc.value.message and KEY not in exc.value.message
    await c.aclose()


@respx.mock
async def test_timeout(groq):
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(AIError, match="unreachable") as exc:
        await groq.parse("hi")
    assert KEY not in exc.value.message


@respx.mock
async def test_bad_model_retries_with_fallback(groq):
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(404, json={}),
            httpx.Response(200, json=tool_response("clarify", question="?", lang="en")),
        ]
    )
    assert (await groq.parse("hi")).action == "clarify"
    assert json.loads(route.calls[1].request.content)["model"] == "backup-model"


@respx.mock
async def test_bad_model_without_fallback_errors():
    c = GroqClient(KEY, "main-model")
    respx.post(URL).respond(404, json={})
    with pytest.raises(AIError, match="unavailable"):
        await c.parse("hi")
    await c.aclose()


@respx.mock
async def test_no_tool_calls_or_bad_json_become_clarify(groq):
    respx.post(URL).mock(
        side_effect=[
            httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]}),
            httpx.Response(
                200,
                json={"choices": [{"message": {"tool_calls": [{"function": {"name": "close_issue", "arguments": "{nope"}}]}}]},
            ),
            httpx.Response(
                200,
                json={"choices": [{"message": {"tool_calls": [{"function": {"name": "drop_table", "arguments": "{}"}}]}}]},
            ),
        ]
    )
    for _ in range(3):
        assert (await groq.parse("hi")).action == "clarify"


def test_validate_clips_and_normalizes():
    out = validate_intent(Intent("create", title="t" * 400, body="b" * 5000, lang="fr"), "tạo")
    assert len(out.title) == 256 and len(out.body) == 4000 and out.lang == "en"
    assert validate_intent(Intent("list", state="weird"), "x").state == "open"
    assert validate_intent(Intent("comment", number=3, body=" "), "comment on 3").action == "clarify"


@respx.mock
async def test_blank_clarify_question_gets_a_default_and_long_ones_are_clipped(groq):
    respx.post(URL).mock(
        side_effect=[
            httpx.Response(200, json=tool_response("clarify", question="  ", lang="vi")),
            httpx.Response(200, json=tool_response("clarify", question="q" * 5000, lang="en")),
        ]
    )
    assert (await groq.parse("hi")).question != ""
    assert len((await groq.parse("hi")).question) == 1000


def test_several_distinct_numbers_become_clarify():
    assert validate_intent(Intent("close", number=15), "close 12 not 15").action == "clarify"
    assert validate_intent(Intent("close", number=12), "close 12 and 12 again").action == "close"
