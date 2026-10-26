from types import SimpleNamespace

from github_discord_bot.thread_draft import (
    Draft,
    _fit,
    apply_form,
    blocking,
    build_body,
    collect,
    missing,
    neutralise_mentions,
    parse_draft,
)

NAMES = ["bug", "enhancement", "game:clash-of-saigon"]
URL = "https://discord.com/channels/1/2"


def test_plain_body_is_just_the_description():
    assert build_body(Draft("t", kind="enhancement", description="Add dark mode")) == "Add dark mode"


def test_bug_with_details_gets_sections_in_order():
    draft = Draft(
        "t",
        kind="bug",
        description="Crash on start",
        steps=("Open the game", "Tap play"),
        expected="It starts",
        actual="It crashes",
    )
    assert build_body(draft) == (
        "## Description\nCrash on start\n\n"
        "## Steps to reproduce\n1. Open the game\n2. Tap play\n\n"
        "## Expected\nIt starts\n\n"
        "## Actual\nIt crashes"
    )


def test_vietnamese_headings_and_source_line():
    draft = Draft("t", kind="bug", description="Lỗi", steps=("Mở game",), lang="vi", source_url=URL)
    body = build_body(draft)
    assert "## Mô tả\nLỗi" in body and "## Các bước tái hiện\n1. Mở game" in body
    assert body.endswith(f"---\nNguồn: {URL}")


def test_empty_sections_are_left_out():
    body = build_body(Draft("t", kind="bug", steps=("one",)))
    assert body == "## Steps to reproduce\n1. one"
    assert build_body(Draft("t")) == ""


def test_source_link_always_comes_last():
    body = build_body(Draft("t", description="x", source_url=URL))
    assert body == f"x\n\n---\nSource: {URL}"


def test_mentions_cannot_ping_on_github():
    out = neutralise_mentions("ping @alice and @bob, lone @ here")
    assert out == "ping @​alice and @​bob, lone @ here"


def test_missing_and_blocking():
    draft = Draft("t", from_thread=True)
    assert missing(draft, game_exists=True) == ["kind", "description", "game"]
    assert blocking(draft) == ["kind", "description"]

    bug = Draft("t", kind="bug", description="d", from_thread=True)
    assert missing(bug, game_exists=False) == ["steps"]
    assert blocking(bug) == []

    done = Draft("t", kind="bug", description="d", steps=("s",), game="game:x", from_thread=True)
    assert missing(done, game_exists=True) == []


def test_description_only_needed_for_thread_drafts():
    typed = Draft("login lỗi", kind="bug")  # /ask: a title alone was always enough
    assert "description" not in missing(typed, game_exists=False)
    assert blocking(typed) == []


def test_skipping_the_game_never_blocks():
    assert blocking(Draft("t", kind="bug", description="d", from_thread=True)) == []


def test_apply_form_replaces_and_cleans():
    draft = Draft("old", kind="bug", description="old d")
    out = apply_form(
        draft,
        title="  New title ",
        description="ping @carol",
        steps="1. Open\n- Tap\n\n  Win ",
        expected="ok",
        actual="",
    )
    assert out.title == "New title"
    assert out.description == "ping @​carol"
    assert out.steps == ("Open", "Tap", "Win")
    assert (out.expected, out.actual) == ("ok", "")
    assert out.kind == "bug"


def test_apply_form_keeps_the_title_when_blank_and_caps_steps():
    out = apply_form(Draft("keep"), title=" ", description="", steps="\n".join(map(str, range(50))), expected="", actual="")
    assert out.title == "keep"
    assert len(out.steps) == 20


def test_parse_draft_checks_every_field():
    draft = parse_draft(
        {
            "title": "  Crash @dev  ",
            "kind": "idea",
            "description": "d",
            "steps": ["a", "", 7, "b"],
            "expected": 5,
            "actual": "boom",
            "game": "Clash of Saigon",
            "lang": "vi",
        },
        thread_name="thread name",
        names=NAMES,
        url=URL,
        read=12,
        total=30,
    )
    assert draft.title == "Crash @​dev"
    assert draft.kind == "enhancement"
    assert draft.game == "game:clash-of-saigon"
    assert draft.steps == ("a", "b")
    assert draft.expected == "" and draft.actual == "boom"
    assert (draft.lang, draft.source_url, draft.from_thread, draft.read, draft.total) == ("vi", URL, True, 12, 30)


