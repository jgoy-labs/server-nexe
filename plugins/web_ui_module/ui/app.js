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
        rag_title: "Filtre RAG",
        rag_info: "Controla quants documents s'inclouen al context. Baix → més info, millors respostes. Alt → descarta documents, el model pot inventar.",
        rag_wide: "Més info",
        rag_strict: "Filtre alt",
        rag_panel_title: "Filtre de documents RAG",
        rag_panel_desc: "Controla quants documents de la memòria s'inclouen al context del model.",
        rag_panel_low: "<strong>← Baix (0.20–0.35):</strong> Inclou més documents. El model té més info per respondre.",
        rag_panel_high: "<strong>→ Alt (0.50–0.70):</strong> Filtre estricte. Descarta documents. <em>El model pot inventar.</em>",
        rag_panel_rec: "<strong>Recomanat: 0.35–0.45</strong> — el model rep prou context sense soroll.",
        thinking: "Pensant...",
        connected: "Connectat",
        disconnected: "Desconnectat",
        toggle_theme: "Canviar tema",
        toggle_frame: "Mostrar/ocultar marc",
        upload_doc: "Pujar document",
        send: "Enviar",
        stop: "Aturar generació",
        saved: "guardat",
        deleted: "esborrat",
        model_loading: "Carregant model a VRAM",
        doc_chat_only: "Aquest document només estarà disponible en aquest chat.",
        doc_uploading: "Processant document",
        language: "Idioma",
        ollama_not_responding: "Ollama no respon — comprova que està instal·lat",
        delete_session: "Eliminar sessió",
        confirm_delete: "Segur que vols eliminar aquesta sessió?",
        reasoning: "Raonament",
        thinking_mode: "Raonament",
        thinking_not_supported: "Aquest model no suporta raonament",
        thinking_tip: "Activa el raonament intern — pensa pas a pas abans de respondre. No tots els models ho suporten.",
        generation_stopped: "Generació aturada",
        model_load_error: "Error carregant model",
        model_loaded: "Model carregat",
        send_error: "Error: No s'ha pogut enviar el missatge.",
        connection_error: "Error de connexió",
        col_title: "Col·leccions",
        col_memory: "Memòria personal",
        col_knowledge: "Documents pujats",
        col_docs: "Base de coneixement",
        col_memory_tip: "Fets personals recordats de converses anteriors",
        col_knowledge_tip: "Documents que has pujat a aquesta sessió",
        col_docs_tip: "Documentació del sistema (IDENTITY, guies, etc.)",
        mem_saving: "Guardant memòria...",
        mem_saved: "Memòria guardada",
        backend_label: "Motor",
        model_label: "Model",
        starting: "Iniciant...",
        support_link: "Suport",
        rag_filter_label: "Filtre RAG",
        col_warning_prefix: "⚠ Desactivat: ",
        col_warning_suffix: ". Desmarca per reactivar.",
        doc_truncated: "⚠ Document massa gran pel context actual ({pct}% descartat)",
        doc_uploaded: "✅ Document \"{name}\" carregat{chunks} en {time}s.",
        doc_fragments: "fragments",
        doc_summarize: "Resumeix aquest document",
        image_describe: "Descriu aquesta foto",
        doc_upload_error: "Error pujant el document",
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
        rag_title: "RAG Filter",
        rag_info: "Controls how many documents are included in context. Low → more info, better answers. High → discards documents, model may hallucinate.",
        rag_wide: "More info",
        rag_strict: "High filter",
        rag_panel_title: "RAG Document Filter",
        rag_panel_desc: "Controls how many memory documents are included in the model's context.",
        rag_panel_low: "<strong>← Low (0.20–0.35):</strong> Includes more documents. The model has more info to answer.",
        rag_panel_high: "<strong>→ High (0.50–0.70):</strong> Strict filter. Discards documents. <em>The model may hallucinate.</em>",
        rag_panel_rec: "<strong>Recommended: 0.35–0.45</strong> — the model gets enough context without noise.",
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
        doc_chat_only: "This document will only be available in this chat.",
        doc_uploading: "Processing document",
        language: "Language",
        ollama_not_responding: "Ollama is not responding — check it's installed",
        delete_session: "Delete session",
        confirm_delete: "Are you sure you want to delete this session?",
        reasoning: "Reasoning",
        thinking_mode: "Thinking",
        thinking_not_supported: "This model does not support reasoning",
        thinking_tip: "Enable reasoning — thinks step by step before answering. Not all models support this.",
        generation_stopped: "Generation stopped",
        model_load_error: "Error loading model",
        model_loaded: "Model loaded",
        send_error: "Error: Could not send the message.",
        connection_error: "Connection error",
        col_title: "Collections",
        col_memory: "Personal memory",
        col_knowledge: "Uploaded documents",
        col_docs: "Knowledge base",
        col_memory_tip: "Personal facts remembered from previous conversations",
        col_knowledge_tip: "Documents you uploaded in this session",
        col_docs_tip: "System documentation (IDENTITY, guides, etc.)",
        mem_saving: "Saving memory...",
        mem_saved: "Memory saved",
        deleted: "deleted",
        backend_label: "Backend",
        model_label: "Model",
        starting: "Starting...",
        support_link: "Support",
        rag_filter_label: "RAG Filter",
        col_warning_prefix: "⚠ Disabled: ",
        col_warning_suffix: ". Uncheck to re-enable.",
        doc_truncated: "⚠ Document too large for current context ({pct}% discarded)",
        doc_uploaded: "✅ Document \"{name}\" uploaded{chunks} in {time}s.",
        doc_fragments: "chunks",
        doc_summarize: "Summarize this document",
        image_describe: "Describe this photo",
        doc_upload_error: "Error uploading document",
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
        rag_title: "Filtro RAG",
        rag_info: "Controla cuántos documentos se incluyen en el contexto. Bajo → más info, mejores respuestas. Alto → descarta documentos, el modelo puede inventar.",
        rag_wide: "Más info",
        rag_strict: "Filtro alto",
        rag_panel_title: "Filtro de documentos RAG",
        rag_panel_desc: "Controla cuántos documentos de la memoria se incluyen en el contexto del modelo.",
        rag_panel_low: "<strong>← Bajo (0.20–0.35):</strong> Incluye más documentos. El modelo tiene más info para responder.",
        rag_panel_high: "<strong>→ Alto (0.50–0.70):</strong> Filtro estricto. Descarta documentos. <em>El modelo puede inventar.</em>",
        rag_panel_rec: "<strong>Recomendado: 0.35–0.45</strong> — el modelo recibe contexto suficiente sin ruido.",
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
        doc_chat_only: "Este documento solo estará disponible en este chat.",
        doc_uploading: "Procesando documento",
        language: "Idioma",
        ollama_not_responding: "Ollama no responde — comprueba que está instalado",
        delete_session: "Eliminar sesión",
        confirm_delete: "¿Seguro que quieres eliminar esta sesión?",
        reasoning: "Razonamiento",
        thinking_mode: "Razonamiento",
        thinking_not_supported: "Este modelo no soporta razonamiento",
        thinking_tip: "Activa el razonamiento interno — piensa paso a paso antes de responder. No todos los modelos lo soportan.",
        generation_stopped: "Generación detenida",
        model_load_error: "Error cargando modelo",
        model_loaded: "Modelo cargado",
        send_error: "Error: No se pudo enviar el mensaje.",
        connection_error: "Error de conexión",
        col_title: "Colecciones",
        col_memory: "Memoria personal",
        col_knowledge: "Documentos subidos",
        col_docs: "Base de conocimiento",
        col_memory_tip: "Hechos personales recordados de conversaciones anteriores",
        col_knowledge_tip: "Documentos que has subido en esta sesión",
        col_docs_tip: "Documentación del sistema (IDENTITY, guías, etc.)",
        mem_saving: "Guardando memoria...",
        mem_saved: "Memoria guardada",
        deleted: "borrado",
        backend_label: "Motor",
        model_label: "Modelo",
        starting: "Iniciando...",
        support_link: "Soporte",
        rag_filter_label: "Filtro RAG",
        col_warning_prefix: "⚠ Desactivado: ",
        col_warning_suffix: ". Desmarca para reactivar.",
        doc_truncated: "⚠ Documento demasiado grande para el contexto actual ({pct}% descartado)",
        doc_uploaded: "✅ Documento \"{name}\" cargado{chunks} en {time}s.",
        doc_fragments: "fragmentos",
        doc_summarize: "Resume este documento",
        image_describe: "Describe esta foto",
        doc_upload_error: "Error subiendo el documento",
    }
};

