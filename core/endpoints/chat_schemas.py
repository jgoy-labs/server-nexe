"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/endpoints/chat_schemas.py
Description: Pydantic schemas for Chat endpoint.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional


class Message(BaseModel):
    """A single message in a chat conversation (role + content).

    Pydantic anti-DoS constraints:
      - role: max_length=64 (standard short identifier, e.g. ``user``, ``assistant``, ``system``)
      - content: max_length=8000 (mirrors the existing ``validate_string_input`` guard;
        rejects oversized payloads at deserialization with HTTP 422 before reaching
        the endpoint, preventing OOM / DoS via huge bodies)
    """

    role: str = Field(..., max_length=64)
    content: str = Field(..., max_length=8000)

    model_config = ConfigDict(protected_namespaces=())

class ChatCompletionRequest(BaseModel):
    """Request body for the ``/v1/chat/completions`` endpoint.

    Pydantic anti-DoS constraints:
      - messages: max_length=100 (no real conversation needs more; prevents DoS via 1M msgs)
      - model: max_length=200 (long enough for HF-style ``org/repo-name:tag``)
      - engine: max_length=50 (``mlx``/``ollama``/``llama_cpp``/``auto``)
    """

    messages: List[Message] = Field(..., min_length=1, max_length=100)
    model: Optional[str] = Field(default=None, max_length=200)
    engine: Optional[str] = Field(default="auto", max_length=50)
    stream: bool = False
    use_rag: bool = True  # RAG enabled by default - searches nexe_documentation + personal_memory
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)  # Validated range
    top_p: Optional[float] = Field(default=None, gt=0.0, le=1.0)  # Nucleus sampling (OpenAI-compat; gt=0 excludes the degenerate empty-nucleus value that engines treat divergently)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=32000)  # Prevent DoS via huge values

    model_config = ConfigDict(protected_namespaces=())
