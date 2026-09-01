/*
 * #127 slice 2 — processChunk, the streaming state machine, was a closure
 * inside sendMessage that MUTATED nine of its variables. Promoting it to a
 * method meant making that state explicit, so unlike slice 1 this is not a
 * verbatim move: every reference to the nine became `st.<name>`.
 *
 * Which is exactly why it needs this. The machine below is the PRE-MOVE
 * closure, pasted in unchanged (only the leading indentation was reduced —
 * not semantics in JS), rebuilt with its original nine `let`s. Both machines
 * get the same chunk sequences and both are compared after EVERY chunk: the
 * nine state values, and the side effects in order — setAiState,
 * _startStreamStats, _scheduleRender, _streamTokens, the think-block
 * open/close, and every write to the think DOM.
 *
 * The sequences are split at deliberately awkward boundaries, because that is
 * where a chunk state machine breaks: a `</think>` cut in half, `analysis`
 * arriving one character at a time, the GPT-OSS probe landing exactly on its
 * 30-character threshold.
 */
/*
 * Mutation-tested against the current method, 6 of 7 caught: the <think> tag
 * length, the 30-character GPT-OSS probe, both token counters, dropping the
 * retroactive-</think> branch, and losing the partial-tag tail of the buffer.
 *
 * The survivor is worth writing down so nobody hunts it twice. Changing
 * `thinkPart.trim().length > 10` to `> 0` does not fail, and no input can make
 * it fail: every route into 'responding' with empty tContent passes the
 * 30-character probe first, so fullResponse already holds more than ten
 * characters by the time a stray </think> can arrive; the one route that
 * arrives with a short fullResponse (the GPT-OSS final marker) leaves tContent
 * full, and the `!st.tContent` guard blocks it. An equivalent mutant, not a
 * coverage hole.
 */
import assert from 'node:assert';

import { loadNexeUI } from './lib/load_nexe_ui.mjs';

const NexeUI = loadNexeUI();

/* A recorder standing in for the think-block DOM. Writes are behaviour here:
 * the token counter and the think text are what the user sees while a model
 * reasons, and a state machine that stops updating them is broken even if its
 * final string is right. */
function makeThinkDom(log, tag) {
    const tokens = { set textContent(v) { log.push(`${tag}.tokens=${v}`); } };
    const block = {
        querySelector: (sel) => (sel === '.think-tokens' ? tokens : { set textContent(v) { log.push(`${tag}.label=${v}`); } }),
        removeAttribute: (a) => log.push(`${tag}.removeAttr(${a})`),
    };
    const text = {
        _v: '',
        get textContent() { return this._v; },
        set textContent(v) { this._v = v; log.push(`${tag}.text=${JSON.stringify(v)}`); },
        set scrollTop(v) { log.push(`${tag}.scrollTop`); },
        get scrollHeight() { return 42; },
    };
    return { block, text };
}

function makeHost(log) {
    return {
        _streamTokens: 0,
        setAiState(s) { log.push(`setAiState(${s})`); },
        _startStreamStats() { log.push('startStreamStats'); },
        _scheduleRender(div, txt) { log.push(`render(${JSON.stringify(txt)})`); },
        _cleanModelTags: NexeUI.prototype._cleanModelTags,
        // Slice 3 unified four inline [MEM_SAVE:] replaces into this helper.
        // The OLD machine below still runs its own inline regex, so this file
        // now also proves that de-duplication changed nothing.
        _extractMemSave: NexeUI.prototype._extractMemSave,
    };
}

