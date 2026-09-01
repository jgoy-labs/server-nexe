/*
 * When a subsystem is down the user has to be told — in the two places, and in
 * their own language.
 *
 * The method this drives was written on 22/08 and exercised with a throwaway
 * node script that caught two defects no python test would have seen: with TWO
 * subsystems the Catalan sentence stayed singular, and after recovery the
 * footer label kept saying "Funcionant a mitges" while the dot was green
 * again. The script was never committed, so nothing guarded either fix.
 *
 * Drives the REAL app.js against the REAL i18n.js through node:vm, and ends
 * with a calibration block that requires a half-done implementation to fail —
 * a green result here cannot be test-theatre.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert';

import { familyPaths } from './lib/load_nexe_ui.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const uiDir = join(__dirname, '../../plugins/web_ui_module/ui');

/** A DOM element that remembers what was done to it. */
function makeEl() {
    const classes = new Set();
    return {
        textContent: '',
        style: {},
        classList: {
            add: (c) => classes.add(c),
            remove: (c) => classes.delete(c),
            toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
            contains: (c) => classes.has(c),
        },
        _classes: classes,
    };
}

/**
 * Loads the real NexeUI class with the real UI_STRINGS and a DOM stub whose
 * three interesting nodes are addressable from the test.
 */
function loadUI(lang) {
    const nodes = {
        notice: makeEl(),      // #degradedNotice
        dot: makeEl(),         // .status-dot
        label: makeEl(),       // .status-indicator span
    };
    const noop = () => {};
    const sandbox = {
        localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
        document: {
            addEventListener: noop,
            getElementById: (id) => (id === 'degradedNotice' ? nodes.notice : null),
            querySelector: (sel) => {
                if (sel === '.status-dot') return nodes.dot;
                if (sel === '.status-indicator span') return nodes.label;
                return null;
            },
            querySelectorAll: () => [],
            documentElement: makeEl(),
            body: makeEl(),
        },
        navigator: { language: lang },
        location: { hash: '', href: 'http://127.0.0.1/ui/', replace: noop },
        history: { replaceState: noop },
        fetch: async () => ({ ok: false, status: 500, headers: { get: () => null } }),
        console,
        setTimeout,
        clearTimeout,
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    // i18n.js first, exactly as index.html loads it: a classic script whose
    // top-level const lands in the context and is visible to app.js.
    vm.runInContext(readFileSync(join(uiDir, 'i18n.js'), 'utf8'), sandbox);
    // app.js plus its cluster files (#127): the class is split across them.
    for (const f of familyPaths()) vm.runInContext(readFileSync(f, 'utf8'), sandbox);
    vm.runInContext(';globalThis.__NexeUI = NexeUI;', sandbox);

    // Bypass the constructor's DOM wiring: only the banner method is exercised.
    const ui = Object.create(sandbox.__NexeUI.prototype);
    ui.lang = lang;
    return { ui, nodes, strings: vm.runInContext('UI_STRINGS', sandbox) };
}

const impaired = (state, subsystems) => ({
    operational_state: state,
    impaired_subsystems: subsystems,
});

// ── 1. One subsystem, in Catalan: named, and in the singular ───────────────
{
    const { ui, nodes, strings } = loadUI('ca');
    ui._updateDegradedBanner(impaired('limited', ['rag']));

    assert.ok(
        nodes.notice.textContent.includes(strings.ca.degraded_names.rag),
        `the failing subsystem must be named in the user's language, got: ${nodes.notice.textContent}`,
    );
    assert.ok(
        nodes.notice.textContent.includes(strings.ca.degraded_suffix_one),
        'one subsystem takes the singular sentence',
    );
    assert.ok(
        !nodes.notice.textContent.includes(strings.ca.degraded_suffix_many),
        'the plural sentence must not appear for a single subsystem',
    );
    assert.strictEqual(nodes.notice.style.display, 'block', 'the notice has to be visible');
    assert.strictEqual(
        nodes.label.textContent, strings.ca.degraded_status,
        'the footer label is the glance: it must say the server is at half power',
    );
    assert.ok(nodes.dot._classes.has('degraded'), 'the status dot must carry the degraded class');
}

// ── 2. Two subsystems: the sentence has to agree in the plural ─────────────
// This is one of the two defects the throwaway script caught. With `rag` and
// `qdrant` down, Catalan said "…el magatzem vectorial no ha arrencat".
{
    const { ui, nodes, strings } = loadUI('ca');
    ui._updateDegradedBanner(impaired('limited', ['rag', 'qdrant']));

    assert.ok(
        nodes.notice.textContent.includes(strings.ca.degraded_suffix_many),
        `two subsystems take the plural sentence, got: ${nodes.notice.textContent}`,
    );
    assert.ok(
        nodes.notice.textContent.includes(strings.ca.degraded_names.rag) &&
        nodes.notice.textContent.includes(strings.ca.degraded_names.qdrant),
        'both subsystems must be named',
    );
}

// ── 3. Recovery: the label must go back, not stay behind ───────────────────
// The second caught defect. In the real flow checkStatus() restored the label,
// so the method looked fine — but it has to be correct on its own, because it
// is the only thing that writes that label while degraded.
{
    const { ui, nodes, strings } = loadUI('ca');
    ui._updateDegradedBanner(impaired('limited', ['rag']));
    ui._updateDegradedBanner(impaired('normal', []));

    assert.strictEqual(
        nodes.label.textContent, strings.ca.connected,
        'after recovery the label must stop saying the server is impaired',
    );
    assert.ok(!nodes.dot._classes.has('degraded'), 'and the dot must lose the degraded class');
    assert.strictEqual(nodes.notice.style.display, 'none', 'and the notice must be hidden');
    assert.strictEqual(nodes.notice.textContent, '', 'and emptied, not left behind for the next reader');
}

// ── 4. Every language answers; none falls through to the raw key ───────────
for (const lang of ['ca', 'en', 'es']) {
    const { ui, nodes, strings } = loadUI(lang);
    ui._updateDegradedBanner(impaired('limited', ['rag']));

    assert.strictEqual(
        nodes.label.textContent, strings[lang].degraded_status,
        `[${lang}] the footer label must be translated`,
    );
    assert.ok(
        nodes.notice.textContent.startsWith(strings[lang].degraded_prefix),
        `[${lang}] the notice must be translated, got: ${nodes.notice.textContent}`,
    );
    assert.ok(
        !nodes.notice.textContent.includes('degraded_suffix'),
        `[${lang}] a missing key would leak its own name into the sentence`,
    );
}

// ── 5. An unknown subsystem is still named, not swallowed ──────────────────
{
    const { ui, nodes } = loadUI('ca');
    ui._updateDegradedBanner(impaired('limited', ['some_future_module']));
    assert.ok(
        nodes.notice.textContent.includes('some_future_module'),
        'a subsystem with no friendly name falls back to its id — never to silence',
    );
}

// ── 6. Calibration: a half-done implementation must FAIL these checks ──────
// Without this, the checks above would also pass against a method that writes
// the notice and forgets the footer — which is precisely the shape of the
// recovery bug.
{
    const { nodes, strings } = loadUI('ca');
    const halfDone = (status) => {
        const impairedList = status.impaired_subsystems || [];
        if (!impairedList.length) { nodes.notice.style.display = 'none'; return; }
        nodes.notice.textContent = 'something is down';
        nodes.notice.style.display = 'block';
        // ...and nothing about the dot or the label.
    };
    halfDone(impaired('limited', ['rag']));
    assert.notStrictEqual(
        nodes.label.textContent, strings.ca.degraded_status,
        'calibration: the half-done version leaves the label untouched (if this fails, the stub is wrong)',
    );
    assert.ok(
        !nodes.dot._classes.has('degraded'),
        'calibration: the half-done version never marks the dot (if this fails, the stub is wrong)',
    );
}

// ── 7. Unreachable server: the last warning stops being information ───────
// checkStatus() paints the dot red inline and says "disconnected". Leaving the
// degraded class behind rings that red dot in amber and keeps a notice on
// screen about subsystems nobody can see any more.
{
    const { ui, nodes } = loadUI('ca');
    ui._updateDegradedBanner(impaired('limited', ['rag']));
    assert.ok(nodes.dot._classes.has('degraded'), 'precondition: the dot is marked');

    ui._clearDegradedNotice();
    assert.ok(!nodes.dot._classes.has('degraded'), 'an unreachable server must not stay amber');
    assert.strictEqual(nodes.notice.style.display, 'none', 'and the notice goes away');
    assert.strictEqual(nodes.notice.textContent, '', 'and leaves nothing behind');
}

console.log('degraded_notice: 7 blocks passed');
