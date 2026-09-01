/**
 * ============================================
 * Nexe UI — engines, models and readiness
 * ============================================
 * Split out of app.js (#127). The backend/model selector and everything that reports on it: which engines exist, which model is active, whether the server is ready, and the degraded banner.
 *
 * Classic <script>, loaded AFTER app.js (the class must exist before its
 * prototype can be extended) and before DOMContentLoaded, which is when the
 * instance is built. Not an ES module: the cache-bust rewrites `.js"` in
 * index.html and never sees an `import` inside a .js file.
 *
 * Bodies are the ones that were in the class, unchanged.
 */
/* global NexeUI, UI_STRINGS */
NexeUI.extend({
    // D-Q: say it out loud when a subsystem is down. Until now the only trace
    // was a line in the boot log; the user kept chatting believing memory
    // worked. The state is the watcher's confirmed one, so a backend that
    // flaps for a few seconds does not blink a warning nobody would read.
    _updateDegradedBanner(status) {
        const state = status && status.operational_state;
        const impaired = (status && status.impaired_subsystems) || [];
        const healthy = !state || state === 'normal' || impaired.length === 0;

        // The health summary: a glance at the footer indicator is enough.
        // Both directions: a label left saying "half power" after recovery is
        // a lie that survives until the next reload. This method only runs
        // when the server answered, so "connected" is the right word here.
        const label = document.querySelector('.status-indicator span');
        if (label) label.textContent = healthy ? this.t('connected') : this.t('degraded_status');

        if (healthy) {
            this._clearDegradedNotice();
            return;
        }

        const dot = document.querySelector('.status-dot');
        if (dot) dot.classList.add('degraded');

        // The detail: right where the user is about to type, so nobody sends
        // a message expecting memory to work when it does not.
        const notice = document.getElementById('degradedNotice');
        if (!notice) return;
        const names = this.t('degraded_names') || {};
        const readable = impaired.map(name => names[name] || name).join(', ');
        const suffix = impaired.length === 1 ? 'degraded_suffix_one' : 'degraded_suffix_many';
        notice.textContent = this.t('degraded_prefix') + readable + this.t(suffix);
        notice.style.display = 'block';
    },

    // While the server is unreachable nothing is known about its subsystems,
    // so the last warning stops being information. Leaving it up also leaves
    // the dot's amber ring around a red dot.
    _clearDegradedNotice() {
        const dot = document.querySelector('.status-dot');
        if (dot) dot.classList.remove('degraded');
        const notice = document.getElementById('degradedNotice');
        if (!notice) return;
        notice.style.display = 'none';
        notice.textContent = '';
    },

    async _waitForReady() {
        const overlay = document.getElementById('readinessOverlay');
        if (!overlay) return;
        overlay.style.display = 'flex';
        const MAX_ATTEMPTS = 120; // ~6 min at 3s intervals
        let attempts = 0;
        while (attempts < MAX_ATTEMPTS) {
            attempts++;
            try {
                const r = await fetch('/health/ready', { cache: 'no-store' });
                if (r.ok) {
                    const data = await r.json();
                    if (data.status === 'healthy' || data.status === 'degraded') {
                        overlay.style.display = 'none';
                        return;
                    }
                    console.warn('[nexe] readiness: status =', data.status);
                } else {
                    console.warn('[nexe] readiness: HTTP', r.status);
                }
            } catch (err) {
                console.warn('[nexe] readiness fetch error:', err.message || err);
            }
            await new Promise(res => setTimeout(res, 3000));
        }
        // Timeout — hide overlay anyway so user can interact
        console.error('[nexe] readiness timeout after', MAX_ATTEMPTS, 'attempts — forcing UI load');
        overlay.style.display = 'none';
    },

    async loadServerInfo() {
        try {
            const resp = await this.fetchWithCsrf('/ui/info');
            if (resp.status === 401) {
                this._handleUnauthorized();
                return;
            }
            if (resp.ok) {
                const data = await resp.json();
                // Apply server language
                if (data.lang && UI_STRINGS[data.lang]) {
                    this.lang = data.lang;
                    document.documentElement.lang = data.lang;
                    const ls = document.getElementById('langSelect');
                    if (ls) ls.value = data.lang;
                    this.applyI18n();
                }
                // Persist the version on the instance so applyI18n() can
                // render the footer copyright in any language without losing
                // the version suffix. Re-apply once after the value lands.
                if (data.version) {
                    this.version = data.version;
                    this.applyI18n();
                }
                const el = document.getElementById('modelInfoText');
                if (el) {
                    const backend = data.backend === 'auto' ? '' : ` · ${data.backend}`;
                    el.textContent = data.model + backend;
                    el.title = `model: ${data.model}\nbackend: ${data.backend}\nversion: ${data.version}`;
                }
            }
        } catch {
            const el = document.getElementById('modelInfoText');
            if (el) el.textContent = 'nexe';
        } finally {
            this.loadBackends();
        }
    },

    async loadBackends(retryCount = 0) {
        const backendSel = document.getElementById('backendSelect');
        const modelSel = document.getElementById('modelSelect');
        if (!backendSel || !modelSel) return;

        try {
            const resp = await this.fetchWithCsrf('/ui/backends');
            if (!resp.ok) {
                if (retryCount < 3) {
                    setTimeout(() => this.loadBackends(retryCount + 1), 2000 * (retryCount + 1));
                }
                return;
            }
            const data = await resp.json();
            this._backends = data.backends;
            this._currentModel = data.current_model || '';

            if (!data.backends.length && retryCount < 3) {
                setTimeout(() => this.loadBackends(retryCount + 1), 2000 * (retryCount + 1));
                return;
            }

            backendSel.innerHTML = '';
            for (const b of data.backends) {
                const opt = document.createElement('option');
                opt.value = b.id;
                const disconnected = b.connected === false;
                opt.textContent = disconnected ? `${b.name} (${this.t('disconnected')})` : b.name;
                opt.dataset.connected = disconnected ? '0' : '1';
                if (b.active) opt.selected = true;
                backendSel.appendChild(opt);
            }

            this._updateModelSelect(backendSel.value, this._currentModel);
            // Update thinking toggle after models are populated
            this._updateThinkingToggle();

            if (!this._backendListenersAttached) {
                this._backendListenersAttached = true;
                backendSel.addEventListener('change', () => {
                    this._updateModelSelect(backendSel.value);
                    this._applyBackendChange();
                });
                modelSel.addEventListener('change', () => {
                    this._applyBackendChange();
                });
            }
        } catch (e) {
            console.error('Failed to load backends:', e);
            if (retryCount < 3) {
                setTimeout(() => this.loadBackends(retryCount + 1), 2000 * (retryCount + 1));
            }
        }
    },

    _updateModelSelect(backendId, currentModel) {
        const modelSel = document.getElementById('modelSelect');
        if (!modelSel || !this._backends) return;

        const backend = this._backends.find(b => b.id === backendId);
        modelSel.innerHTML = '';
        if (backend) {
            for (const m of backend.models) {
                const opt = document.createElement('option');
                // Supports object {name, size_gb} or legacy string
                const name = typeof m === 'object' ? m.name : m;
                opt.value = name;
                // Shows 👁️ if has vision, 🧠 if thinks + approximate RAM size
                const hasVision = this._modelHasVision(name, backendId);
                const hasThinking = this._canThink(name);
                const sizeGb = typeof m === 'object' ? m.size_gb : 0;
                const sizeTag = sizeGb > 0 ? ` (~${sizeGb}GB)` : '';
                const prefix = (hasVision ? '👁️ ' : '') + (hasThinking ? '🧠 ' : '');
                opt.textContent = prefix + name + sizeTag;
                if (currentModel && (currentModel.includes(name) || name.includes(currentModel))) {
                    opt.selected = true;
                }
                modelSel.appendChild(opt);
            }
        }
    },

    /// Client-side heuristic: a model has vision (VLM) if the name contains
    /// known multimodal families/tags. Equivalent to hasVision in the Swift wizard.
    /// backend: 'ollama'|'mlx'|'llamacpp' — used to exclude models that need
    /// runtime deps not present on a given engine.
    _modelHasVision(name, backend) {
        const n = (name || '').toLowerCase();
        // Models that historically crashed on MLX because they needed torch
        // and the dev/DMG bundles did not ship it. Empirical 2026-05-13:
        // PyTorch is now bundled (DMG) and installed in the dev venv, so
        // Qwen3.5-Omni MLX vision works (verified end-to-end with an image
        // describe request to qwen3.5:4b returning a correct caption).
        // Kept here as an empty-by-default list so future incompatibilities
        // can be re-added without restructuring the heuristic.
        const omniExcludes = [
            'qwen3-omni',
            'kimi-vl',
            'qwen3-vl-moe',
        ];
        if (backend === 'mlx' && omniExcludes.some(p => n.includes(p))) return false;

        const patterns = [
            'qwen3.5', 'qwen3-vl', 'qwen2.5-vl', 'qwen-vl',
            'gemma4', 'gemma-4', 'gemma3', 'gemma-3',
            'llama4', 'llama-4', 'llama3.2-vision',
            'pixtral', 'llava', 'moondream', 'bakllava',
            'minicpm-v', 'internvl', 'cogvlm',
            '-vl', '-vlm', 'vision', 'multimodal',
        ];
        return patterns.some(p => n.includes(p));
    },

    async _applyBackendChange() {
        const backendSel = document.getElementById('backendSelect');
        const modelSel = document.getElementById('modelSelect');
        if (!backendSel || !modelSel) return;

        const backend = backendSel.value;
        const model = modelSel.value;
        const selectedOpt = backendSel.selectedOptions[0];
        const wasDisconnected = selectedOpt && selectedOpt.dataset.connected === '0';
        // Flag: the next chat will likely trigger MODEL_LOADING (the
        // new model is not yet in VRAM). `sendMessage` checks this
        // flag to skip the "Processing…" wave placeholder and let
        // the blue loading banner be the primary signal. The flag
        // is cleared on MODEL_READY or at the end of the stream.
        this._modelJustChanged = true;

        const el = document.getElementById('modelInfoText');
        if (wasDisconnected && el) {
            el.textContent = `Ollama — ${this.t('starting')}`;
        }

        try {
            const resp = await this.fetchWithCsrf('/ui/backend', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ backend, model })
            });
            if (resp.ok) {
                const data = await resp.json();
                if (data.ollama_started) {
                    if (el) el.textContent = `Ollama — ${this.t('starting')}`;
                    // Retry until Ollama is connected (max 30s)
                    let ready = false;
                    for (let i = 0; i < 10 && !ready; i++) {
                        await new Promise(r => setTimeout(r, 3000));
                        if (el) el.textContent = `Ollama — ${this.t('starting')} (${(i + 1) * 3}s)`;
                        try {
                            const r2 = await this.fetchWithCsrf('/ui/backends');
                            if (r2.ok) {
                                const d2 = await r2.json();
                                const ollama = d2.backends.find(b => b.id === 'ollama');
                                if (ollama && ollama.connected) {
                                    ready = true;
                                    this._backends = d2.backends;
                                    this._updateModelSelect('ollama');
                                    if (el) el.textContent = `Ollama ${this.t('connected').toLowerCase()}`;
                                    // Update the dropdown (remove "disconnected")
                                    const opt = backendSel.querySelector('[value="ollama"]');
                                    if (opt) opt.textContent = 'Ollama';
                                }
                            }
                        } catch { /* intentional: ignore JSON parse error */ }
                    }
                    if (!ready && el) el.textContent = this.t('ollama_not_responding');
                } else {
                    if (el) el.textContent = `${model} · ${backend}`;
                }
            }
        } catch (e) {
            console.error('Failed to set backend:', e);
        }
        // Update thinking toggle state after model change
        this._updateThinkingToggle();
    },
});
