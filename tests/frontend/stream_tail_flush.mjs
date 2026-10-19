/*
 * #1150 — when the stream ends, what the read loop was holding is shown, not
 * dropped with the reader.
 *
 * Since #1139 every read waits for the next one when it ends inside a sentinel
 * (an odd count of `\x00`). The loop used to `break` on `done` before looking at
 * that carry, so a `\x00` that never got its partner (a NUL in a reply, a cut
 * connection) swallowed the rest of the answer: the CLI showed it
 * (`UiStreamReader.close`), the web did not.
 *
 * Drives the real `_streamChunks` with a fake reader over real encoded bytes.
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
const enc = new TextEncoder();

/** A reader over `parts`, each a string encoded to bytes; then `done`. */
const readerOf = (parts) => {
    let i = 0;
    return { read: async () => (i < parts.length ? { value: enc.encode(parts[i++]), done: false } : { value: undefined, done: true }) };
};
async function chunksOf(parts) {
    const out = [];
    for await (const c of ui._streamChunks(readerOf(parts), new TextDecoder())) out.push(c);
    return out;
}

/** The loop before #1150: `break` on done, the carry never looked at. */
async function oldChunksOf(parts) {
    const reader = readerOf(parts), decoder = new TextDecoder(), out = [];
    let carry = '';
    while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        const t = ui._takeSentinelCarry(carry + decoder.decode(value, { stream: true }));
        carry = t.carry;
        out.push(t.chunk);
    }
    return out;
}

const READY = '\x00[MODEL_READY]\x00';
const plain = (chunks) => chunks.join('');

// ── 1. A lone NUL in the reply: what follows it is shown, not lost ──────────
{
    const parts = ['Hola, ', 'el codi és a\x00b', ' i aquí continua la resposta.'];
    const before = await oldChunksOf(parts);
    assert.ok(!plain(before).includes('aquí continua'),
        'the old loop really lost the tail (else this test proves nothing)');
    const now = plain(await chunksOf(parts));
    assert.strictEqual(now, 'Hola, el codi és ab i aquí continua la resposta.');
}

// ── 2. A cut connection inside a sentinel: its text is kept, the NUL is not ─
{
    const now = plain(await chunksOf(['La resposta.', '\x00[MEM:1:L\'usuari té']));
    assert.strictEqual(now, "La resposta.[MEM:1:L'usuari té");
    assert.ok(!now.includes('\x00'));
}

// ── 3. A whole stream is untouched, at every cut, and the last chunk is empty
{
    const STREAM = '\x00[MODEL:Qwen]\x00' + READY + "D'acord, ho he guardat." + "\x00[MEM:1:un gat]\x00";
    for (let i = 0; i <= STREAM.length; i++) {
        const got = await chunksOf([STREAM.slice(0, i), STREAM.slice(i)]);
        assert.strictEqual(plain(got), STREAM, `cut at ${i}`);
        assert.strictEqual(got[got.length - 1], '', `cut at ${i}: nothing is left for the end`);
    }
}

// ── 4. A character cut between two reads is rebuilt, and the end flushes the
//       decoder ───────────────────────────────────────────────────────────────
{
    const bytes = enc.encode('cafè');
    const reader = (() => { let i = 0; const seq = [bytes.slice(0, 4), bytes.slice(4)];
        return { read: async () => (i < seq.length ? { value: seq[i++], done: false } : { value: undefined, done: true }) }; })();
    const out = [];
    for await (const c of ui._streamChunks(reader, new TextDecoder())) out.push(c);
    assert.strictEqual(plain(out), 'cafè');
}

// A stream that ends inside a character: the decoder is flushed, not forgotten.
{
    const bytes = enc.encode('è');
    let i = 0;
    const seq = [enc.encode('ab'), bytes.slice(0, 1)];
    const reader = { read: async () => (i < seq.length ? { value: seq[i++], done: false } : { value: undefined, done: true }) };
    const out = [];
    for await (const c of ui._streamChunks(reader, new TextDecoder())) out.push(c);
    assert.strictEqual(plain(out), 'ab\uFFFD');
}

// ── 5. The send loop reads through it ───────────────────────────────────────
const chat = readFileSync(new URL('../../plugins/web_ui_module/ui/nexe-chat.js', import.meta.url), 'utf8');
assert.ok(chat.includes('for await (let chunk of this._streamChunks(reader, decoder))'),
    'sendMessage must read through _streamChunks');
assert.ok(!/if \(done\) break;/.test(chat), 'and must not break on done before the carry is looked at');

console.log('stream_tail_flush: a held tail is shown at the end of the stream');
