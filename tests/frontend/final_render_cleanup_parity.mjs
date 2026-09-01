/*
 * #127 slice 3 — the [MEM_SAVE: ...] replace existed FOUR times inside
 * sendMessage (two in the chunk machine, two in the final render) and the tag
 * stripping was five sequential replaces inline. They are two methods now.
 *
 * Four copies of a regex that must agree is not a style problem: the facts
 * they collect drive the memory badge, the stripped text is what the user
 * reads, and a model emitting a tag one copy handles and another does not
 * means the answer and the badge disagree about what was remembered.
 *
 * The pre-unification code is pasted below verbatim as the reference. The two
 * streaming copies are covered by process_chunk_parity.mjs, which still runs
 * the PRE-MOVE closure with its own inline regex — so between the two files
 * all four call sites are compared against what they replaced.
 */
import assert from 'node:assert';

import { loadNexeUI } from './lib/load_nexe_ui.mjs';

const NexeUI = loadNexeUI();

// ── REFERENCE: the final-render copies, exactly as they were ────────────────

// the streaming-side shape (no de-duplication) — three of the four sites
function oldExtractPlain(text) {
    const facts = [];
    const stripped = text.replace(/\[MEM_SAVE:\s*(.+?)\]\s*/g, (_, f) => {
        facts.push(f);
        return '';
    });
    return { text: stripped, facts };
}

// the final-render site, with its hand-rolled first-seen guard
function oldExtractDeduped(text) {
    const memFacts = [];
    const _seenFacts = new Set();
    const out = text.replace(/\[MEM_SAVE:\s*(.+?)\]\s*/g, (_, fact) => {
        if (!_seenFacts.has(fact)) {
            _seenFacts.add(fact);
            memFacts.push(fact);
        }
        return '';
    });
    return { text: out, facts: memFacts };
}

function oldStripLeakedTags(text) {
    text = text.replace(/\[ACTION\]:\s*[^\n]*/g, '');
    text = text.replace(/\[MODEL:[^\]]+\]/g, '');
    text = text.replace(/\[MEM:\d+\]/g, '');
    text = text.replace(/\[MEM\]/g, '');
    text = text.replace(/\[DEL:\d+:.+?\]/g, '');
    return text;
}

const extract = (s) => {
    const r = NexeUI.prototype._extractMemSave.call({}, s);
    return { text: r.text, facts: [...r.facts] };
};
const strip = (s) => NexeUI.prototype._stripLeakedTags.call({}, s);

// ── corpus ──────────────────────────────────────────────────────────────────
const MEM_CORPUS = [
    '',
    'nothing to remember here',
    '[MEM_SAVE: likes tea]',
    'before [MEM_SAVE: likes tea] after',
    '[MEM_SAVE: likes tea][MEM_SAVE: hates coffee]',
    '[MEM_SAVE: likes tea] [MEM_SAVE: likes tea]',              // the duplicate the badge must collapse
    '[MEM_SAVE: likes tea]\n[MEM_SAVE: likes tea]\n[MEM_SAVE: x]',
    'text\n[MEM_SAVE: a fact with, commas and: colons]\nmore',
    '[MEM_SAVE:no space after the colon]',
    '[MEM_SAVE:   lots of leading space]',
    '[MEM_SAVE: ]',                                              // empty-ish, .+? needs one char
    '[MEM_SAVE: first][MEM_SAVE: second][MEM_SAVE: first]',      // order of first appearance
    'unclosed [MEM_SAVE: never ends',
    '[MEM_SAVE: a] trailing newlines\n\n\n',
    'MEM_SAVE: not in brackets at all',
    '[mem_save: lowercase is not the tag]',
];

const TAG_CORPUS = [
    '',
    'a clean answer',
    '[ACTION]: do the thing\nreal text',
    'before [MODEL:qwen-3.5-4b] after',
    'counts [MEM:3] and bare [MEM] both go',
    'delete token [DEL:12:some fact] gone',
    '[ACTION]: one\n[ACTION]: two\ntext',
    'all at once [MODEL:x][MEM:1][MEM][DEL:2:y] end',
    '[MODEL:unclosed and then text',
    'nested-looking [MODEL:[weird]] tail',
    '[ACTION]: eats to end of line only\nnext line survives',
    '[DEL:3:a] [DEL:4:b] two of them',
];

let n = 0;
for (const input of MEM_CORPUS) {
    assert.deepStrictEqual(extract(input), oldExtractPlain(input),
        `_extractMemSave diverged from the pre-unification copy on: ${JSON.stringify(input)}`);
    // the final-render caller de-duplicates; a Set keeps first-seen order,
    // which is exactly what the hand-rolled _seenFacts guard produced.
    const mine = extract(input);
    assert.deepStrictEqual(
        { text: mine.text, facts: [...new Set(mine.facts)] },
        oldExtractDeduped(input),
        `the de-duplicated call site diverged on: ${JSON.stringify(input)}`);
    n++;
}
for (const input of TAG_CORPUS) {
    assert.strictEqual(strip(input), oldStripLeakedTags(input),
        `_stripLeakedTags diverged from the pre-move block on: ${JSON.stringify(input)}`);
    n++;
}

console.log(`OK final-render cleanup parity: ${n} inputs, both helpers identical to the code they replaced`);
