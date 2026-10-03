/*
 * #1146 — the footer names the engine (Jordi, 03/10: «posa'm el motor al peu»).
 * One label for the live footer and the one a reload paints; this drives the
 * real `_modelFooterLabel` and the real `_renderSavedStats`.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert';

import { familyPaths } from './lib/load_nexe_ui.mjs';

function node(tag = 'div') {
    return {
        tag, children: [], textContent: '', className: '', attrs: {},
        classList: { add(c) { this.owner.className += ` ${c}`; }, owner: null },
        appendChild(c) { this.children.push(c); return c; },
        setAttribute(k, v) { this.attrs[k] = v; },
        addEventListener() {}, style: {},
        querySelector: () => null, querySelectorAll: () => [],
    };
}
const make = (tag) => { const n = node(tag); n.classList.owner = n; return n; };

const noop = () => {};
const el = new Proxy({}, { get: () => undefined, set: () => true });
const sandbox = {
    localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
    document: { addEventListener: noop, getElementById: () => el, querySelector: () => el,
        querySelectorAll: () => [], documentElement: el, body: el, createElement: make },
    navigator: { language: 'ca' }, location: { hash: '', href: 'http://127.0.0.1/ui/', replace: noop },
    history: { replaceState: noop }, fetch: async () => ({ ok: false }), console, setTimeout, clearTimeout,
    UI_STRINGS: { ca: {}, en: {}, es: {} },
};
sandbox.window = sandbox; sandbox.globalThis = sandbox;
vm.createContext(sandbox);
for (const f of familyPaths()) vm.runInContext(readFileSync(f, 'utf8'), sandbox);
vm.runInContext(';globalThis.__NexeUI = NexeUI;', sandbox);
const ui = Object.create(sandbox.__NexeUI.prototype);
ui.t = (k) => k;

// ── 1. The label ────────────────────────────────────────────────────────────
assert.strictEqual(ui._modelFooterLabel('Qwen3.5-9B-MLX-4bit', 'mlx'), 'Qwen3.5-9B-MLX-4bit · MLX');
assert.strictEqual(ui._modelFooterLabel('qwen3.5:9b', 'ollama'), 'qwen3.5:9b · Ollama');
assert.strictEqual(ui._modelFooterLabel('/models/Qwen_Qwen3-30B-A3B-Q4_K_M.gguf', 'llama_cpp'),
    'Qwen_Qwen3-30B-A3B-Q4_K_M.gguf · llama.cpp');
assert.strictEqual(ui._modelFooterLabel('nexe-system', undefined), 'nexe-system', 'no engine: the model alone');
assert.strictEqual(ui._modelFooterLabel('', 'mlx'), '', 'no model: nothing');

// ── 2. The footer a reload paints ───────────────────────────────────────────
const texts = (n) => [n.textContent, ...n.children.flatMap(texts)].filter(Boolean);
const stats = make('div');
ui._renderSavedStats(stats, { tokens: 30, elapsed: 1.2, model: 'Qwen3.5-9B-MLX-4bit', engine: 'mlx' }, make('div'));
assert.ok(texts(stats).includes('Qwen3.5-9B-MLX-4bit · MLX'), JSON.stringify(texts(stats)));

// ── 3. The live footer uses the same label ──────────────────────────────────
const chat = readFileSync(new URL('../../plugins/web_ui_module/ui/nexe-chat.js', import.meta.url), 'utf8');
assert.ok(chat.includes('this._modelFooterLabel(usedModel, usedEngine)'), 'the live footer shares the label');
assert.ok(/\[ENGINE:/.test(chat), 'and reads the ENGINE token');

console.log('engine_in_the_footer: label, saved footer and live footer — all name the engine');

// ── 4. The two safety nets drop a leaked ENGINE token (review 04/10) ───────
assert.strictEqual(ui._stripLeakedTags('Hola.[ENGINE:mlx]'), 'Hola.');
// Without marked.js the render escapes what it cleaned; the fake DOM has no
// innerHTML, so the escape is the identity here — or every output reads
// "undefined" and the assertion proves nothing.
ui.escapeHtml = (t) => t;
const rendered = ui.renderMarkdown('Hola [ENGINE:mlx] món');
assert.strictEqual(rendered, 'Hola  món');
console.log('engine_in_the_footer: the safety nets drop a leaked ENGINE token');
