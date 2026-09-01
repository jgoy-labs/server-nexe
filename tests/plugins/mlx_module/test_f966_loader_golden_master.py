"""Golden master del cúmul de CÀRREGA de model — #966, Tros B.

Mateixa regla que el golden master del camí VLM: **aquest fitxer no es toca durant el
refactor**. S'escriu contra el codi actual, ha de ser verd ABANS de moure res, i verd
DESPRÉS sense editar-ne una coma.

Aquest cobreix `_get_model` i la seva política: el guard de RAM, la detecció de VLM i les
tres branques de càrrega. Dues de les funcions que fixa —`_ram_guard_mode` i
`_memory_snapshot_gb`— **no tenien cap test** abans d'aquest fitxer, i `_ram_guard_mode`
és justament la que decideix si el guard refusa o només avisa.

DISSENY: no es patxeja **cap símbol intern**. Totes les palanques són externes o de disc:
  · `psutil.virtual_memory`                       (llibreria externa)
  · `...core.config.model_weights_gb` / `..._kv_bytes_per_token`  (mòdul germà, no es mou)
  · `mlx_lm.load` / `mlx_vlm.load`                (llibreries externes)
  · `sys.modules["torch"] = None`                 (stdlib: fa fallar `import torch`)
  · directoris temporals amb `config.json` REAL   (la detecció de VLM llegeix del disc)
  · variables d'entorn                            (`NEXE_MLX_RAM_GUARD`, `NEXE_LANG`)

Per això sobreviu al moviment allà on el cos acabi vivint: no sap on és.
"""
import json
import logging
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

CONFIG_MOD = "plugins.mlx_module.core.config"
GB = 1024 ** 3


# ── utillatge ────────────────────────────────────────────────────────────────

def _model_dir(tmp_path, *, vlm: bool):
    """Un directori de model REAL: la detecció de VLM llegeix aquest config.json."""
    d = tmp_path / ("vlm-model" if vlm else "text-model")
    d.mkdir()
    config = {"model_type": "qwen3", "architectures": ["Qwen3ForCausalLM"]}
    if vlm:
        config["vision_config"] = {"hidden_size": 1152}
        config["architectures"] = ["Qwen3VLForConditionalGeneration"]
    (d / "config.json").write_text(json.dumps(config))
    return str(d)


def _node(model_path, max_kv_size=4096):
    from plugins.mlx_module.core.chat import MLXChatNode
    from plugins.mlx_module.core.config import MLXConfig

    cfg = MLXConfig(model_path=model_path)
    cfg.max_kv_size = max_kv_size
    cfg.max_tokens = 64
    node = MLXChatNode.__new__(MLXChatNode)
    node.config = cfg
    return node


def _vm(total_gb, available_gb):
    return SimpleNamespace(
        total=total_gb * GB, available=available_gb * GB, free=1 * GB,
        active=1 * GB, inactive=1 * GB, wired=1 * GB,
    )


class _Loads:
    """Captura quina llibreria carrega, sense patxejar res nostre."""

    def __init__(self):
        self.text, self.vlm = [], []

    def _text(self, path):
        self.text.append(path)
        return ("MODEL-TEXT", "TOK-TEXT")

    def _vlm(self, path):
        self.vlm.append(path)
        return ("MODEL-VLM", "PROC-VLM")

    def __enter__(self):
        self._c = [patch("mlx_lm.load", self._text), patch("mlx_vlm.load", self._vlm)]
        for c in self._c:
            c.__enter__()
        return self

    def __exit__(self, *e):
        for c in reversed(self._c):
            c.__exit__(*e)
        return False


def _ram(weights_gb, bpt=256 * 1024):
    """Fixa l'estimació al mòdul germà `config` (que no es mou)."""
    return [
        patch(f"{CONFIG_MOD}.model_weights_gb", return_value=weights_gb),
        patch(f"{CONFIG_MOD}.model_kv_bytes_per_token", return_value=bpt),
    ]


class _Ram:
    def __init__(self, weights_gb, total_gb, available_gb, bpt=256 * 1024):
        self._c = _ram(weights_gb, bpt) + [
            patch("psutil.virtual_memory", return_value=_vm(total_gb, available_gb))
        ]

    def __enter__(self):
        for c in self._c:
            c.__enter__()
        return self

    def __exit__(self, *e):
        for c in reversed(self._c):
            c.__exit__(*e)
        return False


@pytest.fixture(autouse=True)
def _clean_singletons():
    from plugins.mlx_module.core.chat import MLXChatNode

    def reset():
        MLXChatNode._model = None
        MLXChatNode._tokenizer = None
        MLXChatNode._is_vlm = False
        MLXChatNode._config = None

    reset()
    yield
    reset()


@pytest.fixture(autouse=True)
def _neutral_env(monkeypatch):
    monkeypatch.delenv("NEXE_MLX_RAM_GUARD", raising=False)
    monkeypatch.delenv("NEXE_LANG", raising=False)


# ── el singleton mandrós ─────────────────────────────────────────────────────

