/*
 * WS5-02 regression repro — markdown-attribute XSS via poisoned title/href.
 *
 * Drives the REAL vendored marked.min.js with the SAME renderer.link/image logic
 * used by app.js, and asserts that attacker-controlled markdown cannot break out of
 * an HTML attribute. It also runs a deliberately VULNERABLE renderer (the pre-fix
 * behaviour, escaping without quote-encoding) and requires THAT to break out — so the
 * test proves it can actually detect the vulnerability (no test-theatre).
 *
 * Faithful escapeHtml() shim: a browser's textContent→innerHTML encodes & < > but
 * NOT quotes. That quote gap is exactly the bug; escapeAttr() closes it.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const markedPath = join(__dirname, '../../plugins/web_ui_module/ui/marked.min.js');

// --- load the real vendored marked (UMD) ---
const sandbox = {};
sandbox.window = sandbox;
sandbox.self = sandbox;
sandbox.globalThis = sandbox;
const moduleObj = { exports: {} };
sandbox.module = moduleObj;
sandbox.exports = moduleObj.exports;
vm.createContext(sandbox);
vm.runInContext(readFileSync(markedPath, 'utf8'), sandbox);
const marked = sandbox.marked || moduleObj.exports.marked || moduleObj.exports;
const Renderer = (marked && marked.Renderer) || moduleObj.exports.Renderer;
if (!marked || typeof marked.parse !== 'function' || !Renderer) {
    console.error('FAIL: could not load marked/Renderer from marked.min.js');
    process.exit(2);
}

// --- faithful browser escapeHtml (textContent -> innerHTML): encodes & < > only ---
const escapeHtml = (t) =>
    String(t == null ? '' : t)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
// the fix under test:
const escapeAttr = (t) => escapeHtml(t).replace(/"/g, '&quot;').replace(/'/g, '&#39;');

const isSafeHref = (href) => {
    if (!href) return false;
    try {
        return ['http:', 'https:', 'mailto:'].includes(new URL(href, 'http://localhost').protocol);
    } catch { return false; }
};

function buildRenderer(escAttr) {
    const r = new Renderer();
    r.link = function (token) {
        const href = (token && typeof token === 'object') ? (token.href || '') : token;
        let text;
        try {
            text = (token && token.tokens && this.parser)
                ? this.parser.parseInline(token.tokens)
                : escapeHtml((token && token.text) || '');
        } catch { text = escapeHtml((token && token.text) || ''); }
        if (!isSafeHref(href)) return text;
        const title = (token && token.title) ? ` title="${escAttr(token.title)}"` : '';
        return `<a href="${escAttr(href)}"${title} target="_blank" rel="noopener noreferrer">${text}</a>`;
    };
    r.image = function (token) {
        const href = (token && typeof token === 'object') ? (token.href || '') : token;
        const alt = escAttr((token && token.text) || '');
        if (!isSafeHref(href)) return alt;
        const title = (token && token.title) ? ` title="${escAttr(token.title)}"` : '';
        return `<img src="${escAttr(href)}" alt="${alt}"${title}>`;
    };
    return r;
}

const fixedRenderer = buildRenderer(escapeAttr);       // WS5-02 fix
const vulnRenderer = buildRenderer(escapeHtml);        // pre-fix behaviour

// Attack vectors: a safe http scheme (passes isSafeHref) + a quote breakout in the
// TITLE. The title is the marked-reachable attribute sink: marked routes any `"` in
// the link destination into the title, so the title is where a poisoned document can
// inject a quote. (Escaping href/src/alt with escapeAttr is defense-in-depth — see
// app.js — but marked's grammar makes the title the exploitable path, so that is what
// this gate exercises. Vectors that the self-check below cannot make the vulnerable
// renderer break out on are, by construction, not real marked-reachable attacks.)
const vectors = [
    '[x](http://ok "a\\" onmouseover=\\"alert(1)")',      // link title breakout
    '![x](http://ok "z\\" onerror=\\"alert(2)")',          // image title breakout
];

// A breakout is present if a literal quote closes the attribute right before an
// event handler, e.g.  " onmouseover="  /  " onerror="
const BREAKOUT = /"\s+on\w+\s*=\s*"/i;

let failures = 0;
for (const md of vectors) {
    const fixed = marked.parse(md, { breaks: true, gfm: true, renderer: fixedRenderer });
    const vuln = marked.parse(md, { breaks: true, gfm: true, renderer: vulnRenderer });

    // 1) fixed output must NOT contain an attribute breakout
    if (BREAKOUT.test(fixed)) {
        console.error(`FAIL: fixed renderer still breaks out for: ${md}\n  -> ${fixed}`);
        failures++;
        continue;
    }
    // 2) fixed output must have encoded the quote (proof it was escaped, not stripped)
    if (!/&quot;|&#39;/.test(fixed)) {
        console.error(`FAIL: fixed renderer produced no encoded quote for: ${md}\n  -> ${fixed}`);
        failures++;
        continue;
    }
    // 3) meta self-check: the VULNERABLE renderer MUST break out — otherwise this
    //    test can't detect the bug and would be test-theatre.
    if (!BREAKOUT.test(vuln)) {
        console.error(`FAIL(self-check): vulnerable renderer did NOT break out for: ${md}\n  -> ${vuln}\n  (the test cannot detect the vuln -> not a valid gate)`);
        failures++;
        continue;
    }
    console.log(`OK: ${md}`);
}

if (failures) {
    console.error(`\n${failures} vector(s) failed`);
    process.exit(1);
}
console.log(`\nWS5-02 repro: all ${vectors.length} vectors neutralized (and detectable).`);
process.exit(0);
