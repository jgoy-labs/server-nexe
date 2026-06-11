"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/log_redact.py
Description: Redaction helper for user content in logs (MC-109/110/111).
    Chat messages, memory facts and recall queries were logged in plain at
    INFO — on disk, unencrypted — which voids the at-rest encryption promise.
    INFO logs get a length + fingerprint instead; the plain content is only
    logged with the explicit NEXE_LOG_SENSITIVE=1 opt-in (local debugging).

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import hashlib
import os


def redact_user_content(text) -> str:
    """Return a log-safe representation of user content.

    INFO-level logs must never contain the user's words: the sidecar log
    lives in plain on disk next to the SQLCipher-encrypted stores (RT-05
    confirmed the same content readable in sidecar-stdout.log). The
    fingerprint (length + sha prefix) keeps log lines correlatable for
    debugging without persisting the content itself.
    """
    if os.environ.get("NEXE_LOG_SENSITIVE") == "1":
        return str(text)
    if not text:
        return "<empty>"
    text = str(text)
    digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:8]
    return f"<redacted len={len(text)} sha={digest}>"
