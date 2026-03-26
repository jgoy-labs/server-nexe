/**
 * ============================================
 * Nexe UI - Client JavaScript
 * ============================================
 */

const UI_STRINGS = {
    ca: {
        login_subtitle: "Introdueix la API Key per accedir",
        login_btn: "Accedir",
        login_error: 'Clau incorrecta. Comprova el fitxer <code>.env</code>',
        login_hint: 'La clau és a <code>.env</code> → <code>NEXE_PRIMARY_API_KEY</code>',
        loading: "Carregant...",
        welcome_title: "Benvingut a Nexe",
        welcome_subtitle: "IA local amb memòria persistent",
        feature_chat: "Conversa amb memòria contextual",
        feature_upload: "Puja documents (.txt, .md, .pdf)",
        feature_local: "100% local i privat",
        new_chat: "Nova conversa",
        sessions: "Sessions",
        placeholder: "Escriu un missatge...",
        rag_title: "Precisió RAG",
        rag_info: "Controla quant ha de semblar-se un record a la teva pregunta per ser inclòs al context. Valors alts (0.8+) → menys context, molt precís. Valors baixos (0.3) → més context, però pot incloure soroll i causar al·lucinacions.",
        rag_wide: "Ampli",
        rag_strict: "Estricte",
        thinking: "Pensant...",
        connected: "Connectat",
        disconnected: "Desconnectat",
        toggle_theme: "Canviar tema",
        toggle_frame: "Mostrar/ocultar marc",
        upload_doc: "Pujar document",
        send: "Enviar",
        stop: "Aturar generació",
        saved: "guardat",
        model_loading: "Carregant model a VRAM",
    },
    en: {
        login_subtitle: "Enter your API Key to access",
        login_btn: "Login",
        login_error: 'Invalid key. Check the <code>.env</code> file',
        login_hint: 'The key is in <code>.env</code> → <code>NEXE_PRIMARY_API_KEY</code>',
        loading: "Loading...",
        welcome_title: "Welcome to Nexe",
        welcome_subtitle: "Local AI with persistent memory",
        feature_chat: "Chat with contextual memory",
        feature_upload: "Upload documents (.txt, .md, .pdf)",
        feature_local: "100% local and private",
        new_chat: "New conversation",
        sessions: "Sessions",
        placeholder: "Type a message...",
        rag_title: "RAG Precision",
        rag_info: "Controls how closely a memory must match your question to be included in context. High values (0.8+) → less context, very precise. Low values (0.3) → more context, but may include noise and cause hallucinations.",
        rag_wide: "Wide",
        rag_strict: "Strict",
        thinking: "Thinking...",
        connected: "Connected",
        disconnected: "Disconnected",
        toggle_theme: "Toggle theme",
        toggle_frame: "Show/hide frame",
        upload_doc: "Upload document",
        send: "Send",
        stop: "Stop generation",
        saved: "saved",
        model_loading: "Loading model into VRAM",
    },
    es: {
        login_subtitle: "Introduce la API Key para acceder",
        login_btn: "Acceder",
        login_error: 'Clave incorrecta. Comprueba el fichero <code>.env</code>',
        login_hint: 'La clave está en <code>.env</code> → <code>NEXE_PRIMARY_API_KEY</code>',
        loading: "Cargando...",
        welcome_title: "Bienvenido a Nexe",
        welcome_subtitle: "IA local con memoria persistente",
        feature_chat: "Conversa con memoria contextual",
        feature_upload: "Sube documentos (.txt, .md, .pdf)",
        feature_local: "100% local y privado",
        new_chat: "Nueva conversación",
        sessions: "Sesiones",
        placeholder: "Escribe un mensaje...",
        rag_title: "Precisión RAG",
        rag_info: "Controla cuánto debe parecerse un recuerdo a tu pregunta para ser incluido en el contexto. Valores altos (0.8+) → menos contexto, muy preciso. Valores bajos (0.3) → más contexto, pero puede incluir ruido y causar alucinaciones.",
        rag_wide: "Amplio",
        rag_strict: "Estricto",
        thinking: "Pensando...",
        connected: "Conectado",
        disconnected: "Desconectado",
        toggle_theme: "Cambiar tema",
        toggle_frame: "Mostrar/ocultar marco",
        upload_doc: "Subir documento",
        send: "Enviar",
        stop: "Detener generación",
        saved: "guardado",
        model_loading: "Cargando modelo en VRAM",
    }
};

