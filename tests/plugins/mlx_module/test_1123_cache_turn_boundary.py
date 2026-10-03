"""#1123: a hybrid model's prompt cache is reused from one turn to the next.

Live 02/10 with Qwen3.5-9B on MLX: 4 of 4 follow-ups in a conversation logged
"reuse cache state", then "#849 … state reset", and re-read the whole prompt.
mlx_vlm keeps the prompt AND the generated answer in its cache, and reuses it
only when the next prompt starts with all of it — which it never does: the
generation prompt's tail (`<think>\\n\\n</think>\\n\\n` with reasoning off), the
recalled context and the clock line are not rendered back into the history,
and the stored answer is the cleaned one. A hybrid model's recurrent layers
cannot be trimmed back (#849), so the guard threw the cache away every turn.

The runner now brings the cache to where THIS turn's user message starts,
keeps a copy there, generates, and puts the copy back. These tests drive the
real `_generate_vlm` over several turns against an mlx_vlm stand-in with the
real one's two load-bearing habits — a generated token is fed into the cache
before it is yielded, and a recurrent layer cannot be cut — and check the one
property that matters: the cache in memory always holds exactly the tokens
its `token_ids` claim, and from the second turn on it is reused.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytest.importorskip("mlx_vlm", reason="mlx-vlm Apple-Silicon-only, absent al CI Linux")

from mlx_vlm.generate import PromptCacheState  # noqa: E402

from plugins.mlx_module.core.vlm_runner import MLXVisionRunner  # noqa: E402


class _Tok:
    """One token per character: decode is the exact inverse of encode."""

    def encode(self, text):
        return [ord(c) for c in text]

    def decode(self, ids, skip_special_tokens=False):
        return "".join(chr(i) for i in ids)


PROCESSOR = SimpleNamespace(tokenizer=_Tok())


def _render(self, messages, system, processor, has_image, thinking_enabled=True, max_tokens=None, continue_final=False):
    """A chat template with the shape that breaks reuse: the generation prompt
    ends in a reasoning tail that the history never shows again."""
    out = f"<s>{system}</s>"
    for m in messages:
        out += f"<{m['role']}>{m['content']}</{m['role']}>"
    out += "<assistant>" + ("" if thinking_enabled else "<t></t>")
    return out


class _Recurrent:
    """An ArraysCache: what it has read, replaced on every step, never cut."""

    def __init__(self):
        self.cache = [()]


class _Lab:
    """mlx_vlm's stream_generate, as far as the cache goes."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def stream(self, model, processor, prompt, max_tokens, prompt_cache_state=None, sampler=None, **_kw):
        ids = processor.tokenizer.encode(prompt)
        state = prompt_cache_state
        reused = 0
        cache = [_Recurrent()]
        if state is not None and state.cache is not None:
            prefix = state.find_prefix_length(ids)
            if 0 < prefix < len(ids):
                reused, cache = prefix, state.cache  # a recurrent layer is NOT trimmed
        layer = cache[0]
        layer.cache[0] = layer.cache[0] + tuple(ids[reused:])
        if sampler is not None:
            generated = [int(sampler(None).item()) for _ in range(max_tokens)]
        else:
            generated = [ord(c) for c in self.answers.pop(0)]
        self.calls.append({"prompt": prompt, "reused": reused, "new": len(ids) - reused,
                           "max_tokens": max_tokens, "forced": sampler is not None})
        for i, t in enumerate(generated):
            layer.cache[0] = layer.cache[0] + (t,)  # fed before it is yielded
            yield SimpleNamespace(text=chr(t), token=t, prompt_tokens=len(ids), generation_tokens=i + 1,
                                  prompt_tps=1.0, generation_tps=1.0, peak_memory=0.0)
        if state is not None:
            state.update(ids + generated, cache)


def _node():
    from plugins.mlx_module.core.chat import MLXChatNode

    node = MLXChatNode.__new__(MLXChatNode)
    node.config = SimpleNamespace(max_tokens=64, model_path="dummy", max_kv_size=None, max_vlm_session_caches=1)
    return node


def _aligned(state) -> bool:
    return state.cache is not None and list(state.cache[0].cache[0]) == list(state.token_ids)


