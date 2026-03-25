"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy
Location: plugins/web_ui_module/core/rag_handler.py
Description: Funcions RAG per al modul web_ui.
             Extret de manifest.py durant normalitzacio.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import inspect
import logging
import os as _os
import re as _re
from pathlib import Path

logger = logging.getLogger(__name__)


async def generate_rag_metadata(body_content: str, filename: str) -> dict:
    """
    Usa el LLM per generar abstract i tags consistents amb el contingut real del document.
    Fa servir els primers 3000 chars com a mostra. Fallback a extraccio simple si falla.
    """
    stem = Path(filename).stem.replace("_", " ").replace("-", " ")
    _lang = _os.getenv("NEXE_LANG", "ca").split("-")[0].lower()

    def _fallback():
        return {
            "abstract": " ".join(body_content.split())[:300],
            "tags": [stem],
            "priority": "P2",
            "type": "docs",
            "lang": _lang,
        }

    try:
        from core.lifespan import get_server_state
        module_manager = get_server_state().module_manager
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

        for engine_name in ["mlx_module", "ollama_module", "llama_cpp_module"]:
            reg = module_manager.registry.get_module(engine_name)
            if not reg or not reg.instance:
                continue
            engine = reg.instance.get_module_instance() if hasattr(reg.instance, 'get_module_instance') else None
            if not engine or not hasattr(engine, 'chat'):
                continue

            try:
                sig = inspect.signature(engine.chat)
                if 'model' in sig.parameters:
                    full_msgs = [{"role": "system", "content": system_prompt},
                                 {"role": "user", "content": user_prompt}]
                    chat_result = engine.chat(model=model_name, messages=full_msgs, stream=False)
                else:
                    chat_result = engine.chat(messages=[{"role": "user", "content": user_prompt}],
                                              system=system_prompt, stream=False)

                response_text = ""
                if inspect.isasyncgen(chat_result) or hasattr(chat_result, '__aiter__'):
                    async for chunk in chat_result:
                        if isinstance(chunk, dict):
                            response_text += (chunk.get("message", {}).get("content", "")
                                              or chunk.get("content", ""))
                        elif isinstance(chunk, str):
                            response_text += chunk
                elif inspect.iscoroutine(chat_result):
                    result = await chat_result
                    if isinstance(result, dict):
                        response_text = (result.get("message", {}).get("content", "")
                                         or result.get("content", "")
                                         or result.get("response", ""))
                    else:
                        response_text = str(result)
                else:
                    response_text = str(chat_result)

                response_text = _re.sub(r"<think>[\s\S]*?</think>\s*", "", response_text).strip()

                abstract = ""
                tags = [stem]
                for line in response_text.split('\n'):
                    line = line.strip()
                    if line.lower().startswith('abstract:'):
                        abstract = line[9:].strip().strip('"\'')[:400]
                    elif line.lower().startswith('tags:'):
                        tags_str = line[5:].strip().strip('[]')
                        tags = [t.strip().strip('"\'') for t in tags_str.split(',') if t.strip()][:6]

                if abstract:
                    logger.info(f"LLM metadata per '{filename}': abstract={abstract[:60]}... tags={tags}")
                    return {
                        "abstract": abstract,
                        "tags": tags or [stem],
                        "priority": "P2",
                        "type": "docs",
                        "lang": _lang,
                    }
            except Exception as e:
                logger.warning(f"LLM metadata ({engine_name}) fallida: {e}")
                continue

    except Exception as e:
        logger.warning(f"generate_rag_metadata fallida: {e}")

    return _fallback()
