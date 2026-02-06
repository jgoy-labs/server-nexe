/**
 * ============================================
 * Nexe UI - Client JavaScript
 * ============================================
 */

const I18N_MESSAGES = {
    'en-US': {
        'ui.title': 'Nexe - Local AI',
        'ui.new_chat': 'New chat',
        'ui.sessions': 'Sessions',
        'ui.status.connected': 'Connected',
        'ui.welcome.title': 'Welcome to Nexe',
        'ui.welcome.subtitle': 'Local AI with persistent memory',
        'ui.welcome.feature.memory': 'Chat with contextual memory',
        'ui.welcome.feature.upload': 'Upload documents (.txt, .md, .pdf)',
        'ui.welcome.feature.private': '100% local and private',
        'ui.input.upload_title': 'Upload document',
        'ui.input.placeholder': 'Write a message...',
        'ui.input.send_title': 'Send',
        'ui.input.stop_title': 'Stop generation',
        'ui.session.title': 'Conversation',
        'ui.session.delete_title': 'Delete session',
        'ui.session.delete_confirm': 'Are you sure you want to delete this session?',
        'ui.stream.stopped': '⏹️ *[Generation stopped]*',
        'ui.error.send_failed': '❌ Error: Message could not be sent.',
        'ui.error.connection': '❌ Connection error.',
        'ui.role.user': 'You',
        'ui.role.assistant': 'Nexe',
        'ui.upload.loading': '📤 Uploading "{filename}"...',
        'ui.upload.ingested': '✅ Indexed in RAG memory',
        'ui.upload.not_ingested': '⚠️ Not indexed',
        'ui.upload.success': '✅ Document "{filename}" uploaded successfully.\n{ingestedStatus}',
        'ui.upload.prompt_summarize': 'Summarize this document',
        'ui.upload.error': '❌ Error uploading document: {detail}',
        'ui.upload.error_generic': '❌ Error uploading the document.',
        'ui.upload.remove_title': 'Remove file',
        'ui.drop_text': '📁 Drop file here'
    },
    'ca-ES': {
        'ui.title': 'Nexe - IA local',
        'ui.new_chat': 'Nova conversa',
        'ui.sessions': 'Sessions',
        'ui.status.connected': 'Connectat',
        'ui.welcome.title': 'Benvingut a Nexe',
        'ui.welcome.subtitle': 'IA local amb memòria persistent',
        'ui.welcome.feature.memory': 'Conversa amb memòria contextual',
        'ui.welcome.feature.upload': 'Puja documents (.txt, .md, .pdf)',
        'ui.welcome.feature.private': '100% local i privat',
        'ui.input.upload_title': 'Pujar document',
        'ui.input.placeholder': 'Escriu un missatge...',
        'ui.input.send_title': 'Enviar',
        'ui.input.stop_title': 'Aturar generació',
        'ui.session.title': 'Conversa',
        'ui.session.delete_title': 'Eliminar sessió',
        'ui.session.delete_confirm': 'Segur que vols eliminar aquesta sessió?',
        'ui.stream.stopped': '⏹️ *[Generació aturada]*',
        'ui.error.send_failed': "❌ Error: No s'ha pogut enviar el missatge.",
        'ui.error.connection': '❌ Error de connexió.',
        'ui.role.user': 'Tu',
        'ui.role.assistant': 'Nexe',
        'ui.upload.loading': '📤 Pujant "{filename}"...',
        'ui.upload.ingested': '✅ Indexat a memòria RAG',
        'ui.upload.not_ingested': '⚠️ No indexat',
        'ui.upload.success': '✅ Document "{filename}" carregat correctament.\n{ingestedStatus}',
        'ui.upload.prompt_summarize': 'Resumeix aquest document',
        'ui.upload.error': '❌ Error pujant document: {detail}',
        'ui.upload.error_generic': '❌ Error pujant el document.',
        'ui.upload.remove_title': 'Eliminar fitxer',
        'ui.drop_text': '📁 Deixa anar el fitxer aquí'
    },
    'es-ES': {
        'ui.title': 'Nexe - IA local',
        'ui.new_chat': 'Nueva conversación',
        'ui.sessions': 'Sesiones',
        'ui.status.connected': 'Conectado',
        'ui.welcome.title': 'Bienvenido a Nexe',
        'ui.welcome.subtitle': 'IA local con memoria persistente',
        'ui.welcome.feature.memory': 'Conversación con memoria contextual',
        'ui.welcome.feature.upload': 'Sube documentos (.txt, .md, .pdf)',
        'ui.welcome.feature.private': '100% local y privado',
        'ui.input.upload_title': 'Subir documento',
        'ui.input.placeholder': 'Escribe un mensaje...',
        'ui.input.send_title': 'Enviar',
        'ui.input.stop_title': 'Detener generación',
        'ui.session.title': 'Conversación',
        'ui.session.delete_title': 'Eliminar sesión',
        'ui.session.delete_confirm': '¿Seguro que quieres eliminar esta sesión?',
        'ui.stream.stopped': '⏹️ *[Generación detenida]*',
        'ui.error.send_failed': '❌ Error: No se pudo enviar el mensaje.',
        'ui.error.connection': '❌ Error de conexión.',
        'ui.role.user': 'Tú',
        'ui.role.assistant': 'Nexe',
        'ui.upload.loading': '📤 Subiendo "{filename}"...',
        'ui.upload.ingested': '✅ Indexado en memoria RAG',
        'ui.upload.not_ingested': '⚠️ No indexado',
        'ui.upload.success': '✅ Documento "{filename}" cargado correctamente.\n{ingestedStatus}',
        'ui.upload.prompt_summarize': 'Resume este documento',
        'ui.upload.error': '❌ Error subiendo documento: {detail}',
        'ui.upload.error_generic': '❌ Error al subir el documento.',
        'ui.upload.remove_title': 'Eliminar archivo',
        'ui.drop_text': '📁 Suelta el archivo aquí'
    }
};

