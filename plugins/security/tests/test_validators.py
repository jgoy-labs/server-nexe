"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/security/tests/test_validators.py
Description: Tests per validate_safe_path, validate_command, validate_filename, validate_api_endpoint_path.

www.jgoy.net
────────────────────────────────────
"""

import pytest
import tempfile
from pathlib import Path
from fastapi import HTTPException

from plugins.security.core.validators import (
    validate_safe_path,
    validate_command,
    validate_filename,
    validate_api_endpoint_path,
)


class TestValidateSafePath:
    """Tests per validate_safe_path."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.base = Path(self.tmpdir)

    def test_valid_path_returns_resolved(self):
        target = self.base / "valid.txt"
        target.write_text("content")
        result = validate_safe_path(target, self.base)
        assert result == target.resolve()

    def test_path_traversal_raises_400(self):
        traversal = self.base / ".." / "etc" / "passwd"
        with pytest.raises(HTTPException) as exc:
            validate_safe_path(traversal, self.base)
        assert exc.value.status_code == 400

    def test_nonexistent_file_raises_404(self):
        missing = self.base / "doesnotexist.txt"
        with pytest.raises(HTTPException) as exc:
            validate_safe_path(missing, self.base)
        assert exc.value.status_code == 404

    def test_directory_raises_400(self):
        subdir = self.base / "subdir"
        subdir.mkdir()
        with pytest.raises(HTTPException) as exc:
            validate_safe_path(subdir, self.base)
        assert exc.value.status_code == 400

    def test_nested_valid_path(self):
        subdir = self.base / "sub"
        subdir.mkdir()
        target = subdir / "file.txt"
        target.write_text("hello")
        result = validate_safe_path(target, self.base)
        assert result.exists()


class TestValidateCommand:
    """Tests per validate_command."""

    def test_valid_command_returns_parts(self):
        result = validate_command("ls -la", allowed_commands=["ls"])
        assert result == ["ls", "-la"]

    def test_command_not_in_whitelist_raises_403(self):
        with pytest.raises(HTTPException) as exc:
            validate_command("rm -rf /", allowed_commands=["ls", "cat"])
        assert exc.value.status_code == 403

    def test_empty_command_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            validate_command("", allowed_commands=["ls"])
        assert exc.value.status_code == 400

    def test_invalid_shell_format_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            validate_command("cmd 'unclosed quote", allowed_commands=["cmd"])
        assert exc.value.status_code == 400

    def test_command_with_args_and_flags(self):
        result = validate_command("cat -n file.txt", allowed_commands=["cat"])
        assert result[0] == "cat"
        assert len(result) == 3

    def test_single_word_command(self):
        result = validate_command("pwd", allowed_commands=["pwd"])
        assert result == ["pwd"]


class TestValidateFilename:
    """Tests per validate_filename."""

    def test_valid_filename(self):
        result = validate_filename("document.pdf")
        assert result == "document.pdf"

    def test_path_traversal_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            validate_filename("../etc/passwd")
        assert exc.value.status_code == 400

    def test_absolute_path_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            validate_filename("/etc/passwd")
        assert exc.value.status_code == 400

    def test_home_expansion_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            validate_filename("~/secrets")
        assert exc.value.status_code == 400

    def test_null_byte_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            validate_filename("file\x00.txt")
        assert exc.value.status_code == 400

    def test_semicolon_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            validate_filename("file;rm -rf /")
        assert exc.value.status_code == 400

    def test_pipe_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            validate_filename("file|cmd")
        assert exc.value.status_code == 400

    def test_backtick_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            validate_filename("file`cmd`")
        assert exc.value.status_code == 400

    def test_dollar_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            validate_filename("file$var")
        assert exc.value.status_code == 400

    def test_newline_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            validate_filename("file\nname")
        assert exc.value.status_code == 400

    def test_too_long_filename_raises_400(self):
        long_name = "a" * 256
        with pytest.raises(HTTPException) as exc:
            validate_filename(long_name)
        assert exc.value.status_code == 400

    def test_exactly_255_chars_is_valid(self):
        name = "a" * 255
        result = validate_filename(name)
        assert result == name

    def test_filename_with_spaces_is_valid(self):
        result = validate_filename("my document.pdf")
        assert result == "my document.pdf"

    def test_filename_with_dots_is_valid(self):
        result = validate_filename("file.v2.tar.gz")
        assert result == "file.v2.tar.gz"


class TestValidateApiEndpointPath:
    """Tests per validate_api_endpoint_path."""

    def test_valid_prefix_returns_path(self):
        result = validate_api_endpoint_path("/security/report", ["/security"])
        assert result == "/security/report"

    def test_path_not_in_prefixes_raises_403(self):
        with pytest.raises(HTTPException) as exc:
            validate_api_endpoint_path("/admin/config", ["/security", "/health"])
        assert exc.value.status_code == 403

    def test_multiple_prefixes(self):
        result = validate_api_endpoint_path("/health", ["/security", "/health", "/metrics"])
        assert result == "/health"

    def test_path_stripped_of_whitespace(self):
        result = validate_api_endpoint_path("  /security/info  ", ["/security"])
        assert result == "/security/info"

    def test_exact_prefix_match(self):
        result = validate_api_endpoint_path("/v1/chat", ["/v1"])
        assert result == "/v1/chat"