def _run(node, lab, state, messages, *, thinking=False, continue_final=False):
    with patch.object(MLXVisionRunner, "_get_model", return_value=(object(), PROCESSOR)), \
         patch.object(MLXVisionRunner, "_prepare_vlm_prompt", _render), \
         patch("mlx_vlm.stream_generate", lab.stream), \
         patch("plugins.mlx_module.core.vlm_cache_manager.get_vlm_cache_manager") as mgr:
        mgr.return_value = SimpleNamespace(get_or_create=lambda key: state)
        return node._generate_vlm(
            system="sys", messages=messages, images=[], stream_callback=lambda t: None,
            session_id="sess1234", thinking_enabled=thinking, continue_final=continue_final,
        )


def _conversation(thinking):
    node, state = _node(), PromptCacheState()
    lab = _Lab(["Hola!", "Vic.", "Fet."])
    history = []
    for user in ("hola", "on visc?", "gràcies"):
        history.append({"role": "user", "content": user})
        _run(node, lab, state, history, thinking=thinking)
        assert _aligned(state), "the cache in memory is not what its token_ids say"
        history.append({"role": "assistant", "content": lab.calls[-1] and "resposta neta"})
    return lab, state


@pytest.mark.parametrize("thinking", [False, True])
def test_every_follow_up_reuses_the_cache(thinking):
    lab, _state = _conversation(thinking)
    generations = [c for c in lab.calls if not c["forced"]]
    boundaries = [c for c in lab.calls if c["forced"]]
    assert len(generations) == len(boundaries) == 3
    # The first turn starts cold; every later one starts from the kept boundary.
    assert boundaries[0]["reused"] == 0
    assert all(c["reused"] > 0 for c in boundaries[1:])
    # The generation itself only reads this turn's user message and the tail.
    assert all(c["reused"] > 0 for c in generations)
    assert all(c["new"] == len(f"{u}</user><assistant>") + (0 if thinking else len("<t></t>"))
               for c, u in zip(generations, ("hola", "on visc?", "gràcies")))


def test_the_boundary_is_where_this_turns_user_message_starts():
    """Everything before the user's words: what the next turn renders the same.
    The recalled context and the clock line live inside the message, after it."""
    lab, state = _conversation(False)
    prompt = lab.calls[-1]["prompt"]
    assert "".join(chr(i) for i in state.token_ids) == prompt[:prompt.rindex("gràcies")]


def test_the_boundary_prefill_is_forced_to_end_on_the_boundary():
    lab, state = _conversation(False)
    forced = [c for c in lab.calls if c["forced"]]
    assert all(c["max_tokens"] == 1 for c in forced)
    assert _aligned(state)


def test_without_the_boundary_every_follow_up_resets():
    """Calibration: the stand-in reproduces 02/10 when the boundary is off."""
    node, state = _node(), PromptCacheState()
    lab = _Lab(["Hola!", "Vic."])
    history = [{"role": "user", "content": "hola"}]
    with patch.object(MLXVisionRunner, "_cache_at_turn_boundary", return_value=(None, None)):
        _run(node, lab, state, history)
        history += [{"role": "assistant", "content": "resposta neta"}, {"role": "user", "content": "on visc?"}]
        _run(node, lab, state, history)
    assert lab.calls[-1]["reused"] == 0


def test_a_resume_keeps_the_boundary_it_had():
    """A Continue adds no user message: no new boundary, and the one kept
    before it is still there after it."""
    node, state = _node(), PromptCacheState()
    lab = _Lab(["Hola", " i adéu."])
    history = [{"role": "user", "content": "hola"}]
    _run(node, lab, state, history)
    kept = list(state.token_ids)
    history.append({"role": "assistant", "content": "Hola"})
    n_before = len(lab.calls)
    _run(node, lab, state, history, continue_final=True)
    assert [c["forced"] for c in lab.calls[n_before:]] == [False]
    assert list(state.token_ids) == kept
    assert _aligned(state)


def test_a_failed_generation_still_puts_the_boundary_back():
    node, state = _node(), PromptCacheState()
    lab = _Lab([])
    calls = {"n": 0}
    real = lab.stream

    def stream(**kw):
        if kw.get("sampler") is None:
            # Dies after reading part of the prompt: the layers have moved on,
            # and mlx_vlm never got to update the ids.
            layer = kw["prompt_cache_state"].cache[0]
            layer.cache[0] = layer.cache[0] + (1, 2, 3)
            raise RuntimeError("engine died")
        calls["n"] += 1
        yield from real(**kw)

    lab.stream = stream
    with pytest.raises(RuntimeError):
        _run(node, lab, state, [{"role": "user", "content": "hola"}])
    assert _aligned(state)