// ── the PRE-MOVE machine, verbatim, with its original closure variables ─────
function makeOldMachine(log) {
    const host = makeHost(log);
    const dom = makeThinkDom(log, 'old');
    const assistantMessageDiv = { id: 'msg' };
    let tMode = 'init';
    let tBuf  = '';
    let tContent = '';
    let tTok = 0;
    let tBlock = null;
    let tTextEl = null;
    let tGptOssChecked = false;
    let tIsGptOss = false;
    let fullResponse = '';
    const startThinkBlock = () => { log.push('startThinkBlock'); tBlock = dom.block; tTextEl = dom.text; };
    const closeThinkBlock = () => {
        log.push('closeThinkBlock');
        if (!tBlock) return;
        tBlock.querySelector('.think-tokens').textContent = `~${tTok} tok`;
    };
    const self = {
        feed: null,
        state: () => ({ tMode, tBuf, tContent, tTok, tGptOssChecked, tIsGptOss, fullResponse,
                        hasBlock: tBlock !== null, hasText: tTextEl !== null,
                        streamTokens: host._streamTokens }),
    };
    (function () {
    const processChunk = (raw) => {
        tBuf += raw;
        while (tBuf.length > 0) {
            if (tMode === 'init') {
                const s = tBuf.indexOf('<think>');
                if (s >= 0) {
                    tMode = 'thinking';
                    tBuf = tBuf.slice(s + 7);
                    startThinkBlock();
                } else if (!tGptOssChecked && fullResponse.length + tBuf.length >= 30) {
                    // Check for GPT-OSS "analysis...final" format
                    tGptOssChecked = true;
                    const combined = (fullResponse + tBuf).toLowerCase().trimStart();
                    if (combined.startsWith('analysis')) {
                        tIsGptOss = true;
                        tMode = 'thinking';
                        tContent = fullResponse + tBuf;
                        fullResponse = '';
                        tBuf = '';
                        startThinkBlock();
                        if (tTextEl) tTextEl.textContent = tContent.replace(/^analysis\s*/i, '');
                        tTok = Math.ceil(tContent.length / 4);
                        break;
                    } else {
                        // Not GPT-OSS — direct response
                        tMode = 'responding';
                        this.setAiState('streaming');
                        this._startStreamStats();
                    }
                } else if (tGptOssChecked && tBuf.trimStart().length > 0 && !tBuf.trimStart().startsWith('<')) {
                    // First char is not a tag — direct response
                    tMode = 'responding';
                    this.setAiState('streaming');
                    this._startStreamStats();
                } else if (tBuf.length > 7 && tGptOssChecked) {
                    // Large buffer without <think> — direct response
                    tMode = 'responding';
                    this.setAiState('streaming');
                    this._startStreamStats();
                } else if (tBuf.trimStart().length > 0 && !tBuf.trimStart().startsWith('<') && tBuf.length < 30 && !tGptOssChecked) {
                    // Could be GPT-OSS — wait for more data
                    fullResponse += tBuf;
                    tBuf = '';
                    break;
                } else {
                    break; // wait for more data
                }
            } else if (tMode === 'thinking' && tIsGptOss) {
                // GPT-OSS thinking mode: accumulate and look for end marker
                tContent += tBuf;
                tBuf = '';
                const displayContent = tContent.replace(/^analysis\s*/i, '');
                if (tTextEl) {
                    tTextEl.textContent = displayContent;
                    tTextEl.scrollTop = tTextEl.scrollHeight;
                }
                tTok = Math.ceil(tContent.length / 4);
                const tokEl = tBlock?.querySelector('.think-tokens');
                if (tokEl) tokEl.textContent = `~${tTok} tok`;
                // Look for end marker: "assistantfinal" or standalone "final"
                const endMatch = tContent.match(/(assistant\s*final|(?<!\w)final)(.*)$/is);
                if (endMatch) {
                    const markerIdx = tContent.lastIndexOf(endMatch[1]);
                    let thinkText = tContent.substring(0, markerIdx).replace(/^analysis\s*/i, '').trim();
                    // Extract MEM_SAVE from thinking → move to fullResponse for badge
                    const _memGpt = [];
                    thinkText = thinkText.replace(/\[MEM_SAVE:\s*(.+?)\]\s*/g, (_, f) => {
                        _memGpt.push(f);
                        return '';
                    });
                    if (tTextEl) tTextEl.textContent = thinkText;
                    tTok = Math.ceil(thinkText.length / 4);
                    closeThinkBlock();
                    tMode = 'responding';
                    fullResponse = endMatch[2].trimStart();
                    // Inject MEM_SAVE AFTER fullResponse assignment (not before — it overwrites)
                    if (_memGpt.length > 0) {
                        fullResponse += '\n' + _memGpt.map(f => `[MEM_SAVE: ${f}]`).join('\n');
                    }
                    this.setAiState('streaming');
                    this._startStreamStats();
                    if (fullResponse) {
                        this._streamTokens += Math.ceil(fullResponse.length / 4);
                        this._scheduleRender(assistantMessageDiv, fullResponse);
                    }
                }
                break;
            } else if (tMode === 'thinking') {
                const e = tBuf.indexOf('</think>');
                if (e >= 0) {
                    tContent += tBuf.slice(0, e);
                    // Extract MEM_SAVE from thinking → move to fullResponse for badge
                    const _memInThink = [];
                    tContent = tContent.replace(/\[MEM_SAVE:\s*(.+?)\]\s*/g, (_, f) => {
                        _memInThink.push(f);
                        return '';
                    });
                    if (_memInThink.length > 0) {
                        fullResponse += _memInThink.map(f => `[MEM_SAVE: ${f}]`).join('\n') + '\n';
                    }
                    tTok += Math.ceil(tContent.length / 4);
                    if (tTextEl) tTextEl.textContent = tContent;
                    tBuf = tBuf.slice(e + 8).replace(/^\n+/, '');
                    tMode = 'responding';
                    closeThinkBlock();
                    this.setAiState('streaming');
                    this._startStreamStats();
                } else {
                    // Keep possible partial tag at end
                    const partial = Math.min(8, tBuf.length);
                    let keepFrom = tBuf.length;
                    for (let i = partial; i > 0; i--) {
                        if ('</think>'.startsWith(tBuf.slice(-i))) { keepFrom = tBuf.length - i; break; }
                    }
                    tContent += tBuf.slice(0, keepFrom);
                    if (tTextEl) {
                        tTextEl.textContent = tContent;
                        tTextEl.scrollTop = tTextEl.scrollHeight;
                    }
                    tTok = Math.ceil(tContent.length / 4);
                    const tokEl = tBlock?.querySelector('.think-tokens');
                    if (tokEl) tokEl.textContent = `~${tTok} tok`;
                    tBuf = tBuf.slice(keepFrom);
                    break;
                }
            } else { // responding
                // Detect retroactive </think> (DeepSeek without opening <think>)
                const closIdx = tBuf.indexOf('</think>');
                if (closIdx >= 0 && !tContent) {
                    const thinkPart = fullResponse + tBuf.slice(0, closIdx);
                    if (thinkPart.trim().length > 10) {
                        tContent = thinkPart.trim();
                        tTok = Math.ceil(tContent.length / 4);
                        startThinkBlock();
                        if (tTextEl) tTextEl.textContent = tContent;
                        closeThinkBlock();
                        fullResponse = '';
                        this._streamTokens = 0;
                        tBuf = tBuf.slice(closIdx + 8).replace(/^\n+/, '');
                        continue;
                    }
                }
                // [MEM_SAVE: ...] tags pass through — stripped at final render (post-streaming)
                tBuf = this._cleanModelTags(tBuf);
                fullResponse += tBuf;
                this._streamTokens += Math.ceil(tBuf.length / 4);
                this._scheduleRender(assistantMessageDiv, fullResponse);
                tBuf = '';
            }
        }
    };
        self.feed = processChunk;
    }).call(host);
    return self;
}

