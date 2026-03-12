/**
 * ============================================
 * Nexe UI - Client JavaScript
 * ============================================
 */

class NexeUI {
    constructor() {
        this.apiKey = localStorage.getItem('nexe_api_key') || null;
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
    }

    async loadServerInfo() {
        try {
            const resp = await this.fetchWithCsrf('/ui/info');
            if (resp.ok) {
                const data = await resp.json();
                const el = document.getElementById('modelInfoText');
                if (el) {
                    const backend = data.backend === 'auto' ? '' : ` · ${data.backend}`;
                    el.textContent = data.model + backend;
                    el.title = `model: ${data.model}\nbackend: ${data.backend}\nversió: ${data.version}`;
                }
            }
        } catch (e) {
            const el = document.getElementById('modelInfoText');
            if (el) el.textContent = 'nexe';
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
        localStorage.removeItem('nexe_api_key');
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
                        Conversa ${session.message_count > 0 ? `(${session.message_count})` : ''}
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

            if (response.status === 401) {
                this._handleUnauthorized();
                return;
            }

            if (response.ok) {
                let assistantMessageDiv = null;
                let fullResponse = "";

                const reader = response.body.getReader();
                const decoder = new TextDecoder();

                // Add empty message for assistant
                this.addMessageToChat('assistant', '', true);
                const messages = this.chatMessages.querySelectorAll('.message.assistant');
                assistantMessageDiv = messages[messages.length - 1].querySelector('.message-text');

                try {
                    let firstChunk = true;
                    while (true) {
                        const { value, done } = await reader.read();
                        if (done) break;

                        const chunk = decoder.decode(value, { stream: true });
                        fullResponse += chunk;

                        // Al primer chunk, canviem a streaming i iniciem stats
                        if (firstChunk) {
                            firstChunk = false;
                            this.setAiState('streaming');
                            this._startStreamStats();
                        }

                        // Comptar tokens (aprox 1 tok per 4 chars)
                        this._streamTokens += Math.ceil(chunk.length / 4);

                        assistantMessageDiv.textContent = fullResponse;
                        this.scrollToBottom();
                    }
                    // Streaming acabat — renderitzar Markdown
                    assistantMessageDiv.innerHTML = this.renderMarkdown(this.stripThinkTags(fullResponse));
                } catch (readError) {
                    if (readError.name === 'AbortError') {
                        assistantMessageDiv.innerHTML = this.renderMarkdown(fullResponse + '\n\n⏹️ *[Generació aturada]*');
                    } else {
                        throw readError;
                    }
                }

                if (!this.currentSessionId) {
                    this.loadSessions();
                }

            } else {
                this.setAiState('error');
                this.addMessageToChat('assistant', '❌ Error: No s\'ha pogut enviar el missatge.');
            }
        } catch (error) {
            if (error.name === 'AbortError') {
                console.log('Generation stopped by user');
            } else {
                console.error('Error sending message:', error);
                this.setAiState('error');
                this.addMessageToChat('assistant', '❌ Error de connexió.');
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

        const avatar = role === 'user' ? '👤' : '🤖';
        const roleName = role === 'user' ? 'Tu' : 'Nexe';

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
        this.filePreview.innerHTML = `<span class="upload-loading">📤 Pujant "${file.name}"...</span>`;
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
                <span class="uploaded-file-icon">📄</span>
                <span class="uploaded-file-name">${fileData.filename}</span>
                <span class="uploaded-file-size">(${sizeKB} KB)</span>
                <button class="uploaded-file-remove" onclick="nexeUI.removeFilePreview()">✕</button>
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
                <div class="welcome-icon">🤖</div>
                <h2>Benvingut a Nexe</h2>
                <p>IA local amb memòria persistent</p>
                <div class="features">
                    <div class="feature">
                        <span class="feature-icon">💬</span>
                        <span>Conversa amb memòria contextual</span>
                    </div>
                    <div class="feature">
                        <span class="feature-icon">📁</span>
                        <span>Puja documents (.txt, .md, .pdf)</span>
                    </div>
                    <div class="feature">
                        <span class="feature-icon">🔒</span>
                        <span>100% local i privat</span>
                    </div>
                </div>
            </div>
        `;
    }

    scrollToBottom() {
        setTimeout(() => {
            this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
        }, 100);
    }

    stripThinkTags(text) {
        return text.replace(/<think>[\s\S]*?<\/think>\s*/g, '').trim();
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
