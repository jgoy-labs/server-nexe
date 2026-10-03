/*
 * #1126 — an uploaded document goes into the conversation, not over the box
 * the user types in.
 *
 * Live 02/10 (Jordi): «un cop pujat el pdf que s'ajunti al xat i desaparegui
 * de la barra de missatge, confon». Its chip sat over the input, where it read
 * as something still waiting to be sent, and its note said the document was
 * for this chat only — while the upload is ingested into user_knowledge, which
 * every conversation's recall searches. This drives the real methods that put
 * the card up and take it down, and reads the real i18n.js.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert';

import { familyPaths } from './lib/load_nexe_ui.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));

/** A DOM node with just what the card code touches. */
function node() {
    return {
        className: '', innerHTML: '', children: [], parent: null, scrollTop: 0, scrollHeight: 0,
        classList: { add() {}, remove() {}, contains: () => false },
        appendChild(c) { this.children.push(c); c.parent = this; return c; },
        replaceChildren() { this.children = []; },
        remove() {
            if (this.parent) this.parent.children = this.parent.children.filter((x) => x !== this);
            this.parent = null;
        },
    };
}

function loadNexeUI() {
    const noop = () => {};
    const el = new Proxy({}, { get: () => undefined, set: () => true });
    const sandbox = {
        localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
        document: {
            addEventListener: noop, getElementById: () => el, querySelector: () => el,
            querySelectorAll: () => [], documentElement: el, body: el, createElement: () => node(),
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

const NexeUI = loadNexeUI();
const ui = Object.create(NexeUI.prototype);
ui.chatMessages = node();
ui.filePreview = node();
ui.t = (k) => `{${k}}`;
ui.escapeHtml = (s) => s;
const cleared = [];
ui.fetchWithCsrf = async (url) => { cleared.push(url); return { ok: true }; };

// ── 1. The card lands in the conversation, the bar stays empty ──────────────
ui.currentSessionId = 'sess-1';
ui.addUploadedFile({ filename: 'Comunicacio.PDF', size: 25600 }, '13 fragments · 1s');
assert.strictEqual(ui.chatMessages.children.length, 1, 'the card is in the conversation');
assert.strictEqual(ui.filePreview.children.length, 0, 'nothing over the input box');
const card = ui.chatMessages.children[0];
assert.strictEqual(card.className, 'doc-card');
assert.ok(card.innerHTML.includes('Comunicacio.PDF') && card.innerHTML.includes('13 fragments'));
assert.ok(card.innerHTML.includes('{doc_in_chat}'), 'the note says how the document is used');

// ── 2. A second document replaces the first: one card per conversation ─────
ui.addUploadedFile({ filename: 'Altre.pdf', size: 1024 });
assert.strictEqual(ui.chatMessages.children.length, 1);
assert.ok(ui.chatMessages.children[0].innerHTML.includes('Altre.pdf'));

// ── 3. ✕ takes the card away and tells the server ───────────────────────────
ui.removeFilePreview();
assert.strictEqual(ui.chatMessages.children.length, 0);
assert.deepStrictEqual(cleared, ['/ui/session/sess-1/clear-document']);

// ── 4. Switching conversation clears it locally, without the POST ───────────
ui.addUploadedFile({ filename: 'Comunicacio.PDF', size: 25600 });
ui._clearFilePreviewLocal();
assert.strictEqual(ui.chatMessages.children.length, 0);
assert.strictEqual(cleared.length, 1, 'leaving a conversation must not wipe its document');

// ── 5. The note tells the truth, in the three shipped languages ─────────────
{
    const box = { console };
    vm.createContext(box);
    vm.runInContext(
        readFileSync(join(__dirname, '../../plugins/web_ui_module/ui/i18n.js'), 'utf8')
        + '\n;globalThis.__S = UI_STRINGS;', box,
    );
    for (const lang of ['ca', 'en', 'es']) {
        for (const key of ['doc_in_chat', 'doc_remove']) {
            const text = box.__S[lang] && box.__S[lang][key];
            assert.ok(typeof text === 'string' && text.length > 0, `${key} missing in '${lang}'`);
        }
        assert.strictEqual(box.__S[lang].doc_chat_only, undefined,
            `'${lang}' still says the document is for this chat only`);
    }
    assert.ok(!/només/.test(box.__S.ca.doc_in_chat), 'the upload reaches every conversation');
}
