/*
 * #1151 — a memory tag inside code is a quotation, and the live answer drops the
 * whole span, as the saved one does (#1135).
 *
 * The server already removes «`[MEM_SAVE: …]`» entirely (core/memory_facts/
 * extract.py::_drop_quoted_tags); the web client stripped only the tag and left
 * «El format és: ``.» on screen until a reload. The cases are shared with the
 * Python side (lib/quoted_tag_cases.json, checked by test_quoted_tag_cases.py
 * against the server's function), so the two implementations answer the same.
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
// Without marked.js the render returns the cleaned text escaped; the fake DOM
// has no innerHTML, so the escape is the identity here.
ui.escapeHtml = (t) => t;

const cases = JSON.parse(readFileSync(new URL('./lib/quoted_tag_cases.json', import.meta.url), 'utf8'));
assert.ok(cases.length >= 8, 'the shared cases are there');

// ── 1. The rule, case by case, as the server states it ─────────────────────
for (const { input, expected } of cases) {
    assert.strictEqual(ui._dropQuotedMemTags(input), expected, JSON.stringify(input));
}

// ── 2. The live render: no empty `` where the example was ───────────────────
const live = ui.renderMarkdown("El format és: `[MEM_SAVE: L'usuari es diu Jordi]`.");
assert.strictEqual(live, 'El format és: .');
assert.ok(!live.includes('``'), 'no empty code span is left behind');

// ── 3. The final render takes the tag out of the same text, and keeps no fact
//       out of a quotation ───────────────────────────────────────────────────
const quoted = ui._extractMemSave("El format és: `[MEM_SAVE: L'usuari es diu Jordi]`.");
assert.strictEqual(JSON.stringify(quoted), JSON.stringify({ text: 'El format és: .', facts: [] }));

// ── 4. A real tag outside code is still extracted, and a quoted one next to it
//       does not hide it ─────────────────────────────────────────────────────
const both = ui._extractMemSave('Ho he guardat. [MEM_SAVE: té un gat] Format: `[MEM_SAVE: x]`');
assert.strictEqual(JSON.stringify(both.facts), JSON.stringify(['té un gat']));
assert.strictEqual(both.text, 'Ho he guardat. Format: ');

console.log(`quoted_tag_span: ${cases.length} shared cases, the live render and the final extract agree with the server`);
