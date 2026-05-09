"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: plugins/web_ui_module/core/rag_handler.py
Description: RAG functions for the web_ui module.
             Extracted from manifest.py during normalization.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import inspect
import logging
import os as _os
import re as _re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def generate_rag_metadata(body_content: str, filename: str) -> dict:
    """
    Uses the LLM to generate an abstract and tags consistent with the actual document content.
    Uses the first 3000 chars as a sample. Falls back to simple extraction if it fails.
    """
    stem = Path(filename).stem.replace("_", " ").replace("-", " ")
    lang = _os.getenv("NEXE_LANG", "ca").split("-")[0].lower()

    try:
        from core.lifespan import get_server_state
        module_manager = get_server_state().module_manager
        if module_manager is None:
            return _fallback_metadata(body_content, stem, lang)

        model_name = _os.getenv("NEXE_DEFAULT_MODEL", "llama3.2:3b")
        sample = body_content[:3000].strip()
        system_prompt = "Ets un sistema d'indexacio de documents. Respon NOMES en el format demanat, sense explicacions."
        user_prompt = (
            f'Analitza aquest fragment del document "{filename}" i genera:\n'
            f'1. Un abstract de 1-2 frases (max 300 caracters) que descrigui el contingut real\n'
            f'2. Entre 3 i 6 tags rellevants en minuscules\n\n'
            f'Fragment:\n---\n{sample}\n---\n\n'
            f'Respon EXACTAMENT en aquest format:\n'
            f'abstract: [descripcio]\n'
            f'tags: [tag1, tag2, tag3]'
        )

        result = await _try_engines(module_manager, model_name, system_prompt, user_prompt, stem, lang)
        if result is not None:
            return result
    except Exception as e:
        logger.warning(f"generate_rag_metadata fallida: {e}")

    return _fallback_metadata(body_content, stem, lang)


# ─── Private helpers ─────────────────────────────────────────────────────────


def _fallback_metadata(body_content: str, stem: str, lang: str) -> dict:
    """Simple metadata extraction without LLM."""
    return {
        "abstract": " ".join(body_content.split())[:300],
        "tags": [stem],
        "priority": "P2",
        "type": "docs",
        "lang": lang,
    }


def _parse_llm_metadata_response(response_text: str, stem: str) -> tuple[str, list[str]]:
    """Extract abstract and tags from the LLM response text."""
    text = _re.sub(r"<think>[\s\S]*?</think>\s*", "", response_text).strip()
    abstract = ""
    tags = [stem]
    for line in text.split('\n'):
        line = line.strip()
        if line.lower().startswith('abstract:'):
            abstract = line[9:].strip().strip('"\'')[:400]
        elif line.lower().startswith('tags:'):
            tags_str = line[5:].strip().strip('[]')
            tags = [t.strip().strip('"\'') for t in tags_str.split(',') if t.strip()][:6]
    return abstract, tags


def _get_engine_instance(reg: Any) -> Any:
    """Return the engine instance from the registry, or None if not available."""
    if not reg or not reg.instance:
        return None
    if not hasattr(reg.instance, 'get_module_instance'):
        return None
    return reg.instance.get_module_instance()


async def _collect_stream_response(chat_result: Any) -> str:
    """Collect text from an async generator chunk by chunk."""
    text = ""
    async for chunk in chat_result:
        if isinstance(chunk, dict):
            text += chunk.get("message", {}).get("content", "") or chunk.get("content", "")
        elif isinstance(chunk, str):
            text += chunk
    return text


async def _call_llm_for_metadata(
    engine: Any, model_name: str, system_prompt: str, user_prompt: str
) -> str:
    """Call engine.chat and return the response text as a string."""
    sig = inspect.signature(engine.chat)
    if 'model' in sig.parameters:
        chat_result = engine.chat(
            model=model_name,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": user_prompt}],
            stream=False,
        )
    else:
        chat_result = engine.chat(
            messages=[{"role": "user", "content": user_prompt}],
            system=system_prompt,
            stream=False,
        )

    if inspect.isasyncgen(chat_result) or hasattr(chat_result, '__aiter__'):
        return await _collect_stream_response(chat_result)
    if inspect.iscoroutine(chat_result):
        result = await chat_result
        if isinstance(result, dict):
            return (result.get("message", {}).get("content", "")
                    or result.get("content", "")
                    or result.get("response", ""))
        return str(result)
    return str(chat_result)


async def _try_engines(
    module_manager: Any,
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    stem: str,
    lang: str,
) -> dict | None:
    """Try engines in order and return the metadata dict if an abstract is obtained."""
    for engine_name in ["mlx_module", "ollama_module", "llama_cpp_module"]:
        engine = _get_engine_instance(module_manager.registry.get_module(engine_name))
        if not engine or not hasattr(engine, 'chat'):
            continue
        try:
            response_text = await _call_llm_for_metadata(engine, model_name, system_prompt, user_prompt)
            abstract, tags = _parse_llm_metadata_response(response_text, stem)
            if abstract:
                logger.info(f"LLM metadata per '{stem}': abstract={abstract[:60]}... tags={tags}")
                return {"abstract": abstract, "tags": tags or [stem], "priority": "P2", "type": "docs", "lang": lang}
        except Exception as e:
            logger.warning(f"LLM metadata ({engine_name}) fallida: {e}")
    return None