class NexeUI {
    constructor() {
        this.apiKey = localStorage.getItem('nexe_api_key') || null;
        // Idioma: servidor (injectat) > navegador > anglès
        const serverLang = window.NEXE_LANG;
        const browserLang = (navigator.language || 'en').split('-')[0];
        const preferredLang = serverLang || browserLang;
        this.lang = UI_STRINGS[preferredLang] ? preferredLang : 'en';
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
        // Welcome
        s('.welcome-screen h2', 'welcome_title');
        s('.welcome-screen p', 'welcome_subtitle');
        const features = document.querySelectorAll('.feature span:last-child');
        if (features[0]) features[0].textContent = this.t('feature_chat');
        if (features[1]) features[1].textContent = this.t('feature_upload');
        if (features[2]) features[2].textContent = this.t('feature_local');
        // Sidebar
        s('#newChatBtn', 'new_chat');
        const newBtn = document.getElementById('newChatBtn');
        if (newBtn) { newBtn.innerHTML = `<i data-lucide="plus"></i> ${this.t('new_chat')}`; }
        s('.sessions-header h3', 'sessions');
        s('#modelInfoText', 'loading');
        // Selectors
        const bSel = document.getElementById('backendSelect');
        if (bSel && bSel.options[0]) bSel.options[0].textContent = this.t('loading');
        const mSel = document.getElementById('modelSelect');
        if (mSel && mSel.options[0]) mSel.options[0].textContent = this.t('loading');
        // RAG
        s('.rag-threshold-title', 'rag_title');
        const ragInfo = document.querySelector('.rag-info-icon');
        if (ragInfo) ragInfo.title = this.t('rag_info');
        const hints = document.querySelectorAll('.rag-threshold-hints span');
        if (hints[0]) hints[0].textContent = this.t('rag_wide');
        if (hints[1]) hints[1].textContent = this.t('rag_strict');
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
        if (thinkText) thinkText.textContent = this.t('thinking');
        const statusText = document.querySelector('.status-indicator span');
        if (statusText) statusText.textContent = this.t('connected');
        // HTML lang
        document.documentElement.lang = this.lang;
        // Re-render Lucide icons
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }

    setAiState(state) {
        document.documentElement.setAttribute('data-ai-state', state);
        const badge = document.getElementById('thinkingBadge');
        if (badge) {
            badge.classList.toggle('active', state === 'thinking' || state === 'streaming');
        }
        // Tornar a idle al cap de 2s si era error
        if (state === 'error') {
            clearTimeout(this._errorResetTimer);
            this._errorResetTimer = setTimeout(() => {
                document.documentElement.setAttribute('data-ai-state', 'idle');
            }, 2000);
        }
    }

    fetchWithCsrf(url, options = {}) {
        const opts = { ...options };
        const method = (opts.method || 'GET').toUpperCase();
        opts.credentials = opts.credentials || 'same-origin';
        if (this.apiKey) {
            opts.headers = { ...(opts.headers || {}), 'X-API-Key': this.apiKey };
        }
        return fetch(url, opts);
    }

    init() {
        this.applyI18n();
        if (!this.apiKey) {
            this.showLoginOverlay();
            return;
        }
        this.initUI();
    }

