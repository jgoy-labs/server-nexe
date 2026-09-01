/*
 * #127 leftover — Continue seeded st.fullResponse ABOVE `const st`.
 * That is a Temporal Dead Zone ReferenceError on the only path that
 * assigns it (Continue with the truncated bubble still in the DOM).
 * Normal send never takes the branch, which is why a live chat pass
 * can look green. process_chunk_parity.mjs does not drive sendMessage.
 *
 * Pin the source order: the think-state object must exist before Continue
 * writes to it. A runtime sendMessage test would also work, but this is
 * the one-line invariant the split actually broke.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import assert from 'node:assert';

const src = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), '../../plugins/web_ui_module/ui/nexe-chat.js'),
    'utf8',
);

const stDecl = src.indexOf('const st = {');
const seed = src.indexOf('st.fullResponse = continueState.raw');

assert.notEqual(stDecl, -1, 'the think-state object must still exist');
assert.notEqual(seed, -1, 'Continue must still seed fullResponse from the first half');
assert.ok(
    stDecl < seed,
    `Continue seeds st.fullResponse (offset ${seed}) BEFORE const st (offset ${stDecl}) ` +
        '— TDZ ReferenceError on the Continue path',
);
console.log('continue_tdz: const st is declared before the Continue seed');