const I18N = (() => {
    const DEFAULT_LOCALE = 'en-US';

    const normalizeLocale = (locale) => {
        if (!locale) return DEFAULT_LOCALE;
        const value = String(locale).toLowerCase();
        if (value.startsWith('ca')) return 'ca-ES';
        if (value.startsWith('es')) return 'es-ES';
        if (value.startsWith('en')) return 'en-US';
        return DEFAULT_LOCALE;
    };

    const resolveLocale = () => {
        let candidate = null;
        try {
            const params = new URLSearchParams(window.location.search);
            candidate = params.get('lang');
        } catch (e) {
            candidate = null;
        }
        if (!candidate) {
            try {
                candidate = localStorage.getItem('nexe_ui_locale');
            } catch (e) {
                candidate = null;
            }
        }
        if (!candidate) {
            candidate = navigator.language || navigator.userLanguage;
        }
        return normalizeLocale(candidate);
    };

    const format = (template, vars) => {
        if (!vars) return template;
        return template.replace(/\{(\w+)\}/g, (match, key) => {
            if (Object.prototype.hasOwnProperty.call(vars, key)) {
                return String(vars[key]);
            }
            return match;
        });
    };

    const locale = resolveLocale();
    const messages = I18N_MESSAGES[locale] || I18N_MESSAGES[DEFAULT_LOCALE] || {};

    const t = (key, fallback, vars) => {
        const base = messages[key] || (I18N_MESSAGES[DEFAULT_LOCALE] || {})[key] || fallback || key;
        return format(base, vars);
    };

    const applyTranslations = (root = document) => {
        if (!root || !root.querySelectorAll) return;

        root.querySelectorAll('[data-i18n]').forEach((el) => {
            const key = el.getAttribute('data-i18n');
            const fallback = el.textContent || '';
            el.textContent = t(key, fallback);
        });

        root.querySelectorAll('[data-i18n-placeholder]').forEach((el) => {
            const key = el.getAttribute('data-i18n-placeholder');
            const fallback = el.getAttribute('placeholder') || '';
            el.setAttribute('placeholder', t(key, fallback));
        });

        root.querySelectorAll('[data-i18n-title]').forEach((el) => {
            const key = el.getAttribute('data-i18n-title');
            const fallback = el.getAttribute('title') || '';
            el.setAttribute('title', t(key, fallback));
        });

        root.querySelectorAll('[data-i18n-html]').forEach((el) => {
            const key = el.getAttribute('data-i18n-html');
            const fallback = el.innerHTML || '';
            el.innerHTML = t(key, fallback);
        });
    };

    const formatDate = (date, options) => date.toLocaleString(locale, options);

    if (typeof document !== 'undefined' && document.documentElement) {
        document.documentElement.lang = locale;
    }

    return {
        locale,
        t,
        applyTranslations,
        formatDate
    };
})();

class NexeUI {
    constructor() {
        this.currentSessionId = null;
        this.uploadedFile = null;
        this.sessions = [];
        this.abortController = null;
        this.isGenerating = false;
        this.i18n = I18N;

        this.init();
    }

