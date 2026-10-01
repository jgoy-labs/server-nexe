"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: tests/plugins/llama_cpp_module/test_f982_max_tokens_is_configurable.py
Description: #982 — llama.cpp's reply ceiling was the literal 2048 repeated at
    four call sites with no way to raise it, while MLX had
    NEXE_MLX_MAX_TOKENS. A reasoning model can spend that whole ceiling before
    answering (#984), and llama.cpp offers no way to turn reasoning off, so an
    operator needs at least this lever. The default is unchanged.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from plugins.llama_cpp_module.core.config import LlamaCppConfig


def test_the_default_ceiling_is_unchanged(monkeypatch):
    """2048 stays the default: this adds a lever, it does not move behaviour."""
    monkeypatch.delenv("NEXE_LLAMA_CPP_MAX_TOKENS", raising=False)
    assert LlamaCppConfig.from_env().max_tokens == 2048


def test_the_env_var_raises_the_ceiling(monkeypatch):
    monkeypatch.setenv("NEXE_LLAMA_CPP_MAX_TOKENS", "8192")
    assert LlamaCppConfig.from_env().max_tokens == 8192


def test_the_generators_read_the_config_not_a_literal():
    """Every generation goes through `_sampling`, which reads the config.

    The four paths (text, text stream, vision, vision stream) each had their
    own `else 2048`. #1107 added the two resume paths. A lever that only
    reaches some of them is worse than none. The ceiling is written once;
    each call spreads that dict.
    """
    from pathlib import Path

    source = Path("plugins/llama_cpp_module/core/chat.py").read_text(encoding="utf-8")
    assert "else 2048" not in source, "a hardcoded ceiling is back in chat.py"
    assert source.count("else self.config.max_tokens") == 1
    assert source.count("**self._sampling(") == 6
