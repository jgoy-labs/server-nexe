/*
 * #1136 — «Cancel·la» on the delete dialog tells the server.
 *
 * Live 03/10: the dialog came up, Jordi cancelled, and the log shows no request
 * after it — `close(false)` only painted «↩️ Cancel·lat». The delete stayed
 * armed on the server until the next message, where a bare "sí" would have run
 * it. This drives the real `_showDeleteConfirmDialog` and presses each way out:
 * the button, a click outside the box, and the confirm button for contrast.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert';

import { familyPaths } from './lib/load_nexe_ui.mjs';

/** A DOM node with just what the dialog code touches. */
function node() {
    const listeners = {};
    return {
        style: {}, textContent: '', children: [], parent: null, listeners,
        appendChild(c) { this.children.push(c); c.parent = this; return c; },
        addEventListener(type, fn) { listeners[type] = fn; },
        remove() {
            if (this.parent) this.parent.children = this.parent.children.filter((x) => x !== this);
            this.parent = null;
        },
    };
}

const body = node();

function loadNexeUI() {
    const noop = () => {};
    const el = new Proxy({}, { get: () => undefined, set: () => true });
    const sandbox = {
        localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
        document: {
            addEventListener: noop, querySelector: () => el, querySelectorAll: () => [],
            getElementById: (id) => (id === 'nexe-delete-confirm' ? null : el),
            documentElement: el, body, createElement: () => node(),
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

const settle = () => new Promise((r) => setTimeout(r, 0));

function openDialog(answer = () => Promise.resolve({ ok: true, status: 200, json: async () => ({ deleted: 0 }) })) {
    const ui = Object.create(NexeUI.prototype);
    ui.currentSessionId = 'sess-1';
    ui.t = (k) => `{${k}}`;
    ui.posts = [];
    ui.said = [];
    ui.fetchWithCsrf = (url, opts) => {
        ui.posts.push({ url, body: JSON.parse(opts.body) });
        return answer();
    };
    ui.addMessageToChat = (role, text) => ui.said.push(text);
    ui._showDeleteConfirmDialog("el gos de l'usuari es diu Tro");
    const overlay = body.children[body.children.length - 1];
    const box = overlay.children[0];
    const [cancelBtn, confirmBtn] = box.children[3].children;
    assert.strictEqual(cancelBtn.textContent, '{delete_cancel_btn}', 'found the cancel button');
    assert.strictEqual(confirmBtn.textContent, '{delete_confirm_btn}', 'found the confirm button');
    return { ui, overlay, cancelBtn, confirmBtn };
}

// ── 1. «Cancel·la» disarms on the server, for this session ──────────────────
{
    const { ui, overlay, cancelBtn } = openDialog();
    cancelBtn.listeners.click();
    assert.deepStrictEqual(ui.posts, [{ url: '/ui/memory/cancel-delete', body: { session_id: 'sess-1' } }]);
    await settle();
    assert.deepStrictEqual(ui.said, ['↩️ {delete_cancelled}'], 'said only once the server answered');
    assert.ok(!body.children.includes(overlay), 'the dialog is gone');
}

// ── 2. A click outside the box is a cancel too ──────────────────────────────
{
    const { ui, overlay } = openDialog();
    overlay.listeners.click({ target: overlay });
    assert.deepStrictEqual(ui.posts.map((p) => p.url), ['/ui/memory/cancel-delete']);
}

// ── 3. A click inside the box is not a cancel ───────────────────────────────
{
    const { ui, overlay } = openDialog();
    overlay.listeners.click({ target: overlay.children[0] });
    assert.deepStrictEqual(ui.posts, [], 'clicking the box itself sends nothing');
    overlay.remove();
}

// ── 4. «Elimina» still confirms, and does not cancel ────────────────────────
{
    const { ui, confirmBtn } = openDialog();
    confirmBtn.listeners.click();
    assert.deepStrictEqual(ui.posts.map((p) => p.url), ['/ui/memory/confirm-delete']);
    assert.strictEqual(ui.posts[0].body.fact, "el gos de l'usuari es diu Tro");
}

// ── 5. The server refuses (429/5xx) or is unreachable: no «Cancel·lat» ───────
for (const [why, answer] of [
    ['429', () => Promise.resolve({ ok: false, status: 429, json: async () => ({}) })],
    ['no network', () => Promise.reject(new TypeError('Failed to fetch'))],
]) {
    const { ui, cancelBtn } = openDialog(answer);
    cancelBtn.listeners.click();
    await settle();
    assert.deepStrictEqual(ui.said, ['⚠️ {delete_cancel_unconfirmed}'],
        `${why}: the delete is still armed and the user must know`);
}

// ── 6. That warning exists in the three shipped languages ───────────────────
{
    const box = { console };
    vm.createContext(box);
    vm.runInContext(
        readFileSync(new URL('../../plugins/web_ui_module/ui/i18n.js', import.meta.url), 'utf8')
        + '\n;globalThis.__S = UI_STRINGS;', box,
    );
    for (const lang of ['ca', 'en', 'es']) {
        const text = box.__S[lang] && box.__S[lang].delete_cancel_unconfirmed;
        assert.ok(typeof text === 'string' && text.length > 0, `delete_cancel_unconfirmed missing in '${lang}'`);
    }
}

console.log('delete_dialog_cancel: 6 checks passed');
