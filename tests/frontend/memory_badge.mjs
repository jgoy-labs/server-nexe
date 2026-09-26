/*
 * #1098 — the "saved" badge is the SERVER's word, never the model's.
 *
 * Live 25/09 (qwen3.5:4b): on an opening "em dic Aran, recorda-ho" the model
 * wrote two [MEM_SAVE:] tags, the server kept nothing, and the badge said
 * "desat" — sendMessage set memorySaved from the tags it stripped out of the
 * text. Since 25/09 the server tells, on the same turn, what memory kept:
 * \x00[MEM:n:fact1|fact2]\x00. This drives the real method that reads it and
 * pins that sendMessage has no other way to decide "saved".
 *
 * Mutation-checked by hand: letting `_readMemSentinel` count a bare [MEM:0] as
 * saved, or putting `memorySaved = true` back where the model's tags are
 * stripped, turns this red.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import assert from 'node:assert';

import { loadNexeUI } from './lib/load_nexe_ui.mjs';

const NexeUI = loadNexeUI();
const ui = Object.create(NexeUI.prototype);
const empty = () => ({ saved: false, facts: [] });

// 1. The server kept two facts: both listed, the sentinel gone from the text.
let r = ui._readMemSentinel('Fet!\x00[MEM:2:viu a Vic|treballa de fuster]\x00', empty());
assert.strictEqual(r.chunk, 'Fet!');
assert.strictEqual(r.saved, true);
assert.deepStrictEqual([...r.facts], ['viu a Vic', 'treballa de fuster']);

// 2. [MEM:0]: the server looked and kept nothing — no badge.
r = ui._readMemSentinel('\x00[MEM:0]\x00', empty());
assert.strictEqual(r.saved, false, '[MEM:0] must not read as saved');
assert.deepStrictEqual([...r.facts], []);
assert.strictEqual(r.seen, true, 'the sentinel is still consumed, so the spinner clears');

// 3. A fact already in memory (n=0, listed): remembered, so it is shown.
r = ui._readMemSentinel('\x00[MEM:0:es diu Aran]\x00', empty());
assert.strictEqual(r.saved, true);
assert.deepStrictEqual([...r.facts], ['es diu Aran']);

// 4. The continue path still sends a bare count: saved, no list.
r = ui._readMemSentinel('\x00[MEM:1]\x00', empty());
assert.strictEqual(r.saved, true);
assert.deepStrictEqual([...r.facts], []);

// 5. The model's own tag is text, not a sentinel: nothing is learnt from it.
r = ui._readMemSentinel('Hola [MEM_SAVE: El meu nom és Nexe.]', empty());
assert.strictEqual(r.seen, false);
assert.strictEqual(r.saved, false, "a model's [MEM_SAVE:] must never read as saved");

// 6. The one place that decides: sendMessage assigns memorySaved only from
//    the declaration and from _readMemSentinel's result.
const src = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), '../../plugins/web_ui_module/ui/nexe-chat.js'),
    'utf8',
);
const assigns = [...src.matchAll(/memorySaved\s*=(?!=)/g)].length;
assert.strictEqual(assigns, 1, `memorySaved is assigned ${assigns} times — only its declaration may`);
assert.ok(
    /\(\{\s*saved:\s*memorySaved,\s*facts:\s*memFacts,\s*chunk\s*\}\s*=\s*memRead\)/.test(src),
    'memorySaved/memFacts must come from _readMemSentinel',
);
assert.ok(!src.includes("'\\u2705 ' + memFacts"), 'the "✅ facts" stand-in claimed an unconfirmed save');

console.log('memory_badge: the badge reads only the server\'s [MEM:n:facts]');