def test_a_boundary_that_does_not_line_up_starts_cold(caplog):
    node, state = _node(), PromptCacheState()
    lab = _Lab(["Hola!"])
    real = lab.stream

    def stream(**kw):
        for chunk in real(**kw):
            yield chunk
        if kw.get("sampler") is not None:
            state.token_ids = state.token_ids + [0]  # mlx_vlm stored something else

    lab.stream = stream
    _run(node, lab, state, [{"role": "user", "content": "hola"}])
    assert "did not line up" in caplog.text
    assert lab.calls[-1]["reused"] == 0


def test_a_processor_without_a_tokenizer_just_loses_the_reuse():
    runner = MLXVisionRunner(_node())
    with patch.object(MLXVisionRunner, "_prepare_vlm_prompt", _render):
        assert runner._turn_boundary(object(), "x", [{"role": "user", "content": "x"}], "s", False) is None


def test_an_image_turn_starts_cold():
    """mlx_vlm numbers an image turn's new tokens from 0 over a reused cache,
    and image positions are not a plain offset away: no reuse there."""
    state = PromptCacheState()
    state.cache, state.token_ids = [_Recurrent()], [1, 2, 3]
    runner = MLXVisionRunner(_node())
    turn = ([{"role": "user", "content": "què hi ha?"}], "sys", False, False, True)
    assert runner._cache_at_turn_boundary(object(), PROCESSOR, "x", turn, state) == (None, 0)
    assert state.cache is None and state.token_ids is None


class _LM:
    def __init__(self):
        self._rope_deltas = "set by an earlier call"


class _Model:
    def __init__(self):
        self.language_model = _LM()

    def get_input_embeddings(self, input_ids=None, pixel_values=None, **kwargs):
        # what mlx_vlm 0.4.4's Qwen3.5 does for text: forget the deltas
        if pixel_values is None:
            self.language_model._rope_deltas = None
        return "embeddings"


def test_text_over_a_reused_cache_counts_from_its_offset():
    import mlx.core as mx

    from plugins.mlx_module.core.vlm_runner import _positions_follow_the_cache

    model = _Model()
    with _positions_follow_the_cache(model):
        assert model.get_input_embeddings(mx.array([[1, 2, 3]]), None) == "embeddings"
        deltas = model.language_model._rope_deltas
        assert deltas is not None and deltas.shape == (1, 1) and int(deltas.sum()) == 0
        model.language_model._rope_deltas = "image"
        model.get_input_embeddings(mx.array([[1]]), pixel_values="pixels")
        assert model.language_model._rope_deltas == "image", "an image turn sets its own"
    model.get_input_embeddings(mx.array([[1]]), None)
    assert model.language_model._rope_deltas is None, "outside the call, the model is as it was"


def test_a_model_without_rope_deltas_is_left_alone():
    from plugins.mlx_module.core.vlm_runner import _positions_follow_the_cache

    model = SimpleNamespace(language_model=SimpleNamespace(), get_input_embeddings=lambda *a, **k: "e")
    original = model.get_input_embeddings
    with _positions_follow_the_cache(model):
        assert model.get_input_embeddings is original


def test_a_kept_cache_past_the_new_boundary_is_not_trimmed_into():
    """The kept ids reach into this turn's user message (a prefix of the whole
    prompt, longer than the boundary): reusing it would cut a layer that
    cannot be cut. It starts cold instead."""
    node, state = _node(), PromptCacheState()
    messages = [{"role": "user", "content": "hola"}]
    full = _render(None, messages, "sys", PROCESSOR, False, thinking_enabled=False)
    ids = PROCESSOR.tokenizer.encode(full[:full.rindex("hola") + 2])
    layer = _Recurrent()
    layer.cache[0] = tuple(ids)
    state.cache, state.token_ids = [layer], list(ids)
    lab = _Lab(["Hola!"])
    _run(node, lab, state, messages)
    assert _aligned(state)


class _LossyTok(_Tok):
    def decode(self, ids, skip_special_tokens=False):
        return super().decode(ids).replace("<", "", 1)


