"""
────────────────────────────────────
Server Nexe
Location: tests/fixos/test_B204.py
Description: TDD fix for B204 — top_p documentat com suportat pero absent de l'esquema Pydantic.
────────────────────────────────────
"""

import pytest
from pydantic import ValidationError


def _build_request(**kwargs):
    from core.endpoints.chat_schemas import ChatCompletionRequest
    return ChatCompletionRequest(
        messages=[{"role": "user", "content": "hola"}],
        **kwargs,
    )


def test_top_p_accepted_without_error():
    """B204: enviar top_p=0.9 no ha de llançar ValidationError ni ser ignorat (extra=ignore)."""
    req = _build_request(top_p=0.9)
    assert req.top_p == 0.9, "B204: top_p ha de ser accessible com a camp del model"


def test_top_p_none_by_default():
    """B204: top_p opcional — ha de ser None si no s'envia."""
    req = _build_request()
    assert req.top_p is None, "B204: top_p per defecte ha de ser None"


def test_top_p_below_zero_raises():
    """B204: top_p < 0.0 ha de llançar ValidationError (ge=0.0)."""
    with pytest.raises(ValidationError):
        _build_request(top_p=-0.1)


def test_top_p_above_one_raises():
    """B204: top_p > 1.0 ha de llançar ValidationError (le=1.0)."""
    with pytest.raises(ValidationError):
        _build_request(top_p=1.1)