def test_parse_draft_falls_back_when_the_model_gives_junk():
    draft = parse_draft(
        {"title": "", "kind": "nonsense", "game": "tetris", "steps": "not a list", "lang": "fr"},
        thread_name="Forum post title",
        names=NAMES,
        url=URL,
        read=1,
        total=1,
    )
    assert (draft.title, draft.kind, draft.game, draft.steps, draft.lang) == (
        "Forum post title", "", "", (), "en",
    )


# --- reading a thread


def msg(i, text="hello", *, bot=False, name="An", files=()):
    return SimpleNamespace(
        id=i,
        author=SimpleNamespace(bot=bot, display_name=name),
        clean_content=text,
        attachments=[SimpleNamespace(filename=f) for f in files],
    )


class FakeThread:
    id = 10
    name = "Crash on start"

    def __init__(self, messages, message_count=0, parent=None):
        self.messages = messages
        self.message_count = message_count
        self.parent = parent or SimpleNamespace()

    def history(self, limit=None, oldest_first=False):
        async def gen():
            items = list(self.messages) if oldest_first else list(reversed(self.messages))
            for m in items[:limit]:
                yield m

        return gen()


async def test_collect_reads_names_not_ids_skips_bots_and_notes_attachments():
    thread = FakeThread(
        [msg(1, "game crashes"), msg(2, "bot noise", bot=True), msg(3, "", name="Binh", files=["a.png"])]
    )
    got = await collect(thread)
    assert got.text == "Thread title: Crash on start\nAn: game crashes\nBinh: [attachment: a.png]"
    assert (got.read, got.total) == (3, 3)


async def test_collect_empty_thread_has_no_text():
    got = await collect(FakeThread([msg(1, "only bot", bot=True)]))
    assert got.text == ""


async def test_collect_long_thread_keeps_head_and_latest_and_says_total():
    thread = FakeThread([msg(i, f"m{i}") for i in range(1, 101)], message_count=100)
    got = await collect(thread)
    assert got.read == 60 and got.total == 100
    assert "An: m1" in got.text and "An: m3" in got.text and "An: m100" in got.text
    assert "An: m30\n" not in got.text and "An: m4\n" not in got.text


async def test_collect_includes_the_starter_message_of_a_normal_thread():
    parent = SimpleNamespace(fetch_message=lambda mid: _async(msg(10, "the starting post", name="Lan")))
    thread = FakeThread([msg(11, "reply")], parent=parent)
    got = await collect(thread)
    assert "Lan: the starting post" in got.text
    assert got.text.index("starting post") < got.text.index("reply")


async def test_collect_survives_an_unreadable_starter():
    async def boom(mid):
        raise RuntimeError("gone")

    thread = FakeThread([msg(11, "reply")], parent=SimpleNamespace(fetch_message=boom))
    assert "An: reply" in (await collect(thread)).text


async def test_collect_does_not_fetch_a_starter_for_a_forum_post():
    called = []

    async def fetch(mid):
        called.append(mid)

    forum = SimpleNamespace(fetch_message=fetch, available_tags=[])
    await collect(FakeThread([msg(10, "post body")], parent=forum))
    assert called == []


async def _async(value):
    return value


def test_fit_trims_the_middle_and_says_so():
    lines = [f"line{i}" + "x" * 90 for i in range(100)]
    fitted = _fit(lines, 1000)
    assert fitted[:3] == lines[:3]
    assert fitted[-1] == lines[-1]
    assert any("left out" in line for line in fitted)
    assert sum(len(x) + 1 for x in fitted) <= 1000 + 40


def test_fit_leaves_a_short_thread_alone():
    assert _fit(["a", "b"], 1000) == ["a", "b"]


async def test_long_messages_are_cut():
    got = await collect(FakeThread([msg(1, "y" * 5000)]))
    assert len(got.text) < 1700