// ── the machine as it is now ────────────────────────────────────────────────
function makeNewMachine(log) {
    const host = makeHost(log);
    const dom = makeThinkDom(log, 'new');
    const st = {
        tMode: 'init', tBuf: '', tContent: '', tTok: 0, tBlock: null, tTextEl: null,
        tGptOssChecked: false, tIsGptOss: false, fullResponse: '',
    };
    const ctx = {
        assistantMessageDiv: { id: 'msg' },
        startThinkBlock: () => { log.push('startThinkBlock'); st.tBlock = dom.block; st.tTextEl = dom.text; },
        closeThinkBlock: () => {
            log.push('closeThinkBlock');
            if (!st.tBlock) return;
            st.tBlock.querySelector('.think-tokens').textContent = `~${st.tTok} tok`;
        },
    };
    return {
        feed: (raw) => NexeUI.prototype._processChunk.call(host, st, ctx, raw),
        state: () => ({ tMode: st.tMode, tBuf: st.tBuf, tContent: st.tContent, tTok: st.tTok,
                        tGptOssChecked: st.tGptOssChecked, tIsGptOss: st.tIsGptOss,
                        fullResponse: st.fullResponse,
                        hasBlock: st.tBlock !== null, hasText: st.tTextEl !== null,
                        streamTokens: host._streamTokens }),
    };
}

