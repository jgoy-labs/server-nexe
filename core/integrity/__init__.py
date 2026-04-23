"""Integrity helpers shared between installer, memory and runtime.

The public surface lives in :mod:`core.integrity.hashing`. See that module
for SHA256 helpers, the ``verify_sha256`` policy entry point and the
:class:`HashMismatchError` used across the installer to abort on
supply-chain mismatches.
"""

from core.integrity.hashing import (
    HashMismatchError,
    sha256_of_bytes,
    sha256_of_dir,
    sha256_of_file,
    sha256_stream_download,
    verify_sha256,
)

__all__ = [
    "HashMismatchError",
    "sha256_of_bytes",
    "sha256_of_dir",
    "sha256_of_file",
    "sha256_stream_download",
    "verify_sha256",
]
