"""Golden master del camí VLM — #966, Tros A.

**Aquest fitxer NO es pot tocar durant el refactor.** S'escriu contra el codi VELL,
ha de ser verd ABANS del moviment, i ha de seguir verd DESPRÉS sense editar-ne ni una
coma. Si cal canviar una asserció per tornar a verd, el moviment ha canviat comportament
i el tros s'atura.

Per això entra SEMPRE per `MLXChatNode.execute()` — el segell públic — i no anomena cap
mètode intern (`_generate_vlm`, `_prepare_vlm_prompt`, `_run_vlm_streaming`…). Un test que
els nomeni es trencaria mecànicament en moure'ls i deixaria de dir res del comportament,
que és precisament el que aquest fitxer ha de poder distingir.

Les úniques coses falsejades són fronteres EXTERNES, que el refactor no toca:
  · `mlx_vlm.stream_generate` / `mlx_vlm.generate`  (la generació de debò)
  · `mlx_vlm.prompt_utils.apply_chat_template`      (el templating de debò)
  · `_detect_vlm_capability` a `model_loader`        (un sol lloc de resolucio)
  · `MLXChatNode._model` / `._tokenizer`            (estat, no un mètode: evita la càrrega)
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.asyncio

# mlx-vlm només existeix a Apple Silicon (requirements-macos.txt).
pytest.importorskip("mlx_vlm", reason="mlx-vlm Apple-Silicon-only, absent al CI Linux")

# `_detect_vlm_capability` viu a model_loader des de #966 Tros B, i chat.py hi
# accedeix PEL MODUL: patxejar-la aqui val per als dos llocs que la criden.
LOADER = "plugins.mlx_module.core.model_loader"
JPEG = b"\xff\xd8\xff\xe0" + b"NEXE-GOLDEN-MASTER" + b"\x00" * 32


class _FakeTokenizer:
    """El pressupost de context (#845) demana .encode() al tokenizer del processor."""

    def encode(self, text):
        return list(range(max(len(str(text)) // 4, 1)))


class _FakeProcessor:
    """Un processor VLM NO és un tokenizer: exposa .tokenizer (veure #845)."""

    def __init__(self):
        self.tokenizer = _FakeTokenizer()


def _make_node(**config_over):
    from plugins.mlx_module.core.chat import MLXChatNode
    from plugins.mlx_module.core.config import MLXConfig

    cfg = MLXConfig(model_path="/fake/vlm-model")
    cfg.max_tokens = config_over.pop("max_tokens", 64)
    cfg.max_kv_size = config_over.pop("max_kv_size", 4096)
    for k, v in config_over.items():
        setattr(cfg, k, v)

    node = MLXChatNode(config=cfg)
    # Estat, no mètode: amb el singleton ple, la càrrega del model no s'intenta.
    MLXChatNode._model = object()
    MLXChatNode._tokenizer = _FakeProcessor()
    return node


def _reset_singleton():
    from plugins.mlx_module.core.chat import MLXChatNode

    MLXChatNode._model = None
    MLXChatNode._tokenizer = None


@pytest.fixture(autouse=True)
def _clean_singleton():
    _reset_singleton()
    yield
    _reset_singleton()


def _chunks(*texts, **metrics):
    """Chunks tal com els emet mlx_vlm: objectes amb .text; l'últim porta mètriques."""
    out = [SimpleNamespace(text=t) for t in texts]
    if out:
        for k, v in metrics.items():
            setattr(out[-1], k, v)
    return out


class _Harness:
    """Captura què creua la frontera cap a mlx_vlm, sense tocar codi nostre."""

    def __init__(self, chunks=None, oneshot=None):
        self.stream_kwargs = {}
        self.template_kwargs = {}
        self.deltas = []
        self._chunks = chunks or []
        self._oneshot = oneshot

    def _fake_stream(self, **kwargs):
        self.stream_kwargs.update(kwargs)
        for c in self._chunks:
            yield c

    def _fake_generate(self, **kwargs):
        self.stream_kwargs.update(kwargs)
        return self._oneshot

    def _fake_template(self, **kwargs):
        self.template_kwargs.update(kwargs)
        return "PROMPT-FORMATAT"

    def collect(self, delta):
        self.deltas.append(delta)

    def __enter__(self):
        self._ctx = [
            patch(f"{LOADER}._detect_vlm_capability", return_value=True),
            patch("mlx_vlm.prompt_utils.apply_chat_template", self._fake_template),
            patch("mlx_vlm.stream_generate", self._fake_stream),
            patch("mlx_vlm.generate", self._fake_generate),
        ]
        for c in self._ctx:
            c.__enter__()
        return self

    def __exit__(self, *exc):
        for c in reversed(self._ctx):
            c.__exit__(*exc)
        return False


# ── El torn VLM sencer, vist des de fora ─────────────────────────────────────


async def test_streaming_turn_returns_the_generated_text_and_metrics():
    node = _make_node()
    h = _Harness(chunks=_chunks(
        "Veig ", "un ", "gat.",
        prompt_tokens=120, generation_tokens=3,
        prompt_tps=240.0, generation_tps=30.0, peak_memory=2.5,
    ))

    with h:
        result = await node.execute({
            "system": "Ets un assistent.",
            "messages": [{"role": "user", "content": "Què hi ha a la imatge?"}],
            "images": [JPEG],
            "stream_callback": h.collect,
        })

    # El text generat arriba sencer i en ordre pel callback i pel retorn.
    assert result["response"] == "Veig un gat."
    assert h.deltas == ["Veig ", "un ", "gat."]

    # Les mètriques que la UI consumeix.
    assert result["tokens"] == 3
    assert result["prompt_tokens"] == 120
    assert result["tokens_per_second"] == 30.0
    assert result["prompt_tps"] == 240.0
    assert result["model_used"] == "/fake/vlm-model"
    assert set(result["timing"]) == {"prefill_ms", "generation_ms", "overhead_ms"}
    assert result["identity_hash"]

    # El camí VLM mai és continuable (FD-S6/FD-S5).
    assert result["continuable"] is False


async def test_the_image_reaches_the_library_as_a_readable_file_and_is_cleaned_up():
    """Cobreix normalització d'imatge + fitxer temporal + esborrat al finally."""
    node = _make_node()
    h = _Harness(chunks=_chunks("ok"))

    with h:
        await node.execute({
            "system": "",
            "messages": [{"role": "user", "content": "mira"}],
            "images": [JPEG],
            "stream_callback": h.collect,
        })

    import os

    path = h.stream_kwargs["image"]
    assert path, "el camí VLM ha de passar una imatge a mlx_vlm"
    # El fitxer s'esborra en sortir; el contingut s'ha de comprovar via la còpia
    # que la llibreria hauria llegit — aquí verifiquem el contracte d'esborrat.
    assert not os.path.exists(path), "el fitxer temporal ha de quedar esborrat"


async def test_image_bytes_are_written_verbatim():
    """El que rep la llibreria són EXACTAMENT els bytes que ha enviat el client."""
    node = _make_node()
    seen = {}

    class _H(_Harness):
        def _fake_stream(self, **kwargs):
            with open(kwargs["image"], "rb") as fh:
                seen["bytes"] = fh.read()
            return super()._fake_stream(**kwargs)

    h = _H(chunks=_chunks("ok"))
    with h:
        await node.execute({
            "system": "",
            "messages": [{"role": "user", "content": "mira"}],
            "images": [JPEG],
            "stream_callback": h.collect,
        })

    assert seen["bytes"] == JPEG


async def test_kv_cap_travels_to_the_vlm_path():
    """#826: el sostre de KV s'ha d'aplicar TAMBÉ al camí VLM, no només al text."""
    node = _make_node(max_kv_size=8192)
    h = _Harness(chunks=_chunks("ok"))

    with h:
        await node.execute({
            "system": "",
            "messages": [{"role": "user", "content": "hola"}],
            "images": [JPEG],
            "stream_callback": h.collect,
        })

    assert h.stream_kwargs["max_kv_size"] == 8192


async def test_thinking_toggle_reaches_the_chat_template():
    """#fix 2026-05-13: amb Raonament OFF, enable_thinking=False ha d'arribar avall."""
    node = _make_node()
    h = _Harness(chunks=_chunks("ok"))

    with h:
        await node.execute({
            "system": "",
            "messages": [{"role": "user", "content": "hola"}],
            "images": [JPEG],
            "stream_callback": h.collect,
            "thinking_enabled": False,
        })

    assert h.template_kwargs.get("enable_thinking") is False


async def test_thinking_on_passes_no_kwarg():
    """Amb Raonament ON no es passa res: es preserva el default nadiu del model."""
    node = _make_node()
    h = _Harness(chunks=_chunks("ok"))

    with h:
        await node.execute({
            "system": "",
            "messages": [{"role": "user", "content": "hola"}],
            "images": [JPEG],
            "stream_callback": h.collect,
            "thinking_enabled": True,
        })

    assert "enable_thinking" not in h.template_kwargs


async def test_consecutive_same_role_messages_are_merged_before_templating():
    """#860: el camí VLM ha de sanejar l'alternança com fa el camí de text."""
    node = _make_node()
    h = _Harness(chunks=_chunks("ok"))

    with h:
        await node.execute({
            "system": "",
            "messages": [
                {"role": "user", "content": "primera"},
                {"role": "user", "content": "segona"},
            ],
            "images": [JPEG],
            "stream_callback": h.collect,
        })

    prompt = h.template_kwargs["prompt"]
    roles = [m["role"] for m in prompt]
    assert roles == ["user"], f"rols consecutius no fusionats: {roles}"


async def test_cancel_event_stops_the_stream_early():
    """El client desconnecta: la generació ha de parar, no arribar a max_tokens."""
    node = _make_node()

    class _Cancel:
        def __init__(self):
            self.n = 0

        def is_set(self):
            self.n += 1
            return self.n > 2

    h = _Harness(chunks=_chunks("un ", "dos ", "tres ", "quatre ", "cinc"))

    with h:
        result = await node.execute({
            "system": "",
            "messages": [{"role": "user", "content": "hola"}],
            "images": [JPEG],
            "stream_callback": h.collect,
            "cancel_event": _Cancel(),
        })

    assert result["response"] == "un dos "
    assert h.deltas == ["un ", "dos "]


async def test_oneshot_path_when_there_is_no_stream_callback():
    """Sense callback la generació va per mlx_vlm.generate, no per stream_generate."""
    node = _make_node()
    h = _Harness(oneshot=SimpleNamespace(
        text="resposta sencera", prompt_tokens=10, generation_tokens=2,
        prompt_tps=100.0, generation_tps=20.0, peak_memory=1.0,
    ))

    with h:
        result = await node.execute({
            "system": "",
            "messages": [{"role": "user", "content": "hola"}],
            "images": [JPEG],
        })

    assert result["response"] == "resposta sencera"
    assert result["tokens"] == 2


async def test_continue_is_refused_on_the_vlm_path():
    """FD-S6: mlx_vlm no té continue; el camí VLM ho ha de rebutjar explícitament."""
    node = _make_node()
    h = _Harness(chunks=_chunks("ok"))

    with h:
        with pytest.raises(ValueError, match="continue_final"):
            await node.execute({
                "system": "",
                "messages": [{"role": "user", "content": "hola"}],
                "images": [JPEG],
                "stream_callback": h.collect,
                "continue_final": True,
            })


async def test_a_text_only_turn_still_goes_through_the_vlm_path():
    """Un model VLM sense imatge segueix generant per mlx_vlm (sense fitxer temporal)."""
    node = _make_node()
    h = _Harness(chunks=_chunks("sense imatge"))

    with h:
        result = await node.execute({
            "system": "",
            "messages": [{"role": "user", "content": "hola"}],
            "stream_callback": h.collect,
        })

    assert result["response"] == "sense imatge"
    assert h.stream_kwargs["image"] is None
    assert h.template_kwargs["num_images"] == 0
