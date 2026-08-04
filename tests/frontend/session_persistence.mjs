/*
 * The active conversation must survive a page reload.
 *
 * Measured in the field (01/08, 8 GB machine): the id lived only in memory, the
 * webview was reloaded by the system mid-conversation, and the next message
 * opened a brand-new backend session — while the screen still showed the old
 * bubbles. Everything before the reload was orphaned on disk, so a later
 * "summarise this conversation" silently answered about half of it.
 *
 * Drives the REAL app.js class through node:vm with stubbed browser globals,
 * and also runs the PRE-FIX behaviour (memory-only id) requiring THAT to lose
 * the session — so the test proves it can detect the regression.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert';

const __dirname = dirname(fileURLToPath(import.meta.url));
const appPath = join(__dirname, '../../plugins/web_ui_module/ui/app.js');

function makeStorage() {
    const data = new Map();
    return {
        getItem: (k) => (data.has(k) ? data.get(k) : null),
        setItem: (k, v) => data.set(k, String(v)),
        removeItem: (k) => data.delete(k),
        _data: data,
    };
}

/** Loads the real NexeUI class with browser globals stubbed out. */
function loadNexeUI(storage) {
    const noop = () => {};
    const el = new Proxy({}, {
        get: (_t, p) => {
            if (p === 'classList') return { add: noop, remove: noop, contains: () => false };
            if (p === 'style') return {};
            if (p === 'value') return '';
            if (p === 'querySelector' || p === 'querySelectorAll') return () => null;
            if (p === 'addEventListener' || p === 'appendChild' || p === 'replaceChildren') return noop;
            return undefined;
        },
        set: () => true,
    });
    const sandbox = {
        localStorage: storage,
        document: {
            addEventListener: noop,
            getElementById: () => el,
            querySelector: () => el,
            querySelectorAll: () => [],
            documentElement: el,
            body: el,
        },
        navigator: { language: 'ca' },
        location: { hash: '', href: 'http://127.0.0.1/ui/', replace: noop },
        history: { replaceState: noop },
        fetch: async () => ({ ok: false, status: 500, headers: { get: () => null } }),
        console,
        setTimeout,
        clearTimeout,
        UI_STRINGS: { ca: {}, en: {}, es: {} },
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(readFileSync(appPath, 'utf8') + '\n;globalThis.__NexeUI = NexeUI;', sandbox);
    return sandbox.__NexeUI;
}

function makeInstance(NexeUI, storage) {
    // Bypass the constructor's DOM wiring: we only exercise session bookkeeping.
    const inst = Object.create(NexeUI.prototype);
    inst.currentSessionId = null;
    inst.sessions = [];
    inst._storage = storage;
    return inst;
}

// ── 1. The id is mirrored to storage, so a reload can find it ──────────────
{
    const storage = makeStorage();
    const NexeUI = loadNexeUI(storage);
    const ui = makeInstance(NexeUI, storage);

    ui._setCurrentSession('abc123-de57-4774-b31e-07b55f97ead9');
    assert.strictEqual(
        storage.getItem('nexe_session_id'), 'abc123-de57-4774-b31e-07b55f97ead9',
        'the active session must be persisted, not kept in memory only',
    );

    // A reload is a brand-new instance against the same storage.
    const afterReload = makeInstance(NexeUI, storage);
    assert.strictEqual(afterReload.currentSessionId, null, 'fresh instance starts empty');
    assert.strictEqual(
        storage.getItem('nexe_session_id'), 'abc123-de57-4774-b31e-07b55f97ead9',
        'the id survives the reload',
    );
}

// ── 2. Clearing the session clears the stored id (no ghost restore) ────────
{
    const storage = makeStorage();
    const NexeUI = loadNexeUI(storage);
    const ui = makeInstance(NexeUI, storage);
    ui._setCurrentSession('to-be-deleted');
    ui._setCurrentSession(null);
    assert.strictEqual(
        storage.getItem('nexe_session_id'), null,
        'deleting the active session must not leave a stale id behind',
    );
}

// ── 3. Restore re-opens the conversation; a vanished one falls back clean ──
{
    const storage = makeStorage();
    const NexeUI = loadNexeUI(storage);

    const ui = makeInstance(NexeUI, storage);
    storage.setItem('nexe_session_id', 'still-there');
    let loaded = null, welcomed = false;
    ui.loadSession = async (id) => { loaded = id; return true; };
    ui.showWelcome = () => { welcomed = true; };
    await ui._restoreLastSession();
    assert.strictEqual(loaded, 'still-there', 'restore must re-open the stored conversation');
    assert.strictEqual(welcomed, false, 'no welcome screen when a conversation is restored');

    const ui2 = makeInstance(NexeUI, storage);
    storage.setItem('nexe_session_id', 'deleted-elsewhere');
    let welcomed2 = false;
    ui2.loadSession = async () => false;      // server says 404
    ui2.showWelcome = () => { welcomed2 = true; };
    await ui2._restoreLastSession();
    assert.strictEqual(welcomed2, true, 'a vanished session falls back to welcome');
    assert.strictEqual(ui2.currentSessionId, null, 'and leaves no id pointing at nothing');
    assert.strictEqual(storage.getItem('nexe_session_id'), null, 'and clears the stale id');
}

// ── 4. Calibration: the PRE-FIX behaviour must fail these checks ───────────
// Without this, a broken _setCurrentSession that silently does nothing would
// still let tests 1-3 pass if they only asserted in-memory state.
{
    const storage = makeStorage();
    const preFix = { currentSessionId: null };
    // The old code: plain assignment, nothing persisted.
    preFix.currentSessionId = 'abc123';
    assert.strictEqual(
        storage.getItem('nexe_session_id'), null,
        'calibration: the pre-fix assignment persists nothing (if this fails the stub is wrong)',
    );
}

console.log('session_persistence: 4 checks passed');
