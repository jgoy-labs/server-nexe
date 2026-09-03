"""Golden master del camí de TEXT — #966, Tros C.

Tercer i últim golden master de la sèrie. Mateixa regla: escrit contra el codi actual,
verd ABANS de moure res, intocable durant el refactor.

DISSENY, i aquí hi ha la lliçó del Tros B: **no es patxeja cap helper de la canonada**.
Al Tros A el golden master del VLM patxejava `chat._detect_vlm_capability` creient que era
una frontera externa —era un intern— i el moviment següent el va tombar sencer. Aquí la
canonada de 7 passos de `generate_helpers` **s'executa de debò**; l'única cosa fingida és
la frontera de `mlx_lm` (la generació) i el tokenizer. Per això aquest fitxer no sap ni li
importa on acabi vivint el codi.

Palanques, totes externes o d'estat:
  · `mlx_lm.stream_generate`                  (la generació real)
  · `mlx_lm.sample_utils.make_sampler`        (el mostrejador real)
  · `mlx_lm.models.cache.make_prompt_cache`   (el KV real)
  · `MLXChatNode._model` / `._tokenizer`      (estat: evita carregar cap model)
  · un directori de model REAL amb `config.json`
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.asyncio

# mlx-lm només existeix a Apple Silicon (requirements-macos.txt).
pytest.importorskip("mlx_lm", reason="mlx-lm Apple-Silicon-only, absent al CI Linux")


class _FakeTokenizer:
    """El mínim que la canonada real demana: encode, apply_chat_template, eos_token_ids."""

    eos_token_ids = [2]

    def encode(self, text, **kw):
        # Determinista i PROPORCIONAL: sense truncar, perquè la mida del prompt
        # s'ha de moure amb el text. Truncar aquí faria que dos prompts de mides
        # molt diferents donessin el mateix recompte i el test no vigilaria res.
        return [1] + [ord(c) % 97 + 3 for c in str(text)]

    def apply_chat_template(self, messages, **kw):
        return "\n".join(
            f"{m.get('role')}: {m.get('content')}" for m in messages
        )


def _model_dir(tmp_path):
    d = tmp_path / "text-model"
    d.mkdir()
    (d / "config.json").write_text(
        json.dumps({"model_type": "qwen3", "architectures": ["Qwen3ForCausalLM"]})
    )
    return str(d)


def _node(model_path, **over):
    from plugins.mlx_module.core.chat import MLXChatNode
    from plugins.mlx_module.core.config import MLXConfig

    cfg = MLXConfig(model_path=model_path)
    cfg.max_tokens = over.pop("max_tokens", 32)
    cfg.max_kv_size = over.pop("max_kv_size", 4096)
    cfg.temperature = over.pop("temperature", 0.7)
    cfg.top_p = over.pop("top_p", 0.9)
    for k, v in over.items():
        setattr(cfg, k, v)

    node = MLXChatNode(config=cfg)
    MLXChatNode._model = object()
    MLXChatNode._tokenizer = _FakeTokenizer()
    return node


@pytest.fixture(autouse=True)
def _clean():
    from plugins.mlx_module.core.chat import MLXChatNode

    def reset():
        MLXChatNode._model = None
        MLXChatNode._tokenizer = None
        MLXChatNode._is_vlm = False
        MLXChatNode._config = None

    reset()
    yield
    reset()


class _Gen:
    """Fingeix la generació de mlx_lm i captura què hi arriba."""

    def __init__(self, *texts, **metrics):
        self.texts = texts
        self.metrics = metrics or dict(
            prompt_tokens=40, generation_tokens=len(texts),
            prompt_tps=200.0, generation_tps=25.0, peak_memory=1.5,
        )
        self.stream_kwargs = {}
        self.sampler_kwargs = {}
        self.deltas = []

    def _stream(self, model, tokenizer, tokens, **kwargs):
        self.stream_kwargs.update(kwargs)
        self.stream_kwargs["prompt_tokens_in"] = list(tokens)
        chunks = []
        for t in self.texts:
            c = SimpleNamespace(text=t, token=7, finish_reason=None)
            for k, v in self.metrics.items():
                setattr(c, k, v)
            chunks.append(c)
        return iter(chunks)

    def _sampler(self, **kwargs):
        self.sampler_kwargs.update(kwargs)
        return "SAMPLER"

    def collect(self, d):
        self.deltas.append(d)

    def __enter__(self):
        self._c = [
            patch("mlx_lm.stream_generate", self._stream),
            patch("mlx_lm.sample_utils.make_sampler", self._sampler),
            patch("mlx_lm.models.cache.make_prompt_cache", lambda *a, **k: []),
        ]
        for c in self._c:
            c.__enter__()
        return self

    def __exit__(self, *e):
        for c in reversed(self._c):
            c.__exit__(*e)
        return False


# ── el torn de text sencer, des de fora ──────────────────────────────────────

async def test_a_text_turn_streams_and_returns_the_generated_text(tmp_path):
    node = _node(_model_dir(tmp_path))
    g = _Gen("Hola ", "què ", "tal")

    with g:
        result = await node.execute({
            "system": "Ets un assistent.",
            "messages": [{"role": "user", "content": "Hola"}],
            "stream_callback": g.collect,
        })

    assert result["response"] == "Hola què tal"
    assert g.deltas == ["Hola ", "què ", "tal"]
    assert result["model_used"] == str(tmp_path / "text-model")
    assert set(result["timing"]) == {"prefill_ms", "generation_ms", "overhead_ms"}
    assert result["identity_hash"]


async def test_the_text_path_is_used_not_the_vision_one(tmp_path):
    """Un model sense vision_config no ha de passar mai per mlx_vlm."""
    node = _node(_model_dir(tmp_path))
    g = _Gen("ok")

    with patch("mlx_vlm.generate", side_effect=AssertionError("no toca VLM")), \
         patch("mlx_vlm.stream_generate", side_effect=AssertionError("no toca VLM")):
        with g:
            result = await node.execute({
                "system": "",
                "messages": [{"role": "user", "content": "hola"}],
                "stream_callback": g.collect,
            })

    assert result["response"] == "ok"


# ── els paràmetres de mostreig arriben avall ─────────────────────────────────

async def test_request_sampling_wins_over_the_engine_defaults(tmp_path):
    node = _node(_model_dir(tmp_path), temperature=0.7, top_p=0.9)
    g = _Gen("ok")

    with g:
        await node.execute({
            "system": "",
            "messages": [{"role": "user", "content": "hola"}],
            "stream_callback": g.collect,
            "temperature": 0.1,
            "top_p": 0.5,
        })

    assert g.sampler_kwargs == {"temp": 0.1, "top_p": 0.5}


async def test_engine_defaults_apply_when_the_request_says_nothing(tmp_path):
    node = _node(_model_dir(tmp_path), temperature=0.7, top_p=0.9)
    g = _Gen("ok")

    with g:
        await node.execute({
            "system": "",
            "messages": [{"role": "user", "content": "hola"}],
            "stream_callback": g.collect,
        })

    assert g.sampler_kwargs == {"temp": 0.7, "top_p": 0.9}


async def test_the_token_ceiling_reaches_the_generator(tmp_path):
    node = _node(_model_dir(tmp_path), max_tokens=32)
    g = _Gen("ok")

    with g:
        await node.execute({
            "system": "",
            "messages": [{"role": "user", "content": "hola"}],
            "stream_callback": g.collect,
            "max_tokens": 7,
        })

    assert g.stream_kwargs["max_tokens"] == 7


# ── el prompt es construeix de debò ──────────────────────────────────────────

async def test_the_history_is_part_of_the_prompt(tmp_path):
    """La canonada real tokenitza la CONVERSA, no només l'últim torn.

    Els dos casos comparteixen system i últim missatge EXACTES: l'única
    diferència és la història anterior. Si el prompt es construís només amb
    l'últim torn, els dos donarien el mateix nombre de tokens i això passaria
    sense adonar-se'n — que és el que feia la primera versió d'aquest test.
    """
    node = _node(_model_dir(tmp_path))
    system = "Ets un assistent."
    last = {"role": "user", "content": "i ara què?"}

    sense = _Gen("ok")
    with sense:
        await node.execute({
            "system": system,
            "messages": [last],
            "stream_callback": sense.collect,
        })

    amb = _Gen("ok")
    with amb:
        await node.execute({
            "system": system,
            "messages": [
                {"role": "user", "content": "una pregunta anterior ben llarga"},
                {"role": "assistant", "content": "una resposta anterior ben llarga"},
                last,
            ],
            "stream_callback": amb.collect,
        })

    n_sense = len(sense.stream_kwargs["prompt_tokens_in"])
    n_amb = len(amb.stream_kwargs["prompt_tokens_in"])
    assert n_amb > n_sense, (
        f"la història ha de formar part del prompt: {n_amb} tokens amb història "
        f"vs {n_sense} sense, i han de ser diferents"
    )


# ── cancel·lació ─────────────────────────────────────────────────────────────

async def test_cancel_event_stops_the_text_stream_early(tmp_path):
    node = _node(_model_dir(tmp_path))

    class _Cancel:
        def __init__(self):
            self.n = 0

        def is_set(self):
            self.n += 1
            return self.n > 2

    g = _Gen("un ", "dos ", "tres ", "quatre ")
    with g:
        result = await node.execute({
            "system": "",
            "messages": [{"role": "user", "content": "hola"}],
            "stream_callback": g.collect,
            "cancel_event": _Cancel(),
        })

    assert len(g.deltas) < 4, "la cancel·lació ha de tallar abans del final"
    assert result["response"] == "".join(g.deltas)


# ── continue (FD-S6): permès al text, prohibit al VLM ────────────────────────

async def test_continue_is_allowed_on_the_text_path(tmp_path):
    node = _node(_model_dir(tmp_path))
    g = _Gen("segueixo")

    with g:
        result = await node.execute({
            "system": "",
            "messages": [
                {"role": "user", "content": "conta"},
                {"role": "assistant", "content": "un dos"},
            ],
            "stream_callback": g.collect,
            "continue_final": True,
        })

    assert result["response"] == "segueixo"


# ── mètriques que la UI consumeix ────────────────────────────────────────────

async def test_the_result_carries_the_metrics_the_ui_reads(tmp_path):
    node = _node(_model_dir(tmp_path))
    g = _Gen("ok", prompt_tokens=40, generation_tokens=1,
             prompt_tps=200.0, generation_tps=25.0, peak_memory=1.5)

    with g:
        result = await node.execute({
            "system": "",
            "messages": [{"role": "user", "content": "hola"}],
            "stream_callback": g.collect,
        })

    for key in ("tokens", "prompt_tokens", "tokens_per_second", "prefix_reuse",
                "cached_tokens", "actual_prefill_tokens", "reuse_ratio",
                "peak_memory_mb", "prompt_tps", "continuable", "finish_reason"):
        assert key in result, f"falta la mètrica {key!r}"
    assert isinstance(result["prefix_reuse"], bool)


async def test_the_first_turn_reuses_no_prefix(tmp_path):
    node = _node(_model_dir(tmp_path))
    g = _Gen("ok")

    with g:
        result = await node.execute({
            "system": "",
            "messages": [{"role": "user", "content": "hola"}],
            "stream_callback": g.collect,
        })

    assert result["prefix_reuse"] is False
    assert result["cached_tokens"] == 0
    assert result["reuse_ratio"] == 1.0


# ── generació sense streaming ────────────────────────────────────────────────

async def test_a_turn_without_a_callback_still_returns_the_text(tmp_path):
    node = _node(_model_dir(tmp_path))
    g = _Gen("sense streaming")

    with g:
        result = await node.execute({
            "system": "",
            "messages": [{"role": "user", "content": "hola"}],
        })

    assert result["response"] == "sense streaming"
    assert g.deltas == [], "sense callback no s'ha d'emetre res"


# ── errors ───────────────────────────────────────────────────────────────────

async def test_a_generation_failure_propagates(tmp_path):
    """Un error del motor no s'empassa: la ruta ha de poder-lo veure."""
    node = _node(_model_dir(tmp_path))

    def _boom(*a, **k):
        raise RuntimeError("el motor ha petat")

    with patch("mlx_lm.stream_generate", _boom), \
         patch("mlx_lm.sample_utils.make_sampler", lambda **k: "S"), \
         patch("mlx_lm.models.cache.make_prompt_cache", lambda *a, **k: []):
        with pytest.raises(RuntimeError, match="el motor ha petat"):
            await node.execute({
                "system": "",
                "messages": [{"role": "user", "content": "hola"}],
            })
