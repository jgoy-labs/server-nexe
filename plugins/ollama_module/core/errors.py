"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/ollama_module/core/errors.py
Description: Ollama semantic exceptions (Bug 15).
             4xx errors (404 model, 400 bad request, 422 validation) must NOT
             open the circuit breaker. Only 5xx + connection errors should.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""


class OllamaSemanticError(Exception):
    """Base class for Ollama semantic errors (4xx non-infrastructure)."""

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


class ModelNotFoundError(OllamaSemanticError):
    """The requested model does not exist in the Ollama instance (HTTP 404)."""

    def __init__(self, model_name: str, message: str = None):  # type: ignore[assignment]  # no_implicit_optional
        self.model_name = model_name
        super().__init__(
            message or f"Ollama model not found: {model_name}",
            status_code=404,
        )


def is_semantic_http_error(exc: BaseException, httpx_module) -> bool:
    """Returns True if the exception is a semantic 4xx error (non-infra) that should NOT
    open the circuit breaker. 5xx and connection errors do open it.

    `httpx_module` is injected because tests patch httpx on the parent module
    (plugins.ollama_module.module.httpx).
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