def test_the_model_is_loaded_once_and_then_reused(tmp_path):
    node = _node(_model_dir(tmp_path, vlm=False))
    with _Ram(weights_gb=2.0, total_gb=32, available_gb=16), _Loads() as loads:
        first = node._get_model()
        second = node._get_model()

    assert first == ("MODEL-TEXT", "TOK-TEXT")
    assert second == first
    assert len(loads.text) == 1, "el model s'ha de carregar UN sol cop (singleton mandrós)"


# ── quina llibreria carrega ──────────────────────────────────────────────────

def test_a_text_model_loads_through_mlx_lm(tmp_path):
    from plugins.mlx_module.core.chat import MLXChatNode

    node = _node(_model_dir(tmp_path, vlm=False))
    with _Ram(2.0, 32, 16), _Loads() as loads:
        node._get_model()

    assert loads.text and not loads.vlm
    assert MLXChatNode._is_vlm is False


def test_a_vision_model_loads_through_mlx_vlm(tmp_path):
    from plugins.mlx_module.core.chat import MLXChatNode

    node = _node(_model_dir(tmp_path, vlm=True))
    with _Ram(2.0, 32, 16), _Loads() as loads:
        node._get_model()

    assert loads.vlm and not loads.text
    assert MLXChatNode._is_vlm is True


def test_a_vision_model_without_torch_falls_back_to_text_only(tmp_path, caplog):
    """Sense PyTorch, un model VL es carrega en mode NOMÉS TEXT, no peta."""
    from plugins.mlx_module.core.chat import MLXChatNode

    node = _node(_model_dir(tmp_path, vlm=True))
    with caplog.at_level(logging.WARNING):
        # `import torch` falla amb None a sys.modules: cap intern patxejat.
        with patch.dict(sys.modules, {"torch": None}):
            with _Ram(2.0, 32, 16), _Loads() as loads:
                node._get_model()

    assert loads.text and not loads.vlm, "ha de caure al carregador de text"
    assert MLXChatNode._is_vlm is False, "i deixar de dir que és VLM"
    assert any("text-only" in r.getMessage() for r in caplog.records)


# ── el guard de RAM: refús dur ───────────────────────────────────────────────

def test_a_model_that_cannot_physically_fit_is_refused_even_in_warn_mode(tmp_path):
    """pesos + finestra mínima > RAM TOTAL: refús, encara que el mode sigui warn."""
    node = _node(_model_dir(tmp_path, vlm=False))
    with _Ram(weights_gb=60.0, total_gb=8, available_gb=6), _Loads() as loads:
        with pytest.raises(RuntimeError) as err:
            node._get_model()

    assert not loads.text and not loads.vlm, "no s'ha d'arribar a carregar res"
    assert "MLX" in str(err.value), (
        "contracte amb routes_chat._oom_notice: el consell de canviar de motor "
        "només es manté si el text conté 'MLX'"
    )


