/*
 * API providers, phase 2 — the browser's side of the cloud gate.
 *
 * Drives the REAL NexeUI (the family of scripts, loaded the way index.html
 * loads them) against fakes of fetch and of the few DOM nodes the code
 * touches. What is pinned:
 *   - the selector: a cloud group is drawn with a cloud, the thinking toggle
 *     and the vision badge follow the BACKEND (a hosted model is not judged by
 *     its name), the footer says «API · model» (#1155: the engine first);
 *   - the consent dialog: an explicit yes is the only way to consent, outside
 *     the box is a no, everything the dialog shows goes through textContent
 *     (the provider's name comes from the server);
 *   - the follow-up to a refusal: ask, then send the SAME turn again with the
 *     consent; a decline sends nothing and gives the user their text back;
 *   - the switch: strictly what the server answered.
 *
 * NOT covered here, by design: how it LOOKS in a browser. Nobody has seen the
 * dialog rendered; this proves the logic, not the pixels.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { familyPaths } from './lib/load_nexe_ui.mjs';

const UI = join(dirname(fileURLToPath(import.meta.url)), '../../plugins/web_ui_module/ui');

function node(tag = 'div') {
    const listeners = {};
    return {
        tag, children: [], parent: null, listeners, style: {}, textContent: '', className: '', value: '',
        checked: false, disabled: false, title: '', dataset: {}, selected: false, selectedOptions: [],
        classList: { contains(c) { return this.owner.className.split(' ').includes(c); }, add() {}, owner: null },
        get lastElementChild() { return this.children[this.children.length - 1]; },
        appendChild(c) { this.children.push(c); c.parent = this; return c; },
        remove() { if (this.parent) this.parent.children = this.parent.children.filter((x) => x !== this); this.parent = null; },
        addEventListener(type, fn) { listeners[type] = fn; },
        setAttribute() {}, querySelector: () => null, querySelectorAll: () => [],
    };
}
const make = (tag) => { const n = node(tag); n.classList.owner = n; return n; };

const els = {};
const body = make('body');
const noop = () => {};
const proxyEl = new Proxy({}, { get: () => undefined, set: () => true });
const sandbox = {
    localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
    document: {
        addEventListener: noop, querySelector: () => proxyEl, querySelectorAll: () => [],
        getElementById: (id) => els[id] ?? null, documentElement: proxyEl, body, createElement: make,
    },
    navigator: { language: 'ca' }, location: { hash: '', href: 'http://127.0.0.1/ui/', replace: noop },
    history: { replaceState: noop }, fetch: async () => ({ ok: false }), console, setTimeout, clearTimeout,
};
sandbox.window = sandbox; sandbox.globalThis = sandbox;
vm.createContext(sandbox);
// The real strings: the page loads i18n.js before app.js, and what the dialog says is under test.
vm.runInContext(readFileSync(join(UI, 'i18n.js'), 'utf8'), sandbox);
for (const f of familyPaths()) vm.runInContext(readFileSync(f, 'utf8'), sandbox);
vm.runInContext(';globalThis.__NexeUI = NexeUI; globalThis.__STRINGS = UI_STRINGS;', sandbox);
const NexeUI = sandbox.__NexeUI;
const STRINGS = sandbox.__STRINGS;

function fresh() {
    const ui = Object.create(NexeUI.prototype);
    ui.lang = 'ca';
    ui.t = (k) => (STRINGS.ca[k] ?? k);
    return ui;
}
// Objects built inside the vm context have another Object.prototype: compare them as plain data.
const plain = (x) => JSON.parse(JSON.stringify(x));
const jsonResponse = (status, payload) => ({
    status, ok: status >= 200 && status < 300,
    clone() { return this; }, async json() { return payload; },
});

// ── 1. The selector follows the backend ─────────────────────────────────────
{
    const ui = fresh();
    ui._backends = [
        { id: 'api', name: 'API', cloud: true, models: [
            { name: 'deepseek-chat', vision: false }, { name: 'gpt-4o', vision: true },
            { name: 'qwen3.5-hosted', vision: false },
        ] },
        { id: 'ollama', name: 'Ollama', models: [{ name: 'qwen3.5:4b' }] },
    ];
    assert.strictEqual(ui._canThink('deepseek-r1:7b', 'ollama'), true, 'a local reasoning family still thinks');
    assert.strictEqual(ui._canThink('deepseek-r1:7b'), true, 'no backend: the old answer');
    assert.strictEqual(ui._canThink('deepseek-r1', 'api'), false, 'a hosted model is never offered the toggle');
    assert.strictEqual(ui._canThink('qwen3.5-hosted', 'api'), false);

    assert.strictEqual(ui._modelHasVision('gpt-4o', 'api'), true, 'the server says gpt-4o sees');
    assert.strictEqual(ui._modelHasVision('deepseek-chat', 'api'), false);
    assert.strictEqual(ui._modelHasVision('qwen3.5-hosted', 'api'), false, 'the name heuristic must not decide for a hosted model');
    assert.strictEqual(ui._modelHasVision('nonexistent', 'api'), false);
    assert.strictEqual(ui._modelHasVision('qwen3.5:4b', 'ollama'), true, 'a local model keeps the name heuristic');

    assert.strictEqual(ui._modelFooterLabel('deepseek-chat', 'api'), 'API · deepseek-chat');
}

// ── 1b. The thinking toggle reads the backend the selector shows ────────────
{
    const ui = fresh();
    for (const id of ['backendSelect', 'modelSelect', 'thinkingToggle']) els[id] = make('input');
    ui._onThinkingToggleChange = async () => {};
    els.modelSelect.value = 'deepseek-r1';
    els.backendSelect.value = 'api';
    ui._updateThinkingToggle();
    assert.strictEqual(els.thinkingToggle.disabled, true, 'a hosted reasoner is not offered the toggle');
    els.backendSelect.value = 'ollama';
    ui._updateThinkingToggle();
    assert.strictEqual(els.thinkingToggle.disabled, false, 'the same name on a local engine is');
    els.backendSelect.value = 'api';
    ui._restoreThinkingToggle({ thinking_enabled: true });
    assert.strictEqual(els.thinkingToggle.checked, false);
    els.backendSelect.value = 'ollama';
    ui._restoreThinkingToggle({ thinking_enabled: true });
    assert.strictEqual(els.thinkingToggle.checked, true);
}

// ── 2. The group is drawn with a cloud; the others are not ──────────────────
{
    const ui = fresh();
    for (const id of ['backendSelect', 'modelSelect', 'cloudToggle', 'thinkingToggle']) els[id] = make(id === 'backendSelect' || id === 'modelSelect' ? 'select' : 'input');
    els.backendSelect.value = 'ollama';
    ui.fetchWithCsrf = async () => jsonResponse(200, {
        backends: [
            { id: 'ollama', name: 'Ollama', models: [{ name: 'qwen3.5:4b' }], active: true, connected: true },
            { id: 'api', name: 'API', cloud: true, models: [{ name: 'deepseek-chat', vision: false }], active: false, connected: true },
        ],
        current_model: '', cloud: { allowed: true, providers: [{ key: 'deepseek', name: 'DeepSeek', configured: true }] },
    });
    await ui.loadBackends();
    assert.deepStrictEqual(els.backendSelect.children.map((o) => o.textContent), ['Ollama', '☁️ API']);
    assert.strictEqual(els.cloudToggle.checked, true);
    assert.ok(els.cloudToggle.title.includes('DeepSeek'), els.cloudToggle.title);
}

// ── 3. The consent dialog ──────────────────────────────────────────────────
function openDialog(ui, name) {
    body.children = [];
    const answer = ui._askCloudConsent(name);
    const overlay = body.children[0];
    const [box] = overlay.children;
    const [title, msg, row] = box.children;
    const [noBtn, yesBtn] = row.children;
    return { answer, overlay, title, msg, noBtn, yesBtn };
}
{
    const ui = fresh();
    for (const k of ['cloud_consent_title', 'cloud_consent_msg', 'cloud_consent_yes', 'cloud_consent_no']) {
        assert.ok(STRINGS.ca[k], `ca has ${k}`);
    }
    let d = openDialog(ui, 'DeepSeek');
    assert.ok(d.msg.textContent.includes('DeepSeek') && !d.msg.textContent.includes('{provider}'), d.msg.textContent);
    assert.ok(/RAG/.test(d.msg.textContent) && /mem/i.test(d.msg.textContent), 'says what leaves: the conversation, the RAG, the memory');
    d.yesBtn.listeners.click();
    assert.strictEqual(await d.answer, true, 'only the explicit yes consents');
    assert.strictEqual(body.children.length, 0, 'the dialog closes');

    d = openDialog(ui, 'DeepSeek'); d.noBtn.listeners.click();
    assert.strictEqual(await d.answer, false);
    d = openDialog(ui, 'DeepSeek'); d.overlay.listeners.click({ target: d.overlay });
    assert.strictEqual(await d.answer, false, 'a click outside the box is a no');
    d = openDialog(ui, 'DeepSeek'); d.overlay.listeners.click({ target: d.yesBtn });
    d.noBtn.listeners.click();
    assert.strictEqual(await d.answer, false, 'a click bubbling from inside the box is not a click outside');

    const hostile = '<img src=x onerror=alert(1)>';
    d = openDialog(ui, hostile);
    assert.ok(d.msg.textContent.includes(hostile), 'the server-supplied name is text, as is');
    assert.ok(!('innerHTML' in d.msg), 'and never parsed as HTML');
    d.noBtn.listeners.click(); await d.answer;
}

// ── 4. After a refusal: ask, then send the same turn again ──────────────────
{
    const ui = fresh();
    const sent = [];
    ui.abortController = { signal: 'SIGNAL' };
    ui.fetchWithCsrf = async (url, opts) => { sent.push({ url, opts }); return jsonResponse(200, {}); };
    const chatBody = { message: 'hola', session_id: 's1', stream: true, backend: 'api', model: 'deepseek-chat' };
    const consentRequired = jsonResponse(403, { detail: { code: 'cloud_consent_required', provider: 'deepseek', provider_name: 'DeepSeek' } });

    ui._askCloudConsent = async () => true;
    const yes = await ui._cloudRefusalFollowUp(consentRequired, chatBody);
    assert.strictEqual(sent.length, 1);
    assert.strictEqual(sent[0].url, '/ui/chat');
    assert.deepStrictEqual(JSON.parse(sent[0].opts.body), { ...chatBody, cloud_consent: 'deepseek' }, 'the SAME turn plus the consent');
    assert.strictEqual(sent[0].opts.signal, 'SIGNAL');
    assert.ok(yes.response && yes.response.ok);

    sent.length = 0;
    ui._askCloudConsent = async () => false;
    const no = await ui._cloudRefusalFollowUp(consentRequired, chatBody);
    assert.deepStrictEqual(plain(no), { declined: true });
    assert.strictEqual(sent.length, 0, 'a decline sends nothing');

    // The dialog is asked by provider name.
    let askedWith = null;
    ui._askCloudConsent = async (n) => { askedWith = n; return false; };
    await ui._cloudRefusalFollowUp(consentRequired, chatBody);
    assert.strictEqual(askedWith, 'DeepSeek');

    // Other refusals say why, in the UI's language.
    const off = await ui._cloudRefusalFollowUp(jsonResponse(403, { detail: { code: 'cloud_engines_disabled', message: 'EN text' } }), chatBody);
    assert.deepStrictEqual(plain(off), { refused: STRINGS.ca.err_cloud_engines_disabled });
    const unknown = await ui._cloudRefusalFollowUp(jsonResponse(400, { detail: { code: 'cloud_new_code', message: 'EN text' } }), chatBody);
    assert.deepStrictEqual(plain(unknown), { refused: 'EN text' }, 'a code the UI does not know shows the server text');

    // Not the cloud gate's: left to the generic path, even with a message of its own.
    assert.strictEqual(await ui._cloudRefusalFollowUp(jsonResponse(409, { detail: { code: 'session_leased', message: 'leased elsewhere' } }), chatBody), null);

    assert.strictEqual(await ui._cloudRefusalFollowUp(jsonResponse(403, { detail: 'CSRF token missing' }), chatBody), null);
    assert.strictEqual(await ui._cloudRefusalFollowUp(jsonResponse(400, { detail: { code: 'session_leased' } }), chatBody), null);
    assert.strictEqual(await ui._cloudRefusalFollowUp({ status: 403, clone() { return this; }, async json() { throw new Error('html'); } }, chatBody), null);
}

// ── 5. A refused turn is taken back out ─────────────────────────────────────
{
    const ui = fresh();
    ui.chatMessages = make('div'); ui.messageInput = make('textarea');
    const bubble = make('div'); bubble.className = 'message user'; ui.chatMessages.appendChild(bubble);
    ui.imagePreviewBar = make('div'); ui.imagePreviewThumb = make('img'); ui.imagePreviewName = make('span');
    ui._undoUnsentTurn('hola', { b64: 'QUJD', type: 'image/png', name: 'a.png' }, null);
    assert.strictEqual(ui.chatMessages.children.length, 0, 'the bubble the server never stored is removed');
    assert.strictEqual(ui.messageInput.value, 'hola', 'the user gets their text back');
    assert.strictEqual(ui._selectedImage.name, 'a.png');
    assert.strictEqual(ui.imagePreviewThumb.src, 'data:image/png;base64,QUJD');

    const reply = make('div'); reply.className = 'message assistant'; ui.chatMessages.appendChild(reply);
    ui._undoUnsentTurn('hola', null, null);
    assert.strictEqual(ui.chatMessages.children.length, 1, 'only a user bubble is ever removed');

    ui.chatMessages.appendChild(Object.assign(make('div'), { className: 'message user' }));
    ui._undoUnsentTurn('', null, { sessionId: 's' });
    assert.strictEqual(ui.chatMessages.children.length, 2, 'a Continue has no bubble of its own to remove');
}

// ── 6. The switch: what the server says, nothing else ───────────────────────
{
    const ui = fresh();
    const cb = els.cloudToggle; cb.checked = true;
    const calls = []; let reloads = 0; let status = 200;
    ui.fetchWithCsrf = async (url, opts) => { calls.push({ url, body: JSON.parse(opts.body) }); return jsonResponse(status, { allowed: true }); };
    ui.loadBackends = async () => { reloads++; };
    await ui._onCloudToggleChange();
    assert.deepStrictEqual(calls, [{ url: '/ui/cloud-engines', body: { enabled: true } }]);
    assert.strictEqual(reloads, 1, 'the group appears or disappears with the switch');
    assert.strictEqual(cb.checked, true);

    cb.checked = false; calls.length = 0;
    await ui._onCloudToggleChange();
    assert.deepStrictEqual(calls, [{ url: '/ui/cloud-engines', body: { enabled: false } }], 'turning it off says off');
    cb.checked = true; calls.length = 0;

    status = 500; cb.checked = true; reloads = 0;
    await ui._onCloudToggleChange();
    assert.strictEqual(cb.checked, false, 'the server did not take it: the switch shows the truth');
    assert.strictEqual(reloads, 0);

    ui.fetchWithCsrf = async () => { throw new Error('offline'); };
    const quiet = console.error; console.error = noop;
    cb.checked = true; await ui._onCloudToggleChange(); console.error = quiet;
    assert.strictEqual(cb.checked, false, 'offline: the same');
}

// ── 7. i18n: the three languages say it, with the provider in it ────────────
{
    const keys = ['cloud_allow', 'cloud_allow_info', 'cloud_no_provider', 'cloud_consent_title', 'cloud_consent_msg',
        'cloud_consent_yes', 'cloud_consent_no', 'err_cloud_engines_disabled', 'err_cloud_model_not_allowed',
        'err_cloud_provider_not_configured'];
    for (const k of keys) {
        const values = ['ca', 'es', 'en'].map((l) => STRINGS[l][k]);
        assert.ok(values.every((v) => typeof v === 'string' && v.length > 3), `${k} in all three languages`);
        assert.strictEqual(new Set(values).size, 3, `${k} is actually translated`);
    }
    for (const l of ['ca', 'es', 'en']) assert.ok(STRINGS[l].cloud_consent_msg.includes('{provider}'), l);
}

// ── 8. Wiring the real sendMessage depends on (it is too large to drive) ────
{
    const chat = readFileSync(join(UI, 'nexe-chat.js'), 'utf8');
    assert.ok(chat.includes('this._cloudRefusalFollowUp(response, chatBody)'), 'sendMessage asks the follow-up with the turn it sent');
    assert.ok(/response\.status === 403 \|\| response\.status === 400/.test(chat));
    assert.ok(chat.includes('this._undoUnsentTurn(message, pendingImage, continueState)'));
    assert.ok(chat.includes('chatBody.force_lease = true;'), 'a takeover the user confirmed survives the consent resend');
    const html = readFileSync(join(UI, 'index.html'), 'utf8');
    assert.ok(html.includes('id="cloudToggle"') && html.includes('data-i18n="cloud_allow"'));
    const app = readFileSync(join(UI, 'app.js'), 'utf8');
    assert.ok(app.includes("'[data-i18n=\"cloud_allow\"]'"), 'the switch label is translated by applyI18n');
    const models = readFileSync(join(UI, 'nexe-models.js'), 'utf8');
    const cloudPart = models.slice(models.indexOf('// ── Cloud engines'), models.indexOf('_updateModelSelect(backendId'));
    assert.ok(cloudPart.length > 500 && !/innerHTML/.test(cloudPart), 'the cloud code never builds HTML');
}

console.log('cloud_engines_ui: selector, consent dialog, follow-up, switch and i18n all behave');
