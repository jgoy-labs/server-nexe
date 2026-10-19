"""C4.8 part 0 — the API column (phase 3 of the API providers).

The matrix of `test_c48_p0_matrix.py` pins what each door does when a LOCAL engine fails. The API
engine is not in that chain, so it gets its own column: the two real doors (`/v1/chat/completions`
and `/ui/chat`, JSON and streamed) driven by the part 0 lab, with the real `ApiModule` in front of a
fake provider (`_c48_p0_api_lab.py`). Every cell is a real turn.

The rule behind every cell is Jordi's of 06/10, and it is what this column exists to keep true:

* the API answers ONLY when it was asked for by name, past the cloud gate; a healthy local engine
  stands right behind it in every cell and is NEVER asked (`asked=api` is the whole list);
* when the provider fails, the client is told so (401 -> 502, the rest 503 — a timeout too, since
  N5 reads it as an engine failing and the API has no engine behind it) with the provider's own
  sentence, and no local engine answers in its place; a local engine that fails never falls to the API (that is
  `test_the_api_is_never_the_fallback_of_a_local_engine`);
* a refused turn leaves nothing behind and nothing leaves the machine.

Differences between the doors, by label (the register is `test_c48_e_...`): D3 the web stream has
already sent its 200 when the first event fails, so the provider's failure is written in the chat
where /v1 answers the HTTP error; N3 what a failure after the first byte looks like at each door;
R3 an empty reply; N8 the API is reachable at both doors behind the gate; N9 the consent is the
session's at the web door and the request's own at /v1; N10 the model of an API turn is the one the
request names, because an API has no loaded model (D1 is about the engines that do).
"""
from __future__ import annotations

import logging

import pytest

from core import runtime_state
from core.providers.cloud import ALLOW_CLOUD_ENV

from ._c48_p0_api_lab import FAKE_KEY, MODEL, MODES, FakeProvider, ask_api, consent_for
from ._c48_p0_lab import DOORS, build_world, run_door

#: (v1_json, v1_stream, ui_json, ui_stream) per way the provider answers.
API_COLUMN: dict[str, tuple[str, str, str, str]] = {
    "ok": (
        "200 by=api saved asked=api",
        "200 by=api finish=stop saved asked=api",
        "200 by=api saved asked=api",
        "200 by=api saved E=api M=deepseek-chat asked=api",
    ),
    # A refused key is terminal and says so as a 502 (the SERVER is fine; a 401 would log the UI out).
    # D3: the web stream already sent its 200, so the provider's sentence is written in the chat.
    "unauthorized": (
        "502 not-saved asked=api",
        "502 not-saved asked=api",
        "502 not-saved asked=api",
        "200 not-saved M=deepseek-chat asked=api",
    ),
    # A balance, a limit, a 5xx, a request the provider rejects: this engine failing now. With no
    # other engine in its chain the turn ends 503, curated. The local Ollama behind it is NOT asked.
    "balance": (
        "503 not-saved asked=api",
        "503 not-saved asked=api",
        "503 not-saved asked=api",
        "200 not-saved M=deepseek-chat asked=api",
    ),
    "rate_limited": (
        "503 not-saved asked=api",
        "503 not-saved asked=api",
        "503 not-saved asked=api",
        "200 not-saved M=deepseek-chat asked=api",
    ),
    "down": (
        "503 not-saved asked=api",
        "503 not-saved asked=api",
        "503 not-saved asked=api",
        "200 not-saved M=deepseek-chat asked=api",
    ),
    "bad_request": (
        "503 not-saved asked=api",
        "503 not-saved asked=api",
        "503 not-saved asked=api",
        "200 not-saved M=deepseek-chat asked=api",
    ),
    # A provider too slow or out of reach (N5): this engine failing, so the same 503, and the provider's
    # own sentence in the chat (`ApiTimeout`/`ApiUnreachable`). It was a 504, and a generic notice.
    "timeout": (
        "503 not-saved asked=api",
        "503 not-saved asked=api",
        "503 not-saved asked=api",
        "200 not-saved M=deepseek-chat asked=api",
    ),
    "unreachable": (
        "503 not-saved asked=api",
        "503 not-saved asked=api",
        "503 not-saved asked=api",
        "200 not-saved M=deepseek-chat asked=api",
    ),
    # N3: a socket that dies after the first token. The JSON shapes never saw a token (a whole reply
    # is asked for), so it is a connection error; the streams keep the partial answer, the /v1 one
    # closing as `finish=stop` like the in-process engines' does, the web one with the provider's sentence.
    "mid_stream": (
        "503 not-saved asked=api",
        "200 by=api finish=stop saved asked=api",
        "503 not-saved asked=api",
        "200 saved E=api M=deepseek-chat asked=api",
    ),
    # R3: an empty reply is an answer at /v1 and the web stream; the web JSON door passes over an
    # engine that said nothing, and with no other engine behind it that is its 503.
    "empty": (
        "200 empty not-saved asked=api",
        "200 finish=stop empty not-saved asked=api",
        "503 not-saved asked=api",
        "200 empty not-saved E=api M=deepseek-chat asked=api",
    ),
}