class NexeUI {
    constructor() {
        this.apiKey = localStorage.getItem('nexe_api_key') || null;
        // Language: server (injected data-attr) > html lang > browser > english
        const serverLang = document.documentElement.dataset.nexeLang || document.documentElement.lang;
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
        if (thinkLabel) thinkLabel.closest('label').title = this.t('thinking_tip');
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
        // HTML lang
        document.documentElement.lang = this.lang;
        // Re-render Lucide icons
        if (typeof lucide !== 'undefined') lucide.createIcons();
        // Refresh collection warning with updated language
        if (this._listenersAttached) this._updateCollectionWarning();
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
        const method = (opts.method || 'GET').toUpperCase();
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
            // Persistir al servidor
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
            } catch (e) { /* ignore corrupt localStorage */ }
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
        } catch (e) { return ALL; }
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
        this.messageInput = document.getElementById('messageInput');
        this.sendBtn = document.getElementById('sendBtn');
        this.stopBtn = document.getElementById('stopBtn');
        this.newChatBtn = document.getElementById('newChatBtn');
        this.uploadBtn = document.getElementById('uploadBtn');
        this.fileInput = document.getElementById('fileInput');
        this.filePreview = document.getElementById('filePreview');
        this.sessionsList = document.getElementById('sessionsList');
        this.statsBar = document.getElementById('statsBar');

        // VLM: imatge seleccionada {b64, type, name} o null
        this._selectedImage = null;
        this.imageBtn = document.getElementById('imageBtn');
        this.imageInput = document.getElementById('imageInput');
        this.imagePreviewBar = document.getElementById('imagePreviewBar');
        this.imagePreviewThumb = document.getElementById('imagePreviewThumb');
        this.imagePreviewName = document.getElementById('imagePreviewName');
        this.imageBadge = document.getElementById('imageBadge');

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
            const RAG_DEFAULT = 0.25;
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

        // Dynamic status indicator (uses fetchWithCsrf to send X-API-Key)
        // Codex P2 fix: /status now requires authentication (Q2.3)
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
                // Suport objecte {name, size_gb} o string legacy
                const name = typeof m === 'object' ? m.name : m;
                opt.value = name;
                // Mostra 👁️ si té visió, 🧠 si pensa + mida aproximada en RAM
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

    /// Heurística client-side: un model té visió (VLM) si el nom conté
    /// famílies/tags multimodals coneguts. Equivalent al hasVision del Swift wizard.
    /// backend: 'ollama'|'mlx'|'llamacpp' — Qwen3.5 vision funciona a Ollama però no a MLX (torch).
    _modelHasVision(name, backend) {
        const n = (name || '').toLowerCase();
        // Omni-models que requereixen torch/torchvision —
        // a MLX peten. A Ollama funcionen bé.
        // Veure knowledge/*/LIMITATIONS.md secció "Models multimodal (VLM)".
        const omniExcludes = [
            'qwen3.5',      // Qwen3.5 (totes les mides) — torch requerit per MLX
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
                    // Retry fins que Ollama estigui connectat (max 30s)
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
                                    // Actualitzar el dropdown (treure "desconnectat")
                                    const opt = backendSel.querySelector('[value="ollama"]');
                                    if (opt) opt.textContent = 'Ollama';
                                }
                            }
                        } catch (_) {}
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
            this.addMessageToChat(msg.role, msg.content, false, msg.stats || null);
        });

        this.scrollToBottom();
    }

    async sendMessage() {
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
            } catch (e) { /* continue without session */ }
        }

        // Disable input and show stop button
        this.messageInput.disabled = true;
        this.sendBtn.style.display = 'none';
        this.stopBtn.style.display = 'flex';
        this.isGenerating = true;
        this.setAiState('thinking');

        // Create AbortController for this request
        this.abortController = new AbortController();

        // Capturar imatge seleccionada abans de netejar l'estat VLM
        const pendingImage = this._selectedImage ? { ...this._selectedImage } : null;
        this._clearSelectedImage();

        // Add user message to chat — si hi ha imatge adjunta, mostra-la inline
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
                    // Pattern 0b: ...text...</think>... (sense tag d'obertura — DeepSeek R1)
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
                                    // Not GPT-OSS — resposta directa
                                    tMode = 'responding';
                                    this.setAiState('streaming');
                                    this._startStreamStats();
                                }
                            } else if (tGptOssChecked && tBuf.trimStart().length > 0 && !tBuf.trimStart().startsWith('<')) {
                                // Primer char no es tag — resposta directa
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

                        // Detectar token MODEL (model realment usat)
                        const modelMatch = chunk.match(/\x00\[MODEL:([^\]]+)\]\x00/);
                        if (modelMatch) {
                            usedModel = modelMatch[1];
                            chunk = chunk.replace(/\x00\[MODEL:[^\]]+\]\x00/, '');
                        }

                        // Detect RAG token (retrieved memories)
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

                        // Detectar DOC_TRUNCATED (document massa gran pel context)
                        const truncMatch = chunk.match(/\x00\[DOC_TRUNCATED:(\d+)\]\x00/);
                        if (truncMatch) {
                            const truncPct = parseInt(truncMatch[1]);
                            chunk = chunk.replace(/\x00\[DOC_TRUNCATED:\d+\]\x00/, '');
                            const truncNotice = document.createElement('div');
                            truncNotice.className = 'trunc-notice';
                            truncNotice.textContent = this.t('doc_truncated').replace('{pct}', truncPct);
                            lastMsg.querySelector('.message-content').insertBefore(truncNotice, assistantMessageDiv);
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
                            if (this._loadingTimer) { clearInterval(this._loadingTimer); this._loadingTimer = null; }
                            if (loadingEl) {
                                const elapsed = Math.round((Date.now() - (this._loadStartTime || Date.now())) / 1000);
                                loadingEl.className = 'model-loading-indicator loaded';
                                const _be = loadingEl.querySelector('.loading-backend');
                                const _beText = _be ? ` ${_be.outerHTML}` : '';
                                loadingEl.innerHTML = `<span>✓ ${this.t('model_loaded')} (${elapsed}s)${_beText}</span>`;
                                loadingEl = null;
                            }
                        }

                        // Detect saved memory count token [MEM:N] or [MEM]
                        if (chunk.match(/\x00\[MEM:?\d*\]\x00/)) {
                            memorySaved = true;
                            chunk = chunk.replace(/\x00\[MEM:?\d*\]\x00/g, '');
                        }

                        // Detect deleted memory token [DEL:N:fact1|fact2|...]
                        const delMatch = chunk.match(/\x00\[DEL:(\d+):(.+?)\]\x00/);
                        if (delMatch) {
                            memoryDeleted = true;
                            deletedCount = parseInt(delMatch[1]);
                            deletedFacts = delMatch[2].split('|');
                            chunk = chunk.replace(/\x00\[DEL:\d+:.+?\]\x00/g, '');
                        }

                        processChunk(chunk);
                        this.scrollToBottom();
                    }
                    // Streaming done — if loading indicator remains, mark as loaded
                    if (this._loadingTimer) { clearInterval(this._loadingTimer); this._loadingTimer = null; }
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
                    // Guard: si la resposta queda buida despres de treure MEM_SAVE
                    // (el backend fa re-prompt, però per seguretat mantenim fallback UI)
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

    _abortIfGenerating() {
        if (this.isGenerating && this.abortController) {
            this.abortController.abort();
            this.messageInput.disabled = false;
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

        // textDiv: sempre present per assistant (el streaming el necessita via querySelector)
        // per user, només si hi ha contingut (bubbles imatge-only no en necessiten)
        const needsTextDiv = role === 'assistant' || content;
        let textDiv = null;
        if (needsTextDiv) {
            textDiv = document.createElement('div');
            textDiv.className = 'message-text';
            if (role === 'user') {
                textDiv.textContent = content;
            } else {
                textDiv.innerHTML = this.renderMarkdown(content); // renderMarkdown sanititza l'HTML (custom renderer)
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
        }

        messageEl.appendChild(avatarDiv);
        messageEl.appendChild(contentDiv);

        this.chatMessages.appendChild(messageEl);
        if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [avatarDiv] });

        if (scroll) {
            this.scrollToBottom();
        }
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
            .replace(/\x00/g, '')                       // stray delimiters
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

        // Si és una imatge, redirigir al flux VLM en lloc del RAG de documents
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
        // Overlay bloqueig amb spinner i timer
        this.uploadBtn.disabled = true;
        this.messageInput.disabled = true;
        this.setAiState('thinking');

        const sizeMB = file.size / (1024 * 1024);
        const estSec = Math.max(3, Math.round(sizeMB * 4));
        const t0 = Date.now();

        const overlay = document.createElement('div');
        overlay.className = 'upload-overlay';
        overlay.innerHTML = `
            <div class="upload-overlay-content">
                <span class="upload-spinner-lg"></span>
                <div class="upload-overlay-text">${this.t('doc_uploading')}</div>
                <div class="upload-overlay-file">${this.escapeHtml(file.name)}</div>
                <div class="upload-overlay-timer"><span id="uploadElapsed">0</span>s / ~${estSec}s</div>
            </div>
        `;
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

                // Bug #17: prompt específic per imatges vs documents
                const isImage = /\.(jpe?g|png|gif|webp|heic|heif|bmp|tiff?)$/i.test(data.filename || file.name || '');

                // Mostra la imatge inline al chat (bubble usuari) si és una foto
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
            this.messageInput.disabled = false;
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
        // Netejar document server-side
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
                    <div class="feature" title="${this.t('feature_local')}">
                        <span class="feature-icon"><i data-lucide="lock"></i></span>
                        <span>${this.t('feature_local')}</span>
                    </div>
                </div>
            </div>
        `;
        // Make features clickable
        const chatFeature = this.chatMessages.querySelector('[data-action="chat"]');
        if (chatFeature) chatFeature.addEventListener('click', () => this.messageInput.focus());
        const uploadFeature = this.chatMessages.querySelector('[data-action="upload"]');
        if (uploadFeature) uploadFeature.addEventListener('click', () => this.fileInput.click());
        if (typeof lucide !== 'undefined') lucide.createIcons();
    }

    scrollToBottom() {
        setTimeout(() => {
            this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
        }, 100);
    }

    _scheduleRender(el, content) {
        // Render markdown max every 80ms to avoid overloading the DOM
        if (this._renderTimer) return;
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
