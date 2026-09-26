/**
 * ============================================
 * Nexe UI — session list and history
 * ============================================
 * Split out of app.js (#127). Everything that owns the session list: creating, loading, deleting and rendering a conversation, plus the confirm dialog that guards a delete.
 *
 * Classic <script>, loaded AFTER app.js (the class must exist before its
 * prototype can be extended) and before DOMContentLoaded, which is when the
 * instance is built. Not an ES module: the cache-bust rewrites `.js"` in
 * index.html and never sees an `import` inside a .js file.
 *
 * Bodies are the ones that were in the class, unchanged.
 */
/* global NexeUI, confirm */
NexeUI.extend({
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
                this._setCurrentSession(data.session_id);
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
    },

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
    },

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
    },

    async deleteSession(sessionId) {
        if (!confirm(this.t('confirm_delete'))) return;

        try {
            const response = await this.fetchWithCsrf(`/ui/session/${sessionId}`, {
                method: 'DELETE'
            });

            if (response.ok) {
                // If we deleted the current session, clear the chat
                if (sessionId === this.currentSessionId) {
                    this._setCurrentSession(null);
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
    },

    /// Single writer for the active session id, mirrored to localStorage.
    ///
    /// The id used to live only in memory, so ANY page reload silently started
    /// a new conversation while the screen still showed the old bubbles: the
    /// next message opened a fresh backend session and everything before it —
    /// including what the user was reading — was orphaned on disk. In the
    /// desktop app the webview can be reloaded by the system (a memory-pressure
    /// kill of the web content process reloads the page), so this is not a
    /// hypothetical.
    _setCurrentSession(sessionId) {
        this.currentSessionId = sessionId || null;
        try {
            if (this.currentSessionId) {
                localStorage.setItem('nexe_session_id', this.currentSessionId);
            } else {
                localStorage.removeItem('nexe_session_id');
            }
        } catch { /* private mode / storage disabled: memory-only, as before */ }
    },

    /// Re-open the conversation the user was in, or fall back to the welcome
    /// screen if it no longer exists (deleted elsewhere, storage wiped).
    async _restoreLastSession() {
        let saved = null;
        try { saved = localStorage.getItem('nexe_session_id'); } catch { /* ignore */ }
        if (!saved) { this.showWelcome(); return; }
        const restored = await this.loadSession(saved);
        if (!restored) {
            this._setCurrentSession(null);
            this.showWelcome();
        }
    },

    async loadSession(sessionId) {
        this._abortIfGenerating();
        this._clearTruncState();  // FD-S6: a session switch kills any pending Continue
        try {
            // Bug #6 fix: use full session endpoint (not /history) to also receive attached_document
            const response = await this.fetchWithCsrf(`/ui/session/${sessionId}`);
            if (response.ok) {
                const data = await response.json();
                this._setCurrentSession(sessionId);
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
                return true;
            }
            return false;
        } catch (error) {
            console.error('Error loading session:', error);
            return false;
        }
    },

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
    },

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
                // C4.5: the server deletes THE entry this session has pending, by id;
                // `fact` is the text the dialog showed — the reference the confirmation names.
                this.fetchWithCsrf('/ui/memory/confirm-delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ fact, session_id: this.currentSessionId })
                }).then(r => r.json()).then(result => {
                    if ((result.deleted || 0) > 0) {
                        const facts = (result.deleted_facts || []).map(f => f.text || f).join(', ');
                        this.addMessageToChat('assistant', `${this.t('delete_done')}: "${facts}"`);
                    } else if (result.detail || result.message) {
                        // Nothing pending any more, or a profile entry B093 refused: say what the server said.
                        this.addMessageToChat('assistant', `↩️ ${result.detail || result.message}`);
                    }
                }).catch(() => {});
            } else {
                this.addMessageToChat('assistant', `↩️ ${this.t('delete_cancelled')}`);
            }
        };

        confirmBtn.addEventListener('click', () => close(true));
        cancelBtn.addEventListener('click', () => close(false));
        overlay.addEventListener('click', (e) => { if (e.target === overlay) close(false); });
    },

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
    },

    clearChat() {
        this.chatMessages.innerHTML = '';
    },
});
