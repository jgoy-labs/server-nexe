"""
Tests P1-C — Symlink upload: reject saved files that point outside the uploads directory.

Demonstrated attack vector: ln -s /etc/passwd evil.pdf && curl -F "file=@evil.pdf"
→ ingested 17 chunks of /etc/passwd into user_knowledge.

Fix: _is_symlink_outside_uploads() extracted from upload_file, same as
_detect_sensitive_upload (pattern P1-4/P0-2.c: directly testable helper
because @limiter.limit rejects MagicMock).

NOTE: Does NOT affect local models (MLX/llama.cpp/Ollama) — they never go through /upload.

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
        """Real file inside the uploads directory → NOT rejected (False)."""
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        real_file = uploads / "document.pdf"
        real_file.write_bytes(b"%PDF-1.4 content here")

        assert _is_symlink_outside_uploads(real_file) is False

    def test_symlink_to_etc_passwd_rejected(self, tmp_path):
        """Symlink pointing to /etc/passwd → REJECTED (True)."""
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        evil_link = uploads / "evil.pdf"
        os.symlink("/etc/passwd", evil_link)  # nosemgrep

        assert _is_symlink_outside_uploads(evil_link) is True

    def test_symlink_inside_uploads_dir_ok(self, tmp_path):
        """Legitimate symlink pointing to another file inside the uploads directory → OK (False)."""
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        target = uploads / "target.txt"
        target.write_bytes(b"legitimate content")
        link = uploads / "alias.txt"
        os.symlink(target, link)

        assert _is_symlink_outside_uploads(link) is False

    def test_symlink_to_tmp_outside_uploads_rejected(self, tmp_path):
        """Symlink pointing to a file OUTSIDE the uploads directory → REJECTED."""
        uploads = tmp_path / "uploads"
        uploads.mkdir()
        external = tmp_path / "secret.txt"
        external.write_bytes(b"sensitive data outside uploads")
        evil_link = uploads / "disguised.pdf"
        os.symlink(external, evil_link)

        assert _is_symlink_outside_uploads(evil_link) is True