@pytest.fixture
def cloud(monkeypatch):
    """The switch on, DeepSeek's key configured (a fake one), OpenAI's not."""
    runtime_state.reset()
    monkeypatch.setenv(ALLOW_CLOUD_ENV, "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    yield
    runtime_state.reset()


def test_the_column_names_every_way_the_provider_answers():
    assert set(API_COLUMN) == set(MODES)
    assert all(len(cells) == len(DOORS) for cells in API_COLUMN.values())


@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("mode", MODES)
async def test_the_api_is_asked_for_and_the_provider_answers(turn_lab, cloud, mode, door):
    provider = FakeProvider(mode)
    seen, world = await ask_api(turn_lab, door, provider)
    assert seen.sig() == API_COLUMN[mode][DOORS.index(door)]
    # One request, never a retry; and the local engine standing behind it was never asked.
    assert len(provider.seen) == 1
    assert world.asked() == ("api",)
    assert world.engines["ollama"].calls == 0 and world.daemon.requests == []


@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("mode", ["unauthorized", "balance", "rate_limited", "down", "bad_request", "timeout", "unreachable"])
async def test_what_the_client_is_told_names_the_provider_and_never_the_key_or_its_body(turn_lab, cloud, mode, door, caplog):
    caplog.set_level(logging.DEBUG)
    provider = FakeProvider(mode)
    seen, _world = await ask_api(turn_lab, door, provider)
    told = (seen.detail or "") + seen.text
    assert "DeepSeek" in told, "every failure names the provider, a timeout and an unreachable one too"
    assert told.strip(), "the client is told something"
    assert FAKE_KEY not in told and "nope" not in told, "neither the key nor the provider's own body"
    assert FAKE_KEY not in caplog.text and FAKE_KEY not in str(seen.headers)
    if seen.ctx is not None:
        assert FAKE_KEY not in repr(seen.ctx.usage) and FAKE_KEY not in repr(seen.ctx.error)


@pytest.mark.parametrize("door", DOORS)
async def test_a_healthy_answer_is_the_providers_and_the_request_carried_only_what_the_gate_allows(turn_lab, cloud, door):
    provider = FakeProvider("ok")
    seen, _world = await ask_api(turn_lab, door, provider)
    assert "Hola de api." in seen.text
    (request,) = provider.seen
    assert request.headers["authorization"] == f"Bearer {FAKE_KEY}", "the key travels in one header of one request"
    body = provider.bodies()[0]
    assert body["model"] == MODEL and body["stream"] is door.endswith("stream")
    assert set(body) <= {"model", "messages", "stream", "top_p", "stream_options"}, "no stray field leaves the machine"
    # the only extra field asks for the closing token count, and only a stream carries it
    assert ("stream_options" in body) is body["stream"]
    assert FAKE_KEY not in str(body)
    assert all(set(m) == {"role", "content"} for m in body["messages"])


# ----------------------------------------------------------------- the gate, at both doors

REFUSALS = {
    "switch_off": (403, "cloud_engines_disabled"),
    "no_consent": (403, "cloud_consent_required"),
    "other_providers_consent": (403, "cloud_consent_required"),
    "no_model": (400, "cloud_model_not_allowed"),
    "a_local_model": (400, "cloud_model_not_allowed"),
    "no_key": (400, "cloud_provider_not_configured"),
}


async def _refused(lab, door, case, monkeypatch):
    provider = FakeProvider("ok")
    kwargs: dict = {}
    if case == "switch_off":
        monkeypatch.setenv(ALLOW_CLOUD_ENV, "0")
    elif case == "no_consent":
        kwargs["consent"] = False
    elif case == "other_providers_consent":
        kwargs["consent"] = False
        kwargs["extra"] = consent_for(door, "openai")
    elif case == "no_model":
        kwargs["model"] = None
    elif case == "a_local_model":
        kwargs["model"] = "llama3.2:3b"
    elif case == "no_key":
        monkeypatch.delenv("DEEPSEEK_API_KEY")
    seen, world = await ask_api(lab, door, provider, sid=f"refused-{case}-{door}", **kwargs)
    return seen, world, provider


@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("case", sorted(REFUSALS))
async def test_a_turn_that_may_not_go_is_refused_the_same_way_at_both_doors_and_nothing_leaves(
    turn_lab, cloud, monkeypatch, case, door,
):
    seen, world, provider = await _refused(turn_lab, door, case, monkeypatch)
    status, code = REFUSALS[case]
    assert seen.status == status and code in (seen.detail or ""), (seen.status, seen.detail)
    assert provider.seen == [], "no request left the machine"
    assert world.asked() == (), "and no local engine answered in the API's place"
    assert seen.saved is False and seen.text == ""
    assert FAKE_KEY not in (seen.detail or "")


@pytest.mark.parametrize("door", DOORS)
async def test_a_refused_turn_stores_nothing_so_the_retry_cannot_duplicate_it(turn_lab, cloud, session_manager, door):
    provider = FakeProvider("ok")
    sid = f"nothing-stored-{door}"
    seen, _world = await ask_api(turn_lab, door, provider, consent=False, sid=sid)
    assert seen.status == 403
    session = session_manager.get_session(sid)
    assert session is None or session.messages == []


@pytest.mark.parametrize("door", DOORS)
async def test_the_consent_of_one_request_is_not_the_consent_of_the_next(turn_lab, cloud, door):
    """N9: at the web door the session remembers a consent the dialog collected (see test_cloud_gate_turn);
    `/v1` has no session, so the second request must say it again."""
    provider = FakeProvider("ok")
    first, _ = await ask_api(turn_lab, door, provider, sid=f"again-{door}")
    assert first.status == 200
    second, _ = await ask_api(turn_lab, door, provider, consent=False, sid=f"again-{door}")
    if door.startswith("v1"):
        assert second.status == 403 and len(provider.seen) == 1
    else:
        assert second.status == 200 and len(provider.seen) == 2, "the web session remembers (N9)"


# ------------------------------------------------------------ the API is never a fallback

@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("mode", ["pre_byte", "oom", "unreachable", "timeout"])
async def test_the_api_is_never_the_fallback_of_a_local_engine(turn_lab, cloud, mode, door):
    """Every local engine fails; the API is loaded, the switch is on, the key is configured, the consent
    could be given — and it is never asked, because nobody asked for it."""
    provider = FakeProvider("ok")
    world = build_world({"mlx": mode, "ollama": mode}, live=["mlx", "ollama"])
    world.modules["api_module"] = provider.module()
    seen = await run_door(turn_lab, world, door, backend="mlx", sid=f"nofb-{mode}-{door}",
                          extra={"model": MODEL} | consent_for(door))
    assert provider.seen == [], "a local failure did not reach the provider"
    assert "api" not in world.asked() and seen.answered != "api"


@pytest.mark.parametrize("door", DOORS)
@pytest.mark.parametrize("spelling", ["auto", None, "ollama"])
async def test_an_environment_preference_for_the_api_is_not_a_request_for_it(turn_lab, cloud, monkeypatch, spelling, door):
    monkeypatch.setenv("NEXE_MODEL_ENGINE", "api")
    runtime_state.set_override("NEXE_MODEL_ENGINE", "api")
    provider = FakeProvider("ok")
    world = build_world(live=["mlx", "ollama"])
    world.modules["api_module"] = provider.module()
    seen = await run_door(turn_lab, world, door, backend=spelling or "auto", sid=f"envpref-{spelling}-{door}",
                          extra=consent_for(door))
    assert provider.seen == [], "nothing was sent to the provider, whatever the local engines said"
    assert "api" not in world.asked() and seen.answered != "api"
    assert seen.status == 200 and seen.text.strip(), "a local engine answered"


# --------------------------------------------------------------------------- N10, the model

@pytest.mark.parametrize("door", ["v1_json", "v1_stream"])
async def test_n10_at_v1_the_api_answers_with_the_model_the_request_names(turn_lab, cloud, monkeypatch, door):
    """The local engines run the model they have loaded and report it (D1); the API has none loaded, so
    the model of the answer is the request's, in the body, in the stream, and on the turn."""
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_KEY)
    provider = FakeProvider("ok")
    seen, _world = await ask_api(turn_lab, door, provider, model="gpt-4o", consent=False, extra=consent_for(door, "openai"))
    assert seen.status == 200
    assert provider.bodies()[0]["model"] == "gpt-4o"
    generate = next(c for c in seen.ctx.usage["llm"]["calls"] if c["step"] == "generate")
    assert (generate["engine"], generate["model"]) == ("api", "gpt-4o")
    wire = seen.wire if door == "v1_json" else "".join(c.decode() if isinstance(c, bytes) else c for c in seen.wire)
    assert "gpt-4o" in str(wire) and "llama" not in str(wire).lower()