// ── the sequences ───────────────────────────────────────────────────────────
const chars = (s) => [...s];               // one character per chunk
const SEQS = {
    'plain answer, one chunk': ['just an answer, no tags anywhere'],
    'plain answer, char by char': chars('hello there'),
    'think block, clean split': ['<think>', 'reasoning here', '</think>', 'the answer'],
    'think block, closing tag cut in half': ['<think>reasoning', '</thi', 'nk>the answer'],
    'think block, cut inside the opening tag': ['<thi', 'nk>reasoning</think>done'],
    'think block, char by char': chars('<think>abc</think>xyz'),
    'gpt-oss, over the 30-char probe': ['analysis' + 'x'.repeat(25), ' more thinking', 'assistantfinalTHE ANSWER'],
    'gpt-oss, exactly on the threshold': ['analysis' + 'y'.repeat(22), 'assistantfinalanswer'],
    'gpt-oss, standalone final marker': ['analysis' + 'z'.repeat(30), ' final the answer'],
    'gpt-oss, char by char': chars('analysis' + 'q'.repeat(24) + 'assistantfinalok'),
    'deepseek, retroactive close with no opener': ['a stretch of reasoning long enough to pass the guard', '</think>', 'the answer'],
    // Reaching the retroactive branch at all takes work: every route into
    // 'responding' with no think content runs through the 30-character GPT-OSS
    // probe first, so fullResponse is already long by the time a stray
    // </think> can arrive.
    'deepseek, retroactive close once responding has started':
        ['a plain answer with more than thirty characters here', 'and then</think>the real answer'],
    'deepseek, stray close that arrives before init resolves': ['tiny', '</think>', 'answer'],
    'MEM_SAVE inside a think block': ['<think>I should remember [MEM_SAVE: likes tea] this</think>ok'],
    'MEM_SAVE inside gpt-oss thinking': ['analysis' + 'w'.repeat(24) + '[MEM_SAVE: likes tea]', 'assistantfinaldone'],
    'model control tags in the response': ['plain <|channel|>hidden<|end|> text ', '\u25c1think\u25b7x\u25c1/think\u25b7 tail'],
    'empty chunks mixed in': ['', '<think>', '', 'r', '', '</think>', '', 'a'],
    'nothing at all': [''],
    'buffer just under the wait threshold': ['abc'],
    'tag-looking start that never becomes a tag': ['<notathing>', ' and then text'],
};

let seqs = 0, chunks = 0;
for (const [name, seq] of Object.entries(SEQS)) {
    const oldLog = [], newLog = [];
    const oldM = makeOldMachine(oldLog);
    const newM = makeNewMachine(newLog);
    seq.forEach((chunk, i) => {
        oldM.feed(chunk);
        newM.feed(chunk);
        const a = oldM.state(), b = newM.state();
        assert.deepStrictEqual(
            { ...b }, { ...a },
            `STATE DIVERGED in "${name}" after chunk ${i + 1}/${seq.length} ` +
            `(${JSON.stringify(chunk)}).\n  pre-move : ${JSON.stringify(a)}\n  current  : ${JSON.stringify(b)}`,
        );
        assert.deepStrictEqual(
            newLog.map((l) => l.replace(/^new\./, '')), oldLog.map((l) => l.replace(/^old\./, '')),
            `SIDE EFFECTS DIVERGED in "${name}" after chunk ${i + 1}/${seq.length} ` +
            `(${JSON.stringify(chunk)}).\n  pre-move : ${JSON.stringify(oldLog)}\n  current  : ${JSON.stringify(newLog)}`,
        );
        chunks++;
    });
    seqs++;
}

console.log(`OK processChunk parity: ${seqs} sequences, ${chunks} chunks, state and side effects identical to the pre-move closure`);
