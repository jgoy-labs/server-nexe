/**
 * ============================================
 * Nexe UI - Client JavaScript
 * ============================================
 */
/* global confirm, alert, AbortController, TextDecoder, FileReader, UI_STRINGS */

// UI_STRINGS (i18n ca/en/es) lives in i18n.js, loaded as a classic <script>
// BEFORE this file in index.html (shared top-level global scope).

class NexeUI {
    constructor() {
        this.apiKey = localStorage.getItem('nexe_api_key') || null;
        // Cross-origin handoff: when Tauri (splash) or the onboarding wizard
        // navigates the webview to http://127.0.0.1:{port}/ui/#nexe_api_key=K,
        // the splash's localStorage at tauri://localhost is not visible here.
        // The key travels in the URL *fragment* so it is never sent to the
        // server and never reaches uvicorn's access log (K-001). Persist it
        // into the sidecar-origin localStorage and scrub the URL so the secret
        // doesn't linger in history. A legacy ?nexe_api_key= query is still
        // honoured for backward compatibility. No-op when both are absent
        // (standalone browser / manual login flow).
        const _hashApiKey = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('nexe_api_key');
        const _qsApiKey = _hashApiKey || new URLSearchParams(window.location.search).get('nexe_api_key');
        if (_qsApiKey) {
            localStorage.setItem('nexe_api_key', _qsApiKey);
            this.apiKey = _qsApiKey;
            const _clean = new URL(window.location.href);
            _clean.searchParams.delete('nexe_api_key');
            _clean.hash = '';
            window.history.replaceState(null, '', _clean.toString());
        }
        // Language: server (injected data-attr) > html lang > browser > english
        const serverLang = document.documentElement.dataset.nexeLang || document.documentElement.lang;
        const browserLang = (navigator.language || 'en').split('-')[0];
        const preferredLang = serverLang || browserLang;
        this.lang = UI_STRINGS[preferredLang] ? preferredLang : 'en';
        this.version = null;
        this.currentSessionId = null;
        this.uploadedFile = null;
        this.sessions = [];
        this.abortController = null;
        this.isGenerating = false;
        // Stats streaming
        this._streamStart = 0;
        this._streamTokens = 0;
        this._statsInterval = null;

        this.init();
    }

    t(key) {
        return (UI_STRINGS[this.lang] || UI_STRINGS.en)[key] || UI_STRINGS.en[key] || key;
    }

    applyI18n() {
        const s = (sel, key, attr) => {
            const el = document.querySelector(sel);
            if (!el) return;
            if (attr === 'placeholder') el.placeholder = this.t(key);
            else if (attr === 'title') el.title = this.t(key);
            else if (attr === 'html') el.innerHTML = this.t(key);
            else el.textContent = this.t(key);
        };
        // Login
        s('.login-subtitle', 'login_subtitle');
        s('#loginBtn', 'login_btn');
        s('#loginError', 'login_error', 'html');
        s('.login-hint', 'login_hint', 'html');
        // Welcome — regenerate the full DOM if visible (all 10 buttons translated)
        if (this.chatMessages && this.chatMessages.querySelector('.welcome-screen')) {
            this.showWelcome();
        }
        // Sidebar
        s('#newChatBtn', 'new_chat');
        const newBtn = document.getElementById('newChatBtn');
        if (newBtn) { newBtn.innerHTML = `<i data-lucide="plus"></i> ${this.t('new_chat')}`; }
        s('.sessions-header h3', 'sessions');
        // Selectors
        const bSel = document.getElementById('backendSelect');
        if (bSel && bSel.options[0] && !bSel.options[0].value) bSel.options[0].textContent = this.t('loading');
        const mSel = document.getElementById('modelSelect');
        if (mSel && mSel.options[0] && !mSel.options[0].value) mSel.options[0].textContent = this.t('loading');
        // RAG — preserve the ⓘ button inside the title
        const ragTitle = document.querySelector('.rag-threshold-title');
        if (ragTitle) {
            const infoBtn = ragTitle.querySelector('.rag-info-toggle');
            ragTitle.textContent = '';
            ragTitle.append(this.t('rag_title') + ' ');
            if (infoBtn) { infoBtn.title = this.t('rag_info'); ragTitle.appendChild(infoBtn); }
        }
        const hints = document.querySelectorAll('.rag-threshold-hints span');
        if (hints[0]) hints[0].textContent = this.t('rag_wide');
        if (hints[1]) hints[1].textContent = this.t('rag_strict');
        // RAG info panel
        const ragPanel = document.getElementById('ragInfoPanel');
        if (ragPanel) {
            ragPanel.innerHTML = `<p><strong>${this.t('rag_panel_title')}</strong></p>` +
                `<p>${this.t('rag_panel_desc')}</p>` +
                `<ul><li>${this.t('rag_panel_low')}</li>` +
                `<li>${this.t('rag_panel_high')}</li>` +
                `<li>${this.t('rag_panel_rec')}</li></ul>`;
        }
        // Collections
        s('.collection-title', 'col_title');
        s('[data-i18n="col_memory"]', 'col_memory');
        s('[data-i18n="col_knowledge"]', 'col_knowledge');
        s('[data-i18n="col_docs"]', 'col_docs');
        // Collection tooltips (Bug #8: visible ⓘ icon + label fallback)
        const colMemLabel = document.querySelector('[data-i18n="col_memory"]');
        if (colMemLabel) colMemLabel.closest('label').title = this.t('col_memory_tip');
        const colMemInfo = document.getElementById('colMemoryInfo');
        if (colMemInfo) colMemInfo.title = this.t('col_memory_tip');
        const colKnowLabel = document.querySelector('[data-i18n="col_knowledge"]');
        if (colKnowLabel) colKnowLabel.closest('label').title = this.t('col_knowledge_tip');
        const colKnowInfo = document.getElementById('colKnowledgeInfo');
        if (colKnowInfo) colKnowInfo.title = this.t('col_knowledge_tip');
        const colDocsLabel = document.querySelector('[data-i18n="col_docs"]');
        if (colDocsLabel) colDocsLabel.closest('label').title = this.t('col_docs_tip');
        const colDocsInfo = document.getElementById('colDocsInfo');
        if (colDocsInfo) colDocsInfo.title = this.t('col_docs_tip');
        // Thinking toggle tooltip
        const thinkInfo = document.getElementById('thinkingInfo');
        if (thinkInfo) thinkInfo.title = this.t('thinking_tip');
        const thinkLabel = document.querySelector('[data-i18n="thinking_mode"]');
        if (thinkLabel) {
            thinkLabel.textContent = this.t('thinking_mode');
            thinkLabel.closest('label').title = this.t('thinking_tip');
        }
        // Input
        s('#messageInput', 'placeholder', 'placeholder');
        // Buttons
        s('#themeToggleBtn', 'toggle_theme', 'title');
        s('#frameToggleBtn', 'toggle_frame', 'title');
        s('#uploadBtn', 'upload_doc', 'title');
        s('#sendBtn', 'send', 'title');
        s('#stopBtn', 'stop', 'title');
        // Footer
        const thinkText = document.querySelector('.thinking-badge span:last-child');
        if (thinkText) this._setThinkingText(thinkText, this.t('thinking'));
        const statusText = document.querySelector('.status-indicator span');
        if (statusText) statusText.textContent = this.t('connected');
        // Language selector
        s('#langSelect', 'language', 'title');
        // Backend/Model labels
        const bLabels = document.querySelectorAll('.backend-selector-title');
        if (bLabels[0]) bLabels[0].textContent = this.t('backend_label');
        if (bLabels[1]) bLabels[1].textContent = this.t('model_label');
        // Readiness overlay
        s('#readinessText', 'starting');
        // Support link
        const supportLink = document.querySelector('.footer-support');
        if (supportLink) {
            const heartIcon = supportLink.querySelector('i');
            supportLink.textContent = '';
            if (heartIcon) supportLink.appendChild(heartIcon);
            supportLink.append(' ' + this.t('support_link'));
        }
        // Footer copyright (with persisted version). this.version is null
        // until loadServerInfo() succeeds; we then render without "vX.Y" and
        // re-apply once the version arrives.
        const footerText = document.querySelector('.footer-text');
        if (footerText) {
            const versionSuffix = this.version ? ` v${this.version}` : '';
            footerText.textContent = this.t('footer_copyright') + versionSuffix;
        }
        // Footer docs link
        const docsLink = document.querySelector('[data-i18n="footer_docs"]');
        if (docsLink) docsLink.textContent = this.t('footer_docs');
        // HTML lang
        document.documentElement.lang = this.lang;
        // Re-render Lucide icons
        if (typeof lucide !== 'undefined') lucide.createIcons();
        // Refresh collection warning with updated language
        if (this._listenersAttached) this._updateCollectionWarning();
    }

    _setThinkingText(spanEl, text) {
        // Breaks the text into a <span> per letter so CSS can
        // apply a different `animation-delay` to each one and form a
        // loading-style "wave". Preserves spaces with nbsp ( ) because
        // inline-block would collapse whitespace.
        spanEl.textContent = '';
        const chars = [...(text || '')];
        chars.forEach((ch, i) => {
            const letter = document.createElement('span');
            letter.className = 'think-char';
            letter.style.setProperty('--i', String(i));
            letter.textContent = ch === ' ' ? ' ' : ch;
            spanEl.appendChild(letter);
        });
    }

    setAiState(state) {
        document.documentElement.setAttribute('data-ai-state', state);
        const badge = document.getElementById('thinkingBadge');
        if (badge) {
            badge.classList.toggle('active', state === 'thinking' || state === 'streaming');
        }
        // Reset to idle after 2s if it was an error
        if (state === 'error') {
            clearTimeout(this._errorResetTimer);
            this._errorResetTimer = setTimeout(() => {
                document.documentElement.setAttribute('data-ai-state', 'idle');
            }, 2000);
        }
    }

    async fetchWithCsrf(url, options = {}) {
        const opts = { ...options };
        opts.credentials = opts.credentials || 'same-origin';
        if (this.apiKey) {
            opts.headers = { ...(opts.headers || {}), 'X-API-Key': this.apiKey };
        }
        const resp = await fetch(url, opts);
        // Auto-retry once on 401 — handles startup race condition (BUG-04)
        if (resp.status === 401 && this.apiKey && !opts._retried) {
            await new Promise(r => setTimeout(r, 500));
            opts._retried = true;
            if (this.apiKey) {
                opts.headers = { ...(opts.headers || {}), 'X-API-Key': this.apiKey };
            }
            return fetch(url, opts);
        }
        return resp;
    }

    async init() {
        this.applyI18n();
        this._initLangSelector();
        if (!this.apiKey) {
            // Hide readiness overlay immediately — no server contact needed yet
            const ro = document.getElementById('readinessOverlay');
            if (ro) ro.style.display = 'none';
            this.showLoginOverlay();
            return;
        }
        try {
            await this.initUI();
        } catch (err) {
            console.error('[nexe] initUI failed:', err);
            // Force-hide readiness overlay so user sees something
            const overlay = document.getElementById('readinessOverlay');
            if (overlay) overlay.style.display = 'none';
        }
    }