# ------------------------------------------------------------------------ the gates

@pytest.mark.parametrize("door", DOORS)
async def test_while_the_provider_answers_the_turn_holds_the_cloud_slot_and_not_the_local_one(turn_lab, cloud, door):
    provider = FakeProvider("ok")
    held: list = []
    real = provider.handler

    def spy(request):
        held.append((len(turn_lab.app_state.cloud_engine_gate._holders), len(turn_lab.app_state.engine_gate._holders)))
        return real(request)

    provider.handler = spy
    seen, _world = await ask_api(turn_lab, door, provider)
    assert seen.status == 200
    assert held == [(1, 0)], "one cloud slot taken, the local slot untouched"
    assert len(turn_lab.app_state.cloud_engine_gate._holders) == 0, "and given back"


@pytest.mark.parametrize("door", DOORS)
async def test_a_local_turn_holds_the_local_slot_and_never_the_cloud_one(turn_lab, cloud, door):
    held: list = []
    world = build_world(live=["mlx", "ollama"])
    real_chat = world.engines["mlx"].chat

    async def watching_chat(*args, **kwargs):
        held.append((len(turn_lab.app_state.cloud_engine_gate._holders), len(turn_lab.app_state.engine_gate._holders)))
        return await real_chat(*args, **kwargs)

    world.engines["mlx"].chat = watching_chat
    seen = await run_door(turn_lab, world, door, backend="mlx", sid=f"localslot-{door}")
    assert seen.status == 200 and held and all(pair == (0, 1) for pair in held), held
