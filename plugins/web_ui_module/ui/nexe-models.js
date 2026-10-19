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
            this._cloud = data.cloud || { allowed: false, providers: [] };
            this._updateCloudToggle();

            if (!data.backends.length && retryCount < 3) {
                setTimeout(() => this.loadBackends(retryCount + 1), 2000 * (retryCount + 1));
                return;
            }

            backendSel.innerHTML = '';
            for (const b of data.backends) {
                const opt = document.createElement('option');
                opt.value = b.id;
                const disconnected = b.connected === false;
                // The API group is the only one whose answers leave the machine:
                // a cloud in front of it says so before anything is chosen.
                const label = b.cloud ? `☁️ ${b.name}` : b.name;
                opt.textContent = disconnected ? `${label} (${this.t('disconnected')})` : label;
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
                const cloudCb = document.getElementById('cloudToggle');
                if (cloudCb) cloudCb.addEventListener('change', () => this._onCloudToggleChange());
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

    // ── Cloud engines (API providers) ──────────────────────────────────
    // The global switch, the consent dialog and the follow-up to a refusal.
    // The server is the authority on all three: the UI only asks and shows.

    _updateCloudToggle() {
        const cb = document.getElementById('cloudToggle');
        if (!cb) return;
        const cloud = this._cloud || { allowed: false, providers: [] };
        cb.checked = cloud.allowed === true;
        const configured = (cloud.providers || []).filter(p => p.configured).map(p => p.name);
        // Never a key: only which providers have one on the server.
        cb.title = configured.length
            ? `${this.t('cloud_allow_info')} (${configured.join(', ')})`
            : `${this.t('cloud_allow_info')} — ${this.t('cloud_no_provider')}`;
    },

    async _onCloudToggleChange() {
        const cb = document.getElementById('cloudToggle');
        if (!cb) return;
        const desired = cb.checked;
        try {
            const resp = await this.fetchWithCsrf('/ui/cloud-engines', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: desired })
            });
            if (!resp.ok) {
                cb.checked = !desired;  // the server did not take it: show the truth
                return;
            }
        } catch (e) {
            console.error('Error toggling cloud engines:', e);
            cb.checked = !desired;
            return;
        }
        // The API group appears or disappears with the switch.
        await this.loadBackends();
    },

    // Resolves true only on an explicit yes. Everything the dialog shows goes
    // through textContent: the provider's name comes from the server.
    _askCloudConsent(providerName) {
        return new Promise((resolve) => {
            const existing = document.getElementById('nexe-cloud-consent');
            if (existing) existing.remove();

            const overlay = document.createElement('div');
            overlay.id = 'nexe-cloud-consent';
            overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;display:flex;align-items:center;justify-content:center';

            const box = document.createElement('div');
            box.style.cssText = 'background:var(--bg-secondary,#1e1e2e);border:1px solid var(--border,#333);border-radius:12px;padding:24px 28px;max-width:460px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.4)';

            const title = document.createElement('h3');
            title.style.cssText = 'margin:0 0 8px;font-size:15px;color:var(--text-primary,#cdd6f4)';
            title.textContent = `☁️ ${this.t('cloud_consent_title')}`;

            const msg = document.createElement('p');
            msg.style.cssText = 'margin:0 0 20px;font-size:13px;color:var(--text-secondary,#a6adc8)';
            msg.textContent = this.t('cloud_consent_msg').replace(/\{provider\}/g, providerName);

            const btnRow = document.createElement('div');
            btnRow.style.cssText = 'display:flex;gap:10px;justify-content:flex-end';

            const noBtn = document.createElement('button');
            noBtn.style.cssText = 'padding:8px 16px;border-radius:8px;border:1px solid var(--border,#333);background:transparent;color:var(--text-secondary,#a6adc8);cursor:pointer;font-size:13px';
            noBtn.textContent = this.t('cloud_consent_no');

            const yesBtn = document.createElement('button');
            yesBtn.style.cssText = 'padding:8px 16px;border-radius:8px;border:none;background:#2e86de;color:#fff;cursor:pointer;font-size:13px;font-weight:600';
            yesBtn.textContent = this.t('cloud_consent_yes');

            btnRow.appendChild(noBtn);
            btnRow.appendChild(yesBtn);
            box.appendChild(title);
            box.appendChild(msg);
            box.appendChild(btnRow);
            overlay.appendChild(box);
            document.body.appendChild(overlay);

            const close = (yes) => { overlay.remove(); resolve(yes); };
            yesBtn.addEventListener('click', () => close(true));
            noBtn.addEventListener('click', () => close(false));
            // Outside the box is a "no": consent is never given by accident.
            overlay.addEventListener('click', (e) => { if (e.target === overlay) close(false); });
        });
    },

    // The server's reason for a refusal of the cloud gate, in the UI's language
    // (the server's own English text when the code is one the UI does not know).
    async _cloudErrorText(response) {
        let detail = null;
        try { detail = (await response.clone().json()).detail; } catch { /* not JSON */ }
        if (!detail || typeof detail !== 'object' || typeof detail.code !== 'string') return '';
        if (!detail.code.startsWith('cloud_')) return '';
        const known = this.t(`err_${detail.code}`);
        return known && known !== `err_${detail.code}` ? known : (detail.message || '');
    },

    // After a 403/400 on /ui/chat: null when the refusal is not the cloud
    // gate's (the caller keeps its generic path). On "consent required" it
    // asks and, on a yes, sends the same turn again with the consent.
    async _cloudRefusalFollowUp(response, chatBody) {
        let detail = null;
        try { detail = (await response.clone().json()).detail; } catch { /* not JSON */ }
        if (!detail || typeof detail !== 'object' || typeof detail.code !== 'string') return null;
        if (detail.code === 'cloud_consent_required') {
            const yes = await this._askCloudConsent(detail.provider_name || detail.provider || '');
            if (!yes) return { declined: true };
            const again = await this.fetchWithCsrf('/ui/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ...chatBody, cloud_consent: detail.provider }),
                signal: this.abortController ? this.abortController.signal : undefined
            });
            return { response: again };
        }
        const why = await this._cloudErrorText(response);
        return why ? { refused: why } : null;
    },

    // A turn the server refused before storing it: take the bubble back out
    // and give the user their text (and picture) again.
    _undoUnsentTurn(message, pendingImage, continueState) {
        if (continueState) return;
        const last = this.chatMessages && this.chatMessages.lastElementChild;
        if (last && last.classList && last.classList.contains('user')) last.remove();
        if (this.messageInput) this.messageInput.value = message;
        if (pendingImage && this.imagePreviewBar) {
            this._selectedImage = pendingImage;
            this.imagePreviewThumb.src = `data:${pendingImage.type};base64,${pendingImage.b64}`;
            this.imagePreviewName.textContent = pendingImage.name || '';
            this.imagePreviewBar.style.display = 'flex';
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
                const hasThinking = this._canThink(name, backendId);
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
        // A hosted model is not judged by its name: the server says, per model,
        // whether the provider's entry declares it image-capable.
        if (backend === 'api') {
            const group = (this._backends || []).find(b => b.id === 'api');
            const entry = group && group.models.find(m => (typeof m === 'object' ? m.name : m) === name);
            return !!(entry && typeof entry === 'object' && entry.vision === true);
        }
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
            } else if (backend === 'api') {
                const why = await this._cloudErrorText(resp);
                if (el && why) el.textContent = why;
            }
        } catch (e) {
            console.error('Failed to set backend:', e);
        }
        // Update thinking toggle state after model change
        this._updateThinkingToggle();
    },
});
