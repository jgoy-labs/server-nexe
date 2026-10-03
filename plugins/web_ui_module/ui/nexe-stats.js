/**
 * ============================================
 * Nexe UI — streaming and message statistics
 * ============================================
 * Split out of app.js (#127). Loaded as a classic <script> AFTER app.js in
 * index.html — the class has to exist before its prototype can be extended —
 * and before DOMContentLoaded, which is when the instance is built.
 *
 * Classic script on purpose, not an ES module: the cache-bust rewrites
 * `.js"` in index.html to `.js?v=<boot>`, and it only ever sees the src
 * attributes there. An `import` inside a .js file would never get the query
 * string, so a stale sub-module could survive a restart while app.js reloaded.
 *
 * These bodies are the ones that were in the class, unchanged.
 */
/* global NexeUI */
// NexeUI is declared by app.js, loaded before this file (shared top-level
// global scope of classic scripts) — same arrangement as UI_STRINGS/i18n.js,
// with the order reversed because a prototype needs its class to exist first.
NexeUI.extend({
    _startStreamStats() {
        this._streamStart = Date.now();
        this._streamTokens = 0;
        if (this.statsBar) this.statsBar.classList.add('active');
        this._statsInterval = setInterval(() => this._updateStreamStats(), 400);
    },

    _updateStreamStats() {
        const elapsed = (Date.now() - this._streamStart) / 1000;
        const tokPerSec = elapsed > 0.5 ? (this._streamTokens / elapsed).toFixed(1) : '—';
        const tokEl = document.getElementById('statTokens');
        const spdEl = document.getElementById('statSpeed');
        if (tokEl) tokEl.textContent = this._streamTokens;
        if (spdEl) spdEl.textContent = tokPerSec;
    },

    _stopStreamStats() {
        clearInterval(this._statsInterval);
        this._statsInterval = null;
        // Keep stats visible for 3s then hide
        setTimeout(() => {
            if (this.statsBar) this.statsBar.classList.remove('active');
        }, 3000);
    },

    _renderUserStats(statsDiv, content, textDiv, stats = null) {
        // Approximate counter: ~1 token per 4 characters (standard heuristic).
        // If the backend provides `prompt_tokens` in stats, that value is used instead.
        const approxTokens = Math.max(1, Math.ceil((content || '').length / 4));
        const tokens = (stats && stats.prompt_tokens) || approxTokens;
        const tokenLabel = (stats && stats.prompt_tokens) ? `${tokens} tok` : `~${tokens} tok`;

        const tokSpan = document.createElement('span');
        tokSpan.className = 'stat-item';
        const tokI = document.createElement('i');
        tokI.setAttribute('data-lucide', 'activity');
        tokSpan.appendChild(tokI);
        const tokText = document.createElement('span');
        tokText.textContent = tokenLabel;
        tokSpan.appendChild(tokText);
        statsDiv.appendChild(tokSpan);

        // Copy button — same pattern as the assistant's.
        const copyBtn = document.createElement('button');
        copyBtn.className = 'copy-btn';
        copyBtn.title = 'Copy';
        const copyI = document.createElement('i');
        copyI.setAttribute('data-lucide', 'copy');
        copyBtn.appendChild(copyI);
        copyBtn.addEventListener('click', () => {
            navigator.clipboard.writeText(textDiv.innerText).then(() => {
                const checkI = document.createElement('i');
                checkI.setAttribute('data-lucide', 'check');
                copyBtn.replaceChildren(checkI);
                if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [copyBtn] });
                setTimeout(() => {
                    const restoreI = document.createElement('i');
                    restoreI.setAttribute('data-lucide', 'copy');
                    copyBtn.replaceChildren(restoreI);
                    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [copyBtn] });
                }, 2000);
            }).catch(() => {});
        });
        statsDiv.appendChild(copyBtn);

        if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [statsDiv] });
    },

    /**
     * The footer's model, and the engine that answered it (#1146 — Jordi,
     * 03/10: «posa'm el motor al peu»). One label for the live footer and the
     * one a reload paints, so the two cannot drift: «Qwen3.5-9B-MLX-4bit · MLX».
     */
    _modelFooterLabel(model, engine) {
        const name = model ? String(model).split('/').pop() : '';
        const ENGINE_NAMES = { mlx: 'MLX', ollama: 'Ollama', llama_cpp: 'llama.cpp' };
        const label = engine ? (ENGINE_NAMES[engine] || String(engine)) : '';
        if (!name) return '';
        return label ? `${name} · ${label}` : name;
    },

    _renderSavedStats(statsDiv, stats, textDiv) {
        const tok = stats.tokens || 0;
        const elapsed = stats.elapsed || 0;
        const speed = elapsed > 0.5 ? (tok / elapsed).toFixed(1) : null;
        const model = this._modelFooterLabel(stats.model, stats.engine);
        const ragCount = stats.rag_count || 0;
        const ragAvg = stats.rag_avg || 0;
        const memSaved = stats.mem_saved || 0;

        const addStat = (icon, text) => {
            const span = document.createElement('span');
            span.className = 'stat-item';
            const i = document.createElement('i');
            i.setAttribute('data-lucide', icon);
            span.appendChild(i);
            const s = document.createElement('span');
            s.textContent = text;
            span.appendChild(s);
            return span;
        };

        if (tok > 0) statsDiv.appendChild(addStat('activity', `${tok} tok`));
        if (elapsed > 0) {
            const timeText = speed ? `${elapsed}s · ${speed} tok/s` : `${elapsed}s`;
            statsDiv.appendChild(addStat('timer', timeText));
        }
        if (model) {
            const modelSpan = addStat('cpu', model);
            modelSpan.classList.add('stat-model');
            statsDiv.appendChild(modelSpan);
        }
        if (ragCount > 0) {
            const ragSpan = document.createElement('span');
            ragSpan.className = 'stat-item stat-rag';
            const ragIcon = document.createElement('i');
            ragIcon.setAttribute('data-lucide', 'book-open');
            ragSpan.appendChild(ragIcon);
            const ragText = document.createElement('span');
            ragText.textContent = `RAG ${ragCount}`;
            ragSpan.appendChild(ragText);
            if (stats.rag_items && stats.rag_items.length > 0) {
                const barSpan = document.createElement('span');
                barSpan.className = 'rag-bar';
                stats.rag_items.forEach(([col, score]) => {
                    const block = document.createElement('span');
                    block.className = 'rag-block';
                    block.style.opacity = Math.max(0.2, score);
                    block.title = `${col}: ${Math.round(score * 100)}%`;
                    barSpan.appendChild(block);
                });
                ragSpan.appendChild(barSpan);
            }
            if (ragAvg > 0) {
                const pctSpan = document.createElement('span');
                pctSpan.textContent = ` ${Math.round(ragAvg * 100)}%`;
                ragSpan.appendChild(pctSpan);
            }
            statsDiv.appendChild(ragSpan);
        }
        if (memSaved > 0) {
            const memSpan = document.createElement('span');
            memSpan.className = 'stat-item stat-mem' + (stats.mem_facts ? ' mem-expandable' : '');
            const memIcon = document.createElement('i');
            memIcon.setAttribute('data-lucide', 'bookmark-check');
            memSpan.appendChild(memIcon);
            const memText = document.createElement('span');
            memText.textContent = this.t('saved');
            memSpan.appendChild(memText);
            if (stats.mem_facts && stats.mem_facts.length > 0) {
                const tooltip = document.createElement('div');
                tooltip.className = 'mem-tooltip';
                stats.mem_facts.forEach(fact => {
                    const div = document.createElement('div');
                    div.className = 'mem-fact';
                    div.textContent = fact;
                    tooltip.appendChild(div);
                });
                memSpan.appendChild(tooltip);
            }
            statsDiv.appendChild(memSpan);
        }

        // B-mem-delete-ui: show red delete badge for historical delete operations
        const memDeleted = stats.mem_deleted || 0;
        if (memDeleted > 0) {
            const delSpan = document.createElement('span');
            delSpan.className = 'stat-item stat-mem-del';
            const delIcon = document.createElement('i');
            delIcon.setAttribute('data-lucide', 'trash-2');
            delSpan.appendChild(delIcon);
            const delText = document.createElement('span');
            delText.textContent = this.t('deleted');
            delSpan.appendChild(delText);
            statsDiv.appendChild(delSpan);
        }

        // Copy button
        const copyBtn = document.createElement('button');
        copyBtn.className = 'copy-btn';
        copyBtn.title = 'Copy';
        const copyI = document.createElement('i');
        copyI.setAttribute('data-lucide', 'copy');
        copyBtn.appendChild(copyI);
        copyBtn.addEventListener('click', () => {
            navigator.clipboard.writeText(textDiv.innerText).then(() => {
                const checkI = document.createElement('i');
                checkI.setAttribute('data-lucide', 'check');
                copyBtn.replaceChildren(checkI);
                if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [copyBtn] });
                setTimeout(() => {
                    const restoreI = document.createElement('i');
                    restoreI.setAttribute('data-lucide', 'copy');
                    copyBtn.replaceChildren(restoreI);
                    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [copyBtn] });
                }, 2000);
            }).catch(() => {});
        });
        statsDiv.appendChild(copyBtn);

        if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [statsDiv] });
    },
});
