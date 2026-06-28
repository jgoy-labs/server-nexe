"""
Test fix B260: single node-aware source of truth for engine selection.

Before B260 the chat router (chat_engines/routing.py) and /status (endpoints/
root.py) held two divergent notions of engine availability:

  * routing._engine_available only checked dict-key presence, so a "ghost"
    module (key present, _node dead) was reported available; an explicit engine
    was dispatched without any check; and the mlx/llama_cpp forward layer fell
    back to a FIXED Ollama, skipping a live engine in the cascade.
  * /status computed a SEPARATE node-aware availability and could therefore
    disagree with what a real chat call ran (mlx dead + llama_cpp live + ollama
    live → /status said "llama_cpp", chat dispatched the ghost mlx → crashed
    into Ollama).

B260 makes routing._engine_available node-aware (the single source of truth),
routes an explicit dead engine through the graceful cascade (decision: graceful,
not 503), and /status delegates to routing._resolve_engine. These guards lock
that contract. The common single-engine case is unchanged.
"""
from unittest.mock import MagicMock, patch

from core.endpoints.chat_engines.routing import _engine_available, _resolve_engine


def _state(modules, config=None):
    app_state = MagicMock()
    app_state.modules = modules
    app_state.config = config or {}
    return app_state


def _live():
    """A module with a live backend node."""
    m = MagicMock()
    m._node = MagicMock()
    return m


def _ghost():
    """A registered-but-dead module: key present, _node is None."""
    m = MagicMock()
    m._node = None
    return m


class TestEngineAvailableNodeAware:
    def test_ghost_mlx_is_unavailable(self):
        """Key present but _node dead → unavailable (the ghost-module bug)."""
        assert _engine_available("mlx", _state({"mlx_module": _ghost()})) is False

    def test_ghost_llama_cpp_is_unavailable(self):
        assert _engine_available("llama_cpp", _state({"llama_cpp_module": _ghost()})) is False

    def test_live_mlx_is_available(self):
        assert _engine_available("mlx", _state({"mlx_module": _live()})) is True

    def test_ollama_stays_key_presence(self):
        """Ollama has no _node; presence of the key is enough."""
        assert _engine_available("ollama", _state({"ollama_module": MagicMock()})) is True


class TestResolveEngineB260:
    def test_explicit_dead_engine_cascades_not_blind_dispatch(self):
        """engine=mlx with a dead mlx node must NOT be dispatched blindly; it
        cascades to the next live engine and reports mlx as fallback_from."""
        with patch.dict("os.environ", {"NEXE_MODEL_ENGINE": "auto"}):
            engine, fallback = _resolve_engine(
                "mlx", _state({"mlx_module": _ghost(), "ollama_module": MagicMock()})
            )
        assert engine == "ollama"
        assert fallback == "mlx"

    def test_explicit_dead_engine_prefers_cascade_order_over_ollama(self):
        """The crux of B260: mlx dead + llama_cpp live + ollama live, asking for
        mlx, must serve llama_cpp (cascade order), NOT jump straight to Ollama."""
        with patch.dict("os.environ", {"NEXE_MODEL_ENGINE": "auto"}):
            engine, fallback = _resolve_engine(
                "mlx",
                _state({
                    "mlx_module": _ghost(),
                    "llama_cpp_module": _live(),
                    "ollama_module": MagicMock(),
                }),
            )
        assert engine == "llama_cpp"
        assert fallback == "mlx"

    def test_auto_ghost_module_skips_to_live_engine_not_ollama(self):
        """auto with mlx dead + llama_cpp live + ollama live resolves llama_cpp,
        not ollama. The chat path used to dispatch the ghost mlx and fall to the
        fixed Ollama fallback, silently skipping the live llama_cpp."""
        with patch.dict("os.environ", {"NEXE_MODEL_ENGINE": "auto"}):
            engine, fallback = _resolve_engine(
                None,
                _state({
                    "mlx_module": _ghost(),
                    "llama_cpp_module": _live(),
                    "ollama_module": MagicMock(),
                }),
            )
        assert engine == "llama_cpp"
        assert fallback is None

    def test_live_explicit_engine_unchanged(self):
        """A live explicit engine is still used directly: no behavioural change
        for the common single-engine case (Jordi: the multi-engine case is rare,
        keep the fix minimal)."""
        with patch.dict("os.environ", {"NEXE_MODEL_ENGINE": "auto"}):
            engine, fallback = _resolve_engine(
                "mlx", _state({"mlx_module": _live(), "ollama_module": MagicMock()})
            )
        assert engine == "mlx"
        assert fallback is None

    def test_explicit_ollama_nothing_loaded_no_self_fallback(self):
        """engine=ollama with nothing loaded resolves to the ollama terminal with
        no self-fallback (fallback_from stays None — no real switch happened)."""
        with patch.dict("os.environ", {"NEXE_MODEL_ENGINE": "auto"}):
            engine, fallback = _resolve_engine("ollama", _state({}))
        assert engine == "ollama"
        assert fallback is None

    def test_explicit_dead_engine_terminal_still_reports_fallback(self):
        """engine=mlx dead with NOTHING else live (not even ollama, e.g. minimal
        mode) lands on the ollama terminal but STILL reports fallback_from='mlx' —
        the switch is real and must stay observable (X-Nexe-Fallback-From)."""
        with patch.dict("os.environ", {"NEXE_MODEL_ENGINE": "auto"}):
            engine, fallback = _resolve_engine("mlx", _state({"mlx_module": _ghost()}))
        assert engine == "ollama"
        assert fallback == "mlx"
