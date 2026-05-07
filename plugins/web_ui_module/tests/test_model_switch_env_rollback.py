"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/tests/test_model_switch_env_rollback.py
Description: Regression guard P0-3 env rollback — `NEXE_MLX_MODEL` i
             `NEXE_LLAMA_CPP_MODEL` s'han de restaurar al seu estat
             anterior després que el selector de model del UI els muti
             per construir un `from_env()`. Sense rollback, requests
             posteriors sense `body.model` heretarien el valor mutat.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import os

import pytest

# Aquests tests no cal que carreguin tot l'stack FastAPI — exerciten
# la seqüència try/finally que envolta la mutació de `os.environ`
# dins routes_chat.py. Aplanem el patró a una funció helper que
# reprodueix la mateixa lògica; qualsevol canvi a `routes_chat.py`
# que trenqui el rollback s'ha de detectar amb un grep guard.


def _switch_with_rollback(env_var: str, new_value: str) -> str:
    """Replica del patró try/finally de `routes_chat.py` (P0-3 fix)."""
    prev = os.environ.get(env_var)
    try:
        os.environ[env_var] = new_value
        current = os.environ[env_var]
    finally:
        if prev is None:
            os.environ.pop(env_var, None)
        else:
            os.environ[env_var] = prev
    return current


class TestRollback:

    def test_unset_before_stays_unset_after(self, monkeypatch):
        monkeypatch.delenv("NEXE_MLX_MODEL", raising=False)
        _switch_with_rollback("NEXE_MLX_MODEL", "/tmp/new-model")  # nosemgrep
        assert "NEXE_MLX_MODEL" not in os.environ

    def test_set_before_keeps_original_after(self, monkeypatch):
        monkeypatch.setenv("NEXE_MLX_MODEL", "/tmp/original")  # nosemgrep
        _switch_with_rollback("NEXE_MLX_MODEL", "/tmp/new-model")  # nosemgrep
        assert os.environ["NEXE_MLX_MODEL"] == "/tmp/original"  # nosemgrep

    def test_value_is_read_inside_the_window(self, monkeypatch):
        """El consumidor (ex. MLXConfig.from_env) llegeix el valor mutat."""
        monkeypatch.delenv("NEXE_MLX_MODEL", raising=False)
        value_seen = _switch_with_rollback("NEXE_MLX_MODEL", "/tmp/new-model")  # nosemgrep
        assert value_seen == "/tmp/new-model"  # nosemgrep

    def test_rollback_even_if_consumer_raises(self, monkeypatch):
        """Excepció dins el bloc try no ha de trencar el rollback."""
        monkeypatch.setenv("NEXE_LLAMA_CPP_MODEL", "/tmp/original")  # nosemgrep

        prev = os.environ.get("NEXE_LLAMA_CPP_MODEL")
        with pytest.raises(RuntimeError):
            try:
                os.environ["NEXE_LLAMA_CPP_MODEL"] = "/tmp/new"  # nosemgrep
                raise RuntimeError("consumer failed")
            finally:
                if prev is None:
                    os.environ.pop("NEXE_LLAMA_CPP_MODEL", None)
                else:
                    os.environ["NEXE_LLAMA_CPP_MODEL"] = prev

        assert os.environ["NEXE_LLAMA_CPP_MODEL"] == "/tmp/original"  # nosemgrep


class TestSourceGuard:
    """Regression grep guard — el fitxer routes_chat.py ha de tenir els
    rollbacks explícits perquè el patró `_switch_with_rollback` aquí
    només és una còpia didàctica."""

    def test_routes_chat_has_mlx_rollback(self):
        from pathlib import Path
        src = Path(__file__).resolve().parents[1] / "api" / "routes_chat.py"
        content = src.read_text(encoding="utf-8")
        # Busquem els dos marcadors que garanteixen el try/finally P0-3.
        assert "_prev_mlx" in content, "MLX env rollback absent a routes_chat.py"
        assert "_prev_llama" in content, "LLAMA env rollback absent a routes_chat.py"
        assert 'os.environ.pop("NEXE_MLX_MODEL"' in content
        assert 'os.environ.pop("NEXE_LLAMA_CPP_MODEL"' in content
