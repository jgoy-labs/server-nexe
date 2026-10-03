/*
 * #1139 — a sentinel the read cuts in half is finished by the next read.
 *
 * Live 03/10: «[MODEL_READY]» painted at the start of replies and the turn timer
 * at 0.0s — the sentinel was never recognised. The server sends it whole (raw
 * capture: '\x00[MODEL_READY]\x00', its own 15-byte chunk), but a browser read
 * can end anywhere. The old carry kept only an unclosed '\x00[': a read ending
 * in the lone opening '\x00' slipped through, and the next one began with
 * '[MODEL_READY]\x00', which no detector matches.
 *
 * This drives the real `_takeSentinelCarry` over the stream captured live,
 * cut at every position into two reads and three.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert';

import { familyPaths } from './lib/load_nexe_ui.mjs';

function loadNexeUI() {
    const noop = () => {};
    const el = new Proxy({}, { get: () => undefined, set: () => true });
    const sandbox = {
        localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
        document: {
            addEventListener: noop, getElementById: () => el, querySelector: () => el,
            querySelectorAll: () => [], documentElement: el, body: el, createElement: () => el,
        },
        navigator: { language: 'ca' },
        location: { hash: '', href: 'http://127.0.0.1/ui/', replace: noop },
        history: { replaceState: noop },
        fetch: async () => ({ ok: false, status: 500, headers: { get: () => null } }),
        console, setTimeout, clearTimeout,
        UI_STRINGS: { ca: {}, en: {}, es: {} },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    for (const f of familyPaths()) vm.runInContext(readFileSync(f, 'utf8'), sandbox);
    vm.runInContext(';globalThis.__NexeUI = NexeUI;', sandbox);
    return sandbox.__NexeUI;
}

const ui = Object.create(loadNexeUI().prototype);
const READY = '\x00[MODEL_READY]\x00';

// The live stream of 03/10 (node fetch on /ui/chat, MLX + Qwen3.5-9B), joined.
const STREAM = '\x00[MODEL:Qwen3.5-9B-MLX-4bit]\x00\x00[RAG:1]\x00\x00[RAG_AVG:0.96]\x00'
    + '\x00[RAG_ITEM:personal_memory|0.96]\x00' + READY + "D'acord, ho he guardat. [MEM_SAVE: L'usuari té un gat]"
    + "\x00[MEM:1:L'usuari té un gat]\x00";

/** What the read loop does: carry in, take, hand `chunk` to the detectors. */
function readAll(parts, take) {
    const seen = [];
    let carry = '';
    for (const part of parts) {
        const out = take(carry + part);
        seen.push(out.chunk);
        carry = out.carry;
    }
    return { seen, carry };
}

/** The rule before #1139, verbatim, to show the cut it missed. */
function oldTake(text) {
    const openAt = text.lastIndexOf('\x00[');
    if (openAt !== -1 && text.indexOf(']\x00', openAt) === -1) {
        return { chunk: text.slice(0, openAt), carry: text.slice(openAt) };
    }
    return { chunk: text, carry: '' };
}

const take = (t) => ui._takeSentinelCarry(t);
const nuls = (s) => (s.match(/\x00/g) || []).length; // eslint-disable-line no-control-regex

function check(parts, label) {
    const { seen, carry } = readAll(parts, take);
    assert.strictEqual(seen.join('') + carry, STREAM, `${label}: nothing lost or reordered`);
    assert.strictEqual(carry, '', `${label}: a complete stream leaves nothing waiting`);
    for (const c of seen) assert.strictEqual(nuls(c) % 2, 0, `${label}: a half sentinel reached the detectors: ${JSON.stringify(c)}`);
    assert.strictEqual(seen.filter((c) => c.includes(READY)).length, 1, `${label}: MODEL_READY whole in one read`);
}

// ── 1. Every cut into two reads, and every cut into three ───────────────────
let cases = 0;
for (let i = 0; i <= STREAM.length; i++) {
    check([STREAM.slice(0, i), STREAM.slice(i)], `cut at ${i}`);
    cases++;
    for (let j = i; j <= STREAM.length; j += 3) {
        check([STREAM.slice(0, i), STREAM.slice(i, j), STREAM.slice(j)], `cuts at ${i},${j}`);
        cases++;
    }
}

// ── 2. The cut of 03/10: right after MODEL_READY's opening NUL ──────────────
{
    const at = STREAM.indexOf(READY) + 1;
    const parts = [STREAM.slice(0, at), STREAM.slice(at)];
    const before = readAll(parts, oldTake);
    assert.ok(!before.seen.some((c) => c.includes(READY)),
        'the old rule really missed this cut (else this test proves nothing)');
    assert.ok(before.seen[1].startsWith('[MODEL_READY]\x00'), 'and painted «[MODEL_READY]»');
    check(parts, 'the cut of 03/10');
}

// ── 3. A read that is only the opening NUL ──────────────────────────────────
{
    const at = STREAM.indexOf(READY);
    check([STREAM.slice(0, at), '\x00', STREAM.slice(at + 1)], 'a lone NUL read');
}

console.log(`sentinel_carry: ${cases} cuts, the 03/10 cut and a lone NUL — all whole`);
