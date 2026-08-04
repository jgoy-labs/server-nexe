/*
 * #859 — the "I am compacting" notice has to appear before the wait and
 * disappear the moment there is anything else to look at.
 *
 * Compaction is a full LLM summarisation inside the critical path (~100 s
 * measured on an 8 GB machine) that runs BEFORE the response has any headers,
 * so nothing can be said while it happens. The previous turn flags it and the
 * client shows the notice on send; this drives the real app.js methods that
 * put it up and take it down.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert';

const __dirname = dirname(fileURLToPath(import.meta.url));
const appPath = join(__dirname, '../../plugins/web_ui_module/ui/app.js');

/** Loads the real NexeUI class with browser globals stubbed out. */
function loadNexeUI() {
    const noop = () => {};
    const el = new Proxy({}, {
        get: (_t, p) => {
            if (p === 'classList') return { add: noop, remove: noop, contains: () => false, toggle: noop };
            if (p === 'style') return {};
            if (p === 'value') return '';
            if (p === 'querySelector' || p === 'querySelectorAll') return () => null;
            if (p === 'addEventListener' || p === 'appendChild' || p === 'replaceChildren') return noop;
            if (p === 'setAttribute' || p === 'removeAttribute') return noop;
            return undefined;
        },
        set: () => true,
    });
    const sandbox = {
        localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
        document: {
            addEventListener: noop,
            getElementById: () => el,
            querySelector: () => el,
            querySelectorAll: () => [],
            documentElement: el,
            body: el,
            createElement: () => ({ className: '', textContent: '', remove() { this._removed = true; } }),
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

function makeInstance(NexeUI) {
    const inst = Object.create(NexeUI.prototype);
    inst._compactNotice = null;
    inst._willCompactNext = false;
    return inst;
}

const NexeUI = loadNexeUI();

// ── 1. The notice survives 'thinking' — that IS the wait it describes ──────
{
    const ui = makeInstance(NexeUI);
    const notice = { removed: false, remove() { this.removed = true; } };
    ui._compactNotice = notice;

    ui.setAiState('thinking');
    assert.strictEqual(
        notice.removed, false,
        "the notice must stay up during 'thinking' — that is the 100 s it exists to explain",
    );
    assert.ok(ui._compactNotice, 'and must still be tracked');
}

// ── 2. Any other state takes it down ───────────────────────────────────────
for (const state of ['streaming', 'idle', 'error']) {
    const ui = makeInstance(NexeUI);
    const notice = { removed: false, remove() { this.removed = true; } };
    ui._compactNotice = notice;

    ui.setAiState(state);
    assert.strictEqual(
        notice.removed, true,
        `'${state}' means the wait is over — the notice must go`,
    );
    assert.strictEqual(
        ui._compactNotice, null,
        `'${state}' must also drop the reference, or the next turn cannot put up a new one`,
    );
}

// ── 3. Removing twice is safe (no notice, no crash) ────────────────────────
{
    const ui = makeInstance(NexeUI);
    ui._removeCompactNotice();
    ui._removeCompactNotice();
    assert.strictEqual(ui._compactNotice, null, 'idempotent removal');
}

// ── 4. The notice text exists in all three shipped languages ───────────────
// Sixth appearance of the characteristic defect (31/07): the wizard tier tabs
// HAD their translations and painted hardcoded strings anyway. A notice wired
// to a key no language defines fails the same way — fine in review, blank on
// screen. Evaluating the real i18n.js beats grepping for the key: this fails
// if the file stops parsing, too.
{
    const i18nPath = join(__dirname, '../../plugins/web_ui_module/ui/i18n.js');
    const box = { console };
    vm.createContext(box);
    vm.runInContext(readFileSync(i18nPath, 'utf8') + '\n;globalThis.__S = UI_STRINGS;', box);
    for (const lang of ['ca', 'en', 'es']) {
        const text = box.__S[lang] && box.__S[lang].compacting_notice;
        assert.ok(
            typeof text === 'string' && text.length > 0,
            `compacting_notice missing in '${lang}' — the wait would be announced blank `
            + 'precisely to whoever does not read the other languages',
        );
    }
}

// ── 5. Calibration: a stub that never removes must FAIL these checks ───────
// Without this, a setAiState that silently stopped calling _removeCompactNotice
// would leave the checks above green if they only asserted on the reference.
{
    const notice = { removed: false, remove() { this.removed = true; } };
    const brokenUi = { _compactNotice: notice, setAiState() { /* the pre-fix code */ } };
    brokenUi.setAiState('streaming');
    assert.strictEqual(
        notice.removed, false,
        'calibration: the pre-fix setAiState removes nothing (if this fails the stub is wrong)',
    );
}

console.log('compact_notice: 7 checks passed');
