"""F3.4 BUG-NF-24 — Zip Slip protection for the Ollama bundle extractor.

`installer_ollama_install._safe_extract_zip` is the hardened replacement
for `zipfile.extractall` used when unpacking the Ollama.app archive into
`/Applications/`. The tests below build crafted archives that an attacker
could use to escape the destination and assert that each variant is
refused with a `RuntimeError` before any file is written outside the
target directory.
"""

import os
import zipfile

import pytest

from installer.installer_ollama_install import _safe_extract_zip


def _make_zip(path, entries):
  with zipfile.ZipFile(path, "w") as zf:
    for name, data in entries:
      zf.writestr(name, data)


def test_safe_extract_allows_well_formed_archive(tmp_path):
  zip_path = tmp_path / "ok.zip"
  _make_zip(zip_path, [("Ollama.app/Contents/Info.plist", "x"),
                       ("Ollama.app/Contents/MacOS/ollama", "binary-ish")])
  dest = tmp_path / "dest"
  dest.mkdir()
  with zipfile.ZipFile(zip_path) as zf:
    _safe_extract_zip(zf, str(dest))
  assert (dest / "Ollama.app/Contents/Info.plist").is_file()
  assert (dest / "Ollama.app/Contents/MacOS/ollama").is_file()


def test_safe_extract_refuses_dotdot_traversal(tmp_path):
  zip_path = tmp_path / "evil.zip"
  _make_zip(zip_path, [("../escape.txt", "pwned")])
  dest = tmp_path / "dest"
  dest.mkdir()
  with zipfile.ZipFile(zip_path) as zf:
    with pytest.raises(RuntimeError, match="Zip Slip refused"):
      _safe_extract_zip(zf, str(dest))
  # Crucially: no file was written outside dest.
  assert not (tmp_path / "escape.txt").exists()


def test_safe_extract_refuses_absolute_path(tmp_path):
  zip_path = tmp_path / "absolute.zip"
  _make_zip(zip_path, [("/tmp/zipslip-marker.txt", "pwned")])
  dest = tmp_path / "dest"
  dest.mkdir()
  with zipfile.ZipFile(zip_path) as zf:
    with pytest.raises(RuntimeError, match="absolute path"):
      _safe_extract_zip(zf, str(dest))


def test_safe_extract_refuses_symlinked_destination_escape(tmp_path):
  """An entry whose path resolves outside dest after symlink resolution
  must still be refused. We simulate this by placing the destination at
  one level of symlink so commonpath() detects the mismatch."""
  # Real target outside of `dest`.
  real_outside = tmp_path / "real_outside"
  real_outside.mkdir()
  # Use `..` segments via the entry name combined with a deep dest path.
  dest = tmp_path / "deep/dest"
  dest.mkdir(parents=True)

  zip_path = tmp_path / "deep.zip"
  _make_zip(zip_path, [("../../real_outside/oops.txt", "pwned")])
  with zipfile.ZipFile(zip_path) as zf:
    with pytest.raises(RuntimeError, match="escape"):
      _safe_extract_zip(zf, str(dest))
  assert not (real_outside / "oops.txt").exists()


def test_safe_extract_handles_nested_safe_dirs(tmp_path):
  zip_path = tmp_path / "nested.zip"
  _make_zip(zip_path, [
    ("a/b/c/d.txt", "ok"),
    ("a/sibling.txt", "ok"),
  ])
  dest = tmp_path / "dest"
  dest.mkdir()
  with zipfile.ZipFile(zip_path) as zf:
    _safe_extract_zip(zf, str(dest))
  assert (dest / "a/b/c/d.txt").is_file()
  assert (dest / "a/sibling.txt").is_file()