def test_a_boundary_the_tokenizer_cannot_rebuild_is_not_used():
    node, state = _node(), PromptCacheState()
    lab = _Lab(["Hola!"])
    with patch.object(MLXVisionRunner, "_get_model", return_value=(object(), SimpleNamespace(tokenizer=_LossyTok()))), \
         patch.object(MLXVisionRunner, "_prepare_vlm_prompt", _render), \
         patch("mlx_vlm.stream_generate", lab.stream), \
         patch("plugins.mlx_module.core.vlm_cache_manager.get_vlm_cache_manager") as mgr:
        mgr.return_value = SimpleNamespace(get_or_create=lambda key: state)
        node._generate_vlm(system="sys", messages=[{"role": "user", "content": "hola"}], images=[],
                           stream_callback=lambda t: None, session_id="s", thinking_enabled=False)
    assert [c["forced"] for c in lab.calls] == [False]


def _with_context(history, user):
    """What the web door sends: the recalled context and its acknowledgement
    as turns of their own before the user's message, the first one marked."""
    from core.turn.assemble import TURN_START_KEY

    return history + [
        {"role": "user", "content": "INFORMACIO RECUPERADA. [MEMORIA DE L'USUARI] viu a Vic", TURN_START_KEY: True},
        {"role": "assistant", "content": "He rebut el bloc de context."},
        {"role": "user", "content": user},
    ]


def test_the_boundary_is_before_the_context_turns_of_this_turn():
    """The context turns are not rendered next turn (the session keeps the
    bare message): a boundary after them would never be a prefix again."""
    node, state = _node(), PromptCacheState()
    lab = _Lab(["Hola!", "Vic.", "Fet."])
    history = []
    for user in ("hola", "on visc?", "gràcies"):
        _run(node, lab, state, _with_context(history, user))
        assert _aligned(state)
        history += [{"role": "user", "content": user}, {"role": "assistant", "content": "resposta neta"}]
    boundaries = [c for c in lab.calls if c["forced"]]
    generations = [c for c in lab.calls if not c["forced"]]
    assert all(c["reused"] > 0 for c in boundaries[1:]), "a follow-up with recalled context started cold"
    assert all(c["reused"] > 0 for c in generations)
    prompt = generations[-1]["prompt"]
    kept = "".join(chr(i) for i in state.token_ids)
    assert prompt.startswith(kept) and kept.endswith("</assistant><user>")
    assert "INFORMACIO RECUPERADA" not in kept[len(kept) - 40:]


# ── review 02/10 ────────────────────────────────────────────────────────────

class _Trimmable(_Recurrent):
    """A layer the #849 guard takes for a KV one (it has keys) — gemma-4's
    shape. mlx_vlm would trim it; this stand-in cannot, so a reuse that needed
    a trim shows up as a cache that no longer matches its ids."""

    keys = object()


def test_call_a_never_trims_a_kept_cache():
    """An earlier answer was edited: the kept cache is not a prefix of the new
    boundary. It is dropped, never trimmed (gemma-4's rotating window would
    come back corrupted)."""
    node, state = _node(), PromptCacheState()
    lab = _Lab(["Hola!", "Vic.", "Fet."])
    history = [{"role": "user", "content": "hola"}]
    _run(node, lab, state, history)
    history += [{"role": "assistant", "content": "resposta neta"}, {"role": "user", "content": "on visc?"}]
    _run(node, lab, state, history)
    state.cache = [_Trimmable()]
    state.cache[0].cache[0] = tuple(state.token_ids)
    history[1]["content"] = "una altra resposta"
    history += [{"role": "assistant", "content": "resposta"}, {"role": "user", "content": "gràcies"}]
    _run(node, lab, state, history)
    assert [c for c in lab.calls if c["forced"]][-1]["reused"] == 0
    assert _aligned(state)


def test_a_regenerate_reuses_the_boundary_without_reading_it_again():
    node, state = _node(), PromptCacheState()
    lab = _Lab(["Hola!", "Hola de nou!"])
    history = [{"role": "user", "content": "hola"}]
    _run(node, lab, state, history)
    n = len(lab.calls)
    _run(node, lab, state, history)
    assert [c["forced"] for c in lab.calls[n:]] == [False], "the boundary was read again"
    assert lab.calls[-1]["reused"] > 0
    assert _aligned(state)


def test_a_failed_boundary_prefill_starts_the_turn_cold():
    node, state = _node(), PromptCacheState()
    lab = _Lab(["Hola!"])
    real = lab.stream

    def stream(**kw):
        if kw.get("sampler") is not None:
            layer = kw["prompt_cache_state"].cache[0] if kw["prompt_cache_state"].cache else None
            if layer is not None:
                layer.cache[0] = layer.cache[0] + (7, 7)
            raise RuntimeError("[metal] out of memory")
        yield from real(**kw)

    lab.stream = stream
    result = _run(node, lab, state, [{"role": "user", "content": "hola"}])
    assert lab.calls[-1]["reused"] == 0
    assert result["cached_tokens"] == 0
    assert _aligned(state)


