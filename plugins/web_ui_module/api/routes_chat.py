"""
------------------------------------
Server Nexe
Location: plugins/web_ui_module/api/routes_chat.py
Description: POST /chat endpoint (~500 lines).
             Intent detection, RAG, compaction, multi-engine, streaming.
             Extracted from routes.py during tech debt refactoring.

www.jgoy.net · https://server-nexe.org
------------------------------------
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass
import asyncio
import inspect
import logging
import os as _os
import re as _re
from uuid import uuid4
from fastapi import APIRouter, HTTPException, Depends, Request as FastAPIRequest
from fastapi.responses import StreamingResponse
from core.dependencies import limiter
from core.turn.cancel import start_disconnect_monitor as _start_disconnect_monitor
from core.turn.context import TurnContext
from core.turn.post_commit import queue_for
from core.turn.run import run_turn, stream_turn
from core.turn.validate import parse_top_p
from plugins.web_ui_module.api.turn_adapters import ui_adapters

# C4.2: the prompt is assembled in the core now. The `continue` path below
# (FD-S6, decision §5 of the C1 plan) does not walk the turn map and calls
# these three itself; every other turn reaches them through the adapters.
from core.turn.assemble import _assemble_engine_messages, _build_turn_context
from core.turn.prompt import _build_turn_system_prompt

from core.log_redact import redact_user_content
from core.chat_prompt import time_context_line
from core.context_budget import (  # noqa: F401 — re-exported for tests and callers
    compute_context_budget,
    _inject_context_into_messages,
)
import core.memory_facts as memory_facts
from core.memory_facts import intents as memory_intents
from core.memory_facts import extract as memory_extract
from core.memory_facts.write import will_write, write_facts
import core.turn.policy as policy
from core.endpoints.chat_engines._common import extract_engine_text as _engine_text
from plugins.web_ui_module.core.harmony_filter import HarmonyStreamFilter
from plugins.web_ui_module.core.latex_sanitizer import LatexStreamBuffer, latex_to_unicode

logger = logging.getLogger(__name__)


# ─── Bug 17 — Hardened MEM_SAVE extractor ────────────────────────────────────
# The strict format we accept is: [MEM_SAVE: <text>]
# - <text> must be between 5 and MEM_SAVE_MAX_LEN characters
# - Must not contain newlines, tabs, brackets ([]), HTML brackets, or control chars
# - Only letters (including accents/cyrillic), digits, spaces, and safe punctuation
# - Explicitly rejected: <, >, [, ], {, }, |, `, \x00-\x1f
# - Nested MEM_SAVE rejected (one MEM_SAVE inside another)

# ─── Re-prompt override ─────────────────────────────────────────────────────
# When a model emits ONLY [MEM_SAVE: ...] without a conversational response,
# we resend the message with this override added to the system prompt.
# Unknown/invented memory-tag shapes (seen live 04/07: qwen3.5:4b emitted
# "[MEM_OBLIT: …]" — not MEM_SAVE, not MEM_DELETE, not an memory_extract._OBLIT_RE variant —
# and it leaked RAW to the UI). Known tags are extracted/stripped upstream;
# whatever [MEM*_X: …] survives is model confusion: strip it, log it, never
# act on it.

# ─── Context header patterns (compiled once) ─────────────────────────────────
_CTX_HEADERS_RE = _re.compile(
    # (?:FI\s+)?CONTEXT(?:\s+hex)? covers [CONTEXT], [FI CONTEXT] and the
    # nonce'd B030 variants ([CONTEXT a1b2c3d4], [FI CONTEXT a1b2c3d4]).
    r'\[(?:(?:FI\s+)?CONTEXT(?:\s+[0-9a-f]{6,16})?|MEMORIA DE L\'USUARI|MEMORIA DEL USUARIO|'
    r'USER MEMORY|DOCUMENTACI[ÓO] DEL SISTEMA|SYSTEM DOCUMENTATION|'
    r'DOCUMENTACI[ÓO] T[EÈ]CNICA|TECHNICAL DOCUMENTATION|'
    r'DOCUMENT ADJUNTAT|FI DOCUMENT)\]',
    _re.IGNORECASE
)




def _parse_chunk(chunk: Any) -> tuple[str, str]:
    """Extreu (content, thinking) d'un chunk de l'engine."""
    content = ""
    thinking = ""
    if isinstance(chunk, dict):
        if "message" in chunk:
            thinking = chunk["message"].get("thinking", "")
            content = chunk["message"].get("content", "")
        elif "content" in chunk:
            content = chunk["content"]
        elif "response" in chunk:
            content = chunk["response"]
    elif isinstance(chunk, str):
        content = chunk
    return content, thinking


# MC-004: precompiled once (these subs run per stream chunk in _normalize_content).
_PIPE_TAG_RE = _re.compile(r'<\|[^|]+\|>')
_ANGLE_TAG_RE = _re.compile(r'[◁◀][^▷▶]*[▷▶]')


def _normalize_content(content: str, model_name: str) -> str:
    """Normalize GPT-OSS and pipe tags for the specific model."""
    if "gpt-oss" in model_name.lower():
        content = content.replace('<|analysis|>', '<think>')
        content = content.replace('<|assistant|>', '</think>')
    else:
        content = content.replace('<|thinking|>', '<think>')
        content = content.replace('<|/thinking|>', '</think>')
    content = _PIPE_TAG_RE.sub('', content)
    content = _ANGLE_TAG_RE.sub('', content)
    return content


def _process_content_think_tags(content: str, in_think: bool) -> tuple[str, bool, bool]:
    """Split the visible part of a chunk with embedded <think> tags (qwq:32b, etc.).

    Returns (visible, in_think_new, found_thinking).
    """
    if '<think>' not in content and '</think>' not in content and not in_think:
        return content, False, False
    vis_parts: list[str] = []
    sc = 0
    found_thinking = False
    while sc < len(content):
        if in_think:
            te = content.find('</think>', sc)
            if te >= 0:
                in_think = False
                sc = te + 8
            else:
                break
        else:
            ts = content.find('<think>', sc)
            if ts >= 0:
                if ts > sc:
                    vis_parts.append(content[sc:ts])
                in_think = True
                found_thinking = True
                sc = ts + 7
            else:
                vis_parts.append(content[sc:])
                break
    return ''.join(vis_parts), in_think, found_thinking


class _StreamThinkParser:
    """Per-request streaming FSM extracted from response_generator (MC-027 F1).

    Owns the cross-chunk think / content-think / harmony / latex state and turns
    each engine chunk's ``(content, thinking)`` into ``(wire_tokens, full_delta)``:

      - ``wire_tokens``: the strings to yield to the client — already ``<think>``
        wrapped, harmony/latex filtered and ``[MEMORIA: ...]`` stripped (visible).
      - ``full_delta``: the raw text to append to ``full_response`` — think tags
        included, pre-latex — what ``_clean_full_response`` later strips at persist.

    The visible/raw split is load-bearing (INV-HIGH-07): the wire shows the buffered
    visible form while ``full_response`` keeps the raw content so think/harmony tags
    can be removed at persist time. ``feed()`` and ``flush()`` both return
    ``(wire, full_delta)``; ``flush()`` closes any open harmony ``<think>`` (B027a)
    and drains the pending latex buffer. Behaviour is byte-equivalent to the inline
    loop it replaces.
    """

    def __init__(self, model_name: "str | None") -> None:
        self._model_name = model_name
        self._in_thinking = False
        self._in_content_think = False
        self._latex_buf = LatexStreamBuffer()
        # B027a: gpt-oss emits harmony channel tags (<|channel|>analysis<|message|>…)
        # split across chunks — a stateless replace cannot pair them and the
        # reasoning leaked into the visible bubble. Stateful filter → canonical
        # <think>. Only instantiated for gpt-oss; other models use _normalize_content.
        self._harmony_buf = (
            HarmonyStreamFilter()
            if "gpt-oss" in str(model_name).lower() else None
        )
        self.has_any_thinking = False

    def feed(self, content: str, thinking: str) -> "tuple[list[str], str]":
        wire: list[str] = []
        full = ""
        # Stream thinking tokens wrapped in <think> tags (open/close on transition)
        if thinking:
            if not self._in_thinking:
                self._in_thinking = True
                self.has_any_thinking = True
                wire.append("<think>")
                full += "<think>"
            wire.append(thinking)
            full += thinking
        elif self._in_thinking:
            # Transition: thinking done, close tag
            self._in_thinking = False
            wire.append("</think>")
            full += "</think>"

        if content:
            if self._harmony_buf is not None:
                content = self._harmony_buf.feed(content)
            else:
                content = _normalize_content(content, self._model_name)
        if content:
            full += content
            # Separate embedded <think> blocks in content (qwq:32b, etc.)
            visible, self._in_content_think, _found_thinking = _process_content_think_tags(
                content, self._in_content_think
            )
            if _found_thinking:
                self.has_any_thinking = True
            # Bug B-mem-visible: strip [MEMORIA: ...] from visible output — gpt-oss:20b
            # emits this tag instead of [MEM_SAVE: ...]. Processed in clean_response;
            # here we hide it from the user.
            if visible and memory_extract._MEMORIA_RE.search(visible):
                visible = memory_extract._MEMORIA_RE.sub('', visible)
            if visible:
                emit = self._latex_buf.feed(visible)
                if emit:
                    wire.append(emit)
        return wire, full

    def flush(self) -> "tuple[list[str], str]":
        wire: list[str] = []
        full = ""
        # Flush harmony leftovers (closes an open <think>)
        if self._harmony_buf is not None:
            _harmony_tail = self._harmony_buf.flush()
            if _harmony_tail:
                full += _harmony_tail
                _h_visible, self._in_content_think, _f = _process_content_think_tags(
                    _harmony_tail, self._in_content_think
                )
                if _h_visible:
                    emit = self._latex_buf.feed(_h_visible)
                    if emit:
                        wire.append(emit)
        # Flush any buffered LaTeX pending at end of stream
        _latex_tail = self._latex_buf.flush()
        if _latex_tail:
            wire.append(_latex_tail)
        return wire, full


def _build_mem_stats(
    session: Any,
    rag_count: int,
    rag_items: list,
    model_name: "str | None",
    elapsed: float,
    full_response_len: int,
    mem_saved_count: int,
    mem_saves: list,
) -> dict:
    """Build the stats dict for session.add_message."""
    est_tokens = max(1, full_response_len // 4)
    rag_avg_val = None
    if rag_count > 0 and rag_items:
        rag_avg_val = round(sum(s for _, s in rag_items) / len(rag_items), 2)
    saved_facts = [f.strip() for f in mem_saves if f.strip() and len(f.strip()) >= 5] if mem_saved_count > 0 else None
    saved_rag_items = [[str(c)[:30], round(s, 2)] for c, s in rag_items] if rag_items else None
    return {
        "tokens": est_tokens,
        "elapsed": elapsed,
        "model": str(model_name)[:100] if model_name else None,
        "rag_count": rag_count if rag_count > 0 else None,
        "rag_avg": rag_avg_val,
        "rag_items": saved_rag_items,
        "mem_saved": mem_saved_count if mem_saved_count > 0 else None,
        "mem_facts": saved_facts,
    }


async def _yield_response_headers(
    model_name: str,
    rag_count: int,
    rag_items: list,
    compacted: bool,
    compaction_count: int,
    doc_truncated_pct: int,
):
    """Yield the header tokens: MODEL, RAG*, COMPACT, DOC_TRUNCATED."""
    _safe_model = str(model_name).replace("\x00", "").replace("]", "")[:100]
    yield f"\x00[MODEL:{_safe_model}]\x00"
    if rag_count > 0:
        yield f"\x00[RAG:{int(rag_count)}]\x00"
        if rag_items:
            avg_score = sum(s for _, s in rag_items) / len(rag_items)
            yield f"\x00[RAG_AVG:{avg_score:.2f}]\x00"
            for _col, _score in rag_items:
                _safe_col = str(_col).replace("\x00", "").replace("|", "_")[:30]
                yield f"\x00[RAG_ITEM:{_safe_col}|{_score:.2f}]\x00"
    if compacted:
        yield f"\x00[COMPACT:{int(compaction_count)}]\x00"
    if doc_truncated_pct > 0:
        yield f"\x00[DOC_TRUNCATED:{doc_truncated_pct}]\x00"


def _clean_full_response(full_response: str, user_input: str = "") -> tuple[str, list, list]:
    """Clean the full response and extract MEM_SAVE and MEM_DELETE tags.

    Returns (clean_response, mem_saves, mem_deletes).
    The PENDING_DELETE yield must be done by the caller.
    """
    clean_response = full_response
    clean_response = _re.sub(r"<think>[\s\S]*?</think>\s*", "", clean_response)
    clean_response = _re.sub(r'<\|[^|]+\|>', '', clean_response)
    clean_response = _re.sub(r'[◁◀][^▷▶]*[▷▶]', '', clean_response)
    _m = _re.search(r'(?:assistant\s*)?final\s*([\s\S]+)$', clean_response, _re.IGNORECASE)
    if _m:
        clean_response = _m.group(1).strip()
    else:
        clean_response = _re.sub(r'^analysis\s*', '', clean_response, flags=_re.IGNORECASE).strip()
    clean_response = _CTX_HEADERS_RE.sub('', clean_response).strip()
    # C3.2: reading the model's memory tags is the core's job now — the same
    # reading /v1 does, so a tag means the same thing at both doors.
    return memory_extract.extract_memory_tags(clean_response, user_input=user_input)


# Placeholder persisted for a think-only assistant turn (B125).
_THINK_ONLY_PLACEHOLDER = "…"


def _think_only_placeholder(clean_response: str, full_response: str) -> str:
    """B125: keep an assistant turn even when the model produced only thinking.

    When the model emits a turn that cleans down to nothing (e.g. think-only
    output), no assistant message gets persisted. ``get_context_messages()``
    then sees two consecutive ``user`` turns and drops the newer one as a
    duplicate role — silently losing the user's next message. Returning a
    placeholder keeps the user/assistant alternation intact.

    A genuinely empty turn (``full_response`` empty, e.g. an upstream
    exception) is left untouched so nothing spurious is saved.
    """
    if not clean_response and full_response:
        return _THINK_ONLY_PLACEHOLDER
    return clean_response


def _extract_reprompt_chunk_content(chunk) -> tuple[str, bool]:
    """Extract text content from a reprompt chunk. Returns (content, skip).

    skip=True means the chunk is a pure thinking token and should be discarded.
    """
    if isinstance(chunk, dict) and "message" in chunk:
        if chunk["message"].get("thinking", ""):
            return "", True
        return chunk["message"].get("content", ""), False
    if isinstance(chunk, dict):
        return chunk.get("content", chunk.get("response", "")) or "", False  # type: ignore[return-value]
    if isinstance(chunk, str):
        return chunk, False
    return "", False


def _filter_reprompt_think_tags(content: str, in_think: bool) -> tuple[str, bool]:
    """Strip <think>…</think> tags inline, updating in_think state. Returns (filtered_content, in_think).

    B124: a chunk that carries a COMPLETE ``<think>…</think>`` plus trailing
    visible text must keep that visible text. The close tag is matched on the
    ORIGINAL chunk (previously it was searched in the already-truncated
    pre-``<think>`` slice, so the text after ``</think>`` was discarded and
    in_think wrongly stayed True — the visible reply was lost).
    """
    before = content.split('<think>')[0] if '<think>' in content else ""
    if '<think>' in content:
        in_think = True
    if '</think>' in content:
        # visible = text before this chunk's <think> (if any) + text after </think>
        return before + content.split('</think>')[-1], False
    if in_think:
        return "", True
    return content, in_think


async def _yield_reprompt(
    engine: Any,
    model_name: str,
    sig: Any,
    lang: str,
    system_prompt: str,
    messages: list,
    mem_saves: list,
    thinking_enabled: bool,
    rp_out: list,
):
    """Re-prompt when the response is empty but there are MEM_SAVEs.

    Yields filtered chunks (no think, no MEM_SAVE).
    If the response is OK, rp_out[0] = accumulated clean_response.
    The fallback (yield 'Memory saved: ...') lives one level up, in
    `_yield_reprompt_when_only_mem_saves`.
    """
    _fallback_facts = [f.strip() for f in mem_saves if f and f.strip()]
    if not _fallback_facts:
        return
    _lang_short = lang[:2] if lang else "ca"
    _rp_override = policy.REPROMPT_OVERRIDE.get(_lang_short, policy.REPROMPT_OVERRIDE["en"])
    _rp_system = system_prompt + _rp_override
    try:
        if 'model' in sig.parameters:
            logger.info("Re-prompt: empty after MEM_SAVE, re-calling %s", model_name)
            _rp_msgs = [{"role": "system", "content": _rp_system}] + messages
            _rp_result = engine.chat(model=model_name, messages=_rp_msgs, stream=True,
                                     thinking_enabled=thinking_enabled)
            _rp_response = ""
            _rp_in_think = False
            async for _rp_chunk in _rp_result:
                _rp_content, _skip = _extract_reprompt_chunk_content(_rp_chunk)
                if _skip:
                    continue
                _rp_content, _rp_in_think = _filter_reprompt_think_tags(_rp_content, _rp_in_think)
                if _rp_in_think:
                    continue
                _rp_content = _re.sub(r'\[MEM_SAVE:[^\[\]\n\r\t]{1,250}\]', '', _rp_content)
                if _rp_content:
                    _rp_response += _rp_content
                    yield _rp_content
            if _rp_response.strip():
                rp_out.append(_rp_response.strip())
                logger.info("Re-prompt OK: %d chars", len(_rp_response.strip()))
    except Exception as e:
        logger.warning("Re-prompt failed: %s", e)


def render_intent_for_ui(outcome: "memory_intents.IntentOutcome") -> str:
    """The web UI's alphabet for a memory command: the core answered with data,
    this adds the sentinels `nexe-chat.js` reads. The core stays wire-agnostic
    (ADR-007 C3.1); /v1 renders the same outcome as plain text plus headers."""
    rendered = f"\x00[MODEL:nexe-system]\x00{outcome.text}"
    if outcome.deleted_facts:
        facts_pipe = "|".join(f[:80] for f in outcome.deleted_facts[:5])
        rendered += f"\x00[DEL:{outcome.mem_deleted}:{facts_pipe}]\x00"
    if outcome.pending_delete_fact is not None:
        # PENDING_DELETE marker: the web UI shows its confirmation dialog. Text
        # confirmation ("si") works in parallel via session._pending_partial_delete.
        fact = outcome.pending_delete_fact.replace("|", "\\|")[:200]
        rendered += f"\x00[PENDING_DELETE:{fact}]\x00"
    return rendered


# B126 v2: name claims are no longer blanket-junk here either — the contextual
# guard (NAME_CLAIM_RE + user_text check) in core.memory_facts.write
# replaces them, in parity with the streaming path (_filter_facts).

def _clean_nonstreaming_text(response_text: str) -> str:
    """Strip think/GPT-OSS tags and extract the final answer section."""
    response_text = _re.sub(r"<think>[\s\S]*?</think>\s*", "", response_text)
    response_text = _re.sub(r'<\|[^|]+\|>', '', response_text)
    _m = _re.search(r'(?:assistant\s*)?final\s*([\s\S]+)$', response_text, _re.IGNORECASE)
    if _m:
        return _m.group(1).strip()
    return _re.sub(r'^analysis\s*', '', response_text, flags=_re.IGNORECASE).strip()


async def _arm_mem_deletes_nonstreaming(
    mem_deletes: list,
    session,
    memory_helper,
) -> str:
    """B028: model-emitted MEM_DELETE tags must NOT delete directly.

    The streaming path already routes them through a confirmation
    ([PENDING_DELETE:] → UI dialog); the non-streaming path used to execute
    them straight away — a RAG-injected document could erase memory with zero
    human in the loop. Now: preview the first valid fact, arm the 2-turn
    confirmation, and return the question to append to the response.
    """
    for _del_fact in mem_deletes:
        _del_fact = _del_fact.strip()
        if not _del_fact or len(_del_fact) < 3:
            continue
        try:
            preview = await memory_helper.preview_delete_from_memory(_del_fact)
            candidates = preview.get("candidates", [])
            if preview.get("success") and candidates:
                best = candidates[:1]
                session._pending_partial_delete = {"content": _del_fact, "entries": best}
                logger.info("MEM_DELETE (model tag, no-stream): pending confirmation for %s", redact_user_content(_del_fact))
                return render_intent_for_ui(memory_intents.IntentOutcome(
                    kind="delete_pending",
                    text=memory_intents.delete_confirm_question(best),
                    pending_delete_fact=best[0].get("text", "") if best else "",
                ))
            logger.info("MEM_DELETE (model tag, no-stream): no match for %s", redact_user_content(_del_fact))
        except Exception as e:
            logger.warning("MEM_DELETE preview failed (no-stream): %s", e)
    return ""


@dataclass
class NonStreamRepromptContext:
    """El que el re-prompt de #856 necessita i que viu dins `_handle_chat_engine`.

    `_yield_reprompt` demana engine/model/sig/lang/system_prompt/messages i
    thinking_enabled. Al camí streaming els porta `StreamingChatContext`; el camí
    no-streaming no tenia cap vehicle, i per això acea60f1 (31/07) va portar-hi
    només la segona meitat de la xarxa (la confirmació) i no el re-prompt. Això
    és el vehicle: els mateixos valors, capturats al mateix lloc, sense
    reconstruir el torn ni duplicar-ne la preparació.
    """
    engine: Any
    model_name: "str | None"
    sig: Any
    lang: str
    system_prompt: str
    messages: list
    thinking_enabled: bool


async def _reprompt_nonstreaming(
    ctx: "NonStreamRepromptContext", mem_saves: list,
) -> str:
    """Re-prompt del camí no-streaming. Torna "" si no rendeix text.

    Mateix generador que el camí streaming (`_yield_reprompt`, la font única):
    allà els trossos es van emetent al client a mesura que arriben; aquí no hi
    ha res a qui emetre'ls, així que es consumeixen i el que compta és el text
    acumulat que el generador deixa a `rp_out`. Els errors ja els empassa
    `_yield_reprompt` (log + res), de manera que un re-prompt que falla acaba
    igual que un que no rendeix: cadena buida i, més amunt, la confirmació.
    """
    _rp_out: list = []
    async for _chunk in _yield_reprompt(
        ctx.engine, ctx.model_name, ctx.sig, ctx.lang,
        ctx.system_prompt, ctx.messages, mem_saves,
        ctx.thinking_enabled, _rp_out,
    ):
        pass
    return _rp_out[0] if _rp_out else ""


async def _postprocess_nonstreaming(
    response_text: str,
    session,
    memory_helper,
    message: str,
    memory_action: Optional[str],
    rag_collections: "list | None" = None,
    reprompt_ctx: "NonStreamRepromptContext | None" = None,
) -> tuple[str, Optional[str], int, list]:
    """The non-streaming `postprocess` step: returns
    (response_text, memory_action, mem_deleted_delta, mem_saves).

    Everything the old (single-call) non-stream handler did EXCEPT writing the
    facts to memory — that is the turn's `memory.write` step, which runs after
    the turn is on disk (ADR-007 I3; decision of 06/09/2026). `mem_saves` is
    handed to the caller, who runs `core.memory_facts.write.write_facts` afterwards
    (C1.4, 06/09/2026: the facade that called both in the old order had no
    production caller left — removed).
    """
    response_text = _clean_nonstreaming_text(response_text)
    # TUR-NS-MEMORIA: normalise the [MEMORIA:] alias → [MEM_SAVE:] (mirror of
    # the streaming _clean_full_response) so models that emit it (e.g.
    # gpt-oss:20b) get the fact SAVED and the raw tag stripped — without this,
    # the non-stream path leaks [MEMORIA:] raw to the JSON/disk response and
    # never persists the fact (parity with stream broken).
    response_text = memory_extract._MEMORIA_RE.sub(lambda m: f'[MEM_SAVE: {m.group(1)}]', response_text)
    # Bug 17: Extract [MEM_SAVE: ...] facts with strict validation before strip
    _mem_saves_ns = memory_extract._extract_safe_mem_saves(response_text, user_input=message)
    response_text = _re.sub(r'\[MEM_SAVE:[^\[\]\n\r\t]{1,250}\]\s*', '', response_text).strip()
    # F1 fix: if the model generated inline MEM_SAVE, reflect it in memory_action
    # (the facts themselves are written by the caller's `memory.write`, after disk).
    # C3 review (08/09): only when there is no memory_action yet. A D6 "save"
    # already ran deterministically at the `intent` step, before this text
    # existed — the model parroting its own confirmation back as another
    # inline tag (common on small models, live-tested 08/09) must not relabel
    # that already-completed, already-counted save as the unreliable
    # "mem_save_inline" bucket. /v1's postprocess (core/turn/adapters_api.py)
    # never overwrote memory_action for this reason; the UI door diverged.
    if _mem_saves_ns and not memory_action:
        memory_action = "mem_save_inline"
    # Bug 18: Extract [MEM_DELETE: ...] and [OLVIDA/OBLIT/FORGET: ...] (non-streaming)
    response_text = memory_extract._OBLIT_RE.sub(lambda m: f'[MEM_DELETE: {m.group(2)}]', response_text)
    _mem_deletes_ns = memory_extract._MEM_DELETE_RE.findall(response_text)
    mem_deleted_delta = 0
    if _mem_deletes_ns:
        response_text = _re.sub(r'\[MEM_DELETE:[^\[\]\n\r\t]{1,250}\]\s*', '', response_text).strip()
        # B028: arm the 2-turn confirmation instead of deleting directly.
        _confirm_q = await _arm_mem_deletes_nonstreaming(_mem_deletes_ns, session, memory_helper)
        if _confirm_q:
            response_text = f"{response_text}\n\n{_confirm_q}" if response_text else _confirm_q
            memory_action = "delete_pending"
    # Last pass (parity with _clean_full_response): invented [MEM_*] variants
    # must never reach the client.
    response_text = memory_extract._strip_unknown_mem_tags(response_text)
    # #856: a turn that cleans down to ONLY the MEM_SAVE tag left the client
    # with 200 + empty body here, while the streaming path re-prompted and,
    # failing that, emitted a confirmation. Seen live 31/07 (glm-4.7-flash
    # answered a bare hallucinated directive in 0.58 s). The re-prompt itself
    # needs engine/sig/system_prompt/messages, which stay local to
    # _handle_chat_engine — so this path landed straight on the same fallback
    # text the streaming one uses when its re-prompt yields nothing.
    # 23/08: la paritat es completa — el context del torn ara viatja fins aquí
    # (NonStreamRepromptContext) i el re-prompt es prova PRIMER, com al camí
    # streaming; la confirmació queda com el que sempre havia de ser: l'última
    # xarxa quan el segon intent tampoc rendeix text.
    if not response_text and _mem_saves_ns and reprompt_ctx is not None and policy.reprompt_enabled():
        response_text = await _reprompt_nonstreaming(reprompt_ctx, _mem_saves_ns)
    if not response_text:
        response_text = policy.mem_save_fallback_text(_mem_saves_ns)
    return response_text, memory_action, mem_deleted_delta, _mem_saves_ns


async def _yield_model_loading_check(engine, model_name: str, engine_name: str):
    """Yield a MODEL_LOADING token if the engine reports the model is not yet loaded."""
    if not hasattr(engine, 'is_model_loaded'):
        return
    _safe_model = str(model_name).replace("\x00", "").replace("]", "")[:100]
    try:
        loaded = await engine.is_model_loaded(model_name)
        if not loaded:
            logger.info("Model %s not loaded — loading... [%s]", model_name, engine_name)
            yield f"\x00[MODEL_LOADING:{_safe_model}|{engine_name}]\x00"
    except Exception as e:
        logger.debug("Model loaded check failed for %s: %s", model_name, e)


def _inject_image_block(messages: list) -> list:
    """Prepend a localised image-context block to the last user message if present."""
    _img_blocks = {
        "ca": (
            "[IMATGE ADJUNTA]\n"
            "L'usuari ha adjuntat una imatge a aquest missatge. "
            "Analitza la imatge i incorpora-la a la teva resposta. "
            "Prioritza el que veus a la imatge per sobre de memòries anteriors.\n"
            "[FI IMATGE]"
        ),
        "es": (
            "[IMAGEN ADJUNTA]\n"
            "El usuario ha adjuntado una imagen a este mensaje. "
            "Analiza la imagen e incorpórala a tu respuesta. "
            "Prioriza lo que ves en la imagen por encima de memorias anteriores.\n"
            "[FIN IMAGEN]"
        ),
        "en": (
            "[ATTACHED IMAGE]\n"
            "The user has attached an image to this message. "
            "Analyze the image and incorporate it into your response. "
            "Prioritize what you see in the image over previous memories.\n"
            "[END IMAGE]"
        ),
    }
    _lang_key2 = _os.environ.get("NEXE_LANG", "en").split("-")[0].lower()
    _img_block = _img_blocks.get(_lang_key2, _img_blocks["en"])
    if messages and messages[-1]["role"] == "user":
        messages[-1] = dict(messages[-1])
        messages[-1]["content"] = f"{_img_block}\n\n{messages[-1]['content']}"
    return messages


async def _accumulate_nonstreaming_response(chat_result, response_chunks: list) -> None:
    """Accumulate chunks from a non-streaming chat_result into response_chunks."""
    import inspect
    if inspect.isasyncgen(chat_result) or hasattr(chat_result, '__aiter__'):
        async for chunk in chat_result:
            if isinstance(chunk, dict) and "message" in chunk and "content" in chunk["message"]:
                response_chunks.append(chunk["message"]["content"])
            elif isinstance(chunk, dict) and "content" in chunk:
                response_chunks.append(chunk["content"])
            elif isinstance(chunk, str):
                response_chunks.append(chunk)
    else:
        result = await chat_result if inspect.iscoroutine(chat_result) else chat_result
        content = _engine_text(result)
        if content:
            response_chunks.append(content)


@dataclass
class StreamingChatContext:
    """Request-scoped state for `_generate_streaming_response` (MC-027 F2).

    Carries the ~18 values the streaming body used to capture as closure free-vars.
    `session`, `messages` and `memory_helper` are LIVE references (mutated in place,
    never copied); `session_mgr` comes from the `register_chat_routes` factory scope,
    NOT a module global; `disconnect_monitor_task` is the live asyncio.Task whose
    ownership `_handle_chat_engine` hands off to the generator (INV-CRIT-01/02/06).
    """
    model_name: "str | None"
    rag_count: int
    rag_items: list
    compacted: bool
    doc_truncated_pct: int
    session: Any
    session_mgr: Any
    memory_helper: Any
    engine: Any
    engine_name: str
    chat_result: Any
    sig: Any
    system_prompt: str
    messages: list
    thinking_enabled: bool
    lang: "str | None"
    message: str
    disconnect_monitor_task: "asyncio.Task"
    # UI collection toggles for this request; None = all collections enabled
    # (old clients / bare API calls). Gates MEM_SAVE persistence.
    rag_collections: "list | None" = None
    # FD-S6: this stream RESUMES the session's last assistant message — the
    # tail must MERGE into it (never add_message: get_context_messages
    # dedupes consecutive roles keeping only the latest, which would erase
    # the first half of the answer).
    continue_mode: bool = False


@dataclass
class _StreamFlags:
    """Per-request flags the engine loop hands back to the streaming body.

    `_yield_engine_chunks` cannot return values while it is yielding, so the
    three flags it discovers travel on this object instead. `full_response`
    deliberately does NOT live here: it stays a bare local of
    `_generate_streaming_response`, accumulated at the yield site, so a client
    disconnect finds the partial text exactly where MC-116 expects it.
    """
    # FD-S5: truncation marker state. Set by the in-band sentinel (MLX
    # via queue_generator) or by an Ollama done_reason=='length' chunk.
    trunc: bool = False
    trunc_continuable: bool = False
    has_any_thinking: bool = False
    # #1040 (C2.4): the exception `_yield_engine_chunks` caught mid-stream, if
    # any. The generator itself only has room to turn it into wire text (see
    # `_stream_error_notice`); this is the out-of-band channel that lets the
    # caller (`generate_stream`) mark the turn PARTIAL after the fact — the
    # error is already committed to the wire by the time this is read, so the
    # turn cannot be retried, only recorded as broken.
    error: "Exception | None" = None


def _oom_notice(err_msg: str, lang: str) -> str:
    """Curated out-of-memory notice for the chat body, by originating engine.

    The MLX pre-load guard already raises a message telling the user to switch
    engines, but the streaming handler used to replace every OOM with a generic
    "close other applications" — and since the UI always streams, that advice
    never reached anyone. It is restored here, gated on the failure actually
    coming from MLX: this branch also catches OOM raised by other engines, and
    telling a user who is already on Ollama to switch to Ollama is nonsense.

    MC-133 still holds: the text is curated per language and never echoes the
    raw exception, which can carry internal paths or state.
    """
    mlx_specific = {
        "ca": "Memòria insuficient per carregar el model amb MLX. Canvia el motor a Ollama (fa servir molta menys memòria) o tanca altres aplicacions i torna-ho a provar.",
        "es": "Memoria insuficiente para cargar el modelo con MLX. Cambia el motor a Ollama (usa mucha menos memoria) o cierra otras aplicaciones e inténtalo de nuevo.",
        "en": "Not enough memory to load the model with MLX. Switch the engine to Ollama (it uses far less memory) or close other applications and try again.",
    }
    generic = {
        "ca": "Memòria insuficient. Tanca altres aplicacions per alliberar memòria i torna-ho a provar.",
        "es": "Memoria insuficiente. Cierra otras aplicaciones para liberar memoria e inténtalo de nuevo.",
        "en": "Not enough memory. Close other applications to free up memory and try again.",
    }
    table = mlx_specific if "MLX" in (err_msg or "") else generic
    return table.get(lang, table["en"])


def _apply_trunc_sentinels(chunk: Any, flags: _StreamFlags) -> bool:
    """Read the FD-S5 truncation sentinels off a chunk. True = skip the chunk.

    Two shapes, and only the first one is skippable:
      - the in-band `__nexe_trunc__` sentinel (MLX, via queue_generator), which
        carries no text and must never be mixed with a content yield;
      - an Ollama passthrough `done` chunk with done_reason == 'length', which
        may still carry content for `_parse_chunk` — so it is NOT skipped.
    """
    if isinstance(chunk, dict) and chunk.get("__nexe_trunc__"):
        flags.trunc = True
        flags.trunc_continuable = bool(chunk.get("continuable"))
        return True
    if (
        isinstance(chunk, dict)
        and chunk.get("done")
        and chunk.get("done_reason") == "length"
    ):
        flags.trunc = True
    return False


def _is_oom_error(err_msg: str) -> bool:
    """True when an engine's error text describes an out-of-memory failure.

    Shared by `_stream_error_notice` (which message to show) and
    `_classify_engine_error` (#1040, C2.4: which ADR-007 §8 class to record —
    Fatal, since closing other applications or switching engines is a step
    the user must take, not something a retry on the next engine fixes).
    """
    return any(k in err_msg for k in (
        "Insufficient Memory", "OutOfMemory",
        "Memòria insuficient", "Memoria insuficiente",
        "Not enough memory",
    ))


def _classify_engine_error(exc: Exception) -> str:
    """ADR-007 §8 class for an exception caught mid-stream (#1040, C2.4).

    Used only to annotate `ctx.error` for the trace — C2 does not yet act on
    the class (that starts with C2.5's deadline/budget work). OOM is Fatal
    (the user must free memory or switch engines); anything else caught here
    is the current engine failing at this moment, i.e. Retryable in the
    sense that a fresh turn against a different engine could still succeed —
    though this turn itself, with tokens already on the wire, cannot be.
    """
    err_msg = repr(exc) if not str(exc) else str(exc)
    return "Fatal" if _is_oom_error(err_msg) else "Retryable"


def _stream_error_notice(exc: Exception, lang: "str | None") -> str:
    """Chat-body text for an exception raised mid-generation (MC-133).

    Logs the full detail (with traceback) locally and returns ONLY the curated,
    localized notice: the raw exception text can carry internal paths or state
    and must never reach the wire. OOM keeps its own message (`_oom_notice`).
    """
    err_msg = repr(exc) if not str(exc) else str(exc)
    # MC-133: the full detail (with traceback) belongs in the local log,
    # never in the chat body. exc_info=True keeps diagnostics; the user
    # sees a curated message below.
    logger.error("Streaming error: %s", err_msg, exc_info=True)
    _lk = lang[:2] if lang else "ca"
    if _is_oom_error(err_msg):
        return f"\n⚠️ {_oom_notice(err_msg, _lk)}"
    # MC-133: do not echo the raw exception text (err_msg) — it can
    # carry internal paths/state. Surface a generic, localized notice.
    _err = {
        "ca": "S'ha produït un error en generar la resposta. Torna-ho a provar.",
        "es": "Se ha producido un error al generar la respuesta. Inténtalo de nuevo.",
        "en": "An error occurred while generating the response. Please try again.",
    }
    return f"\n⚠️ {_err.get(_lk, _err['en'])}"


def _gen_truncated_token(
    trunc: bool, trunc_continuable: bool, clean_response: str
) -> "str | None":
    """FD-S5 marker for an answer cut by the token ceiling, or None.

    A silent cut mid-sentence reads as the model going mute. The caller emits
    this as its OWN yield (a marker split across reads would not be parsed).
    Degrades to :0 (informative, no Continue) when the visible text is empty or
    the think-only placeholder — there is nothing to resume.
    """
    if not trunc:
        return None
    _cont_flag = 1 if (
        trunc_continuable and clean_response and clean_response != "…"
    ) else 0
    return f"\x00[GEN_TRUNCATED:{_cont_flag}]\x00"


async def _yield_engine_chunks(ctx: "StreamingChatContext", flags: _StreamFlags):
    """Consume the engine's stream, yielding `(wire_token, full_delta)` pairs.

    The caller owns `full_response`: each pair carries either a token for the
    wire or text to accumulate (never both), so the caller can do
    `full_response += delta` at the same point the inline loop did — before the
    wire tokens of that chunk go out — and a disconnect leaves the partial text
    where MC-116 expects it. A pair whose token is None is accumulation only.

    The `except Exception` stays with the loop it guards. GeneratorExit is a
    BaseException, so a client disconnect still tears this generator down
    instead of being turned into an error notice.
    """
    try:
        # Handle both AsyncIterator (streaming) and direct coroutine response (non-streaming)
        if inspect.isasyncgen(ctx.chat_result) or hasattr(ctx.chat_result, '__aiter__'):
            _first_chunk = True
            # MC-027 F1: the per-request think/content-think/harmony/latex FSM
            # lives in _StreamThinkParser. feed() returns (wire_tokens, full_delta):
            # the wire gets the visible/buffered form, full_response keeps the raw
            # text so _clean_full_response can strip tags at persist (INV-HIGH-07).
            _think_parser = _StreamThinkParser(ctx.model_name)
            async for chunk in ctx.chat_result:
                if _apply_trunc_sentinels(chunk, flags):
                    continue
                content, thinking = _parse_chunk(chunk)

                # Model loaded — any chunk = model is responding
                if _first_chunk:
                    _first_chunk = False
                    yield "\x00[MODEL_READY]\x00", ""

                _wire, _full_delta = _think_parser.feed(content, thinking)
                yield None, _full_delta
                for _tok in _wire:
                    yield _tok, ""
                flags.has_any_thinking = _think_parser.has_any_thinking
            # Flush harmony leftovers (closes an open <think>) +
            # any buffered LaTeX pending at end of stream
            _wire, _full_delta = _think_parser.flush()
            yield None, _full_delta
            for _tok in _wire:
                yield _tok, ""
        else:
            # Fallback for non-streaming engines
            yield "\x00[MODEL_READY]\x00", ""
            result = await ctx.chat_result if inspect.iscoroutine(ctx.chat_result) else ctx.chat_result
            content = _engine_text(result)
            if content:
                yield latex_to_unicode(content), content
    except Exception as e:
        flags.error = e
        yield _stream_error_notice(e, ctx.lang), ""


async def _yield_mem_delete_prompts(ctx: "StreamingChatContext", mem_deletes: list):
    """Arm each MEM_DELETE and yield its confirm-dialog token (MC-117).

    Body moved verbatim out of `_generate_streaming_response` (MC-027 F3): same
    arming order, same entries=[:1], same TUR-PHANTOM-DEL rule that the token
    only surfaces for a fact that actually armed a pending delete.
    """
    for _del_fact in mem_deletes:
        _encoded = _del_fact.replace('|', '\\|')
        # MC-117: arm the 2-turn TEXT confirmation (a typed "sí" next
        # turn), not only the UI dialog. Mirrors the non-stream arming
        # (_handle_delete_intent) so the documented behaviour holds.
        # Arm BEFORE emitting the UI token so a typed "sí" / dialog
        # click never races a not-yet-set flag, and a failed preview
        # never leaves a dead confirm button visible. entries=[:1] is
        # intentional (B028/RT-04: best global match only, no cross-
        # collection collateral — identical to the non-stream path).
        _df = _del_fact.strip()
        _armed = False
        if _df and not getattr(ctx.session, "_pending_partial_delete", None):
            try:
                _preview = await ctx.memory_helper.preview_delete_from_memory(_df)
                _cands = _preview.get("candidates", [])
                if _preview.get("success") and _cands:
                    ctx.session._pending_partial_delete = {"content": _df, "entries": _cands[:1]}
                    _armed = True
            except Exception:
                logger.debug("MC-117: preview_delete_from_memory failed in stream", exc_info=True)
        # TUR-PHANTOM-DEL: surface the confirm-dialog token ONLY when THIS
        # fact actually armed a pending delete. A failed/empty/raising
        # preview (Memory API down, or the common "forget X not stored"
        # case → success but candidates=[]) must NOT leave a dead confirm
        # button — parity with the non-stream _arm_mem_deletes_nonstreaming,
        # which only emits the token on success+candidates. This is the
        # invariant the MC-117 comment above already declares.
        if _armed:
            yield f"\x00[PENDING_DELETE:{_encoded}]\x00"


async def _yield_reprompt_when_only_mem_saves(
    ctx: "StreamingChatContext", clean_response: str, mem_saves: list, rp_out: list,
):
    """Re-prompt (or fall back) when the turn produced only [MEM_SAVE: ...].

    No-op unless the visible response is empty AND there are mem_saves. On the
    fallback path the confirmation text is BOTH yielded and appended to
    `rp_out`, so the caller assigns `clean_response = rp_out[0]` for either
    outcome — the split the inline `if/else` used to make.
    """
    if clean_response or not mem_saves:
        return
    if policy.reprompt_enabled():
        async for _chunk in _yield_reprompt(
            ctx.engine, ctx.model_name, ctx.sig, ctx.lang,
            ctx.system_prompt, ctx.messages, mem_saves,
            ctx.thinking_enabled, rp_out,
        ):
            yield _chunk
    if not rp_out:
        _fallback = policy.mem_save_fallback_text(mem_saves)
        if _fallback:
            rp_out.append(_fallback)
            yield _fallback
            logger.info("Re-prompt fallback: confirmation message")


def _persist_assistant_turn(
    ctx: "StreamingChatContext",
    clean_response: str,
    full_response: str,
    stats: dict,
    trunc: bool,
    trunc_continuable: bool,
) -> None:
    """Write the assistant turn into the session (FD-S6 merge or add_message).

    Sync on purpose: it is called from the streaming body between
    `_save_session_to_disk` and the `_assistant_saved` flag, and that ordering
    is what keeps the single-persist contract (INV-CRIT-03) intact — an `await`
    here would open a cancellation point in the middle of it.
    """
    if ctx.continue_mode and ctx.session.messages \
            and ctx.session.messages[-1].get("role") == "assistant":
        # FD-S6: MERGE the tail into the truncated turn — direct
        # concatenation, no separator (the tail resumes mid-sentence).
        # Never add_message: get_context_messages dedupes consecutive
        # assistant turns keeping only the LATEST, which would erase
        # the first half of the answer.
        _last = ctx.session.messages[-1]
        _last["content"] += clean_response
        if trunc and trunc_continuable:
            # Chained continue (truncated again): extend the raw so
            # the NEXT continue prompt stays an exact token prefix.
            if _last.get("gen_raw"):
                _last["gen_raw"] += full_response
            else:
                _last["gen_raw"] = _last["content"]
        else:
            _last.pop("gen_raw", None)  # completed: drop the raw
    else:
        ctx.session.add_message("assistant", clean_response, stats=stats)
        if trunc and trunc_continuable and ctx.session.messages:
            # FD-S6: persist the RAW generation next to the clean
            # content. With thinking ON the clean text's re-render
            # diverges token-wise from the KV cache entry — gen_raw is
            # what makes the future continue prompt an exact prefix.
            ctx.session.messages[-1]["gen_raw"] = full_response


def _persist_partial_assistant(ctx: "StreamingChatContext", full_response: str) -> None:
    """Best-effort persist of an interrupted turn (MC-116), for the `finally`.

    Sync on purpose: the caller runs this while unwinding a GeneratorExit, where
    awaiting is not an option. Never raises — a failure to save a partial turn
    must not replace the original teardown.
    """
    try:
        _partial_clean, _, _ = _clean_full_response(full_response, ctx.message)
        _partial_clean = _think_only_placeholder(_partial_clean, full_response)
        if _partial_clean and ctx.continue_mode and ctx.session.messages \
                and ctx.session.messages[-1].get("role") == "assistant":
            # FD-S6 (MC-116): interrupted continue → merge the partial
            # tail in-place, same no-separator contract as the clean
            # path (add_message would trip the consecutive-role dedupe).
            ctx.session.messages[-1]["content"] += _partial_clean
            ctx.session.messages[-1].pop("gen_raw", None)
        elif _partial_clean:
            ctx.session.add_message("assistant", _partial_clean, stats={"interrupted": True})
            ctx.session_mgr._save_session_to_disk(ctx.session)
    except Exception:
        logger.warning("MC-116: could not persist partial assistant on stream interruption", exc_info=True)


async def _generate_streaming_response(ctx: StreamingChatContext):
    """Streaming response body, flattened out of `_handle_chat_engine` (MC-027 F2).

    All request-scoped state is carried explicitly on `ctx` instead of closure
    free-vars. `full_response` / `clean_response` / `_assistant_saved` stay BARE
    LOCALS (single-persist idempotency + the B125 getsource sentinel). The
    disconnect-monitor ownership handoff stays in `_handle_chat_engine` (which sets
    `_returning_stream` before returning the StreamingResponse); this generator only
    cancels the monitor on a clean finish (INV-CRIT-01). Behaviour is byte-equivalent
    to the inline closure it replaces.

    The phases live in `_yield_*` / `_persist_*` helpers (2026-08-20, CCN 66 -> 20);
    what stays here is the sequence, the three bare locals, and the accumulation of
    `full_response` at the yield site. The engine loop reports its truncation and
    thinking flags back on a `_StreamFlags`, since a generator cannot return while
    it yields.
    """
    _assistant_saved = False  # MC-116
    try:
        full_response = ""
        _mem_saves = []  # init here so fallback extractor never hits UnboundLocalError
        async for _h in _yield_response_headers(
            ctx.model_name, ctx.rag_count, ctx.rag_items, ctx.compacted,
            ctx.session.compaction_count, ctx.doc_truncated_pct,
        ):
            yield _h

        # Check if model is loaded (Ollama, MLX, llama.cpp)
        async for _tok in _yield_model_loading_check(ctx.engine, ctx.model_name, ctx.engine_name):
            yield _tok

        import time as _time_mod
        _stream_start_t = _time_mod.time()
        _flags = _StreamFlags()
        # The pairs are (wire token | None, text to accumulate). `full_response`
        # grows HERE, at the same point the inline loop grew it — before the
        # chunk's wire tokens go out — so a disconnect mid-stream leaves the
        # partial text for the MC-116 persist in the `finally`.
        async for _tok, _full_delta in _yield_engine_chunks(ctx, _flags):
            full_response += _full_delta
            if _tok is not None:
                yield _tok

        if not _flags.has_any_thinking:
            logger.info("Model did not produce thinking tokens (model decides when to think)")

        # Save clean response (no think/GPT-OSS tags) to session/disk
        clean_response, _mem_saves, _mem_deletes = _clean_full_response(full_response, ctx.message)

        # FD-S5: tell the client the answer was cut by the token ceiling.
        # Its OWN yield (a marker split across reads would not be parsed).
        _trunc_tok = _gen_truncated_token(
            _flags.trunc, _flags.trunc_continuable, clean_response,
        )
        if _trunc_tok:
            yield _trunc_tok

        async for _del_tok in _yield_mem_delete_prompts(ctx, _mem_deletes):
            yield _del_tok

        # Re-prompt: if the model emitted ONLY [MEM_SAVE: ...] without
        # a conversational response, resend with system prompt without
        # MEM_SAVE instructions so it generates a natural response.
        _rp_out = []
        async for _chunk in _yield_reprompt_when_only_mem_saves(
            ctx, clean_response, _mem_saves, _rp_out,
        ):
            yield _chunk
        if _rp_out:
            clean_response = _rp_out[0]

        # B125: persist a placeholder for a think-only turn so
        # the next user message is not dropped as a duplicate role.
        if not clean_response and full_response:
            logger.info("Think-only turn: persisting placeholder assistant message (B125)")
        clean_response = _think_only_placeholder(clean_response, full_response)

        if clean_response:
            # C3.3: the same core write both doors use. This path (the pre-C1.3
            # streaming body, kept for `continue`) still has a listener on the
            # wire, so it keeps emitting its own sentinels — unlike the queued
            # step, where nobody is there to read them.
            # The spinner is only honest when something can actually be saved:
            # `[SAVING]` is cleared by `[MEM:n]`, and a turn that stores nothing
            # never sends one — the user was left with a spinner forever.
            if will_write(_mem_saves, ctx.session, ctx.rag_collections):
                yield "\x00[SAVING]\x00"
            _write = await write_facts(
                _mem_saves, ctx.session, ctx.memory_helper,
                engine=ctx.engine, model_name=ctx.model_name, sig=ctx.sig,
                lang=ctx.lang, rag_collections=ctx.rag_collections,
            )
            _mem_saves[:] = _write.facts
            _mem_saved_count = _write.saved
            if _mem_saved_count:
                yield f"\x00[MEM:{_mem_saved_count}]\x00"

            # Save message with stats for persistence
            _elapsed = round(_time_mod.time() - _stream_start_t, 1)
            _stats = _build_mem_stats(
                ctx.session, ctx.rag_count, ctx.rag_items, ctx.model_name,
                _elapsed, len(full_response), _mem_saved_count, _mem_saves,
            )
            _persist_assistant_turn(
                ctx, clean_response, full_response, _stats,
                _flags.trunc, _flags.trunc_continuable,
            )
            ctx.session_mgr._save_session_to_disk(ctx.session)
            _assistant_saved = True  # MC-116

            # #859: the NEXT turn will compact before it generates anything, and
            # compaction is a full LLM summarisation inside the critical path
            # (~100 s measured on 8 GB) with an empty screen in front of it.
            # We cannot warn while it runs: it happens before that request has
            # even produced response headers, so there is no stream to speak on.
            # The turn that fills the window warns about the one after it, and
            # the client can say so the instant the user hits send.
            # #965: same window the next turn's compaction will measure against,
            # or the warning and the compaction could disagree. Deferred import:
            # a plugin must not pull core at import time (layering gate, #471).
            from core.context_window import ask_engine_window
            if ctx.session.needs_compaction(ask_engine_window(ctx.engine)):
                yield "\x00[WILL_COMPACT:1]\x00"

        # Stream finished cleanly — release the disconnect
        # monitor so it doesn't keep polling forever.
        if not ctx.disconnect_monitor_task.done():
            ctx.disconnect_monitor_task.cancel()

    finally:
        # MC-116: a client disconnect (Stop / closed tab) tears down this
        # async generator via aclose()->GeneratorExit at the current yield,
        # so the normal persist path above is skipped (esp. non-MLX engines
        # where cancel_event is not wired). Persist a best-effort assistant
        # turn so the session isn't left with an orphan 'user' message.
        if not _assistant_saved and full_response:
            _persist_partial_assistant(ctx, full_response)


def _start_engine_call(
    engine, engine_name: str, sig, model_name, system_prompt: str, messages: list, *,
    stream: bool, image_b64, thinking_enabled: bool, cancel_event, sampling_kwargs: dict,
    session_id: str, _continue: bool,
):
    """Start the engine's generation and return its `chat_result` (a dict, a
    coroutine or an async generator, depending on the engine's shape).

    Three shapes: Ollama-style `chat(model, messages, stream=…)`, the in-process
    engines (MLX, llama.cpp) driven through a queue + background task, and the
    generic `chat(messages, system=…)`. Extracted verbatim out of
    `_handle_chat_engine` on 2026-09-06 (ADR-007 C1.3) so the turn adapters and
    the `continue` path share one copy; the bodies are untouched (hot streaming
    path).
    """
    # Ollama/MLX/LlamaCpp expect base64 strings, not bytes
    _images_arg = [image_b64] if image_b64 else None

    # cancel_event covers the in-process engines (MLX and
    # llama.cpp): both run a synchronous generation loop in a
    # worker thread that won't notice an HTTP disconnect on its
    # own, so the handler sets the event and the loop breaks
    # early instead of running to max_tokens (orphan worker
    # blocking the model — MC-011). Ollama cancels naturally via
    # its httpx async transport when the asyncio task is
    # cancelled, so it doesn't need the event.
    cancel_kwargs = (
        {"cancel_event": cancel_event}
        if engine_name in ("mlx", "llama_cpp")
        else {}
    )

    if 'model' in sig.parameters:
        # Ollama-style: chat(model, messages, stream=...)
        # We inject system prompt as first message for Ollama
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        chat_result = engine.chat(model=model_name, messages=full_messages, stream=stream,
                                  images=_images_arg,
                                  thinking_enabled=thinking_enabled,
                                  **cancel_kwargs, **sampling_kwargs)
    else:
        # MLX/LlamaCpp-style: chat(messages, system=...)
        if engine_name in ("mlx", "llama_cpp"):
            # MLX module requires a callback for streaming
            queue: asyncio.Queue = asyncio.Queue()

            _stream_chunk_count = [0]

            # B023: `stream_cb` and `queue_generator` below outlive the
            # iteration that built them — the engine task keeps
            # running while the cascade may already be on the next
            # engine, and a free name would then read THAT engine's
            # queue. The defaults pin each closure to the objects of
            # its own turn; the bodies are untouched on purpose (hot
            # streaming path).
            def stream_cb(token, *, _stream_chunk_count=_stream_chunk_count, queue=queue):
                # MLXChatNode already marshals this to the main loop, so we can just put in queue
                _stream_chunk_count[0] += 1
                if _stream_chunk_count[0] <= 3 or _stream_chunk_count[0] % 50 == 0:
                    logger.debug("stream_cb: chunk #%d (%d chars)", _stream_chunk_count[0], len(token))
                queue.put_nowait(token)

            # FD-S6: continue only reaches the MLX text path
            # (the marker is only :1 there). llama_cpp would
            # silently ignore the kwarg and REPEAT — hard gate.
            _continue_kwargs = {}
            if _continue:
                if engine_name != "mlx":
                    raise ValueError(
                        "continue is only supported on the MLX engine"
                    )
                _continue_kwargs = {"continue_final": True}
            # Launch chat in background task
            # B007 (1b): session_id scopes the prefix-cache key —
            # without it every conversation shares ":default".
            ml_task = asyncio.create_task(engine.chat(
                messages=messages, system=system_prompt, stream_callback=stream_cb,
                session_id=session_id,
                images=_images_arg, thinking_enabled=thinking_enabled,
                **_continue_kwargs, **cancel_kwargs, **sampling_kwargs,
            ))

            # Async generator that yields from queue until task is done
            async def queue_generator(*, queue=queue, ml_task=ml_task):
                while True:
                    # Check if queue has items first
                    if not queue.empty():
                        yield await queue.get()
                        continue

                    # If queue is empty, check if task is done
                    if ml_task.done():
                        # If task failed, re-raise exception
                        _exc = ml_task.exception()
                        if _exc is not None:
                            raise _exc
                        # FD-S5: the engine's result dict was
                        # discarded here — finish_reason died
                        # with it. Surface the truncation as
                        # an in-band sentinel. Defensive
                        # isinstance: llama_cpp shares this
                        # branch with its own result shape.
                        _res = ml_task.result()
                        if (
                            isinstance(_res, dict)
                            and _res.get("finish_reason") == "length"
                        ):
                            yield {
                                "__nexe_trunc__": True,
                                "continuable": bool(_res.get("continuable")),
                            }
                        break

                    # Wait for new tokens with short timeout
                    try:
                        token = await asyncio.wait_for(queue.get(), timeout=0.05)
                        yield token
                    except asyncio.TimeoutError:
                        continue

            chat_result = queue_generator()

        else:
            # Generic engine: only pass session_id if accepted.
            _sid_kwargs = (
                {"session_id": session_id}
                if "session_id" in sig.parameters else {}
            )
            chat_result = engine.chat(messages=messages, system=system_prompt,
                                      images=_images_arg,
                                      thinking_enabled=thinking_enabled,
                                      **_sid_kwargs,
                                      **cancel_kwargs, **sampling_kwargs)

    return chat_result


def register_chat_routes(router: APIRouter, *, session_mgr, require_ui_auth):
    """Registers endpoint: POST /chat"""

    # P0-3's lock around body.model singleton mutations now lives with the
    # switch it guards (core.endpoints.chat_engines.model_switch), because what
    # it protects — LlamaCppChatNode._pool / MLXChatNode._model — is
    # process-global while this function runs once per router. Its reasoning is
    # unchanged and is written there: server-nexe is architecturally mono-user
    # (workers=1, class-level singletons), so the race is a breadcrumb for a
    # future multi-user design rather than something seen in the field.

    # -- POST /chat --
    #    ~550 lines: intent detection, RAG, compaction,
    #    multi-engine, streaming

    @router.post("/chat", operation_id="webui_chat")
    @limiter.limit("20/minute")
    async def chat(request: FastAPIRequest, body: Dict[str, Any], _auth=Depends(require_ui_auth)):
        """Chat endpoint with streaming and memory intent detection.

        Concurrency is the engine gate's job now (ADR-007 §7, C2.1,
        core/turn/gate.py) — held by `generate_stream`/`generate_json` for as
        long as their body is being driven, not by this route for as long as
        it takes to get a `StreamingResponse` OBJECT back (that used to be the
        whole of the old `Semaphore(2)` here: it released before a single
        token was generated).
        """
        return await _chat_inner(request, body, _auth)

    async def _handle_chat_engine(
        body: dict,
        session,
        memory_helper,
        message: str,
        request: FastAPIRequest,
    ) -> tuple[str, Optional[str], Any, "NonStreamRepromptContext | None"]:
        """Returns (response_text, model_name, streaming_response_or_None, reprompt_ctx).

        `reprompt_ctx` és el que #856 necessita al camí no-streaming (re-prompt);
        és None si cap engine ha arribat a preparar el torn.
        """
        model_name = None
        # #856: el context del re-prompt es capta dins el bucle d'engines, quan
        # el torn ja està preparat. S'inicialitza AQUÍ, abans de qualsevol
        # `try`, perquè el retorn del camí d'error (get_server_state() que peta,
        # cap engine viu) el troba definit igualment — inicialitzar-lo a dins
        # feia que aquell retorn petés amb UnboundLocalError i el 200 degradat
        # es convertís en un 500.
        _reprompt_ctx: "NonStreamRepromptContext | None" = None
        image_b64 = body.get("image_b64")
        stream = body.get("stream", False)
        # FD-S6: continue mode — resume the last assistant turn.
        _continue = body.get("continue") is True
        # Opt-in nucleus sampling from the UI body → forwarded to every engine.
        # Empty dict when absent so the engine keeps its current default.
        _top_p = parse_top_p(body)
        sampling_kwargs = {"top_p": _top_p} if _top_p is not None else {}

        # Cancellation propagation (Bug C handoff, fix 2026-05-14): when the
        # HTTP client disconnects (UI Stop button → AbortController) we set
        # this event so the MLX worker thread can break out of its streaming
        # loop instead of running to max_tokens. Without this, the
        # single-worker MLX executor stays busy ~100s after the user clicks
        # Stop, blocking every subsequent request.
        cancel_event, _disconnect_monitor_task = _start_disconnect_monitor(request)
        # When we return a StreamingResponse, ownership of the monitor task
        # transfers to response_generator (which cancels it after the
        # generator finishes). The non-streaming path cancels it from the
        # finally block.
        # The flag prevents premature cancel between `return StreamingResponse`
        # and the first client read.
        _returning_stream = False
        # Normal chat - Auto-detect and use available LLM engine
        try:
            from core.lifespan import get_server_state
            import os

            # Deferred, like the ask_engine_window import above: a plugin must
            # not pull core at import time (layering gate, #471).
            from core.endpoints.chat_engines.model_switch import (
                model_switch_lock,
                switch_engine_model,
            )
            from core.endpoints.chat_engines.routing import (
                iter_live_engines,
                raise_if_terminal,
                resolve_engine_cascade,
            )

            module_manager = get_server_state().module_manager
            if module_manager is None:
                raise HTTPException(status_code=503, detail="Service unavailable: module manager not initialized")
            # Prioritize model/backend from request (UI selector) over env vars
            model_name = body.get("model") or os.getenv("NEXE_DEFAULT_MODEL", "llama3.2:3b")
            if len(model_name) > 100:  # type: ignore[arg-type]  # model_name: Any|str|None; os.getenv default prevents None in practice
                raise HTTPException(status_code=400, detail="Model name too long (max 100 chars)")
            preferred_engine = (body.get("backend") or os.getenv("NEXE_MODEL_ENGINE", "auto")).lower()  # type: ignore[union-attr]  # Any|str|None .lower(); os.getenv default "auto" prevents None

            # Log available modules
            available_modules = [m.name for m in module_manager.registry.list_modules()]
            logger.info(f"Available modules: {available_modules}")

            # F-D block 5: which engines to try, and which of them are live,
            # both come from the core resolver. What was here was a second
            # engine table with its own alias map ("llamacpp" and nothing else)
            # and its own five-deep walk (registry → .instance →
            # get_module_instance() → .chat) — a walk the loader had already
            # done once at startup, whose result is exactly what
            # get_engine_module reads. Neither copy was node-aware, so a module
            # registered with a dead node was dispatched to here while /status
            # reported it down.
            #
            # The names in this loop are the core's canonical ones now ("mlx",
            # not "mlx_module"). What the user sees does not change: the UI
            # strips "_module" before upper-casing the MODEL_LOADING label, so
            # both spellings render "MLX".
            _cascade = resolve_engine_cascade(preferred_engine, request.app.state)
            logger.info("Engine cascade for this turn: %s", _cascade)

            response_text = None  # type: ignore[assignment]  # Optional[str] by design, initialized None and assigned post-engine
            for engine_name, engine in iter_live_engines(_cascade, request.app.state):
                logger.info(f"Trying engine: {engine_name}")
                try:
                    # Resolve local model path if coming from the UI selector.
                    # The lock serialises concurrent swaps of class-level
                    # singletons; the env dance that builds the new config
                    # (mutated for the minimum time and always restored — P0-3
                    # env leak) now lives inside each engine module, which is
                    # the only place that knows its own config.
                    if body.get("model"):
                        async with model_switch_lock():
                            await switch_engine_model(engine, engine_name, model_name)

                    # Per-session thinking toggle
                    thinking_enabled = getattr(session, "thinking_enabled", False)

                    logger.info(f"Calling {engine_name}.chat with model={model_name} thinking={thinking_enabled}")

                    # --- Context Compacting + Build Context ---
                    # Three helpers (MC-026/MC-027). Still inside the engine
                    # loop, exactly as before — what moved out of this function
                    # is ~130 lines of pure data preparation with no response
                    # I/O in them, which is what took it to CCN 58.
                    _turn = await _build_turn_context(
                        body, session, session_mgr, engine, message, _continue,
                    )
                    system_prompt, _lang = _build_turn_system_prompt(
                        body, session, message, _continue,
                        # C4.2: the same state the turn's `system_prompt` step
                        # hands over (`ctx.app_state`), so a `continue` resolves
                        # the base prompt from where the turn it resumes did —
                        # the two must land in the same prefix-cache namespace.
                        app_state=request.app.state,
                    )
                    # C4.2: the clock is a step of the turn now, and this path
                    # does not walk the map — it resolves the same line itself
                    # instead of the assembler doing it behind its back.
                    _clock_line = time_context_line(message, _lang)
                    messages, _doc_truncated_pct = _assemble_engine_messages(
                        _turn, system_prompt, _lang, message, session, _continue,
                        engine, clock_line=_clock_line,
                    )
                    response_chunks: list[str] = []

                    # When an image is attached, wrap with context block (same pattern as documents)
                    if image_b64:
                        messages = _inject_image_block(messages)

                    # Adapt to different chat signatures
                    import inspect
                    sig = inspect.signature(engine.chat)

                    # #856: el re-prompt del camí no-streaming necessita aquests
                    # locals, que moren en sortir d'aquí. Es capturen ara, que
                    # són vius, i viatgen amb el retorn.
                    _reprompt_ctx = NonStreamRepromptContext(
                        engine=engine, model_name=model_name, sig=sig, lang=_lang,
                        system_prompt=system_prompt, messages=messages,
                        thinking_enabled=thinking_enabled,
                    )

                    chat_result = _start_engine_call(
                        engine, engine_name, sig, model_name, system_prompt, messages,
                        stream=stream, image_b64=image_b64, thinking_enabled=thinking_enabled,
                        cancel_event=cancel_event, sampling_kwargs=sampling_kwargs,
                        session_id=session.id, _continue=_continue,
                    )

                    # Flag if compacted to notify the client
                    _compacted = session.compaction_count > 0 and session.context_summary is not None

                    if stream:
                        _stream_ctx = StreamingChatContext(
                            model_name=model_name,
                            rag_count=_turn.rag_count,
                            rag_items=_turn.rag_items,
                            compacted=_compacted,
                            doc_truncated_pct=_doc_truncated_pct,
                            session=session,
                            session_mgr=session_mgr,
                            memory_helper=memory_helper,
                            engine=engine,
                            engine_name=engine_name,
                            chat_result=chat_result,
                            sig=sig,
                            system_prompt=system_prompt,
                            messages=messages,
                            thinking_enabled=thinking_enabled,
                            lang=_lang,
                            message=message,
                            disconnect_monitor_task=_disconnect_monitor_task,
                            rag_collections=body.get("rag_collections"),
                            continue_mode=_continue,
                        )
                        _returning_stream = True
                        return "", model_name, StreamingResponse(
                            _generate_streaming_response(_stream_ctx),
                            media_type="text/plain",
                            headers={
                                "Cache-Control": "no-cache, no-store",
                                "X-Accel-Buffering": "no",
                                "X-Content-Type-Options": "nosniff",
                                # The session this turn was stored in. The JSON
                                # path already returns it; streaming did not, so
                                # a client that lost its id (or never learned the
                                # one the server minted for it) had no way back
                                # and silently started a new conversation on the
                                # next message, orphaning everything before it.
                                "X-Session-Id": session.id,
                            }
                        ), _reprompt_ctx

                    # Handle non-streaming response accumulation
                    await _accumulate_nonstreaming_response(chat_result, response_chunks)

                    response_text = "".join(response_chunks)
                    if response_text:
                        logger.info(f"{engine_name} succeeded!")
                        break
                except Exception as e:
                    # F-D block 5: which errors end the turn and which are worth
                    # another engine is one decision, and it lives in the core
                    # (engine_error_to_http) instead of four except clauses here
                    # — /v1 had none of them and turned every engine failure
                    # into a 500.
                    raise_if_terminal(e, engine_name)
                    logger.warning(f"{engine_name} failed: {e}")
                    logger.debug("Engine error details:", exc_info=True)
                    continue

            if not response_text:
                # D-I phase 2 / #884: this is a failed request, not an
                # assistant turn. 200 + error-string painted the phrase
                # inside the chat bubble (app.js only errors when not ok).
                raise HTTPException(
                    status_code=503,
                    detail="No AI engine available",
                )
        except HTTPException:
            # Make sure the disconnect monitor doesn't outlive a 4xx/5xx exit.
            if not _disconnect_monitor_task.done():
                _disconnect_monitor_task.cancel()
            raise
        except Exception as e:
            # MC-133: log the detail (with traceback) but never echo str(e) to the
            # response body — it can carry internal paths/state. The user-facing
            # text stays generic (kept English to match the sibling fallback above,
            # since _lang may be unset this early in the catch-all).
            logger.error("Error calling LLM: %s", e, exc_info=True)
            response_text = "Error: an internal error occurred while generating the response."
        finally:
            # Only cancel monitor if NOT returning a stream. For streams the
            # response_generator owns the monitor and cancels it after [DONE];
            # cancelling here would kill the monitor before the client even
            # starts reading the response.
            if not _returning_stream and not _disconnect_monitor_task.done():
                _disconnect_monitor_task.cancel()

    # Strip MEM_SAVE tags and extract facts (non-streaming path)
        return response_text or "", model_name, None, _reprompt_ctx


    async def _chat_inner(request: FastAPIRequest, body: Dict[str, Any], _auth):
        """Inner chat logic, called under semaphore."""
        session_id = body.get("session_id")
        # RT-10: clean 400 for malformed/traversal session ids (see routes_files).
        if session_id is not None and not session_mgr.is_valid_session_id(session_id):
            raise HTTPException(status_code=400, detail="Invalid session_id")
        stream = body.get("stream", False)

        # ── FD-S6: Continue — resume the last (truncated) assistant turn ──
        # Dedicated branch BEFORE the turn's `validate` step (which 400s an empty
        # message). No new user message is persisted, no intent detection, no
        # compaction, no doc/RAG injection: the engine re-enters the last
        # assistant message with continue_final=True and the tail merges
        # in-place. Server-side stateless: everything derives from the
        # session history at click time.
        if body.get("continue") is True:
            if not session_id:
                raise HTTPException(
                    status_code=400, detail="continue requires session_id"
                )
            _c_session = session_mgr.get_or_create_session(session_id)
            if (
                not _c_session.messages
                or _c_session.messages[-1].get("role") != "assistant"
            ):
                raise HTTPException(
                    status_code=400,
                    detail="continue requires the last message to be an assistant turn",
                )
            # The last REAL user message drives language detection + system.
            _last_user = next(
                (m.get("content", "") for m in reversed(_c_session.messages)
                 if m.get("role") == "user"),
                "",
            )
            # El 4t element (context de re-prompt de #856) no aplica al camí
            # continue: aquí no hi ha extracció de MEM_SAVE ni cos buit a cobrir
            # — el torn es reprèn i el text es fusiona amb l'anterior.
            response_text, model_name, _streaming_resp, _ = await _handle_chat_engine(
                body, _c_session, memory_facts.helper_for(request.app.state), _last_user, request
            )
            if _streaming_resp is not None:
                return _streaming_resp
            # Non-streaming continue: merge the tail in-place (same contract
            # as the streaming finally).
            if response_text and not response_text.startswith("Error:"):
                _c_session.messages[-1]["content"] += response_text
                _c_session.messages[-1].pop("gen_raw", None)
                session_mgr._save_session_to_disk(_c_session)
            return {
                "response": response_text,
                "session_id": _c_session.id,
                "intent": "chat",
                "memory_action": None,
            }

        # ADR-007 (C1.3): from here on this door no longer decides the order of
        # the turn. It builds a TurnContext and lets the engine walk TURN_STEPS;
        # every step is an adapter in `turn_adapters.py` wrapping the functions
        # this body used to call. Two tables, one per wire format, because four
        # steps really differ between them. The `continue` branch above keeps
        # its own path on purpose (C1 plan, decision §5).
        ctx = TurnContext(
            turn_id=uuid4().hex,
            entry="ui",
            # C4.1 (#1044): WHO `require_ui_auth` authenticated, recorded on the
            # request by `auth_dependencies._remember_principal`. This door was
            # already fail-closed, so the turn's `authorize` step never fires
            # here — it is filled so there is ONE step, not a step and an
            # exception for the door that happened to be right.
            principal=getattr(getattr(request, "state", None), "principal", None),
            streaming=bool(stream),
            body=body,
            request=request,
            app_state=request.app.state,
        )
        adapters = ui_adapters(session_mgr, streaming=bool(stream))
        # C2.2: memory.write/compact go to the post-commit queue when a real
        # one is attached (production always has one — the lifespan attaches
        # it next to the engine gate); None here makes them run inline,
        # exactly as before C2.2 — the fallback pre-C2.2 test harnesses need.
        post_commit = queue_for(ctx.app_state)
        if stream:
            body_iterator = await stream_turn(ctx, adapters, post_commit=post_commit)
            return StreamingResponse(
                body_iterator,
                media_type="text/plain",
                headers={
                    "Cache-Control": "no-cache, no-store",
                    "X-Accel-Buffering": "no",
                    "X-Content-Type-Options": "nosniff",
                    # The session this turn was stored in (see the note in
                    # `_handle_chat_engine`): a client that lost its id has
                    # a way back.
                    "X-Session-Id": ctx.session.id,
                    # C2.0: one id to grep for in `turn.trace` log lines.
                    "X-Nexe-Turn-Id": ctx.turn_id,
                },
            )
        await run_turn(ctx, adapters, post_commit=post_commit)
        return ctx.wire
