"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: core/endpoints/chat_schemas.py
Description: Pydantic schemas for Chat endpoint.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional


class Message(BaseModel):
    role: str
    content: str

    model_config = ConfigDict(protected_namespaces=())

class ChatCompletionRequest(BaseModel):
    messages: List[Message] = Field(..., min_length=1)
    model: Optional[str] = None
    engine: Optional[str] = "auto"
    stream: bool = False
    use_rag: bool = True  # RAG enabled by default - searches nexe_documentation + nexe_chat_memory
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)  # Validated range
    max_tokens: Optional[int] = Field(default=None, ge=1, le=32000)  # Prevent DoS via huge values

    model_config = ConfigDict(protected_namespaces=())
