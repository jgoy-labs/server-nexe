import hashlib


def compute_system_hash(system: str) -> str:
    """
    Calcula un hash de 8 caràcters per al system prompt.
    Utilitzat per al prefix caching en els motors d'inferència.
    """
    if not system:
        return "empty"
    
    # Normalitzar (opcional, però recomanat per evitar fallades per espais)
    normalized = system.strip()
    return hashlib.md5(normalized.encode("utf-8")).hexdigest()[:8]
