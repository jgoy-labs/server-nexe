"""
────────────────────────────────────
Server Nexe
Location: tests/test_crypto_keys_chmod_warning.py
Description: Verify chmod failure on the master-key parent directory logs a
WARNING instead of being silently swallowed.
────────────────────────────────────

Before the fix, `path.parent.chmod(stat.S_IRWXU)` was wrapped in a
try/except that did nothing but `pass`. A permission or filesystem
failure (noexec mount, ACL-restricted filesystem, etc.) left the key
directory with broader-than-intended permissions and NO trace in logs.
After the fix, every chmod failure emits a WARNING with the path and
the underlying exception so operators can see it.
"""

import logging
import stat
from pathlib import Path
from unittest.mock import patch

from core.crypto import keys as crypto_keys


def test_chmod_parent_failure_logs_warning(tmp_path: Path, caplog) -> None:
  """When `path.parent.chmod` raises, a WARNING is emitted and the
  function still succeeds (the file itself is still created 0o600)."""
  key_path = tmp_path / "master.key"
  key = b"\x09" * crypto_keys.KEY_SIZE

  real_chmod = Path.chmod

  def fake_chmod(self: Path, mode: int) -> None:
    if self == tmp_path and mode == stat.S_IRWXU:
      raise PermissionError("simulated noexec mount")
    real_chmod(self, mode)

  with caplog.at_level(logging.WARNING, logger=crypto_keys.__name__):
    with patch.object(Path, "chmod", autospec=True, side_effect=fake_chmod):
      ok = crypto_keys._try_file_set(key, path=key_path)

  assert ok is True, "key write must still succeed even if parent chmod fails"
  assert key_path.exists()
  # The file itself is created via os.open with mode 0o600, not via Path.chmod,
  # so the file permissions are still tight despite the parent chmod failure.
  mode = stat.S_IMODE(key_path.stat().st_mode)
  assert mode == 0o600

  warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
  assert warnings, "expected at least one WARNING log record on chmod failure"
  msg = warnings[0].getMessage()
  assert "chmod" in msg.lower()
  assert str(tmp_path) in msg
  assert "simulated noexec mount" in msg


def test_chmod_parent_success_no_warning(tmp_path: Path, caplog) -> None:
  """When `path.parent.chmod` succeeds, no WARNING is emitted."""
  key_path = tmp_path / "master.key"
  key = b"\x0a" * crypto_keys.KEY_SIZE

  with caplog.at_level(logging.WARNING, logger=crypto_keys.__name__):
    ok = crypto_keys._try_file_set(key, path=key_path)

  assert ok is True
  warnings = [
    r for r in caplog.records
    if r.levelno == logging.WARNING and "chmod" in r.getMessage().lower()
  ]
  assert not warnings, f"unexpected chmod warning: {warnings}"