    showLoginOverlay() {
        const overlay = document.getElementById('loginOverlay');
        overlay.style.display = 'flex';
        const input = document.getElementById('apiKeyInput');
        const btn = document.getElementById('loginBtn');
        const error = document.getElementById('loginError');

        // Pre-omplir amb la key guardada (si existeix)
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
                    this.initUI();
                    if (typeof lucide !== 'undefined') lucide.createIcons();
                } else {
                    error.style.display = 'block';
                    input.value = '';
                    input.focus();
                }
            } catch (e) {
                error.style.display = 'block';
            } finally {
                btn.disabled = false;
            }
        };

        btn.addEventListener('click', doLogin);
        input.addEventListener('keydown', (e) => { if (e.key === 'Enter') doLogin(); });
        input.focus();
    }

    initUI() {
        // DOM elements
        this.chatMessages = document.getElementById('chatMessages');
        this.messageInput = document.getElementById('messageInput');
        this.sendBtn = document.getElementById('sendBtn');
        this.stopBtn = document.getElementById('stopBtn');
        this.newChatBtn = document.getElementById('newChatBtn');
        this.uploadBtn = document.getElementById('uploadBtn');
        this.fileInput = document.getElementById('fileInput');
        this.filePreview = document.getElementById('filePreview');
        this.sessionsList = document.getElementById('sessionsList');
        this.statsBar = document.getElementById('statsBar');

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

        // Auto-resize textarea
        this.messageInput.addEventListener('input', () => {
            this.messageInput.style.height = 'auto';
            this.messageInput.style.height = this.messageInput.scrollHeight + 'px';
        });

        // RAG threshold slider
        const ragSlider = document.getElementById('ragThresholdSlider');
        const ragBadge = document.getElementById('ragThresholdValue');
        if (ragSlider && ragBadge) {
            const saved = localStorage.getItem('nexe_rag_threshold');
            if (saved) { ragSlider.value = saved; ragBadge.textContent = saved; }
            ragSlider.addEventListener('input', () => {
                ragBadge.textContent = ragSlider.value;
                localStorage.setItem('nexe_rag_threshold', ragSlider.value);
            });
        }

        // Toggle tema clar/fosc (detecta preferència del SO si no hi ha preferència guardada)
        const themeBtn = document.getElementById('themeToggleBtn');
        if (themeBtn) {
            const applyTheme = (light) => {
                document.body.classList.toggle('light', light);
                document.documentElement.setAttribute('data-theme', light ? 'light' : 'dark');
            };
            const saved = localStorage.getItem('nexe_theme');
            const preferLight = saved ? saved === 'light' : window.matchMedia('(prefers-color-scheme: light)').matches;
            applyTheme(preferLight);
            // Seguir canvis del SO si l'usuari no ha triat manualment
            window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', (e) => {
                if (!localStorage.getItem('nexe_theme')) applyTheme(e.matches);
            });
            themeBtn.addEventListener('click', () => {
                const isLight = document.body.classList.toggle('light');
                document.documentElement.setAttribute('data-theme', isLight ? 'light' : 'dark');
                localStorage.setItem('nexe_theme', isLight ? 'light' : 'dark');
            });
        }

        // Status indicator dinàmic
        const statusDot  = document.querySelector('.status-dot');
        const statusText = document.querySelector('.status-indicator span');
        const checkStatus = async () => {
            try {
                const r = await fetch('/status', { cache: 'no-store' });
                const ok = r.ok;
                statusDot.classList.toggle('active', ok);
                statusDot.style.background = ok ? '' : '#ff4444';
                statusText.textContent = ok ? 'Connectat' : 'Desconnectat';
            } catch {
                statusDot.classList.remove('active');
                statusDot.style.background = '#ff4444';
                statusText.textContent = 'Desconnectat';
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

        // Load sessions i info model
        this.loadSessions();
        this.loadServerInfo();

        // Setup drag and drop
        this.setupDragAndDrop();

        // Inicialitzar icones Lucide
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
                // Aplicar idioma del servidor
                if (data.lang && UI_STRINGS[data.lang]) {
                    this.lang = data.lang;
                    this.applyI18n();
                }
                const el = document.getElementById('modelInfoText');
                if (el) {
                    const backend = data.backend === 'auto' ? '' : ` · ${data.backend}`;
                    el.textContent = data.model + backend;
                    el.title = `model: ${data.model}\nbackend: ${data.backend}\nversion: ${data.version}`;
                }
            }
        } catch (e) {
            const el = document.getElementById('modelInfoText');
            if (el) el.textContent = 'nexe';
        }
        this.loadBackends();
    }

    async loadBackends() {
        const backendSel = document.getElementById('backendSelect');
        const modelSel = document.getElementById('modelSelect');
        if (!backendSel || !modelSel) return;

        try {
            const resp = await this.fetchWithCsrf('/ui/backends');
            if (!resp.ok) return;
            const data = await resp.json();
            this._backends = data.backends;
            this._currentModel = data.current_model || '';

            backendSel.innerHTML = '';
            for (const b of data.backends) {
                const opt = document.createElement('option');
                opt.value = b.id;
                opt.textContent = b.name;
                if (b.active) opt.selected = true;
                backendSel.appendChild(opt);
            }

            this._updateModelSelect(backendSel.value, this._currentModel);

            backendSel.addEventListener('change', () => {
                this._updateModelSelect(backendSel.value);
                this._applyBackendChange();
            });
            modelSel.addEventListener('change', () => {
                this._applyBackendChange();
            });
        } catch (e) {
            console.error('Failed to load backends:', e);
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
                // Suport objecte {name, size_gb} o string legacy
                const name = typeof m === 'object' ? m.name : m;
                const sizeGb = typeof m === 'object' ? m.size_gb : 0;
                opt.value = name;
                opt.textContent = sizeGb > 0 ? `${name} (${sizeGb}GB)` : name;
                if (currentModel && (currentModel.includes(name) || name.includes(currentModel))) {
                    opt.selected = true;
                }
                modelSel.appendChild(opt);
            }
        }
    }

    async _applyBackendChange() {
        const backendSel = document.getElementById('backendSelect');
        const modelSel = document.getElementById('modelSelect');
        if (!backendSel || !modelSel) return;

        const backend = backendSel.value;
        const model = modelSel.value;

        try {
            const resp = await this.fetchWithCsrf('/ui/backend', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ backend, model })
            });
            if (resp.ok) {
                const el = document.getElementById('modelInfoText');
                if (el) el.textContent = `${model} · ${backend}`;
            }
        } catch (e) {
            console.error('Failed to set backend:', e);
        }
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
        // Deixa les stats visibles 3s i desapareix
        setTimeout(() => {
            if (this.statsBar) this.statsBar.classList.remove('active');
        }, 3000);
    }

    _handleUnauthorized() {
        // No esborrem localStorage — Safari amb ITP pot netejar-lo
        // entre sessions. Si la key era valida, l'usuari simplement
        // la torna a enviar sense haver de recordar-la.
        this.apiKey = null;
        this.showLoginOverlay();
    }

    async createNewSession() {
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

            sessionEl.innerHTML = `
                <div class="session-item-content">
                    <div class="session-item-title">
                        ${session.first_message || 'Nova conversa'}
                    </div>
                    <div class="session-item-meta">${timeStr}</div>
                </div>
                <button class="btn-delete-session" title="Eliminar sessió">✕</button>
            `;

            // Click on session content to load
            const contentEl = sessionEl.querySelector('.session-item-content');
            contentEl.addEventListener('click', () => this.loadSession(session.id));

            // Click on delete button
            const deleteBtn = sessionEl.querySelector('.btn-delete-session');
            deleteBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.deleteSession(session.id);
            });

            this.sessionsList.appendChild(sessionEl);
        });
    }

    async deleteSession(sessionId) {
        if (!confirm('Segur que vols eliminar aquesta sessió?')) return;

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
        try {
            const response = await this.fetchWithCsrf(`/ui/session/${sessionId}/history`);
            if (response.ok) {
                const data = await response.json();
                this.currentSessionId = sessionId;
                this.clearChat();
                this.renderMessages(data.messages || []);
                this.renderSessions();
            }
        } catch (error) {
            console.error('Error loading session:', error);
        }
    }

    renderMessages(messages) {
        this.chatMessages.innerHTML = '';

        messages.forEach(msg => {
            this.addMessageToChat(msg.role, msg.content, false);
        });

        this.scrollToBottom();
    }

    async sendMessage() {
        const message = this.messageInput.value.trim();
        if (!message) return;

        // Auto-crear sessió si no en tenim — el servidor no retorna l'ID per streaming
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
            } catch (e) { /* continua sense sessió */ }
        }

        // Disable input and show stop button
        this.messageInput.disabled = true;
        this.sendBtn.style.display = 'none';
        this.stopBtn.style.display = 'flex';
        this.isGenerating = true;
        this.setAiState('thinking');

        // Create AbortController for this request
        this.abortController = new AbortController();

        // Add user message to chat
        this.addMessageToChat('user', message);
        this.messageInput.value = '';
        this.messageInput.style.height = 'auto';

        try {
            const ragSlider = document.getElementById('ragThresholdSlider');
            const ragThreshold = ragSlider ? parseFloat(ragSlider.value) : 0.6;
            const backendSel = document.getElementById('backendSelect');
            const modelSel = document.getElementById('modelSelect');
            const response = await this.fetchWithCsrf('/ui/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: message,
                    session_id: this.currentSessionId,
                    stream: true,
                    rag_threshold: ragThreshold,
                    backend: backendSel ? backendSel.value : undefined,
                    model: modelSel ? modelSel.value : undefined
                }),
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
                let loadingEl = null;

                // Think state machine
                let tMode = 'init';   // 'init' | 'thinking' | 'responding'
                let tBuf  = '';       // partial tag buffer
                let tContent = '';    // accumulated think text
                let tTok = 0;         // think token count
                let tBlock = null;    // .think-block DOM element
                let tTextEl = null;   // .think-text inside block

                const startThinkBlock = () => {
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
                    tBlock.querySelector('.think-label').textContent = 'Raonament';
                    tBlock.querySelector('.think-tokens').textContent = `~${tTok} tok`;
                    tBlock.removeAttribute('open'); // col·lapsa automàticament
                };

                // Netejar tags especials de models (GPT-OSS, etc.)
                const _cleanModelTags = (buf) => {
                    buf = buf.replace(/<\|[^|]+\|>/g, '');
                    buf = buf.replace(/[◁◀][^▷▶]*[▷▶]/g, '');
                    return buf;
                };

                // Parseja thinking/content de GPT-OSS (post-streaming)
                const _parseThinkingChannels = (text) => {
                    if (!text) return { thinking: null, content: '' };
                    let cleaned = text.replace(/<\|[^|]+\|>/g, '').replace(/[◁◀][^▷▶]*[▷▶]/g, '');
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
                            } else if (tBuf.trimStart().length > 0 && !tBuf.trimStart().startsWith('<')) {
                                // Primer char no es tag — resposta directa
                                tMode = 'responding';
                                this.setAiState('streaming');
                                this._startStreamStats();
                            } else if (tBuf.length > 7) {
                                // Buffer gran sense <think> — resposta directa
                                tMode = 'responding';
                                this.setAiState('streaming');
                                this._startStreamStats();
                            } else {
                                break; // espera més dades
                            }
                        } else if (tMode === 'thinking') {
                            const e = tBuf.indexOf('</think>');
                            if (e >= 0) {
                                tContent += tBuf.slice(0, e);
                                tTok += Math.ceil(tContent.length / 4);
                                if (tTextEl) tTextEl.textContent = tContent;
                                tBuf = tBuf.slice(e + 8).replace(/^\n+/, '');
                                tMode = 'responding';
                                closeThinkBlock();
                                this.setAiState('streaming');
                                this._startStreamStats();
                            } else {
                                // Guarda possible tag parcial al final
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

                        // Detectar token MODEL (model realment usat)
                        const modelMatch = chunk.match(/\x00\[MODEL:([^\]]+)\]\x00/);
                        if (modelMatch) {
                            usedModel = modelMatch[1];
                            chunk = chunk.replace(/\x00\[MODEL:[^\]]+\]\x00/, '');
                        }

                        // Detectar token RAG (memòries recuperades)
                        const ragMatch = chunk.match(/\x00\[RAG:(\d+)\]\x00/);
                        if (ragMatch) {
                            ragCount = parseInt(ragMatch[1], 10);
                            chunk = chunk.replace(/\x00\[RAG:\d+\]\x00/, '');
                        }

                        // Detectar RAG average score
                        const ragAvgMatch = chunk.match(/\x00\[RAG_AVG:([\d.]+)\]\x00/);
                        if (ragAvgMatch) {
                            ragAvg = parseFloat(ragAvgMatch[1]);
                            chunk = chunk.replace(/\x00\[RAG_AVG:[\d.]+\]\x00/, '');
                        }

                        // Detectar RAG items (per-font scores)
                        let ragItemMatch;
                        const ragItemRe = /\x00\[RAG_ITEM:([^|]+)\|([\d.]+)\]\x00/g;
                        while ((ragItemMatch = ragItemRe.exec(chunk)) !== null) {
                            ragItems.push({ col: ragItemMatch[1], score: parseFloat(ragItemMatch[2]) });
                        }
                        chunk = chunk.replace(/\x00\[RAG_ITEM:[^\]]+\]\x00/g, '');

                        // Detectar token COMPACT (context compactat)
                        compactMatch = chunk.match(/\x00\[COMPACT:(\d+)\]\x00/);
                        if (compactMatch) {
                            chunk = chunk.replace(/\x00\[COMPACT:\d+\]\x00/, '');
                        }

                        // Detectar MODEL_LOADING (model carregant-se a VRAM)
                        const loadingMatch = chunk.match(/\x00\[MODEL_LOADING:([^\]|]+)\|?([^\]]*)\]\x00/);
                        if (loadingMatch) {
                            chunk = chunk.replace(/\x00\[MODEL_LOADING:[^\]]+\]\x00/, '');
                            const loadingModel = loadingMatch[1];
                            const loadingBackend = loadingMatch[2] || '';
                            const backendLabel = loadingBackend.replace('_module', '').toUpperCase();
                            loadingEl = document.createElement('div');
                            loadingEl.className = 'model-loading-indicator';
                            loadingEl.innerHTML = `
                                <div class="loading-spinner"></div>
                                <span>${this.t('model_loading')}… <strong>${loadingModel}</strong>${backendLabel ? ` <em class="loading-backend">[${backendLabel}]</em>` : ''} — <em class="loading-timer">0s</em></span>
                            `;
                            lastMsg.querySelector('.message-content').insertBefore(loadingEl, assistantMessageDiv);
                            this.scrollToBottom();
                            // Cronòmetre en temps real
                            this._loadStartTime = Date.now();
                            const _timerEl = loadingEl.querySelector('.loading-timer');
                            this._loadingTimer = setInterval(() => {
                                if (_timerEl) _timerEl.textContent = `${Math.round((Date.now() - this._loadStartTime) / 1000)}s`;
                            }, 1000);
                        }

                        // Detectar MODEL_READY (model carregat, comença a respondre)
                        if (chunk.includes('\x00[MODEL_READY]\x00')) {
                            chunk = chunk.replace('\x00[MODEL_READY]\x00', '');
                            if (this._loadingTimer) { clearInterval(this._loadingTimer); this._loadingTimer = null; }
                            if (loadingEl) {
                                const elapsed = Math.round((Date.now() - (this._loadStartTime || Date.now())) / 1000);
                                loadingEl.className = 'model-loading-indicator loaded';
                                const _be = loadingEl.querySelector('.loading-backend');
                                const _beText = _be ? ` ${_be.outerHTML}` : '';
                                loadingEl.innerHTML = `<span>✓ Model carregat (${elapsed}s)${_beText}</span>`;
                                loadingEl = null;
                            }
                        }

                        // Detectar token de memòria guardat
                        if (chunk.includes('\x00[MEM]\x00')) {
                            memorySaved = true;
                            chunk = chunk.replace('\x00[MEM]\x00', '');
                        }

                        processChunk(chunk);
                        this.scrollToBottom();
                    }
                    // Streaming acabat — si loading indicator queda, marcar com carregat
                    if (this._loadingTimer) { clearInterval(this._loadingTimer); this._loadingTimer = null; }
                    if (loadingEl) {
                        const elapsed = Math.round((Date.now() - (this._loadStartTime || Date.now())) / 1000);
                        loadingEl.className = 'model-loading-indicator loaded';
                        loadingEl.innerHTML = `<span>✓ Model carregat (${elapsed}s)</span>`;
                        loadingEl = null;
                    }
                    // Render final definitiu
                    clearTimeout(this._renderTimer);
                    // Si no s'ha detectat thinking via <think>, provar parsing GPT-OSS
                    if (tMode !== 'thinking' && !tContent) {
                        const parsed = _parseThinkingChannels(fullResponse);
                        if (parsed.thinking) {
                            // Mostrar thinking block retroactivament
                            startThinkBlock();
                            if (tTextEl) tTextEl.textContent = parsed.thinking;
                            const tokEl = tBlock?.querySelector('.think-tokens');
                            if (tokEl) tokEl.textContent = `~${Math.ceil(parsed.thinking.length / 4)} tok`;
                            closeThinkBlock();
                            fullResponse = parsed.content;
                        } else {
                            fullResponse = _cleanModelTags(fullResponse);
                        }
                    }
                    assistantMessageDiv.innerHTML = this.renderMarkdown(fullResponse);
                    if (tMode !== 'responding' && tMode !== 'init') closeThinkBlock();
                    // Stats per missatge
                    const elapsed = (Date.now() - this._streamStart) / 1000;
                    const finalTok = this._streamTokens;
                    const finalSpd = elapsed > 0.5 ? (finalTok / elapsed).toFixed(1) : null;
                    const statsEl = lastMsg.querySelector('.message-stats');
                    if (statsEl && finalTok > 0) {
                        const timeStr = elapsed > 0 ? `${elapsed.toFixed(1)}s` : '';
                        const spdStr = finalSpd ? ` · ${finalSpd} tok/s` : '';
                        const modelShort = usedModel ? usedModel.split('/').pop() : '';
                        const memBadge = memorySaved
                            ? `<span class="stat-item stat-mem"><i data-lucide="bookmark-check"></i><span>${this.t('saved')}</span></span>`
                            : '';
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
                                    return `<div class="rag-detail-row ${color}"><span class="rag-col">${item.col}</span><span class="rag-detail-bar">${bar}</span><span class="rag-score">${(item.score * 100).toFixed(0)}%</span></div>`;
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
                            ${modelShort ? `<span class="stat-item stat-model"><i data-lucide="cpu"></i><span>${modelShort}</span></span>` : ''}
                            ${ragBadge}
                            ${compactBadge}
                            ${memBadge}
                        `;
                        if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [statsEl] });
                    }
                } catch (readError) {
                    if (this._loadingTimer) { clearInterval(this._loadingTimer); this._loadingTimer = null; }
                    if (loadingEl) {
                        loadingEl.className = 'model-loading-indicator error';
                        loadingEl.innerHTML = `<span>✗ Error carregant model</span>`;
                        loadingEl = null;
                    }
                    if (readError.name === 'AbortError') {
                        if (tMode === 'thinking') closeThinkBlock();
                        assistantMessageDiv.innerHTML = this.renderMarkdown(fullResponse + '\n\n*[Generació aturada]*');
                    } else {
                        throw readError;
                    }
                }

            } else {
                this.setAiState('error');
                this.addMessageToChat('assistant', '❌ Error: No s\'ha pogut enviar el missatge.');
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                // User cancelled generation (AbortError)
            } else {
                console.error('Error sending message:', error);
                this.setAiState('error');
                this.addMessageToChat('assistant', `❌ Error de connexió: ${error.message || error}`);
            }
        } finally {
            this._stopStreamStats();
            this.setAiState('idle');
            this.messageInput.disabled = false;
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

    addMessageToChat(role, content, scroll = true) {
        // Remove welcome screen if exists
        const welcome = this.chatMessages.querySelector('.welcome-screen');
        if (welcome) {
            welcome.remove();
        }

        const messageEl = document.createElement('div');
        messageEl.className = `message ${role}`;

        const avatarIcon = role === 'user' ? 'user' : 'bot';
        const roleName = role === 'user' ? 'Tu' : 'Nexe';

        // User messages: escape HTML, Assistant messages: render Markdown
        const messageContent = role === 'user'
            ? this.escapeHtml(content)
            : this.renderMarkdown(content);

        messageEl.innerHTML = `
            <div class="message-avatar"><i data-lucide="${avatarIcon}"></i></div>
            <div class="message-content">
                <div class="message-role">${roleName}</div>
                <div class="message-text">${messageContent}</div>
                ${role === 'assistant' ? '<div class="message-stats"></div>' : ''}
            </div>
        `;

        this.chatMessages.appendChild(messageEl);
        if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [messageEl.querySelector('.message-avatar')] });

        if (scroll) {
            this.scrollToBottom();
        }
    }

    renderMarkdown(text) {
        // Use marked.js to render Markdown
        if (typeof marked !== 'undefined' && text) {
            try {
                // Override raw HTML renderer to prevent XSS injection via HTML blocks
                const renderer = new marked.Renderer();
                const _escape = this.escapeHtml.bind(this);
                renderer.html = function(token) {
                    const raw = typeof token === 'string' ? token : (token.text || '');
                    return _escape(raw);
                };
                return marked.parse(text, { breaks: true, gfm: true, renderer });
            } catch (e) {
                console.error('Markdown parsing error:', e);
                return this.escapeHtml(text);
            }
        }
        return this.escapeHtml(text);
    }

    async handleFileUpload(event) {
        const file = event.target.files?.[0] || event;
        if (!file || !file.name) return;

        await this.uploadFile(file);

        // Reset file input
        this.fileInput.value = '';
    }

    async uploadFile(file) {
        // Show loading indicator
        this.filePreview.innerHTML = `<span class="upload-loading">Pujant "${file.name}"...</span>`;
        this.filePreview.classList.add('active');
        this.uploadBtn.disabled = true;

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

                // Use the session_id from upload response
                if (data.session_id && !this.currentSessionId) {
                    this.currentSessionId = data.session_id;
                    this.loadSessions();
                }

                // Add to uploaded files list
                this.addUploadedFile(data);

                // Show success message (without preview)
                const ingestedMsg = data.ingested ? '✅ Indexat a memòria RAG' : '⚠️ No indexat';
                this.addMessageToChat('assistant', `✅ Document "${data.filename}" carregat correctament.\n${ingestedMsg}`);

                // Focus input with suggested prompt
                this.messageInput.value = `Resumeix aquest document`;
                this.messageInput.focus();
                this.messageInput.select();
            } else {
                const error = await response.json();
                this.filePreview.classList.remove('active');
                this.addMessageToChat('assistant', `❌ Error pujant document: ${error.detail}`);
            }
        } catch (error) {
            console.error('Error uploading file:', error);
            this.filePreview.classList.remove('active');
            this.addMessageToChat('assistant', '❌ Error pujant el document.');
        } finally {
            this.uploadBtn.disabled = false;
        }
    }

    addUploadedFile(fileData) {
        // Update file preview to show uploaded file
        const sizeKB = (fileData.size / 1024).toFixed(1);
        this.filePreview.innerHTML = `
            <div class="uploaded-file">
                <span class="uploaded-file-icon"><i data-lucide="file-text"></i></span>
                <span class="uploaded-file-name">${fileData.filename}</span>
                <span class="uploaded-file-size">(${sizeKB} KB)</span>
                <button class="uploaded-file-remove" onclick="nexeUI.removeFilePreview()">✕</button>
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [this.filePreview] });
        this.filePreview.classList.add('active');
    }

    removeFilePreview() {
        this.filePreview.innerHTML = '';
        this.filePreview.classList.remove('active');
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
                this.uploadFile(files[0]);
            }
        });
    }

    clearChat() {
        this.chatMessages.innerHTML = '';
    }

    showWelcome() {
        this.chatMessages.innerHTML = `
            <div class="welcome-screen">
                <div class="welcome-icon"><i data-lucide="bot"></i></div>
                <h2>Benvingut a Nexe</h2>
                <p>IA local amb memòria persistent</p>
                <div class="features">
                    <div class="feature">
                        <span class="feature-icon"><i data-lucide="message-circle"></i></span>
                        <span>Conversa amb memòria contextual</span>
                    </div>
                    <div class="feature">
                        <span class="feature-icon"><i data-lucide="folder-open"></i></span>
                        <span>Puja documents (.txt, .md, .pdf)</span>
                    </div>
                    <div class="feature">
                        <span class="feature-icon"><i data-lucide="lock"></i></span>
                        <span>100% local i privat</span>
                    </div>
                </div>
            </div>
        `;
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }

    scrollToBottom() {
        setTimeout(() => {
            this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
        }, 100);
    }

    _scheduleRender(el, content) {
        // Render markdown màxim cada 80ms per no sobrecarregar el DOM
        if (this._renderTimer) return;
        this._renderTimer = setTimeout(() => {
            this._renderTimer = null;
            el.innerHTML = this.renderMarkdown(content);
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
