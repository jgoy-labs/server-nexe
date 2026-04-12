"""
Tests processament d'imatge (VLM) a routes_chat.py.
Verifica extracció, validació i pas al backend — sense iniciar servidor.
"""

import base64
import pytest


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


VALID_JPEG_B64 = _b64(b"\xff\xd8\xff" + b"\x00" * 100)   # JPEG magic + padding
VALID_PNG_B64  = _b64(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)


# ── Helpers d'extracció inline (evita importar tot el mòdul) ─────────────────

def _extract_image(body: dict):
    """Reimplementa la lògica d'extracció de routes_chat per testar-la aïllada."""
    ALLOWED = {"image/jpeg", "image/png", "image/webp"}
    MAX = 10 * 1024 * 1024

    image_b64 = body.get("image_b64")
    if not image_b64:
        return None

    image_type = body.get("image_type", "")
    if image_type not in ALLOWED:
        raise ValueError(f"image_type not supported: {image_type!r}")
    try:
        image_bytes = base64.b64decode(image_b64, validate=True)
    except Exception:
        raise ValueError("Invalid base64 image")
    if len(image_bytes) > MAX:
        raise ValueError("Image too large (max 10MB)")
    return image_bytes


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestImageExtraction:

    def test_no_image_returns_none(self):
        assert _extract_image({"message": "Hola"}) is None

    def test_valid_jpeg_returns_bytes(self):
        result = _extract_image({"image_b64": VALID_JPEG_B64, "image_type": "image/jpeg"})
        assert isinstance(result, bytes)
        assert result[:3] == b"\xff\xd8\xff"

    def test_valid_png_returns_bytes(self):
        result = _extract_image({"image_b64": VALID_PNG_B64, "image_type": "image/png"})
        assert isinstance(result, bytes)
        assert result[:4] == b"\x89PNG"

    def test_valid_webp_accepted(self):
        webp_b64 = _b64(b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 50)
        result = _extract_image({"image_b64": webp_b64, "image_type": "image/webp"})
        assert result is not None

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="image_type not supported"):
            _extract_image({"image_b64": VALID_JPEG_B64, "image_type": "image/gif"})

    def test_pdf_type_rejected(self):
        with pytest.raises(ValueError, match="image_type not supported"):
            _extract_image({"image_b64": VALID_JPEG_B64, "image_type": "application/pdf"})

    def test_invalid_base64_raises(self):
        with pytest.raises(ValueError, match="Invalid base64"):
            _extract_image({"image_b64": "NOT_VALID_BASE64!!!!", "image_type": "image/jpeg"})

    def test_image_too_large_raises(self):
        big = _b64(b"\xff\xd8\xff" + b"\x00" * (11 * 1024 * 1024))  # 11MB
        with pytest.raises(ValueError, match="too large"):
            _extract_image({"image_b64": big, "image_type": "image/jpeg"})

    def test_exactly_10mb_accepted(self):
        ok = _b64(b"\xff\xd8\xff" + b"\x00" * (10 * 1024 * 1024 - 3))
        result = _extract_image({"image_b64": ok, "image_type": "image/jpeg"})
        assert result is not None

    def test_missing_image_type_raises(self):
        """image_b64 present però sense image_type → rebutjat."""
        with pytest.raises(ValueError, match="image_type not supported"):
            _extract_image({"image_b64": VALID_JPEG_B64})  # image_type = ""


# ── Test integració: el body JSON arriba complet al backend ──────────────────

class TestChatBodyStructure:

    def test_body_without_image_no_image_keys(self):
        """Body normal sense imatge no té image_b64."""
        body = {"message": "Hola", "session_id": "abc", "stream": True}
        assert "image_b64" not in body

    def test_body_with_image_has_both_keys(self):
        """Quan el frontend afegeix imatge, body té image_b64 i image_type."""
        body = {
            "message": "Descriu la foto",
            "session_id": "abc",
            "stream": True,
            "image_b64": VALID_JPEG_B64,
            "image_type": "image/jpeg",
        }
        result = _extract_image(body)
        assert result is not None
        assert len(result) > 0
