/*
 * Stopping a generation leaves the same footer a finished one does, plus who
 * stopped it (Jordi, 13/10, live on MLX and on the API: «quan paro la generació
 * hauria d'haver un avís al footer: parat per l'usuari, el model i els tokens;
 * ara no surt res»).
 *
 * The footer was painted only when the stream ended by itself. «Atura» raises an
 * AbortError inside the read loop, which jumped to the catch and skipped it; the
 * only trace was an italic line in the body. The footer is now one closure,
 * `paintFooter(stopped)`, called from both ends.
 *
 * sendMessage is too large to drive (see cloud_engines_ui.mjs), so this pins the
 * wiring and the three languages. Mutation-checked by hand: removing the
 * `paintFooter(true)` in the AbortError branch, putting the italic line back, or
 * dropping the badge from the template turns this red.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import assert from 'node:assert';

const UI = join(dirname(fileURLToPath(import.meta.url)), '../../plugins/web_ui_module/ui');
const chat = readFileSync(join(UI, 'nexe-chat.js'), 'utf8');
const i18n = readFileSync(join(UI, 'i18n.js'), 'utf8');

// 1. One footer, two callers: the normal end and the stop.
assert.strictEqual([...chat.matchAll(/paintFooter\(false\)/g)].length, 1, 'the normal end paints the footer once');
assert.strictEqual([...chat.matchAll(/paintFooter\(true\)/g)].length, 1, 'the stop paints it once');

// 2. The stop call sits in the AbortError branch, after the text is rendered.
const abort = chat.indexOf("readError.name === 'AbortError'");
assert.notEqual(abort, -1);
const branch = chat.slice(abort, chat.indexOf('} else {', abort));
assert.ok(branch.includes('paintFooter(true)'), 'the AbortError branch paints the footer');
assert.ok(!branch.includes('generation_stopped'), 'the notice is in the footer, not an italic line in the body');

// 3. Even a stop before the first token paints it (finalTok is 0 then).
assert.ok(chat.includes('(finalTok > 0 || stopped)'), 'a stop with 0 tokens still gets a footer');

// 4. The footer says model, tokens (an estimate, so «~») and who stopped it.
const fn = chat.slice(chat.indexOf('const paintFooter'), chat.indexOf('paintFooter(false)'));
assert.ok(fn.includes("${exact ? '' : '~'}${finalTok} tok"), 'tokens that are not the engine\'s own count are marked as an estimate');
assert.ok(fn.includes('const exact = !stopped && usedUsage'), 'a stopped turn never claims an exact count');
assert.ok(fn.includes('_modelFooterLabel(usedModel, usedEngine)'), 'the model and the engine are still named');
assert.ok(fn.includes("stat-stopped") && fn.includes("this.t('stopped_by_user')"), 'the badge says it was the user');

// 5. The text exists in the three languages.
for (const [lang, text] of [['ca', "aturat per l'usuari"], ['en', 'stopped by user'], ['es', 'detenido por el usuario']]) {
    assert.ok(i18n.includes(`stopped_by_user: "${text}"`), `${lang}: stopped_by_user`);
}

console.log('stop_footer: a stopped turn gets the footer, with the model, the tokens and «stopped by user»');