    _initLangSelector() {
        const langSelect = document.getElementById('langSelect');
        if (!langSelect) return;
        langSelect.value = this.lang;
        langSelect.addEventListener('change', async () => {
            this.lang = langSelect.value;
            this.applyI18n();
            // Persist to server
            try {
                await this.fetchWithCsrf('/ui/lang', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ lang: langSelect.value })
                });
            } catch (e) {
                console.warn('Could not save language to server:', e);
            }
        });
    }

    _initCollectionToggles() {
        const COLL_MAP = {
            colMemory: 'personal_memory',
            colKnowledge: 'user_knowledge',
            colDocs: 'nexe_documentation'
        };
        const saved = localStorage.getItem('nexe_collections');
        if (saved) {
            try {
                const disabled = JSON.parse(saved);
                for (const [id, coll] of Object.entries(COLL_MAP)) {
                    const cb = document.getElementById(id);
                    if (cb) cb.checked = !disabled.includes(coll);
                }
            } catch { /* ignore corrupt localStorage */ }
        }
        for (const id of Object.keys(COLL_MAP)) {
            const cb = document.getElementById(id);
            if (cb) cb.addEventListener('change', () => {
                this._saveCollectionState();
                this._updateCollectionWarning();
            });
        }
        this._updateCollectionWarning();
    }

    _saveCollectionState() {
        const COLL_MAP = {
            colMemory: 'personal_memory',
            colKnowledge: 'user_knowledge',
            colDocs: 'nexe_documentation'
        };
        const disabled = [];
        for (const [id, coll] of Object.entries(COLL_MAP)) {
            const cb = document.getElementById(id);
            if (cb && !cb.checked) disabled.push(coll);
        }
        localStorage.setItem('nexe_collections', JSON.stringify(disabled));
    }

    // F-checks-info + B-coll-check: show warning when any collection is disabled
    _updateCollectionWarning() {
        const warn = document.getElementById('collectionWarning');
        if (!warn) return;
        const active = this._getActiveCollections();
        const COLL_LABELS = {
            personal_memory: this.t('col_memory') || 'Personal memory',
            user_knowledge: this.t('col_knowledge') || 'Knowledge base',
            nexe_documentation: this.t('col_docs') || 'Documentation'
        };
        const ALL = ['personal_memory', 'user_knowledge', 'nexe_documentation'];
        const disabled = ALL.filter(c => !active.includes(c));
        if (disabled.length === 0) {
            warn.style.display = 'none';
            warn.textContent = '';
        } else {
            const names = disabled.map(c => COLL_LABELS[c] || c).join(', ');
            warn.style.display = 'block';
            warn.textContent = this.t('col_warning_prefix') + names + this.t('col_warning_suffix');
        }
    }

    _getActiveCollections() {
        const ALL = ['personal_memory', 'user_knowledge', 'nexe_documentation'];
        const saved = localStorage.getItem('nexe_collections');
        if (!saved) return ALL;
        try {
            const disabled = JSON.parse(saved);
            return ALL.filter(c => !disabled.includes(c));
        } catch { return ALL; }
    }

    // ── Thinking toggle ────────────────────────────────────────────
    // Mirror of Python THINKING_CAPABLE safelist (ollama_module/core/chat.py)
    _canThink(model) {
        const THINKING_FAMILIES = [
            'qwen3.5', 'qwen3', 'qwq',
            'deepseek-r1',
            'gemma3', 'gemma4',
            'llama4', 'gpt-oss',
        ];
        const n = (model || '').toLowerCase().split('/').pop().split(':')[0];
        return THINKING_FAMILIES.some(f => n.includes(f));
    }

    _initThinkingToggle() {
        const cb = document.getElementById('thinkingToggle');
        if (!cb) return;
        // Default OFF — never auto-enable
        cb.checked = false;
        cb.addEventListener('change', () => {
            this._onThinkingToggleChange();
        });
        // Set initial enabled/disabled state based on current model
        this._updateThinkingToggle();
    }

    _updateThinkingToggle() {
        const cb = document.getElementById('thinkingToggle');
        if (!cb) return;
        const modelSel = document.getElementById('modelSelect');
        const model = modelSel ? modelSel.value : '';
        const supported = this._canThink(model);
        cb.disabled = !supported;
        if (!supported && cb.checked) {
            cb.checked = false;
            this._onThinkingToggleChange();
        }
        cb.title = supported ? this.t('thinking_mode') : this.t('thinking_not_supported');
    }

    async _onThinkingToggleChange() {
        const cb = document.getElementById('thinkingToggle');
        if (!cb || !this.currentSessionId) return;
        const desired = cb.checked;
        try {
            const resp = await this.fetchWithCsrf(`/ui/session/${this.currentSessionId}/thinking`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: desired })
            });
            if (!resp.ok) {
                console.error('PATCH thinking failed:', resp.status);
                cb.checked = !desired;  // revert on failure
            }
        } catch (e) {
            console.error('Error toggling thinking:', e);
            cb.checked = !desired;  // revert on network error
        }
    }

    _restoreThinkingToggle(session) {
        const cb = document.getElementById('thinkingToggle');
        if (!cb) return;
        const enabled = session && session.thinking_enabled === true;
        const modelSel = document.getElementById('modelSelect');
        const model = modelSel ? modelSel.value : '';
        const supported = this._canThink(model);
        cb.disabled = !supported;
        cb.checked = supported && enabled;
        cb.title = supported ? this.t('thinking_mode') : this.t('thinking_not_supported');
    }

    showLoginOverlay() {
        const overlay = document.getElementById('loginOverlay');
        overlay.style.display = 'flex';
        const input = document.getElementById('apiKeyInput');
        const btn = document.getElementById('loginBtn');
        const error = document.getElementById('loginError');

        // Pre-fill with the saved key (if it exists)
        const savedKey = localStorage.getItem('nexe_api_key');
        if (savedKey && !input.value) {
            input.value = savedKey;
        }

        const doLogin = async () => {
            const key = input.value.trim();
            if (!key) return;
            error.style.display = 'none';
            btn.disabled = true;
            try {
                const resp = await fetch('/ui/auth', { headers: { 'X-API-Key': key } });
                if (resp.ok) {
                    this.apiKey = key;
                    localStorage.setItem('nexe_api_key', key);
                    overlay.style.display = 'none';
                    try {
                        await this.initUI();
                    } catch (err) {
                        console.error('[nexe] initUI after login failed:', err);
                        const ro = document.getElementById('readinessOverlay');
                        if (ro) ro.style.display = 'none';
                    }
                    if (typeof lucide !== 'undefined') lucide.createIcons();
                } else {
                    error.style.display = 'block';
                    input.value = '';
                    input.focus();
                }
            } catch {
                error.style.display = 'block';
            } finally {
                btn.disabled = false;
            }
        };

        btn.addEventListener('click', doLogin);
        input.addEventListener('keydown', (e) => { if (e.key === 'Enter') doLogin(); });
        input.focus();
    }

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
    }

    async initUI() {
        // Wait for server readiness before loading UI
        await this._waitForReady();

        // Prevent duplicate event listeners when initUI() is called multiple times
        // (e.g. init → 401 → login → initUI again)
        if (this._listenersAttached) return;
        this._listenersAttached = true;

        // DOM elements
        this.chatMessages = document.getElementById('chatMessages');
        // B025: scroll-lock — track whether the user scrolled up to read.
        // While true, streaming chunks must not drag the view back down.
        this._userScrolledUp = false;
        this.chatMessages.addEventListener('scroll', () => {
            const el = this.chatMessages;
            const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
            this._userScrolledUp = distanceFromBottom > 80;
        });
        this.messageInput = document.getElementById('messageInput');
        this.sendBtn = document.getElementById('sendBtn');
        this.stopBtn = document.getElementById('stopBtn');
        this.newChatBtn = document.getElementById('newChatBtn');
        this.uploadBtn = document.getElementById('uploadBtn');
        this.fileInput = document.getElementById('fileInput');
        this.filePreview = document.getElementById('filePreview');
        this.sessionsList = document.getElementById('sessionsList');
        this.statsBar = document.getElementById('statsBar');

        // VLM: selected image {b64, type, name} or null
        this._selectedImage = null;
        this.imageBtn = document.getElementById('imageBtn');
        this.imageInput = document.getElementById('imageInput');
        this.imagePreviewBar = document.getElementById('imagePreviewBar');
        this.imagePreviewThumb = document.getElementById('imagePreviewThumb');
        this.imagePreviewName = document.getElementById('imagePreviewName');
        this.imageBadge = document.getElementById('imageBadge');

        // Intercepts Cmd+C / Ctrl+C on chat messages: the bubbles
        // (`.message.user`, `.message.assistant`) have a colored background and the
        // default HTML copy carries the styled `background`, which
        // gets pasted to the destination. We replace the clipboard HTML with
        // text/plain + bare HTML without styles.
        this.chatMessages.addEventListener('copy', (e) => {
            const selection = window.getSelection();
            if (!selection || selection.rangeCount === 0) return;
            const text = selection.toString();
            if (!text) return;
            e.preventDefault();
            e.clipboardData.setData('text/plain', text);
            // "Plain" HTML: each line as <br>, no attributes or classes → does not carry background styling.
            const html = text
                .split('\n')
                .map(l => l.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'))
                .join('<br>');
            e.clipboardData.setData('text/html', html);
        });

        // Event listeners
        this.sendBtn.addEventListener('click', () => this.sendMessage());
        this.stopBtn.addEventListener('click', () => this.stopGeneration());
        this.messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        this.newChatBtn.addEventListener('click', () => this.createNewSession());
        this.uploadBtn.addEventListener('click', () => this.fileInput.click());
        this.fileInput.addEventListener('change', (e) => this.handleFileUpload(e));

        // VLM: image attach
        if (this.imageBtn && this.imageInput) {
            this.imageBtn.addEventListener('click', () => this.imageInput.click());
            this.imageInput.addEventListener('change', (e) => this._handleImageSelect(e));
            const clearBtn = document.getElementById('imageClearBtn');
            if (clearBtn) clearBtn.addEventListener('click', () => this._clearSelectedImage());
        }

        // Auto-resize textarea
        this.messageInput.addEventListener('input', () => {
            this.messageInput.style.height = 'auto';
            this.messageInput.style.height = this.messageInput.scrollHeight + 'px';
        });

        // RAG threshold slider
        const ragSlider = document.getElementById('ragThresholdSlider');
        const ragBadge = document.getElementById('ragThresholdValue');
        if (ragSlider && ragBadge) {
            const RAG_DEFAULT = 0.35;
            const saved = localStorage.getItem('nexe_rag_threshold');
            if (saved) {
                const clamped = Math.min(parseFloat(saved), parseFloat(ragSlider.max));
                ragSlider.value = clamped;
                ragBadge.textContent = clamped;
                if (clamped !== parseFloat(saved)) localStorage.setItem('nexe_rag_threshold', clamped);
            } else {
                // B-slider-reset: persist default so it survives page reloads
                ragSlider.value = RAG_DEFAULT;
                ragBadge.textContent = RAG_DEFAULT;
                localStorage.setItem('nexe_rag_threshold', RAG_DEFAULT);
            }
            ragSlider.addEventListener('input', () => {
                ragBadge.textContent = ragSlider.value;
                localStorage.setItem('nexe_rag_threshold', ragSlider.value);
            });
        }

        // RAG info toggle
        const ragInfoBtn = document.getElementById('ragInfoToggle');
        const ragInfoPanel = document.getElementById('ragInfoPanel');
        if (ragInfoBtn && ragInfoPanel) {
            ragInfoBtn.addEventListener('click', () => {
                const open = ragInfoPanel.style.display !== 'none';
                ragInfoPanel.style.display = open ? 'none' : 'block';
                ragInfoBtn.classList.toggle('active', !open);
            });
        }

        // Collection info icons — click shows tooltip text (B8)
        const _showColInfo = (btn) => {
            if (!btn) return;
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                const existing = btn.parentElement.querySelector('.col-info-popup');
                if (existing) { existing.remove(); return; }
                const pop = document.createElement('span');
                pop.className = 'col-info-popup';
                pop.textContent = btn.title;
                btn.parentElement.appendChild(pop);
                setTimeout(() => pop.remove(), 3000);
            });
        };
        _showColInfo(document.getElementById('colMemoryInfo'));
        _showColInfo(document.getElementById('colKnowledgeInfo'));
        _showColInfo(document.getElementById('colDocsInfo'));

        // Collection checkboxes — restore from localStorage
        this._initCollectionToggles();

        // Thinking toggle — default OFF, disabled for non-thinking models
        this._initThinkingToggle();

        // Toggle light/dark theme (detects OS preference if no saved preference)
        const themeBtn = document.getElementById('themeToggleBtn');
        if (themeBtn) {
            const applyTheme = (light) => {
                document.body.classList.toggle('light', light);
                document.documentElement.setAttribute('data-theme', light ? 'light' : 'dark');
            };
            const saved = localStorage.getItem('nexe_theme');
            const preferLight = saved ? saved === 'light' : window.matchMedia('(prefers-color-scheme: light)').matches;
            applyTheme(preferLight);
            // Follow OS changes if the user has not chosen manually
            window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', (e) => {
                if (!localStorage.getItem('nexe_theme')) applyTheme(e.matches);
            });
            themeBtn.addEventListener('click', () => {
                const isLight = document.body.classList.toggle('light');
                document.documentElement.setAttribute('data-theme', isLight ? 'light' : 'dark');
                localStorage.setItem('nexe_theme', isLight ? 'light' : 'dark');
            });
        }

        // Dynamic status indicator (uses fetchWithCsrf to send X-API-Key)
        // /status now requires authentication (Q2.3)
        const statusDot  = document.querySelector('.status-dot');
        const statusText = document.querySelector('.status-indicator span');
        const checkStatus = async () => {
            try {
                const r = await this.fetchWithCsrf('/status', { cache: 'no-store' });
                const ok = r.ok;
                statusDot.classList.toggle('active', ok);
                statusDot.style.background = ok ? '' : '#ff4444';
                statusText.textContent = ok ? this.t('connected') : this.t('disconnected');
            } catch {
                statusDot.classList.remove('active');
                statusDot.style.background = '#ff4444';
                statusText.textContent = this.t('disconnected');
            }
        };
        checkStatus();
        setInterval(checkStatus, 10000);

        // Toggle marc
        const frameBtn = document.getElementById('frameToggleBtn');
        if (frameBtn) {
            const frameHidden = localStorage.getItem('nexe_frame_hidden') === '1';
            if (frameHidden) document.body.classList.add('frame-hidden');
            frameBtn.addEventListener('click', () => {
                const hidden = document.body.classList.toggle('frame-hidden');
                localStorage.setItem('nexe_frame_hidden', hidden ? '1' : '0');
            });
        }

        // Sidebar toggle
        const sidebarToggleBtn = document.getElementById('sidebarToggleBtn');
        const sidebar = document.querySelector('.sidebar');
        if (sidebarToggleBtn && sidebar) {
            if (localStorage.getItem('nexe_sidebar_collapsed') === '1') {
                sidebar.classList.add('collapsed');
                const iconInit = sidebarToggleBtn.querySelector('i');
                if (iconInit) iconInit.setAttribute('data-lucide', 'panel-left-open');
            }
            sidebarToggleBtn.addEventListener('click', () => {
                sidebar.classList.toggle('collapsed');
                const collapsed = sidebar.classList.contains('collapsed');
                const iconEl = sidebarToggleBtn.querySelector('i');
                if (iconEl) {
                    iconEl.setAttribute('data-lucide', collapsed ? 'panel-left-open' : 'panel-left-close');
                    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [sidebarToggleBtn] });
                }
                localStorage.setItem('nexe_sidebar_collapsed', collapsed ? '1' : '0');
            });
        }

        // Load sessions and model info
        this.loadSessions();
        this.loadServerInfo();
        this.showWelcome();

        // Setup drag and drop
        this.setupDragAndDrop();

        // Initialize Lucide icons
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }

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
    }

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
    }

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
    }

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
    }

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
    }

    _startStreamStats() {
        this._streamStart = Date.now();
        this._streamTokens = 0;
        if (this.statsBar) this.statsBar.classList.add('active');
        this._statsInterval = setInterval(() => this._updateStreamStats(), 400);
    }

    _updateStreamStats() {
        const elapsed = (Date.now() - this._streamStart) / 1000;
        const tokPerSec = elapsed > 0.5 ? (this._streamTokens / elapsed).toFixed(1) : '—';
        const tokEl = document.getElementById('statTokens');
        const spdEl = document.getElementById('statSpeed');
        if (tokEl) tokEl.textContent = this._streamTokens;
        if (spdEl) spdEl.textContent = tokPerSec;
    }

    _stopStreamStats() {
        clearInterval(this._statsInterval);
        this._statsInterval = null;
        // Keep stats visible for 3s then hide
        setTimeout(() => {
            if (this.statsBar) this.statsBar.classList.remove('active');
        }, 3000);
    }

    _handleUnauthorized() {
        // We don't clear localStorage — Safari with ITP may clear it
        // between sessions. If the key was valid, the user simply
        // resends it without having to remember it.
        this.apiKey = null;
        this.showLoginOverlay();
    }

    async createNewSession() {
        this._abortIfGenerating();
        try {
            const response = await this.fetchWithCsrf('/ui/session/new', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            });

            if (response.ok) {
                const data = await response.json();
                this.currentSessionId = data.session_id;
                this.clearChat();
                this.removeFilePreview();
                // Reset thinking toggle for new session (default OFF)
                this._restoreThinkingToggle(null);
                this.loadSessions();
                this.showWelcome();
            }
        } catch (error) {
            console.error('Error creating session:', error);
        }
    }

    async loadSessions() {
        try {
            const response = await this.fetchWithCsrf('/ui/sessions');
            if (response.ok) {
                const data = await response.json();
                this.sessions = data.sessions || [];
                this.renderSessions();
            }
        } catch (error) {
            console.error('Error loading sessions:', error);
        }
    }

    renderSessions() {
        this.sessionsList.innerHTML = '';

        // Sort sessions by created_at descending (newest first)
        const sortedSessions = [...this.sessions].sort((a, b) => {
            return new Date(b.created_at) - new Date(a.created_at);
        });

        sortedSessions.forEach(session => {
            const sessionEl = document.createElement('div');
            sessionEl.className = 'session-item';
            if (session.id === this.currentSessionId) {
                sessionEl.classList.add('active');
            }

            const date = new Date(session.created_at);
            const timeStr = date.toLocaleString('ca-ES', {
                day: 'numeric',
                month: 'short',
                hour: '2-digit',
                minute: '2-digit'
            });

            const contentEl = document.createElement('div');
            contentEl.className = 'session-item-content';

            const titleEl = document.createElement('div');
            titleEl.className = 'session-item-title';
            titleEl.textContent = session.first_message || this.t('new_chat');
            contentEl.appendChild(titleEl);

            const metaEl = document.createElement('div');
            metaEl.className = 'session-item-meta';
            metaEl.textContent = timeStr;
            contentEl.appendChild(metaEl);

            const actionsEl = document.createElement('div');
            actionsEl.className = 'session-item-actions';

            const renameBtn = document.createElement('button');
            renameBtn.className = 'btn-rename-session';
            renameBtn.title = 'Rename';
            const pencilI = document.createElement('i');
            pencilI.setAttribute('data-lucide', 'pencil');
            renameBtn.appendChild(pencilI);

            const deleteBtn = document.createElement('button');
            deleteBtn.className = 'btn-delete-session';
            deleteBtn.title = this.t('delete_session');
            deleteBtn.textContent = '\u2715';

            actionsEl.appendChild(renameBtn);
            actionsEl.appendChild(deleteBtn);

            sessionEl.appendChild(contentEl);
            sessionEl.appendChild(actionsEl);

            contentEl.addEventListener('click', () => this.loadSession(session.id));

            renameBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                const input = document.createElement('input');
                input.className = 'session-rename-input';
                input.value = titleEl.textContent;
                input.maxLength = 100;
                titleEl.replaceWith(input);
                input.addEventListener('click', (ev) => ev.stopPropagation());
                input.focus();
                input.select();

                let finished = false;
                const finish = async (save) => {
                    if (finished) return;
                    finished = true;
                    if (save && input.value.trim()) {
                        try {
                            await this.fetchWithCsrf(`/ui/session/${session.id}`, {
                                method: 'PATCH',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ name: input.value.trim() })
                            });
                            titleEl.textContent = input.value.trim();
                        } catch (err) {
                            console.error('Rename failed:', err);
                        }
                    }
                    input.replaceWith(titleEl);
                };

                input.addEventListener('keydown', (ev) => {
                    if (ev.key === 'Enter') { ev.preventDefault(); finish(true); }
                    if (ev.key === 'Escape') { finish(false); }
                });
                input.addEventListener('blur', () => finish(true));
            });

            deleteBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.deleteSession(session.id);
            });

            this.sessionsList.appendChild(sessionEl);
        });
        if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [this.sessionsList] });
    }

    async deleteSession(sessionId) {
        if (!confirm(this.t('confirm_delete'))) return;

        try {
            const response = await this.fetchWithCsrf(`/ui/session/${sessionId}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                // If we deleted the current session, clear the chat
                if (sessionId === this.currentSessionId) {
                    this.currentSessionId = null;
                    this.showWelcome();
                }
                // Reload sessions list
                this.loadSessions();
            } else {
                console.error('Error deleting session');
            }
        } catch (error) {
            console.error('Error deleting session:', error);
        }
    }

    async loadSession(sessionId) {
        this._abortIfGenerating();
        try {
            // Bug #6 fix: use full session endpoint (not /history) to also receive attached_document
            const response = await this.fetchWithCsrf(`/ui/session/${sessionId}`);
            if (response.ok) {
                const data = await response.json();
                this.currentSessionId = sessionId;
                this.clearChat();
                // Local UI clear only — do NOT call removeFilePreview() because it
                // POSTs to /clear-document and would wipe the backend attachment
                // every time the user switches sessions.
                this._clearFilePreviewLocal();
                this.renderMessages(data.messages || []);

                // Bug #6 fix: re-hydrate attached document badge if the session has one
                if (data.attached_document && data.attached_document.filename) {
                    const doc = data.attached_document;
                    this.addUploadedFile({
                        filename: doc.filename,
                        size: doc.total_chars || 0
                    });
                    this.uploadedFile = { filename: doc.filename };
                }

                // Restore thinking toggle state from session
                this._restoreThinkingToggle(data);

                this.renderSessions();
            }
        } catch (error) {
            console.error('Error loading session:', error);
        }
    }

    _clearFilePreviewLocal() {
        // Same UI cleanup as removeFilePreview() but WITHOUT the destructive
        // POST /clear-document call. Used when switching sessions so we don't
        // wipe the backend attachment of the session we're leaving.
        if (this.filePreview) {
            this.filePreview.replaceChildren();
            this.filePreview.classList.remove('active');
        }
        this.uploadedFile = null;
    }

    renderMessages(messages) {
        this.chatMessages.innerHTML = '';

        messages.forEach(msg => {
            // Fix 2026-04-22: reconstructs the data URL of the image persisted
            // in the session. Without this, after a restart the image would disappear
            // even though `image_b64` was on disk.
            let imageUrl = null;
            if (msg.image_b64) {
                const mime = msg.image_type || 'image/jpeg';
                imageUrl = `data:${mime};base64,${msg.image_b64}`;
            }
            this.addMessageToChat(msg.role, msg.content, false, msg.stats || null, imageUrl);
        });

        this.scrollToBottom();
    }

    async sendMessage() {
        if (this.isGenerating) return;
        const message = this.messageInput.value.trim();
        if (!message) return;

        // Auto-create session if we don't have one — server doesn't return ID via streaming
        if (!this.currentSessionId) {
            try {
                const sr = await this.fetchWithCsrf('/ui/session/new', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                });
                if (sr.ok) {
                    const sd = await sr.json();
                    this.currentSessionId = sd.session_id;
                    this.loadSessions();
                }
            } catch { /* continue without session */ }
        }

        // Show stop button
        this.sendBtn.style.display = 'none';
        this.stopBtn.style.display = 'flex';
        this.isGenerating = true;
        this.setAiState('thinking');

        // Create AbortController for this request
        this.abortController = new AbortController();

        // Capture selected image before clearing VLM state
        const pendingImage = this._selectedImage ? { ...this._selectedImage } : null;
        this._clearSelectedImage();

        // Add user message to chat — if there is an attached image, show it inline
        const userImageUrl = pendingImage ? `data:${pendingImage.type};base64,${pendingImage.b64}` : null;
        this.addMessageToChat('user', message, true, null, userImageUrl);
        this.messageInput.value = '';
        this.messageInput.style.height = 'auto';

        try {
            const ragSlider = document.getElementById('ragThresholdSlider');
            const ragThreshold = ragSlider ? parseFloat(ragSlider.value) : 0.25;
            const backendSel = document.getElementById('backendSelect');
            const modelSel = document.getElementById('modelSelect');
            // Collection toggles — build list of active collections
            const ragCollections = this._getActiveCollections();
            const chatBody = {
                message: message,
                session_id: this.currentSessionId,
                stream: true,
                rag_threshold: ragThreshold,
                rag_collections: ragCollections.length < 3 ? ragCollections : undefined,
                backend: backendSel ? backendSel.value : undefined,
                model: modelSel ? modelSel.value : undefined,
                ...(pendingImage ? { image_b64: pendingImage.b64, image_type: pendingImage.type } : {})
            };
            const response = await this.fetchWithCsrf('/ui/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(chatBody),
                signal: this.abortController.signal
            });

            if (response.status === 401) {
                this._handleUnauthorized();
                return;
            }

            if (response.ok) {
                let assistantMessageDiv = null;
                let fullResponse = "";
                let memorySaved = false;
                let memoryDeleted = false;
                let deletedCount = 0;
                let deletedFacts = [];
                let ragCount = 0;
                let ragAvg = 0;
                let ragItems = [];  // [{col, score}]
                let usedModel = '';
                let compactMatch = null;

                const reader = response.body.getReader();
                const decoder = new TextDecoder();

                // Add empty message for assistant
                this.addMessageToChat('assistant', '', true);
                const messages = this.chatMessages.querySelectorAll('.message.assistant');
                const lastMsg = messages[messages.length - 1];
                assistantMessageDiv = lastMsg.querySelector('.message-text');
                // "Processing…" wave placeholder only when both
                // conditions allow it (Jordi logic 2026-04-22):
                //   (a) the thinking mode toggle is OFF — if it's ON,
                //       the model will open a `.think-block` with its own
                //       indicator and the bubble does not need to be occupied.
                //   (b) the user has NOT just changed the model — if they have,
                //       the blue `MODEL_LOADING` is the primary signal;
                //       the placeholder would arrive too late anyway.
                const _thinkOn = (() => {
                    const tt = document.getElementById('thinkingToggle');
                    return tt && tt.checked;
                })();
                if (assistantMessageDiv && !_thinkOn && !this._modelJustChanged) {
                    assistantMessageDiv.classList.add('thinking-placeholder');
                    this._setThinkingText(assistantMessageDiv, this.t('thinking'));
                }
                let loadingEl = null;

                // Think state machine
                let tMode = 'init';   // 'init' | 'thinking' | 'responding'
                let tBuf  = '';       // partial tag buffer
                let tContent = '';    // accumulated think text
                let tTok = 0;         // think token count
                let tBlock = null;    // .think-block DOM element
                let tTextEl = null;   // .think-text inside block
                let tGptOssChecked = false; // GPT-OSS format detection done?
                let tIsGptOss = false;      // GPT-OSS thinking mode active?

                // Check if thinking blocks should be shown (toggle checked)
                const _thinkToggle = document.getElementById('thinkingToggle');
                const _showThinking = _thinkToggle && _thinkToggle.checked;

                const startThinkBlock = () => {
                    // If thinking toggle is OFF, don't create DOM — still parse tags to strip from output
                    if (!_showThinking) {
                        tBlock = null;
                        tTextEl = null;
                        return;
                    }
                    lastMsg.querySelector('.message-content').insertAdjacentHTML('afterbegin',
                        `<details class="think-block" open>
                            <summary class="think-header">
                                <i data-lucide="brain"></i>
                                <span class="think-label">Pensant...</span>
                                <span class="think-tokens"></span>
                            </summary>
                            <div class="think-text"></div>
                        </details>`
                    );
                    tBlock = lastMsg.querySelector('.think-block');
                    tTextEl = tBlock.querySelector('.think-text');
                    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [tBlock.querySelector('.think-header')] });
                };

                const closeThinkBlock = () => {
                    if (!tBlock) return;
                    tBlock.querySelector('.think-label').textContent = this.t('reasoning');
                    tBlock.querySelector('.think-tokens').textContent = `~${tTok} tok`;
                    tBlock.removeAttribute('open'); // auto-collapse
                };

                // Clean special model tags (GPT-OSS, etc.)
                const _cleanModelTags = (buf) => {
                    buf = buf.replace(/<\|[^|]+\|>/g, '');
                    buf = buf.replace(/[◁◀][^▷▶]*[▷▶]/g, '');
                    return buf;
                };

                // Parseja thinking/content post-streaming (DeepSeek, GPT-OSS, etc.)
                const _parseThinkingChannels = (text) => {
                    if (!text) return { thinking: null, content: '' };
                    let cleaned = text.replace(/<\|[^|]+\|>/g, '').replace(/[◁◀][^▷▶]*[▷▶]/g, '');
                    // Pattern 0: <think>...</think>... (tag complet)
                    const m0 = cleaned.match(/<think>([\s\S]*?)<\/think>\s*([\s\S]*)/);
                    if (m0) return { thinking: m0[1].trim(), content: m0[2].trim() };
                    // Pattern 0b: ...text...</think>... (without opening tag — DeepSeek R1)
                    const m0b = cleaned.match(/^([\s\S]+?)<\/think>\s*([\s\S]*)/);
                    if (m0b && m0b[1].trim().length > 10) return { thinking: m0b[1].trim(), content: m0b[2].trim() };
                    // Pattern 1: "analysisXXX...assistantfinalYYY" (gpt-oss)
                    const m1 = cleaned.match(/^(?:assistant)?analysis([\s\S]+?)\.?assistant\s*final([\s\S]+)$/i);
                    if (m1) return { thinking: m1[1].trim(), content: m1[2].trim() };
                    // Pattern 2: "analysisXXX...finalYYY"
                    const m2 = cleaned.match(/^analysis([\s\S]+?)final([\s\S]+)$/i);
                    if (m2 && m2[1].trim().length > 10) return { thinking: m2[1].trim(), content: m2[2].trim() };
                    return { thinking: null, content: cleaned.trim() };
                };

                const processChunk = (raw) => {
                    tBuf += raw;
                    while (tBuf.length > 0) {
                        if (tMode === 'init') {
                            const s = tBuf.indexOf('<think>');
                            if (s >= 0) {
                                tMode = 'thinking';
                                tBuf = tBuf.slice(s + 7);
                                startThinkBlock();
                            } else if (!tGptOssChecked && fullResponse.length + tBuf.length >= 30) {
                                // Check for GPT-OSS "analysis...final" format
                                tGptOssChecked = true;
                                const combined = (fullResponse + tBuf).toLowerCase().trimStart();
                                if (combined.startsWith('analysis')) {
                                    tIsGptOss = true;
                                    tMode = 'thinking';
                                    tContent = fullResponse + tBuf;
                                    fullResponse = '';
                                    tBuf = '';
                                    startThinkBlock();
                                    if (tTextEl) tTextEl.textContent = tContent.replace(/^analysis\s*/i, '');
                                    tTok = Math.ceil(tContent.length / 4);
                                    break;
                                } else {
                                    // Not GPT-OSS — direct response
                                    tMode = 'responding';
                                    this.setAiState('streaming');
                                    this._startStreamStats();
                                }
                            } else if (tGptOssChecked && tBuf.trimStart().length > 0 && !tBuf.trimStart().startsWith('<')) {
                                // First char is not a tag — direct response
                                tMode = 'responding';
                                this.setAiState('streaming');
                                this._startStreamStats();
                            } else if (tBuf.length > 7 && tGptOssChecked) {
                                // Large buffer without <think> — direct response
                                tMode = 'responding';
                                this.setAiState('streaming');
                                this._startStreamStats();
                            } else if (tBuf.trimStart().length > 0 && !tBuf.trimStart().startsWith('<') && tBuf.length < 30 && !tGptOssChecked) {
                                // Could be GPT-OSS — wait for more data
                                fullResponse += tBuf;
                                tBuf = '';
                                break;
                            } else {
                                break; // wait for more data
                            }
                        } else if (tMode === 'thinking' && tIsGptOss) {
                            // GPT-OSS thinking mode: accumulate and look for end marker
                            tContent += tBuf;
                            tBuf = '';
                            const displayContent = tContent.replace(/^analysis\s*/i, '');
                            if (tTextEl) {
                                tTextEl.textContent = displayContent;
                                tTextEl.scrollTop = tTextEl.scrollHeight;
                            }
                            tTok = Math.ceil(tContent.length / 4);
                            const tokEl = tBlock?.querySelector('.think-tokens');
                            if (tokEl) tokEl.textContent = `~${tTok} tok`;
                            // Look for end marker: "assistantfinal" or standalone "final"
                            const endMatch = tContent.match(/(assistant\s*final|(?<!\w)final)(.*)$/is);
                            if (endMatch) {
                                const markerIdx = tContent.lastIndexOf(endMatch[1]);
                                let thinkText = tContent.substring(0, markerIdx).replace(/^analysis\s*/i, '').trim();
                                // Extract MEM_SAVE from thinking → move to fullResponse for badge
                                const _memGpt = [];
                                thinkText = thinkText.replace(/\[MEM_SAVE:\s*(.+?)\]\s*/g, (_, f) => {
                                    _memGpt.push(f);
                                    return '';
                                });
                                if (tTextEl) tTextEl.textContent = thinkText;
                                tTok = Math.ceil(thinkText.length / 4);
                                closeThinkBlock();
                                tMode = 'responding';
                                fullResponse = endMatch[2].trimStart();
                                // Inject MEM_SAVE AFTER fullResponse assignment (not before — it overwrites)
                                if (_memGpt.length > 0) {
                                    fullResponse += '\n' + _memGpt.map(f => `[MEM_SAVE: ${f}]`).join('\n');
                                }
                                this.setAiState('streaming');
                                this._startStreamStats();
                                if (fullResponse) {
                                    this._streamTokens += Math.ceil(fullResponse.length / 4);
                                    this._scheduleRender(assistantMessageDiv, fullResponse);
                                }
                            }
                            break;
                        } else if (tMode === 'thinking') {
                            const e = tBuf.indexOf('</think>');
                            if (e >= 0) {
                                tContent += tBuf.slice(0, e);
                                // Extract MEM_SAVE from thinking → move to fullResponse for badge
                                const _memInThink = [];
                                tContent = tContent.replace(/\[MEM_SAVE:\s*(.+?)\]\s*/g, (_, f) => {
                                    _memInThink.push(f);
                                    return '';
                                });
                                if (_memInThink.length > 0) {
                                    fullResponse += _memInThink.map(f => `[MEM_SAVE: ${f}]`).join('\n') + '\n';
                                }
                                tTok += Math.ceil(tContent.length / 4);
                                if (tTextEl) tTextEl.textContent = tContent;
                                tBuf = tBuf.slice(e + 8).replace(/^\n+/, '');
                                tMode = 'responding';
                                closeThinkBlock();
                                this.setAiState('streaming');
                                this._startStreamStats();
                            } else {
                                // Keep possible partial tag at end
                                const partial = Math.min(8, tBuf.length);
                                let keepFrom = tBuf.length;
                                for (let i = partial; i > 0; i--) {
                                    if ('</think>'.startsWith(tBuf.slice(-i))) { keepFrom = tBuf.length - i; break; }
                                }
                                tContent += tBuf.slice(0, keepFrom);
                                if (tTextEl) {
                                    tTextEl.textContent = tContent;
                                    tTextEl.scrollTop = tTextEl.scrollHeight;
                                }
                                tTok = Math.ceil(tContent.length / 4);
                                const tokEl = tBlock?.querySelector('.think-tokens');
                                if (tokEl) tokEl.textContent = `~${tTok} tok`;
                                tBuf = tBuf.slice(keepFrom);
                                break;
                            }
                        } else { // responding
                            // Detect retroactive </think> (DeepSeek without opening <think>)
                            const closIdx = tBuf.indexOf('</think>');
                            if (closIdx >= 0 && !tContent) {
                                const thinkPart = fullResponse + tBuf.slice(0, closIdx);
                                if (thinkPart.trim().length > 10) {
                                    tContent = thinkPart.trim();
                                    tTok = Math.ceil(tContent.length / 4);
                                    startThinkBlock();
                                    if (tTextEl) tTextEl.textContent = tContent;
                                    closeThinkBlock();
                                    fullResponse = '';
                                    this._streamTokens = 0;
                                    tBuf = tBuf.slice(closIdx + 8).replace(/^\n+/, '');
                                    continue;
                                }
                            }
                            // [MEM_SAVE: ...] tags pass through — stripped at final render (post-streaming)
                            tBuf = _cleanModelTags(tBuf);
                            fullResponse += tBuf;
                            this._streamTokens += Math.ceil(tBuf.length / 4);
                            this._scheduleRender(assistantMessageDiv, fullResponse);
                            tBuf = '';
                        }
                    }
                };

                try {
                    while (true) {
                        const { value, done } = await reader.read();
                        if (done) break;

                        let chunk = decoder.decode(value, { stream: true });

                        // Detect MODEL token (model actually used)
                        const modelMatch = chunk.match(/\x00\[MODEL:([^\]]+)\]\x00/); // eslint-disable-line no-control-regex
                        if (modelMatch) {
                            usedModel = modelMatch[1];
                            chunk = chunk.replace(/\x00\[MODEL:[^\]]+\]\x00/, ''); // eslint-disable-line no-control-regex
                        }

                        // Detect RAG token (retrieved memories)
                        const ragMatch = chunk.match(/\x00\[RAG:(\d+)\]\x00/); // eslint-disable-line no-control-regex
                        if (ragMatch) {
                            ragCount = parseInt(ragMatch[1], 10);
                            chunk = chunk.replace(/\x00\[RAG:\d+\]\x00/, ''); // eslint-disable-line no-control-regex
                        }

                        // Detect RAG average score
                        const ragAvgMatch = chunk.match(/\x00\[RAG_AVG:([\d.]+)\]\x00/); // eslint-disable-line no-control-regex
                        if (ragAvgMatch) {
                            ragAvg = parseFloat(ragAvgMatch[1]);
                            chunk = chunk.replace(/\x00\[RAG_AVG:[\d.]+\]\x00/, ''); // eslint-disable-line no-control-regex
                        }

                        // Detect RAG items (per-source scores)
                        let ragItemMatch;
                        const ragItemRe = /\x00\[RAG_ITEM:([^|]+)\|([\d.]+)\]\x00/g; // eslint-disable-line no-control-regex
                        while ((ragItemMatch = ragItemRe.exec(chunk)) !== null) {
                            ragItems.push({ col: ragItemMatch[1], score: parseFloat(ragItemMatch[2]) });
                        }
                        chunk = chunk.replace(/\x00\[RAG_ITEM:[^\]]+\]\x00/g, ''); // eslint-disable-line no-control-regex

                        // Detect COMPACT token (compacted context)
                        compactMatch = chunk.match(/\x00\[COMPACT:(\d+)\]\x00/); // eslint-disable-line no-control-regex
                        if (compactMatch) {
                            chunk = chunk.replace(/\x00\[COMPACT:\d+\]\x00/, ''); // eslint-disable-line no-control-regex
                        }

                        // Detect DOC_TRUNCATED (document too large for context)
                        const truncMatch = chunk.match(/\x00\[DOC_TRUNCATED:(\d+)\]\x00/); // eslint-disable-line no-control-regex
                        if (truncMatch) {
                            const truncPct = parseInt(truncMatch[1]);
                            chunk = chunk.replace(/\x00\[DOC_TRUNCATED:\d+\]\x00/, ''); // eslint-disable-line no-control-regex
                            const truncNotice = document.createElement('div');
                            truncNotice.className = 'trunc-notice';
                            truncNotice.textContent = this.t('doc_truncated').replace('{pct}', truncPct);
                            lastMsg.querySelector('.message-content').insertBefore(truncNotice, assistantMessageDiv);
                        }

                        // Detect MODEL_LOADING (model loading into VRAM)
                        const loadingMatch = chunk.match(/\x00\[MODEL_LOADING:([^\]|]+)\|?([^\]]*)\]\x00/); // eslint-disable-line no-control-regex
                        if (loadingMatch) {
                            chunk = chunk.replace(/\x00\[MODEL_LOADING:[^\]]+\]\x00/, ''); // eslint-disable-line no-control-regex
                            const loadingModel = loadingMatch[1];
                            const loadingBackend = loadingMatch[2] || '';
                            const backendLabel = loadingBackend.replace('_module', '').toUpperCase();
                            loadingEl = document.createElement('div');
                            loadingEl.className = 'model-loading-indicator';
                            loadingEl.innerHTML = `
                                <div class="loading-spinner"></div>
                                <span>${this.t('model_loading')}… <strong>${this.escapeHtml(loadingModel)}</strong>${backendLabel ? ` <em class="loading-backend">[${this.escapeHtml(backendLabel)}]</em>` : ''} — <em class="loading-timer">0s</em></span>
                            `;
                            lastMsg.querySelector('.message-content').insertBefore(loadingEl, assistantMessageDiv);
                            // During model loading into VRAM, the blue loadingEl
                            // is the primary signal — we hide the "Processing…"
                            // placeholder so it's not visually crushed. It will
                            // return with the first real token (if the model is
                            // still "thinking") or the streaming text will simply
                            // overwrite it.
                            if (assistantMessageDiv.classList.contains('thinking-placeholder')) {
                                assistantMessageDiv.classList.remove('thinking-placeholder');
                                assistantMessageDiv.textContent = '';
                            }
                            this.scrollToBottom();
                            // Real-time timer
                            this._loadStartTime = Date.now();
                            const _timerEl = loadingEl.querySelector('.loading-timer');
                            this._loadingTimer = setInterval(() => {
                                if (_timerEl) _timerEl.textContent = `${Math.round((Date.now() - this._loadStartTime) / 1000)}s`;
                            }, 1000);
                        }

                        // Detect MODEL_READY (model loaded, starts responding)
                        if (chunk.includes('\x00[MODEL_READY]\x00')) {
                            chunk = chunk.replace('\x00[MODEL_READY]\x00', '');
                            // Model already loaded — if the user sends more chats,
                            // the "Processing…" wave placeholder can return.
                            this._modelJustChanged = false;
                            if (this._loadingTimer) { clearInterval(this._loadingTimer); this._loadingTimer = null; }
                            if (loadingEl) {
                                const _loadingElRef = loadingEl;
                                loadingEl = null;
                                const startedAt = this._loadStartTime || Date.now();
                                const visibleMs = Date.now() - startedAt;
                                // Minimum guarantee of 700ms of visible blue banner —
                                // if MODEL_LOADING and MODEL_READY arrive in the same
                                // chunk (case of very fast loads), the user would see
                                // the green "0s" directly without ever seeing the blue.
                                const MIN_BLUE_MS = 700;
                                const finalize = () => {
                                    const totalSec = Math.round((Date.now() - startedAt) / 1000);
                                    _loadingElRef.className = 'model-loading-indicator loaded';
                                    const _be = _loadingElRef.querySelector('.loading-backend');
                                    const _beText = _be ? ` ${_be.outerHTML}` : '';
                                    _loadingElRef.innerHTML = `<span>✓ ${this.t('model_loaded')} (${totalSec}s)${_beText}</span>`;
                                };
                                if (visibleMs < MIN_BLUE_MS) {
                                    setTimeout(finalize, MIN_BLUE_MS - visibleMs);
                                } else {
                                    finalize();
                                }
                            }
                        }

                        // Detect saving spinner [SAVING]
                        if (chunk.match(/\x00\[SAVING\]\x00/)) { // eslint-disable-line no-control-regex
                            chunk = chunk.replace(/\x00\[SAVING\]\x00/g, ''); // eslint-disable-line no-control-regex
                            const savingEl = document.getElementById('nexe-mem-saving');
                            if (!savingEl) {
                                const el = document.createElement('span');
                                el.id = 'nexe-mem-saving';
                                el.style.cssText = 'display:inline-flex;align-items:center;gap:4px;font-size:11px;color:var(--text-muted,#888);margin-left:8px';
                                el.textContent = `⏳ ${this.t('mem_saving')}`;
                                const statsBar = assistantMessageDiv && assistantMessageDiv.parentElement && assistantMessageDiv.parentElement.querySelector('.message-stats');
                                if (statsBar) statsBar.appendChild(el);
                            }
                        }
                        // Detect saved memory count token [MEM:N] or [MEM]
                        if (chunk.match(/\x00\[MEM:?\d*\]\x00/)) { // eslint-disable-line no-control-regex
                            memorySaved = true;
                            chunk = chunk.replace(/\x00\[MEM:?\d*\]\x00/g, ''); // eslint-disable-line no-control-regex
                            const savingEl = document.getElementById('nexe-mem-saving');
                            if (savingEl) savingEl.remove();
                        }

                        // Detect deleted memory token [DEL:N:fact1|fact2|...]
                        const delMatch = chunk.match(/\x00\[DEL:(\d+):(.+?)\]\x00/); // eslint-disable-line no-control-regex
                        if (delMatch) {
                            memoryDeleted = true;
                            deletedCount = parseInt(delMatch[1]);
                            deletedFacts = delMatch[2].split('|');
                            chunk = chunk.replace(/\x00\[DEL:\d+:.+?\]\x00/g, ''); // eslint-disable-line no-control-regex
                        }
                        // Detect pending delete — model wants to delete, but confirmation needed
                        const pendingDelMatch = chunk.match(/\x00\[PENDING_DELETE:(.+?)\]\x00/); // eslint-disable-line no-control-regex
                        if (pendingDelMatch) {
                            const fact = pendingDelMatch[1].replace(/\\\|/g, '|');
                            chunk = chunk.replace(/\x00\[PENDING_DELETE:.+?\]\x00/g, ''); // eslint-disable-line no-control-regex
                            // Show confirmation dialog after streaming ends
                            setTimeout(() => this._showDeleteConfirmDialog(fact), 100);
                        }

                        processChunk(chunk);
                        this.scrollToBottom();
                    }
                    // Streaming done — if loading indicator remains, mark as loaded
                    if (this._loadingTimer) { clearInterval(this._loadingTimer); this._loadingTimer = null; }
                    // Reset flag if not cleared via MODEL_READY (e.g. model
                    // was already loaded and `[MODEL_READY]` was not emitted).
                    this._modelJustChanged = false;
                    if (loadingEl) {
                        const elapsed = Math.round((Date.now() - (this._loadStartTime || Date.now())) / 1000);
                        loadingEl.className = 'model-loading-indicator loaded';
                        const _be = loadingEl.querySelector('.loading-backend');
                        const _beText = _be ? ` ${_be.outerHTML}` : '';
                        loadingEl.innerHTML = `<span>✓ ${this.t('model_loaded')} (${elapsed}s)${_beText}</span>`;
                        loadingEl = null;
                    }
                    // Final definitive render
                    clearTimeout(this._renderTimer);
                    this._renderTimer = null;
                    // If thinking not detected via <think>, try GPT-OSS parsing
                    if (tMode !== 'thinking' && !tContent) {
                        const parsed = _parseThinkingChannels(fullResponse);
                        if (parsed.thinking) {
                            // Show thinking block retroactively
                            startThinkBlock();
                            // Extract MEM_SAVE from thinking → move to content for badge
                            let _cleanThink = parsed.thinking;
                            const _memRetro = [];
                            _cleanThink = _cleanThink.replace(/\[MEM_SAVE:\s*(.+?)\]\s*/g, (_, f) => {
                                _memRetro.push(f);
                                return '';
                            });
                            if (tTextEl) tTextEl.textContent = _cleanThink;
                            const tokEl = tBlock?.querySelector('.think-tokens');
                            if (tokEl) tokEl.textContent = `~${Math.ceil(_cleanThink.length / 4)} tok`;
                            closeThinkBlock();
                            fullResponse = parsed.content + (_memRetro.length > 0 ? '\n' + _memRetro.map(f => `[MEM_SAVE: ${f}]`).join('\n') : '');
                        } else {
                            fullResponse = _cleanModelTags(fullResponse);
                        }
                    }
                    // Strip [MEM_SAVE: ...] from final render and collect facts for stats badge
                    const memFacts = [];
                    const _seenFacts = new Set();
                    fullResponse = fullResponse.replace(/\[MEM_SAVE:\s*(.+?)\]\s*/g, (_, fact) => {
                        if (!_seenFacts.has(fact)) {
                            _seenFacts.add(fact);
                            memFacts.push(fact);
                        }
                        return '';
                    });
                    if (memFacts.length > 0) {
                        memorySaved = true;
                        // Clean up orphaned MEM_SAVE remnants (intro lines ending in ":", lone dots)
                        fullResponse = fullResponse.replace(/\n[^\n]*:\s*\n\s*\.\s*\n/g, '\n');
                        fullResponse = fullResponse.replace(/\n\s*\.\s*\n/g, '\n');
                        fullResponse = fullResponse.replace(/\n{3,}/g, '\n\n');
                    }
                    // Guard: if the response is empty after removing MEM_SAVE
                    // (backend does re-prompt, but for safety we keep UI fallback)
                    if (!fullResponse.trim() && memFacts.length > 0) {
                        console.info('[nexe] Empty response after MEM_SAVE — backend should have re-prompted. Facts:', memFacts);
                        fullResponse = '\u2705 ' + memFacts.join(', ');
                    }
                    // Strip model tags that leak into visible text
                    fullResponse = fullResponse.replace(/\[ACTION\]:\s*[^\n]*/g, '');
                    fullResponse = fullResponse.replace(/\[MODEL:[^\]]+\]/g, '');
                    fullResponse = fullResponse.replace(/\[MEM:\d+\]/g, '');
                    fullResponse = fullResponse.replace(/\[MEM\]/g, '');
                    // Strip [DEL:N:...] tokens from final render
                    fullResponse = fullResponse.replace(/\[DEL:\d+:.+?\]/g, '');
                    // Note: renderMarkdown sanitizes HTML via marked.js (safe render)
                    // Guard: if for some reason _scheduleRender was never entered,
                    // clean the placeholder class here (not visible but we remove it).
                    if (assistantMessageDiv.classList.contains('thinking-placeholder')) {
                        assistantMessageDiv.classList.remove('thinking-placeholder');
                    }
                    assistantMessageDiv.innerHTML = this.renderMarkdown(fullResponse);
                    if (tMode !== 'responding' && tMode !== 'init') closeThinkBlock();
                    // Per-message stats
                    const elapsed = (Date.now() - this._streamStart) / 1000;
                    const finalTok = this._streamTokens;
                    const finalSpd = elapsed > 0.5 ? (finalTok / elapsed).toFixed(1) : null;
                    const statsEl = lastMsg.querySelector('.message-stats');
                    if (statsEl && finalTok > 0) {
                        const timeStr = elapsed > 0 ? `${elapsed.toFixed(1)}s` : '';
                        const spdStr = finalSpd ? ` · ${finalSpd} tok/s` : '';
                        const modelShort = usedModel ? usedModel.split('/').pop() : '';
                        let memBadge = '';
                        if (memorySaved && memFacts.length > 0) {
                            const factsHtml = memFacts.map(f => {
                                const safe = f.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
                                return '<div class="mem-fact">' + safe + '</div>';
                            }).join('');
                            memBadge = '<span class="stat-item stat-mem mem-expandable">'
                                + '<i data-lucide="bookmark-check"></i>'
                                + '<span>' + this.t('saved') + '</span>'
                                + '<div class="mem-tooltip">' + factsHtml + '</div>'
                                + '</span>';
                        } else if (memorySaved) {
                            memBadge = '<span class="stat-item stat-mem"><i data-lucide="bookmark-check"></i><span>' + this.t('saved') + '</span></span>';
                        }
                        let delBadge = '';
                        if (memoryDeleted && deletedFacts.length > 0) {
                            const delFactsHtml = deletedFacts.map(f => {
                                const safe = f.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
                                return '<div class="mem-fact">' + safe + '</div>';
                            }).join('');
                            delBadge = '<span class="stat-item stat-mem-del mem-expandable">'
                                + '<i data-lucide="trash-2"></i>'
                                + '<span>esborrat (' + deletedCount + ')</span>'
                                + '<div class="mem-tooltip mem-del-tooltip">' + delFactsHtml + '</div>'
                                + '</span>';
                        } else if (memoryDeleted) {
                            delBadge = '<span class="stat-item stat-mem-del"><i data-lucide="trash-2"></i><span>esborrat</span></span>';
                        }
                        let ragBadge = '';
                        if (ragCount > 0) {
                            const pct = ragAvg > 0 ? Math.round(ragAvg * 100) : 0;
                            const barWidth = 8;
                            const filled = Math.round(ragAvg * barWidth);
                            const ragBar = ragAvg > 0
                                ? `<span class="rag-bar">${'▓'.repeat(filled)}${'░'.repeat(barWidth - filled)}</span> ${pct}%`
                                : '';
                            let ragDetail = '';
                            if (ragItems.length > 0) {
                                const detailRows = ragItems.map(item => {
                                    const f = Math.round(item.score * 10);
                                    const bar = '▓'.repeat(f) + '░'.repeat(10 - f);
                                    const color = item.score >= 0.8 ? 'rag-high' : item.score >= 0.6 ? 'rag-mid' : 'rag-low';
                                    return `<div class="rag-detail-row ${color}"><span class="rag-col">${this.escapeHtml(item.col)}</span><span class="rag-detail-bar">${bar}</span><span class="rag-score">${(item.score * 100).toFixed(0)}%</span></div>`;
                                }).join('');
                                ragDetail = `<div class="rag-detail" style="display:none">${detailRows}</div>`;
                            }
                            const toggleBtn = ragItems.length > 0
                                ? `<span class="rag-toggle" onclick="this.parentElement.querySelector('.rag-detail').style.display=this.parentElement.querySelector('.rag-detail').style.display==='none'?'block':'none';this.textContent=this.textContent==='▼'?'▲':'▼'">▼</span>`
                                : '';
                            ragBadge = `<span class="stat-item stat-rag"><i data-lucide="brain"></i><span>RAG ${ragCount} ${ragBar}</span>${toggleBtn}${ragDetail}</span>`;
                        }
                        const compactBadge = compactMatch
                            ? `<span class="stat-item stat-compact"><i data-lucide="archive"></i><span>ctx ${compactMatch[1]}x</span></span>`
                            : '';
                        statsEl.innerHTML = `
                            <span class="stat-item"><i data-lucide="activity"></i><span>${finalTok} tok</span></span>
                            ${timeStr ? `<span class="stat-item"><i data-lucide="timer"></i><span>${timeStr}${spdStr}</span></span>` : ''}
                            ${modelShort ? `<span class="stat-item stat-model"><i data-lucide="cpu"></i><span>${this.escapeHtml(modelShort)}</span></span>` : ''}
                            ${ragBadge}
                            ${compactBadge}
                            ${memBadge}
                            ${delBadge}
                            <button class="copy-btn" title="Copy"><i data-lucide="copy"></i></button>
                        `;  // Safe: all values are server-controlled (token counts, model names, pre-built badge HTML)
                        const _copyBtn = statsEl.querySelector('.copy-btn');
                        if (_copyBtn) {
                            const _textDiv = lastMsg.querySelector('.message-text');
                            _copyBtn.addEventListener('click', () => {
                                navigator.clipboard.writeText(_textDiv ? _textDiv.innerText : '').then(() => {
                                    const checkI = document.createElement('i');
                                    checkI.setAttribute('data-lucide', 'check');
                                    _copyBtn.replaceChildren(checkI);
                                    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [_copyBtn] });
                                    setTimeout(() => {
                                        const restoreI = document.createElement('i');
                                        restoreI.setAttribute('data-lucide', 'copy');
                                        _copyBtn.replaceChildren(restoreI);
                                        if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [_copyBtn] });
                                    }, 2000);
                                }).catch(() => {});
                            });
                        }
                        if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [statsEl] });
                    }
                } catch (readError) {
                    if (this._loadingTimer) { clearInterval(this._loadingTimer); this._loadingTimer = null; }
                    if (loadingEl) {
                        loadingEl.className = 'model-loading-indicator error';
                        loadingEl.innerHTML = `<span>✗ ${this.t('model_load_error')}</span>`;
                        loadingEl = null;
                    }
                    if (readError.name === 'AbortError') {
                        if (tMode === 'thinking') closeThinkBlock();
                        assistantMessageDiv.innerHTML = this.renderMarkdown(fullResponse + `\n\n*[${this.t('generation_stopped')}]*`);
                    } else {
                        throw readError;
                    }
                }

            } else {
                this.setAiState('error');
                this.addMessageToChat('assistant', `❌ ${this.t('send_error')}`);
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                // User cancelled generation (AbortError)
            } else {
                console.error('Error sending message:', error);
                this.setAiState('error');
                this.addMessageToChat('assistant', `❌ ${this.t('connection_error')}: ${error.message || error}`);
            }
        } finally {
            this._stopStreamStats();
            this.setAiState('idle');
            this.sendBtn.style.display = 'flex';
            this.stopBtn.style.display = 'none';
            this.isGenerating = false;
            this.abortController = null;
            this.messageInput.focus();
        }
    }

    stopGeneration() {
        if (this.abortController && this.isGenerating) {
            this.abortController.abort();
        }
    }

    _showDeleteConfirmDialog(fact) {
        const existing = document.getElementById('nexe-delete-confirm');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'nexe-delete-confirm';
        overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.45);z-index:9999;display:flex;align-items:center;justify-content:center';

        const box = document.createElement('div');
        box.style.cssText = 'background:var(--bg-secondary,#1e1e2e);border:1px solid var(--border,#333);border-radius:12px;padding:24px 28px;max-width:420px;width:90%;box-shadow:0 8px 32px rgba(0,0,0,0.4)';

        const title = document.createElement('h3');
        title.style.cssText = 'margin:0 0 8px;font-size:15px;color:var(--text-primary,#cdd6f4)';
        title.textContent = this.t('delete_confirm_title');

        const msg = document.createElement('p');
        msg.style.cssText = 'margin:0 0 12px;font-size:13px;color:var(--text-secondary,#a6adc8)';
        msg.textContent = this.t('delete_confirm_msg');

        const factEl = document.createElement('div');
        factEl.style.cssText = 'background:var(--bg-tertiary,#181825);border-radius:8px;padding:10px 14px;margin-bottom:20px;font-size:13px;color:var(--text-primary,#cdd6f4);word-break:break-word';
        factEl.textContent = fact;

        const btnRow = document.createElement('div');
        btnRow.style.cssText = 'display:flex;gap:10px;justify-content:flex-end';

        const cancelBtn = document.createElement('button');
        cancelBtn.style.cssText = 'padding:8px 16px;border-radius:8px;border:1px solid var(--border,#333);background:transparent;color:var(--text-secondary,#a6adc8);cursor:pointer;font-size:13px';
        cancelBtn.textContent = this.t('delete_cancel_btn');

        const confirmBtn = document.createElement('button');
        confirmBtn.style.cssText = 'padding:8px 16px;border-radius:8px;border:none;background:#e74c3c;color:#fff;cursor:pointer;font-size:13px;font-weight:600';
        confirmBtn.textContent = this.t('delete_confirm_btn');

        btnRow.appendChild(cancelBtn);
        btnRow.appendChild(confirmBtn);
        box.appendChild(title);
        box.appendChild(msg);
        box.appendChild(factEl);
        box.appendChild(btnRow);
        overlay.appendChild(box);
        document.body.appendChild(overlay);

        const close = (confirmed) => {
            overlay.remove();
            if (confirmed) {
                this.fetchWithCsrf('/ui/memory/confirm-delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ fact })
                }).then(r => r.json()).then(result => {
                    if ((result.deleted || 0) > 0) {
                        const facts = (result.deleted_facts || []).map(f => f.text || f).join(', ');
                        this.addMessageToChat('assistant', `${this.t('delete_done')}: "${facts}"`);
                    }
                }).catch(() => {});
            } else {
                this.addMessageToChat('assistant', `↩️ ${this.t('delete_cancelled')}`);
            }
        };

        confirmBtn.addEventListener('click', () => close(true));
        cancelBtn.addEventListener('click', () => close(false));
        overlay.addEventListener('click', (e) => { if (e.target === overlay) close(false); });
    }

    _abortIfGenerating() {
        if (this.isGenerating && this.abortController) {
            this.abortController.abort();
            this.sendBtn.style.display = 'flex';
            this.stopBtn.style.display = 'none';
            this.isGenerating = false;
            this.abortController = null;
            this._stopStreamStats();
            this.setAiState('idle');
        }
    }

    addMessageToChat(role, content, scroll = true, stats = null, imageUrl = null) {
        // Remove welcome screen if exists
        const welcome = this.chatMessages.querySelector('.welcome-screen');
        if (welcome) {
            welcome.remove();
        }

        const messageEl = document.createElement('div');
        messageEl.className = `message ${role}`;

        const avatarIcon = role === 'user' ? 'user' : 'bot';
        const roleName = role === 'user' ? 'Tu' : 'Nexe';

        const avatarDiv = document.createElement('div');
        avatarDiv.className = 'message-avatar';
        const avatarI = document.createElement('i');
        avatarI.setAttribute('data-lucide', avatarIcon);
        avatarDiv.appendChild(avatarI);

        const contentDiv = document.createElement('div');
        contentDiv.className = 'message-content';

        const roleDiv = document.createElement('div');
        roleDiv.className = 'message-role';
        roleDiv.textContent = roleName;
        contentDiv.appendChild(roleDiv);

        if (imageUrl) {
            const imgEl = document.createElement('img');
            imgEl.src = imageUrl;
            imgEl.className = 'message-image-preview';
            imgEl.alt = content || 'imatge';
            contentDiv.appendChild(imgEl);
        }

        // textDiv: always present for assistant (streaming needs it via querySelector)
        // for user, only if there is content (image-only bubbles don't need one)
        const needsTextDiv = role === 'assistant' || content;
        let textDiv = null;
        if (needsTextDiv) {
            textDiv = document.createElement('div');
            textDiv.className = 'message-text';
            if (role === 'user') {
                textDiv.textContent = content;
            } else {
                textDiv.innerHTML = this.renderMarkdown(content); // renderMarkdown sanitizes HTML (custom renderer)
            }
            contentDiv.appendChild(textDiv);
        }

        if (role === 'assistant') {
            const statsDiv = document.createElement('div');
            statsDiv.className = 'message-stats';
            if (stats) {
                this._renderSavedStats(statsDiv, stats, textDiv);
            }
            contentDiv.appendChild(statsDiv);
        } else if (role === 'user' && textDiv) {
            // Symmetry with assistant: the user message also needs
            // an approximate token counter and a copy button.
            // The real count comes from the backend as `prompt_tokens` when the
            // response arrives; until then the heuristic ~1 tok / 4 chars is used.
            const statsDiv = document.createElement('div');
            statsDiv.className = 'message-stats';
            this._renderUserStats(statsDiv, content, textDiv, stats);
            contentDiv.appendChild(statsDiv);
        }

        messageEl.appendChild(avatarDiv);
        messageEl.appendChild(contentDiv);

        this.chatMessages.appendChild(messageEl);
        if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [avatarDiv] });

        if (scroll) {
            this.scrollToBottom();
        }
    }

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
    }

    _renderSavedStats(statsDiv, stats, textDiv) {
        const tok = stats.tokens || 0;
        const elapsed = stats.elapsed || 0;
        const speed = elapsed > 0.5 ? (tok / elapsed).toFixed(1) : null;
        const model = stats.model ? stats.model.split('/').pop() : '';
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
    }

    renderMarkdown(text) {
        if (!text) return '';

        // Bug #18 P1 follow-up: system markers leak into non-streamed
        // responses (intent=save/delete/list/clear_all return a pre-built
        // response_text with \x00[MODEL:nexe-system]\x00... delimiters;
        // when that text is serialized to JSON the \x00 bytes are lost,
        // so the client receives bare [MODEL:nexe-system] tokens and the
        // streaming-path stripper never sees them. Also hits loadSession
        // (persisted messages re-rendered from disk). Central strip here
        // = single source of truth for every render path.
        const cleaned = text
            .replace(/\x00/g, '') // eslint-disable-line no-control-regex
            .replace(/\[MODEL:[^\]]+\]/g, '')          // [MODEL:nexe-system]
            .replace(/\[MEM(?::\d+)?\]/g, '')          // [MEM] and [MEM:N]
            .replace(/\[DEL:\d+(?::[^\]]*)?\]/g, '')   // [DEL:N:facts]
            .replace(/\[MEM_SAVE:[^\]]*\]/g, '')       // [MEM_SAVE: ...]
            .replace(/\[MEM_DELETE:[^\]]*\]/g, '')     // [MEM_DELETE: ...]
            .replace(/\[MEMORIA:[^\]]*\]/g, '')        // [MEMORIA: ...] gpt-oss alias
            .trimStart();                               // leading whitespace after strip

        // Use marked.js to render Markdown
        if (typeof marked !== 'undefined' && cleaned) {
            try {
                // Override raw HTML renderer to prevent XSS injection via HTML blocks
                const renderer = new marked.Renderer();
                const _escape = this.escapeHtml.bind(this);
                renderer.html = function(token) {
                    const raw = typeof token === 'string' ? token : (token.text || '');
                    return _escape(raw);
                };
                // I-001: marked v15 dropped scheme sanitization, so a model-emitted
                // [click](javascript:…) (e.g. via RAG/web poisoning) would render as a
                // live, clickable anchor. Override link/image to allow only safe schemes
                // (http/https/mailto); anything else degrades to plain text.
                const _isSafeHref = function(href) {
                    if (!href) return false;
                    try {
                        return ['http:', 'https:', 'mailto:'].includes(
                            new URL(href, 'http://localhost').protocol
                        );
                    } catch {
                        return false;
                    }
                };
                renderer.link = function(token) {
                    const href = (token && typeof token === 'object') ? (token.href || '') : token;
                    let text;
                    try {
                        text = (token && token.tokens && this.parser)
                            ? this.parser.parseInline(token.tokens)
                            : _escape((token && token.text) || '');
                    } catch {
                        text = _escape((token && token.text) || '');
                    }
                    if (!_isSafeHref(href)) return text;
                    const title = (token && token.title) ? ` title="${_escape(token.title)}"` : '';
                    return `<a href="${_escape(href)}"${title} target="_blank" rel="noopener noreferrer">${text}</a>`;
                };
                renderer.image = function(token) {
                    const href = (token && typeof token === 'object') ? (token.href || '') : token;
                    const alt = _escape((token && token.text) || '');
                    if (!_isSafeHref(href)) return alt;
                    const title = (token && token.title) ? ` title="${_escape(token.title)}"` : '';
                    return `<img src="${_escape(href)}" alt="${alt}"${title}>`;
                };
                return marked.parse(cleaned, { breaks: true, gfm: true, renderer });
            } catch (e) {
                console.error('Markdown parsing error:', e);
                return this.escapeHtml(cleaned);
            }
        }
        return this.escapeHtml(cleaned);
    }

    // ── VLM image helpers ────────────────────────────────────────────────────

    async _handleImageSelect(event) {
        const file = event.target.files?.[0];
        if (!file) return;
        await this._attachImageFile(file);
        if (this.imageInput) this.imageInput.value = '';
    }

    async _attachImageFile(file) {
        const allowed = ['image/jpeg', 'image/png', 'image/webp'];
        if (!allowed.includes(file.type)) {
            alert('Only JPEG, PNG and WebP images are supported.');
            return;
        }
        const b64 = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = e => resolve(e.target.result.split(',')[1]);
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
        this._selectedImage = { b64, type: file.type, name: file.name };
        if (this.imagePreviewBar) {
            this.imagePreviewThumb.src = `data:${file.type};base64,${b64}`;
            this.imagePreviewName.textContent = file.name;
            this.imagePreviewBar.style.display = 'flex';
        }
        if (this.imageBadge) this.imageBadge.style.display = 'block';
    }

    _clearSelectedImage() {
        this._selectedImage = null;
        if (this.imageInput) this.imageInput.value = '';
        if (this.imagePreviewBar) this.imagePreviewBar.style.display = 'none';
        if (this.imagePreviewThumb) this.imagePreviewThumb.src = '';
        if (this.imageBadge) this.imageBadge.style.display = 'none';
    }

    // ────────────────────────────────────────────────────────────────────────

    async handleFileUpload(event) {
        const file = event.target.files?.[0] || event;
        if (!file || !file.name) return;

        // If it's an image, redirect to VLM flow instead of document RAG
        const IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
        const IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.webp'];
        const _ext = '.' + (file.name.split('.').pop() || '').toLowerCase();
        if (IMAGE_TYPES.includes(file.type) || IMAGE_EXTS.includes(_ext)) {
            await this._attachImageFile(file);
            this.fileInput.value = '';
            return;
        }

        await this.uploadFile(file);
        this.fileInput.value = '';
    }

    async uploadFile(file) {
        // Blocking overlay with spinner and timer
        this.uploadBtn.disabled = true;
        this.setAiState('thinking');

        const t0 = Date.now();
        const overlay = document.createElement('div');
        overlay.className = 'upload-overlay';
        const _c = document.createElement('div');
        _c.className = 'upload-overlay-content';
        _c.appendChild(Object.assign(document.createElement('span'), {className: 'upload-spinner-lg'}));
        const _txt = Object.assign(document.createElement('div'), {className: 'upload-overlay-text'});
        _txt.textContent = this.t('doc_uploading');
        _c.appendChild(_txt);
        const _f = Object.assign(document.createElement('div'), {className: 'upload-overlay-file'});
        _f.textContent = file.name;
        _c.appendChild(_f);
        const _timer = Object.assign(document.createElement('div'), {className: 'upload-overlay-timer'});
        const _elapsed = document.createElement('span');
        _elapsed.id = 'uploadElapsed';
        _elapsed.textContent = '0';
        _timer.appendChild(_elapsed);
        _timer.appendChild(document.createTextNode('s'));
        _c.appendChild(_timer);
        const _hint = Object.assign(document.createElement('div'), {className: 'upload-overlay-hint'});
        _hint.textContent = this.t('doc_upload_hint');
        _c.appendChild(_hint);
        overlay.appendChild(_c);
        document.querySelector('.chat-main').appendChild(overlay);

        const timerInterval = setInterval(() => {
            const el = document.getElementById('uploadElapsed');
            if (el) el.textContent = Math.round((Date.now() - t0) / 1000);
        }, 500);

        const formData = new FormData();
        formData.append('file', file);
        if (this.currentSessionId) {
            formData.append('session_id', this.currentSessionId);
        }

        try {
            const response = await this.fetchWithCsrf('/ui/upload', {
                method: 'POST',
                body: formData
            });

            if (response.ok) {
                const data = await response.json();

                if (data.session_id && !this.currentSessionId) {
                    this.currentSessionId = data.session_id;
                    this.loadSessions();
                }

                this.addUploadedFile(data);

                // Bug #17: specific prompt for images vs documents
                const isImage = /\.(jpe?g|png|gif|webp|heic|heif|bmp|tiff?)$/i.test(data.filename || file.name || '');

                // Show image inline in the chat (user bubble) if it's a photo
                if (isImage) {
                    const previewUrl = URL.createObjectURL(file);
                    this.addMessageToChat('user', '', true, null, previewUrl);
                }

                const elapsed = Math.round((Date.now() - t0) / 1000);
                const chunkMsg = data.chunks_saved ? ` (${data.chunks_saved} ${this.t('doc_fragments')})` : '';
                this.addMessageToChat('assistant', `${this.t('doc_uploaded').replace('{name}', data.filename).replace('{chunks}', chunkMsg).replace('{time}', elapsed)}\nℹ️ ${this.t('doc_chat_only')}`);
                this.messageInput.value = this.t(isImage ? 'image_describe' : 'doc_summarize');
                this.messageInput.focus();
                this.messageInput.select();
            } else {
                const error = await response.json();
                this.filePreview.classList.remove('active');
                this.addMessageToChat('assistant', `❌ ${this.t('doc_upload_error')}: ${error.detail}`);
            }
        } catch (error) {
            console.error('Error uploading file:', error);
            this.filePreview.classList.remove('active');
            this.addMessageToChat('assistant', `❌ ${this.t('doc_upload_error')}.`);
        } finally {
            clearInterval(timerInterval);
            overlay.remove();
            this.uploadBtn.disabled = false;
            this.setAiState('idle');
        }
    }

    addUploadedFile(fileData) {
        // Update file preview to show uploaded file
        const sizeKB = (fileData.size / 1024).toFixed(1);
        this.filePreview.innerHTML = `
            <div class="uploaded-file">
                <span class="uploaded-file-icon"><i data-lucide="file-text"></i></span>
                <span class="uploaded-file-name">${this.escapeHtml(fileData.filename)}</span>
                <span class="uploaded-file-size">(${sizeKB} KB)</span>
                <button class="uploaded-file-remove" onclick="nexeUI.removeFilePreview()">✕</button>
            </div>
            <div class="uploaded-file-notice">${this.t('doc_chat_only')}</div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [this.filePreview] });
        this.filePreview.classList.add('active');
    }

    removeFilePreview() {
        this.filePreview.replaceChildren();
        this.filePreview.classList.remove('active');
        this.uploadedFile = null;
        // Clear document server-side
        if (this.currentSessionId) {
            this.fetchWithCsrf('/ui/session/' + this.currentSessionId + '/clear-document', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            }).catch(function(e) { console.warn('Could not clear document:', e); });
        }
    }

    setupDragAndDrop() {
        const chatMain = document.querySelector('.chat-main');

        // Prevent default drag behaviors
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            chatMain.addEventListener(eventName, (e) => {
                e.preventDefault();
                e.stopPropagation();
            });
        });

        // Highlight drop zone
        ['dragenter', 'dragover'].forEach(eventName => {
            chatMain.addEventListener(eventName, () => {
                chatMain.classList.add('drag-over');
            });
        });

        ['dragleave', 'drop'].forEach(eventName => {
            chatMain.addEventListener(eventName, () => {
                chatMain.classList.remove('drag-over');
            });
        });

        // Handle drop
        chatMain.addEventListener('drop', (e) => {
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                this.handleFileUpload({ target: { files } });
            }
        });
    }

    clearChat() {
        this.chatMessages.innerHTML = '';
    }

    showWelcome() {
        // NOTE: innerHTML uses only trusted i18n strings from UI_STRINGS, not user input
        this.chatMessages.innerHTML = `
            <div class="welcome-screen">
                <div class="welcome-icon"><i data-lucide="bot"></i></div>
                <h2>${this.t('welcome_title')}</h2>
                <p>${this.t('welcome_subtitle')}</p>
                <div class="features">
                    <div class="feature feature-clickable" data-action="chat" title="${this.t('feature_chat')}">
                        <span class="feature-icon"><i data-lucide="message-circle"></i></span>
                        <span>${this.t('feature_chat')}</span>
                    </div>
                    <div class="feature feature-clickable" data-action="upload" title="${this.t('feature_upload')}">
                        <span class="feature-icon"><i data-lucide="folder-open"></i></span>
                        <span>${this.t('feature_upload')}</span>
                    </div>
                    <div class="feature feature-clickable" data-action="image" title="${this.t('feature_image')}">
                        <span class="feature-icon"><i data-lucide="image"></i></span>
                        <span>${this.t('feature_image')}</span>
                    </div>
                    <div class="feature feature-clickable" data-action="rag" title="${this.t('feature_rag')}">
                        <span class="feature-icon"><i data-lucide="sliders-horizontal"></i></span>
                        <span>${this.t('feature_rag')}</span>
                    </div>
                    <div class="feature feature-clickable" data-action="tray" title="${this.t('feature_tray')}">
                        <span class="feature-icon"><i data-lucide="layout-panel-top"></i></span>
                        <span>${this.t('feature_tray')}</span>
                    </div>
                    <div class="feature feature-clickable" data-action="models" title="${this.t('feature_models')}">
                        <span class="feature-icon"><i data-lucide="package-plus"></i></span>
                        <span>${this.t('feature_models')}</span>
                    </div>
                    <div class="feature feature-clickable" data-action="sysprompt" title="${this.t('feature_sysprompt')}">
                        <span class="feature-icon"><i data-lucide="pencil-line"></i></span>
                        <span>${this.t('feature_sysprompt')}</span>
                    </div>
                    <div class="feature feature-clickable" data-action="basics" title="${this.t('feature_basics')}">
                        <span class="feature-icon"><i data-lucide="book-open"></i></span>
                        <span>${this.t('feature_basics')}</span>
                    </div>
                    <div class="feature feature-clickable" data-action="plugin" title="${this.t('feature_plugin')}">
                        <span class="feature-icon"><i data-lucide="puzzle"></i></span>
                        <span>${this.t('feature_plugin')}</span>
                    </div>
                    <div class="feature feature-clickable" data-action="local" title="${this.t('feature_local')}">
                        <span class="feature-icon"><i data-lucide="lock"></i></span>
                        <span>${this.t('feature_local')}</span>
                    </div>
                </div>
                <p class="welcome-disclaimer">${this.t('welcome_disclaimer')}</p>
            </div>
        `;
        const chatFeature = this.chatMessages.querySelector('[data-action="chat"]');
        if (chatFeature) chatFeature.addEventListener('click', () => {
            this.messageInput.value = this.t('prompt_chat_help');
            this.messageInput.focus();
        });
        const uploadFeature = this.chatMessages.querySelector('[data-action="upload"]');
        if (uploadFeature) uploadFeature.addEventListener('click', () => this.fileInput.click());
        const imageFeature = this.chatMessages.querySelector('[data-action="image"]');
        if (imageFeature) imageFeature.addEventListener('click', () => this.imageInput && this.imageInput.click());
        const ragFeature = this.chatMessages.querySelector('[data-action="rag"]');
        if (ragFeature) ragFeature.addEventListener('click', () => {
            this.messageInput.value = this.t('prompt_rag_help');
            this.messageInput.focus();
        });
        const trayFeature = this.chatMessages.querySelector('[data-action="tray"]');
        if (trayFeature) trayFeature.addEventListener('click', () => {
            this.messageInput.value = this.t('prompt_tray_help');
            this.messageInput.focus();
        });
        const modelsFeature = this.chatMessages.querySelector('[data-action="models"]');
        if (modelsFeature) modelsFeature.addEventListener('click', () => {
            this.messageInput.value = this.t('prompt_models_install');
            this.messageInput.focus();
        });
        const syspromptFeature = this.chatMessages.querySelector('[data-action="sysprompt"]');
        if (syspromptFeature) syspromptFeature.addEventListener('click', () => {
            this.messageInput.value = this.t('prompt_sysprompt');
            this.messageInput.focus();
        });
        const basicsFeature = this.chatMessages.querySelector('[data-action="basics"]');
        if (basicsFeature) basicsFeature.addEventListener('click', () => {
            this.messageInput.value = this.t('prompt_basics');
            this.messageInput.focus();
        });
        const pluginFeature = this.chatMessages.querySelector('[data-action="plugin"]');
        if (pluginFeature) pluginFeature.addEventListener('click', () => {
            this.messageInput.value = this.t('prompt_plugin');
            this.messageInput.focus();
        });
        const localFeature = this.chatMessages.querySelector('[data-action="local"]');
        if (localFeature) localFeature.addEventListener('click', () => {
            this.messageInput.value = this.t('prompt_local_help');
            this.messageInput.focus();
        });
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }

    scrollToBottom(force = false) {
        // B025: scroll-lock — only auto-scroll if the user is near the bottom.
        // If they scrolled up to read while the model streams, leave them there;
        // the lock releases itself when they scroll back down (listener above).
        // force=true is for user-initiated turns (sending a message, loading a
        // session), where jumping to the bottom is the expected behavior.
        if (!force && this._userScrolledUp) return;
        setTimeout(() => {
            this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
        }, 100);
    }

    _scheduleRender(el, content) {
        // Render markdown max every 80ms to avoid overloading the DOM
        if (this._renderTimer) return;
        // First token with REAL text — removes the placeholder wave. We do not
        // clear it with empty `content`, since [MODEL_LOADING] chunks
        // arrive before tokens and would clear the placeholder leaving
        // a gap while the model is still loading into VRAM.
        if (el && el.classList.contains('thinking-placeholder') && content && content.trim()) {
            el.classList.remove('thinking-placeholder');
            el.textContent = '';
        }
        this._renderTimer = setTimeout(() => {
            this._renderTimer = null;
            // renderMarkdown now centralizes the strip (bug #18 follow-up)
            const _rendered = this.renderMarkdown(content);
            el.innerHTML = _rendered;  // safe: renderMarkdown sanitizes via marked.js custom renderer
        }, 80);
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    window.nexeUI = new NexeUI();
});
