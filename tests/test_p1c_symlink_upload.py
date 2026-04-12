"""
Tests P1-C — Symlink upload: rebutjar fitxers desats que apuntin fora del directori d'uploads.

Attack vector demostrat: ln -s /etc/passwd evil.pdf && curl -F "file=@evil.pdf"
→ ingeria 17 chunks de /etc/passwd a user_knowledge.

Fix: _is_symlink_outside_uploads() extret de upload_file, igual que
_detect_sensitive_upload (patró P1-4/P0-2.c: helper testejable directament
perquè @limiter.limit rebutja MagicMock).

NOTA: NO afecta models locals (MLX/llama.cpp/Ollama) — mai passen per /upload.

www.jgoy.net · https://server-nexe.org
"""

import os
import tempfile
from pathlib import Path

import pytest

try:
    from plugins.web_ui_module.api.routes_files import _is_symlink_outside_uploads
except ImportError:
    pytest.skip("_is_symlink_outside_uploads helper not available", allow_module_level=True)


class TestIsSymlinkOutsideUploads:
    def test_real_file_inside_dir_ok(self, tmp_path):
        """Fitxer real dins del directori d'uploads → NO rebutjat (False)."""
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        real_file = uploads / "document.pdf"
        real_file.write_bytes(b"%PDF-1.4 content here")

        assert _is_symlink_outside_uploads(real_file) is False

    def test_symlink_to_etc_passwd_rejected(self, tmp_path):
        """Symlink que apunta a /etc/passwd → REBUTJAT (True)."""
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        evil_link = uploads / "evil.pdf"
        os.symlink("/etc/passwd", evil_link)

        assert _is_symlink_outside_uploads(evil_link) is True

    def test_symlink_inside_uploads_dir_ok(self, tmp_path):
        """Symlink legítim que apunta a un altre fitxer dins del directori d'uploads → OK (False)."""
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        target = uploads / "target.txt"
        target.write_bytes(b"legitimate content")
        link = uploads / "alias.txt"
        os.symlink(target, link)

        assert _is_symlink_outside_uploads(link) is False

    def test_symlink_to_tmp_outside_uploads_rejected(self, tmp_path):
        """Symlink que apunta a un fitxer FORA del directori d'uploads → REBUTJAT."""
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        external = tmp_path / "secret.txt"
        external.write_bytes(b"sensitive data outside uploads")
        evil_link = uploads / "disguised.pdf"
        os.symlink(external, evil_link)

        assert _is_symlink_outside_uploads(evil_link) is True