def test_the_hard_refusal_is_suppressed_when_the_guard_is_off(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXE_MLX_RAM_GUARD", "off")
    node = _node(_model_dir(tmp_path, vlm=False))
    with _Ram(weights_gb=60.0, total_gb=8, available_gb=6), _Loads() as loads:
        node._get_model()

    assert loads.text, "amb el guard off ha de carregar igualment"


def test_no_refusal_when_the_weights_could_not_be_measured(tmp_path):
    """Una estimació de reserva no pot refusar mai: pesos=None → endavant."""
    node = _node(_model_dir(tmp_path, vlm=False))
    with _Ram(weights_gb=None, total_gb=8, available_gb=0.5), _Loads() as loads:
        node._get_model()

    assert loads.text


# ── el guard de RAM: llindar tou ─────────────────────────────────────────────

def test_strict_mode_refuses_below_the_soft_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXE_MLX_RAM_GUARD", "strict")
    node = _node(_model_dir(tmp_path, vlm=False))
    with _Ram(weights_gb=6.0, total_gb=32, available_gb=0.5), _Loads() as loads:
        with pytest.raises(RuntimeError) as err:
            node._get_model()

    assert not loads.text
    assert "MLX" in str(err.value)


def test_warn_mode_loads_anyway_below_the_soft_threshold(tmp_path, caplog):
    """El default des del 23/07: avisa i carrega — `available` no prediu res."""
    node = _node(_model_dir(tmp_path, vlm=False))
    with caplog.at_level(logging.WARNING):
        with _Ram(weights_gb=6.0, total_gb=32, available_gb=0.5), _Loads() as loads:
            node._get_model()

    assert loads.text, "warn és el default i ha de carregar igualment"
    assert any("warn" in r.getMessage() for r in caplog.records)


# ── localització dels missatges de refús ─────────────────────────────────────

@pytest.mark.parametrize(
    "lang,needle",
    [("ca", "Memòria insuficient"), ("es", "Memoria insuficiente"),
     ("en", "Not enough memory"), ("de", "Not enough memory")],
)
def test_the_hard_refusal_speaks_the_user_language(tmp_path, monkeypatch, lang, needle):
    """Un idioma desconegut cau a l'anglès, no peta."""
    monkeypatch.setenv("NEXE_LANG", lang)
    node = _node(_model_dir(tmp_path, vlm=False))
    with _Ram(weights_gb=60.0, total_gb=8, available_gb=6), _Loads():
        with pytest.raises(RuntimeError) as err:
            node._get_model()

    assert needle in str(err.value)


@pytest.mark.parametrize(
    "lang,needle",
    [("ca", "Memòria insuficient"), ("es", "Memoria insuficiente"),
     ("en", "Not enough memory")],
)
def test_the_strict_refusal_speaks_the_user_language(tmp_path, monkeypatch, lang, needle):
    monkeypatch.setenv("NEXE_MLX_RAM_GUARD", "strict")
    monkeypatch.setenv("NEXE_LANG", lang)
    node = _node(_model_dir(tmp_path, vlm=False))
    with _Ram(weights_gb=6.0, total_gb=32, available_gb=0.5), _Loads():
        with pytest.raises(RuntimeError) as err:
            node._get_model()

    assert needle in str(err.value)


# ── error d'import curat (finding 820) ───────────────────────────────────────

def test_a_broken_dependency_becomes_a_curated_message(tmp_path):
    """Un combo de dependències trencat no ha d'aflorar com AttributeError cru."""
    node = _node(_model_dir(tmp_path, vlm=False))
    with _Ram(2.0, 32, 16):
        with patch.dict(sys.modules, {"mlx_lm": None}):
            with pytest.raises(RuntimeError) as err:
                node._get_model()

    msg = str(err.value)
    assert "820" in msg or "incompatible dependency" in msg
    assert "Ollama" in msg, "ha de dir a l'usuari què fer"


# ── `_ram_guard_mode`: SENSE cap test abans d'aquest fitxer ──────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "warn"),          # default
        ("warn", "warn"),
        ("strict", "strict"),
        ("off", "off"),
        ("0", "off"),            # el que la gent escriu de debò
        ("false", "off"),
        ("no", "off"),
        ("disabled", "off"),
        ("STRICT", "strict"),    # insensible a majúscules
        ("  off  ", "off"),      # i a espais
        ("qualsevol-cosa", "warn"),   # desconegut → warn, mai off
    ],
)
def test_ram_guard_mode_parsing(monkeypatch, raw, expected):
    from plugins.mlx_module.core.chat import _ram_guard_mode

    if raw is None:
        monkeypatch.delenv("NEXE_MLX_RAM_GUARD", raising=False)
    else:
        monkeypatch.setenv("NEXE_MLX_RAM_GUARD", raw)
    assert _ram_guard_mode() == expected


def test_an_unknown_guard_mode_never_disables_the_guard(monkeypatch):
    """La propietat que importa: equivocar-se escrivint NO ha d'obrir la porta."""
    from plugins.mlx_module.core.chat import _ram_guard_mode

    for typo in ("of", "ofF!", "sctrict", "true", "1", "yes"):
        monkeypatch.setenv("NEXE_MLX_RAM_GUARD", typo)
        assert _ram_guard_mode() != "off", f"{typo!r} no pot desactivar el guard"


# ── `_memory_snapshot_gb`: SENSE cap test abans d'aquest fitxer ──────────────

def test_memory_snapshot_converts_every_field_to_gb():
    from plugins.mlx_module.core.chat import _memory_snapshot_gb

    snap = _memory_snapshot_gb(_vm(total_gb=32, available_gb=8))
    assert snap["total"] == pytest.approx(32.0)
    assert snap["available"] == pytest.approx(8.0)
    assert set(snap) == {"total", "available", "free", "active", "inactive", "wired"}


def test_memory_snapshot_never_raises_on_a_partial_psutil():
    """El diagnòstic no pot petar des de DINS del guard: camps absents → -1.0."""
    from plugins.mlx_module.core.chat import _memory_snapshot_gb

    snap = _memory_snapshot_gb(SimpleNamespace(total=8 * GB))
    assert snap["total"] == pytest.approx(8.0)
    assert snap["available"] == -1.0
    assert snap["wired"] == -1.0


def test_memory_snapshot_survives_non_numeric_fields():
    from plugins.mlx_module.core.chat import _memory_snapshot_gb

    snap = _memory_snapshot_gb(SimpleNamespace(total="molta", available=None))
    assert snap["total"] == -1.0
    assert snap["available"] == -1.0


# ── detecció de VLM, dirigida per disc real ──────────────────────────────────

def test_vision_detection_reads_the_model_config(tmp_path):
    from plugins.mlx_module.core.chat import _detect_vlm_capability

    assert _detect_vlm_capability(_model_dir(tmp_path, vlm=True)) is True
    assert _detect_vlm_capability(_model_dir(tmp_path, vlm=False)) is False


def test_vision_detection_is_false_without_a_path_or_config(tmp_path):
    from plugins.mlx_module.core.chat import _detect_vlm_capability

    assert _detect_vlm_capability("") is False
    empty = tmp_path / "buit"
    empty.mkdir()
    assert _detect_vlm_capability(str(empty)) is False