    getCsrfToken() {
        const match = document.cookie.match(/(?:^|; )nexe_csrf_token=([^;]*)/);
        return match ? decodeURIComponent(match[1]) : null;
    }

    fetchWithCsrf(url, options = {}) {
        const opts = { ...options };
        const method = (opts.method || 'GET').toUpperCase();
        opts.credentials = opts.credentials || 'same-origin';
        if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
            const token = this.getCsrfToken();
            if (token) {
                opts.headers = { ...(opts.headers || {}), 'X-CSRF-Token': token };
            }
        }
        return fetch(url, opts);
    }

    init() {
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

        // Load sessions
        this.loadSessions();

        // Setup drag and drop
        this.setupDragAndDrop();
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
            const timeStr = this.i18n.formatDate(date, {
                day: 'numeric',
                month: 'short',
                hour: '2-digit',
                minute: '2-digit'
            });

            const sessionTitle = this.i18n.t('ui.session.title', 'Conversation');
            const countLabel = session.message_count > 0 ? ` (${session.message_count})` : '';
            const deleteTitle = this.i18n.t('ui.session.delete_title', 'Delete session');

            sessionEl.innerHTML = `
                <div class="session-item-content">
                    <div class="session-item-title">
                        ${sessionTitle}${countLabel}
                    </div>
                    <div class="session-item-meta">${timeStr}</div>
                </div>
                <button class="btn-delete-session" title="${deleteTitle}">✕</button>
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
        const confirmText = this.i18n.t(
            'ui.session.delete_confirm',
            'Are you sure you want to delete this session?'
        );
        if (!confirm(confirmText)) return;

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

        // Disable input and show stop button
        this.messageInput.disabled = true;
        this.sendBtn.style.display = 'none';
        this.stopBtn.style.display = 'flex';
        this.isGenerating = true;

        // Create AbortController for this request
        this.abortController = new AbortController();

        // Add user message to chat
        this.addMessageToChat('user', message);
        this.messageInput.value = '';
        this.messageInput.style.height = 'auto';

        try {
            const response = await this.fetchWithCsrf('/ui/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: message,
                    session_id: this.currentSessionId,
                    stream: true
                }),
                signal: this.abortController.signal
            });

            if (response.ok) {
                // Create placeholders
                let assistantMessageDiv = null;
                let fullResponse = "";

                const reader = response.body.getReader();
                const decoder = new TextDecoder();

                // Add empty message for assistant
                this.addMessageToChat('assistant', '', true);
                const messages = this.chatMessages.querySelectorAll('.message.assistant');
                assistantMessageDiv = messages[messages.length - 1].querySelector('.message-text');

                try {
                    while (true) {
                        const { value, done } = await reader.read();
                        if (done) break;

                        const chunk = decoder.decode(value, { stream: true });
                        fullResponse += chunk;
                        // During streaming, show plain text for performance
                        assistantMessageDiv.textContent = fullResponse;
                        this.scrollToBottom();
                    }
                    // After streaming completes, render as Markdown
                    assistantMessageDiv.innerHTML = this.renderMarkdown(fullResponse);
                } catch (readError) {
                    if (readError.name === 'AbortError') {
                        // User stopped generation - render with indicator
                        const stopped = this.i18n.t('ui.stream.stopped', '⏹️ *[Generation stopped]*');
                        assistantMessageDiv.innerHTML = this.renderMarkdown(`${fullResponse}\n\n${stopped}`);
                    } else {
                        throw readError;
                    }
                }

                // Reload sessions list to catch up updates
                if (!this.currentSessionId) {
                    this.loadSessions();
                }

            } else {
                this.addMessageToChat(
                    'assistant',
                    this.i18n.t('ui.error.send_failed', '❌ Error: Message could not be sent.')
                );
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                console.log('Generation stopped by user');
            } else {
                console.error('Error sending message:', error);
                this.addMessageToChat(
                    'assistant',
                    this.i18n.t('ui.error.connection', '❌ Connection error.')
                );
            }
        } finally {
            // Re-enable input and show send button
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

        const avatar = role === 'user' ? '👤' : '🤖';
        const roleName = role === 'user'
            ? this.i18n.t('ui.role.user', 'You')
            : this.i18n.t('ui.role.assistant', 'Nexe');

        // User messages: escape HTML, Assistant messages: render Markdown
        const messageContent = role === 'user'
            ? this.escapeHtml(content)
            : this.renderMarkdown(content);

        messageEl.innerHTML = `
            <div class="message-avatar">${avatar}</div>
            <div class="message-content">
                <div class="message-role">${roleName}</div>
                <div class="message-text">${messageContent}</div>
            </div>
        `;

        this.chatMessages.appendChild(messageEl);

        if (scroll) {
            this.scrollToBottom();
        }
    }

    renderMarkdown(text) {
        // Use marked.js to render Markdown
        if (typeof marked !== 'undefined' && text) {
            try {
                // Configure marked for safety
                marked.setOptions({
                    breaks: true,      // Convert \n to <br>
                    gfm: true,         // GitHub Flavored Markdown
                    sanitize: false    // We trust our own content
                });
                return marked.parse(text);
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
        const loadingText = this.i18n.t('ui.upload.loading', '📤 Uploading "{filename}"...', {
            filename: file.name
        });
        this.filePreview.innerHTML = `<span class="upload-loading">${loadingText}</span>`;
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
                const ingestedMsg = data.ingested
                    ? this.i18n.t('ui.upload.ingested', '✅ Indexed in RAG memory')
                    : this.i18n.t('ui.upload.not_ingested', '⚠️ Not indexed');
                const successMessage = this.i18n.t(
                    'ui.upload.success',
                    '✅ Document "{filename}" uploaded successfully.\n{ingestedStatus}',
                    {
                        filename: data.filename,
                        ingestedStatus: ingestedMsg
                    }
                );
                this.addMessageToChat('assistant', successMessage);

                // Focus input with suggested prompt
                this.messageInput.value = this.i18n.t(
                    'ui.upload.prompt_summarize',
                    'Summarize this document'
                );
                this.messageInput.focus();
                this.messageInput.select();
            } else {
                const error = await response.json();
                this.filePreview.classList.remove('active');
                this.addMessageToChat(
                    'assistant',
                    this.i18n.t('ui.upload.error', '❌ Error uploading document: {detail}', {
                        detail: error.detail || ''
                    })
                );
            }
        } catch (error) {
            console.error('Error uploading file:', error);
            this.filePreview.classList.remove('active');
            this.addMessageToChat(
                'assistant',
                this.i18n.t('ui.upload.error_generic', '❌ Error uploading the document.')
            );
        } finally {
            this.uploadBtn.disabled = false;
        }
    }

    addUploadedFile(fileData) {
        // Update file preview to show uploaded file
        const sizeKB = (fileData.size / 1024).toFixed(1);
        const removeTitle = this.i18n.t('ui.upload.remove_title', 'Remove file');
        this.filePreview.innerHTML = `
            <div class="uploaded-file">
                <span class="uploaded-file-icon">📄</span>
                <span class="uploaded-file-name">${fileData.filename}</span>
                <span class="uploaded-file-size">(${sizeKB} KB)</span>
                <button class="uploaded-file-remove" title="${removeTitle}" onclick="nexeUI.removeFilePreview()">✕</button>
            </div>
        `;
        this.filePreview.classList.add('active');
    }

    removeFilePreview() {
        this.filePreview.innerHTML = '';
        this.filePreview.classList.remove('active');
    }

    setupDragAndDrop() {
        const chatMain = document.querySelector('.chat-main');
        if (chatMain) {
            chatMain.dataset.dropText = this.i18n.t('ui.drop_text', '📁 Drop file here');
        }

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

    getWelcomeHtml() {
        return `
            <div class="welcome-screen">
                <div class="welcome-icon">🤖</div>
                <h2>${this.i18n.t('ui.welcome.title', 'Welcome to Nexe')}</h2>
                <p>${this.i18n.t('ui.welcome.subtitle', 'Local AI with persistent memory')}</p>
                <div class="features">
                    <div class="feature">
                        <span class="feature-icon">💬</span>
                        <span>${this.i18n.t('ui.welcome.feature.memory', 'Chat with contextual memory')}</span>
                    </div>
                    <div class="feature">
                        <span class="feature-icon">📁</span>
                        <span>${this.i18n.t('ui.welcome.feature.upload', 'Upload documents (.txt, .md, .pdf)')}</span>
                    </div>
                    <div class="feature">
                        <span class="feature-icon">🔒</span>
                        <span>${this.i18n.t('ui.welcome.feature.private', '100% local and private')}</span>
                    </div>
                </div>
            </div>
        `;
    }

    showWelcome() {
        this.chatMessages.innerHTML = this.getWelcomeHtml();
    }

    scrollToBottom() {
        setTimeout(() => {
            this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
        }, 100);
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Initialize app
document.addEventListener('DOMContentLoaded', () => {
    I18N.applyTranslations(document);
    window.nexeUI = new NexeUI();
});
