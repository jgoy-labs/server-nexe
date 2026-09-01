/*
 * Loads the real NexeUI the way the browser does, for tests/frontend/*.mjs.
 *
 * Lives in lib/ on purpose: test_frontend_mjs_gate.py globs *.mjs in the
 * frontend directory itself and runs each one as a self-checking script. A
 * helper sitting there would be executed, exit 0, and count as a passing test
 * that asserts nothing — the very illusion that gate exists to prevent.
 *
 * The file list is READ from index.html rather than hardcoded, so the tests
 * follow the split (#127) without being edited each time a cluster moves, and
 * an ordering mistake in the page shows up here instead of in production.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const UI = join(dirname(fileURLToPath(import.meta.url)), '../../../plugins/web_ui_module/ui');

export function familyFiles() {
    const html = readFileSync(join(UI, 'index.html'), 'utf8');
    return [...html.matchAll(/<script src="\/ui\/static\/([^"]+\.js)"><\/script>/g)]
        .map((m) => m[1])
        .filter((f) => f === 'app.js' || f.startsWith('nexe-'));
}

/** Absolute paths of the family, in page order — for tests that keep their own
 * sandbox (their stubs are part of what they assert) and only need the file
 * list to follow the split. */
export function familyPaths() {
    return familyFiles().map((f) => join(UI, f));
}

/** The real NexeUI class, with browser globals stubbed out. */
export function loadNexeUI(files = familyFiles()) {
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
        localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
        document: {
            addEventListener: noop, getElementById: () => el, querySelector: () => el,
            querySelectorAll: () => [], documentElement: el, body: el,
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
    for (const f of files) vm.runInContext(readFileSync(join(UI, f), 'utf8'), sandbox);
    vm.runInContext(';globalThis.__NexeUI = NexeUI;', sandbox);
    return sandbox.__NexeUI;
}
