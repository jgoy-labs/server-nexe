/*
 * #127 — app.js is being split into sibling classic scripts that extend
 * NexeUI.prototype. This guards the four ways that split can rot.
 *
 * The order is not invented here: it is READ from index.html, so the test
 * loads the family exactly as a browser would. A test that hardcodes its own
 * order proves nothing about the page.
 */
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import assert from 'node:assert';

import { familyFiles, loadNexeUI } from './lib/load_nexe_ui.mjs';

const __dirname = dirname(fileURLToPath(import.meta.url));
const UI = join(__dirname, '../../plugins/web_ui_module/ui');

const html = readFileSync(join(UI, 'index.html'), 'utf8');
const declared = [...html.matchAll(/<script src="\/ui\/static\/([^"]+\.js)"><\/script>/g)]
    .map((m) => m[1]);
const family = familyFiles();

// 1. Every nexe-*.js on disk is actually loaded by the page. A cluster file
//    nobody references looks like working code and runs nowhere — the exact
//    failure test_frontend_mjs_gate.py exists to stop for .mjs scripts.
const onDisk = readdirSync(UI).filter((f) => f.startsWith('nexe-') && f.endsWith('.js'));
const orphans = onDisk.filter((f) => !declared.includes(f));
assert.deepStrictEqual(orphans, [], `nexe-*.js files index.html never loads: ${orphans}`);

// 2. app.js must come first: the class has to exist before its prototype can
//    be extended, and a reordered index.html would throw at page load.
assert.strictEqual(family[0], 'app.js', `app.js must load before the clusters, got ${family}`);

const NexeUI = loadNexeUI(family);

// 3. A method moved to a cluster file must be INDISTINGUISHABLE from one written
//    in the class body. Class methods are non-enumerable; Object.assign would
//    define them enumerable, and every split-out method would start appearing in
//    a `for...in` over an instance. Nothing in the UI does that today, which is
//    precisely why the day something does, nobody would connect the two.
const enumerable = Object.getOwnPropertyNames(NexeUI.prototype)
    .filter((n) => Object.getOwnPropertyDescriptor(NexeUI.prototype, n).enumerable);
assert.deepStrictEqual(
    enumerable, [],
    `these prototype members are enumerable and class methods are not: ${enumerable}. ` +
    'Use NexeUI.extend, never Object.assign.',
);

// 4. One home per method, enforced at load time rather than trusted. Two files
//    defining the same name is a silent last-one-wins.
assert.throws(
    () => NexeUI.extend({ t() { return 'collision'; } }),
    /already has a home/,
    'NexeUI.extend must refuse to redefine an existing method',
);

// And the split is real: without the cluster files, their methods are absent.
if (family.length > 1) {
    const alone = loadNexeUI(['app.js']);
    const moved = Object.getOwnPropertyNames(NexeUI.prototype)
        .filter((n) => !Object.prototype.hasOwnProperty.call(alone.prototype, n));
    assert.ok(
        moved.length > 0,
        'no method actually lives in a cluster file — the split left copies behind in app.js',
    );
    console.log(`OK prototype surface: ${family.length} files, ` +
        `${Object.getOwnPropertyNames(NexeUI.prototype).length} members, ` +
        `${moved.length} of them extended in, none enumerable`);
} else {
    console.log('OK prototype surface: app.js only, nothing split yet');
}
