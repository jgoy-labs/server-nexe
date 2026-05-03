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
    # MD5 used as a non-cryptographic cache key (8-char prefix for inference
    # prefix-cache lookup), not for authentication or integrity. usedforsecurity=False
    # also makes this safe under FIPS-only Python builds.
    return hashlib.md5(normalized.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
