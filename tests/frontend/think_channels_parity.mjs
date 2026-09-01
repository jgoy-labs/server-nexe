/*
 * #127 slice 1 — _cleanModelTags and _parseThinkingChannels were closures
 * declared INSIDE sendMessage (810 L). A closure cannot be reached from here,
 * so neither had, or could have, a single test: the only way to exercise them
 * was to drive the whole streaming path.
 *
 * They are pure — argument in, value out, nothing captured — so promoting them
 * to methods is supposed to change nothing. This proves it rather than
 * asserting it: the PRE-MOVE source is pasted below verbatim as a reference
 * implementation, and every input goes through both. Any difference in the
 * move shows up as a mismatch, not as a bug found weeks later in a model whose
 * thinking channel stops rendering.
 *
 * Drives the REAL app.js through node:vm with browser globals stubbed, the
 * same way session_persistence.mjs does.
 */
import assert from 'node:assert';

import { loadNexeUI } from './lib/load_nexe_ui.mjs';

// ── REFERENCE: the two closures exactly as they were inside sendMessage ──────
const oldCleanModelTags = (buf) => {
    buf = buf.replace(/<\|[^|]+\|>/g, '');
    buf = buf.replace(/[◁◀][^▷▶]*[▷▶]/g, '');
    return buf;
};

const oldParseThinkingChannels = (text) => {
    if (!text) return { thinking: null, content: '' };
    let cleaned = text.replace(/<\|[^|]+\|>/g, '').replace(/[◁◀][^▷▶]*[▷▶]/g, '');
    const m0 = cleaned.match(/<think>([\s\S]*?)<\/think>\s*([\s\S]*)/);
    if (m0) return { thinking: m0[1].trim(), content: m0[2].trim() };
    const m0b = cleaned.match(/^([\s\S]+?)<\/think>\s*([\s\S]*)/);
    if (m0b && m0b[1].trim().length > 10) return { thinking: m0b[1].trim(), content: m0b[2].trim() };
    const m1 = cleaned.match(/^(?:assistant)?analysis([\s\S]+?)\.?assistant\s*final([\s\S]+)$/i);
    if (m1) return { thinking: m1[1].trim(), content: m1[2].trim() };
    const m2 = cleaned.match(/^analysis([\s\S]+?)final([\s\S]+)$/i);
    if (m2 && m2[1].trim().length > 10) return { thinking: m2[1].trim(), content: m2[2].trim() };
    return { thinking: null, content: cleaned.trim() };
};

// ── load the real class ──────────────────────────────────────────────────────

const NexeUI = loadNexeUI();

// The methods must EXIST on the prototype. If someone inlines them back into
// sendMessage this fails first, with a clear reason, instead of the parity
// checks below failing as "undefined is not a function".
for (const name of ['_cleanModelTags', '_parseThinkingChannels']) {
    assert.strictEqual(
        typeof NexeUI.prototype[name], 'function',
        `NexeUI.prototype.${name} is missing — was it inlined back into sendMessage? ` +
        'These are promoted out on purpose (#127): a closure cannot be tested.',
    );
}

const clean = (s) => NexeUI.prototype._cleanModelTags.call({}, s);

// The class is built inside the vm sandbox, so the objects it returns carry the
// SANDBOX's Object.prototype. deepStrictEqual compares prototypes and would
// report two identical {thinking, content} pairs as different. Flatten to a
// host object so the comparison is about the values, which is what is at stake.
const parse = (s) => {
    const r = NexeUI.prototype._parseThinkingChannels.call({}, s);
    return { thinking: r.thinking, content: r.content };
};

// ── corpus: the real shapes, not toy strings ─────────────────────────────────
const CORPUS = [
    '',
    'plain answer with no tags at all',
    '<|channel|>analysis<|message|>hidden<|end|>visible',                 // gpt-oss control tags
    '◁think▷reasoning here◁/think▷the answer',                            // ◁▷ variant
    '<think>step one\nstep two</think>the final answer',                  // full think tags
    'a long stretch of reasoning that easily clears ten chars</think>answer', // DeepSeek R1, no opener
    'short</think>answer',                                                // under the 10-char guard
    'analysisI am thinking about it.assistantfinalHere is the answer',    // gpt-oss analysis/final
    'assistantanalysismore thinking hereassistant final and the answer',
    'analysisenough thinking to pass the guardfinalthe answer',           // pattern 2
    'analysisshortfinalx',                                                // under the 10-char guard
    '<think>only reasoning, no content</think>',
    'multi\nline\ncontent\nwith <|weird|> tags ◁and▷ both',
    'nested <think>outer <think>inner</think> tail</think> end',
    '   whitespace around   ',
];

let checked = 0;
for (const input of CORPUS) {
    assert.strictEqual(clean(input), oldCleanModelTags(input),
        `_cleanModelTags diverged from the pre-move closure on: ${JSON.stringify(input)}`);
    assert.deepStrictEqual(parse(input), oldParseThinkingChannels(input),
        `_parseThinkingChannels diverged from the pre-move closure on: ${JSON.stringify(input)}`);
    checked++;
}

// null/undefined reach _parseThinkingChannels in the real path (fullResponse
// starts empty), so the falsy guard is behaviour, not defensive noise.
for (const input of [null, undefined, 0]) {
    assert.deepStrictEqual(parse(input), oldParseThinkingChannels(input),
        `_parseThinkingChannels diverged on falsy input: ${JSON.stringify(input)}`);
    checked++;
}

console.log(`OK think-channel parity: ${checked} inputs, both helpers identical to the pre-move closures`);
