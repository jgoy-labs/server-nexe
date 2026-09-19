"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/files/__init__.py
Description: Uploaded documents in the core — attach the session-neutral body
             and the process-wide FileHandler that backs it.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from core.files.attach import attach_file_handler
from core.files.handler import FileHandler

__all__ = [
    "FileHandler",
    "attach_file_handler",
]
