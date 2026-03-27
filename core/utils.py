import hashlib


def compute_system_hash(system: str) -> str:
    """
    Compute an 8-character hash for the system prompt.
    Used for prefix caching in inference engines.
    """
    if not system:
        return "empty"
    
    # Normalize (optional but recommended to avoid mismatches due to whitespace)
    normalized = system.strip()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:8]