def test_without_a_boundary_the_cache_is_not_frozen_at_the_first_turn():
    """No boundary (the tokenizer cannot rebuild it): mlx_vlm reuses on its
    own, as before. Restoring a copy anyway would pin the cache to turn 1."""
    node, state = _node(), PromptCacheState()
    lab = _Lab(["Hola!", "Vic."])
    lossy = SimpleNamespace(tokenizer=_LossyTok())

    def run(messages):
        with patch.object(MLXVisionRunner, "_get_model", return_value=(object(), lossy)), \
             patch.object(MLXVisionRunner, "_prepare_vlm_prompt", _render), \
             patch("mlx_vlm.stream_generate", lab.stream), \
             patch("plugins.mlx_module.core.vlm_cache_manager.get_vlm_cache_manager") as mgr:
            mgr.return_value = SimpleNamespace(get_or_create=lambda key: state)
            node._generate_vlm(system="sys", messages=messages, images=[], stream_callback=lambda t: None,
                               session_id="s", thinking_enabled=False)

    run([{"role": "user", "content": "hola"}])
    first = len(state.token_ids)
    # A model whose layers all trim (gemma-4): the #849 guard keeps the cache,
    # so only the copy taken without a boundary could pin it.
    trimmable = _Trimmable()
    trimmable.cache[0] = state.cache[0].cache[0]
    state.cache = [trimmable]
    run([{"role": "user", "content": "hola"}, {"role": "assistant", "content": "Hola!"},
         {"role": "user", "content": "on visc?"}])
    assert len(state.token_ids) > first


def test_an_image_turn_reports_no_reuse():
    node, state = _node(), PromptCacheState()
    lab = _Lab(["Hola!", "Un gat."])
    _run(node, lab, state, [{"role": "user", "content": "hola"}])
    with patch.object(MLXVisionRunner, "_get_model", return_value=(object(), PROCESSOR)), \
         patch.object(MLXVisionRunner, "_prepare_vlm_prompt", _render), \
         patch("mlx_vlm.stream_generate", lab.stream), \
         patch("plugins.mlx_module.core.vlm_cache_manager.get_vlm_cache_manager") as mgr:
        mgr.return_value = SimpleNamespace(get_or_create=lambda key: state)
        result = node._generate_vlm(
            system="sys", images=[b"png"], stream_callback=lambda t: None, session_id="sess1234",
            messages=[{"role": "user", "content": "hola"}, {"role": "assistant", "content": "Hola!"},
                      {"role": "user", "content": "què hi ha?"}], thinking_enabled=False,
        )
    assert result["cached_tokens"] == 0 and result["prefix_reused"] is False



class RotatingKVCache(_Trimmable):
    """Named like mlx_lm's, the way the #826 guard recognises it."""

    max_size = 8


def test_call_a_does_not_extend_a_rotated_window():
    """#826: a rotating window that has wrapped cannot be reused at all. The
    boundary prefill starts from nothing instead of extending it."""
    node, state = _node(), PromptCacheState()
    lab = _Lab(["Hola!", "Vic."])
    history = [{"role": "user", "content": "hola"}]
    _run(node, lab, state, history)
    layer = RotatingKVCache()
    layer.cache[0] = tuple(state.token_ids)
    layer.offset = len(state.token_ids)  # past max_size: it has rotated
    state.cache = [layer]
    history += [{"role": "assistant", "content": "resposta neta"}, {"role": "user", "content": "on visc?"}]
    _run(node, lab, state, history)
    assert [c for c in lab.calls if c["forced"]][-1]["reused"] == 0


def test_cached_counts_what_came_from_an_earlier_turn():
    """Not what the boundary prefill read a moment ago in the same turn: the
    log line is how a person checks the reuse (Jordi's test, 02/10)."""
    node, state = _node(), PromptCacheState()
    lab = _Lab(["Hola!", "Vic."])
    history = [{"role": "user", "content": "hola"}]
    first = _run(node, lab, state, history)
    kept = len(state.token_ids)
    history += [{"role": "assistant", "content": "resposta neta"}, {"role": "user", "content": "on visc?"}]
    second = _run(node, lab, state, history)
    assert first["cached_tokens"] == 0 and first["prefix_reused"] is False
    assert second["cached_tokens"] == kept and second["prefix_reused"] is True

