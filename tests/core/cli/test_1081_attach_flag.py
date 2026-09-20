"""`nexe chat --attach <path>` (#1081): repoint an existing upload path.

`upload_file` (`core/cli/utils/api_client.py`) and the interactive `/upload
<path>` command have always existed; the only thing missing was a flag to
attach a file WITHOUT entering interactive mode first. `_upload_attachment`
is the shared helper `/upload` and `--attach` both call — one upload path,
not two.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.cli.chat_cli import _upload_attachment


# ── _upload_attachment: the shared helper ────────────────────────────────────

class TestUploadAttachment:

    async def test_missing_file_is_reported_and_returns_false(self, tmp_path):
        client = MagicMock()
        client.upload_file = AsyncMock()
        ok = await _upload_attachment(str(tmp_path / "does-not-exist.txt"), client, "sess-1")
        assert ok is False
        client.upload_file.assert_not_called()

    async def test_successful_upload_calls_the_client_and_returns_true(self, tmp_path):
        f = tmp_path / "informe.txt"
        f.write_text("contingut")
        client = MagicMock()
        client.upload_file = AsyncMock(return_value={"chunks": 3})

        ok = await _upload_attachment(str(f), client, "sess-1")

        assert ok is True
        client.upload_file.assert_awaited_once_with(str(f), "sess-1")

    async def test_server_rejecting_the_upload_returns_false(self, tmp_path):
        f = tmp_path / "informe.pdf"
        f.write_text("contingut")
        client = MagicMock()
        client.upload_file = AsyncMock(return_value=None)

        ok = await _upload_attachment(str(f), client, "sess-1")

        assert ok is False

    async def test_client_exception_is_caught_and_returns_false(self, tmp_path):
        f = tmp_path / "informe.txt"
        f.write_text("contingut")
        client = MagicMock()
        client.upload_file = AsyncMock(side_effect=RuntimeError("network down"))

        ok = await _upload_attachment(str(f), client, "sess-1")

        assert ok is False


# ── --attach wiring: uploaded before the interactive loop starts ────────────

class TestChatAsyncAttachFlag:

    def _client_double(self) -> MagicMock:
        client = MagicMock()
        client.is_server_running = AsyncMock(return_value=True)
        client.create_ui_session = AsyncMock(return_value="sess-1")
        client.upload_file = AsyncMock(return_value={"chunks": 1})
        return client

    async def test_attach_uploads_before_the_prompt_loop(self, tmp_path):
        from core.cli.chat_cli import _chat_async

        f = tmp_path / "informe.txt"
        f.write_text("contingut")
        client = self._client_double()

        with (
            patch("core.cli.utils.api_client.NexeAPIClient", return_value=client),
            patch("core.cli.chat_cli._chat_resolve_actual_engine", new=AsyncMock(return_value="ollama")),
            patch("click.prompt", side_effect=KeyboardInterrupt),
        ):
            await _chat_async(
                engine="ollama", system=None, no_rag=False, model="m",
                attach=str(f),
            )

        client.upload_file.assert_awaited_once_with(str(f), "sess-1")

    async def test_no_attach_means_no_upload_call(self, tmp_path):
        from core.cli.chat_cli import _chat_async

        client = self._client_double()

        with (
            patch("core.cli.utils.api_client.NexeAPIClient", return_value=client),
            patch("core.cli.chat_cli._chat_resolve_actual_engine", new=AsyncMock(return_value="ollama")),
            patch("click.prompt", side_effect=KeyboardInterrupt),
        ):
            await _chat_async(
                engine="ollama", system=None, no_rag=False, model="m",
                attach=None,
            )

        client.upload_file.assert_not_called()
