"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/core/errors.py
Description: Excepcions semantiques d'Ollama (Bug 15).
             Errors 4xx (404 model, 400 bad request, 422 validation) NO han
             d'obrir el circuit breaker. Nomes 5xx + errors connexio.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""


class OllamaSemanticError(Exception):
    """Base d'errors semantics Ollama (4xx no infraestructura)."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class ModelNotFoundError(OllamaSemanticError):
    """El model demanat no existeix a la instancia Ollama (HTTP 404)."""

    def __init__(self, model_name: str, message: str = None):
        self.model_name = model_name
        super().__init__(
            message or f"Ollama model not found: {model_name}",
            status_code=404,
        )


def is_semantic_http_error(exc: BaseException, httpx_module) -> bool:
    """Retorna True si l'excepcio es un error semantic 4xx (no infra) que NO
    hauria d'obrir el circuit breaker. 5xx i errors de connexio si l'obren.

    `httpx_module` s'injecta perque els tests fan patch de httpx al modul
    parent (plugins.ollama_module.module.httpx).
    """
    if httpx_module is None:
        return False
    if isinstance(exc, OllamaSemanticError):
        return True
    if isinstance(exc, httpx_module.HTTPStatusError):
        code = exc.response.status_code
        # 4xx semantics (404 model, 400 bad request, 422 validation...) -> no infra
        return 400 <= code < 500
    return False
