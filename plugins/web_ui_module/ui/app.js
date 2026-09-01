/**
 * ============================================
 * Nexe UI - Client JavaScript
 * ============================================
 */
/* global UI_STRINGS */

// UI_STRINGS (i18n ca/en/es) lives in i18n.js, loaded as a classic <script>
// BEFORE this file in index.html (shared top-level global scope).

// #896: the 3 collection ids, spelled once. Was 4 independent literal lists
// in this file (COLL_MAP x2, ALL x2) — Python's server-nexe.core.memory_access
// is the cross-language source of truth; keep this in sync with it by hand.

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


    /** #859: drop the "compacting" notice once there is something else to look at. */


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
                // _updateDegradedBanner overwrites this with the degraded
                // label when a subsystem is down; "connected" is only about
                // reaching the server, not about it being well.
                statusText.textContent = ok ? this.t('connected') : this.t('disconnected');
                if (ok) {
                    try {
                        this._updateDegradedBanner(await r.json());
                    } catch (err) {
                        console.warn('[nexe] status payload:', err.message || err);
                    }
                } else {
                    this._clearDegradedNotice();
                }
            } catch {
                statusDot.classList.remove('active');
                statusDot.style.background = '#ff4444';
                statusText.textContent = this.t('disconnected');
                this._clearDegradedNotice();
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
        this._restoreLastSession();

        // Setup drag and drop
        this.setupDragAndDrop();

        // Initialize Lucide icons
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }









    _handleUnauthorized() {
        // We don't clear localStorage — Safari with ITP may clear it
        // between sessions. If the key was valid, the user simply
        // resends it without having to remember it.
        this.apiKey = null;
        this.showLoginOverlay();
    }























    // ── VLM image helpers ────────────────────────────────────────────────────




    // ────────────────────────────────────────────────────────────────────────







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





}

// Prototype extension point for the sibling nexe-*.js files (#127). The class
// stays the façade; each cluster lives in its own file, loaded after this one
// and before DOMContentLoaded — which is when the instance below is built, so
// every extension is in place by then.
//
// Deliberately not Object.assign: class methods are NON-enumerable, and assign
// would define them enumerable, so every split-out method would suddenly show
// up in a `for...in` over an instance. Copying the descriptors with enumerable
// forced back to false makes a moved method indistinguishable from one written
// in the class body.
//
// The collision check is the same rule the installer split follows: one home
// per name. Two files defining the same method is a silent last-one-wins.
NexeUI.extend = function (methods) {
    for (const [name, desc] of Object.entries(Object.getOwnPropertyDescriptors(methods))) {
        if (Object.prototype.hasOwnProperty.call(NexeUI.prototype, name)) {
            throw new Error(`NexeUI.extend: ${name} already has a home`);
        }
        desc.enumerable = false;
        Object.defineProperty(NexeUI.prototype, name, desc);
    }
};

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    window.nexeUI = new NexeUI();
});
