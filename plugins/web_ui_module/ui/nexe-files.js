/**
 * ============================================
 * Nexe UI — uploads, drag-and-drop and RAG collections
 * ============================================
 * Split out of app.js (#127). Documents and images the user attaches, and the collection toggles that decide what the RAG search will see.
 *
 * Classic <script>, loaded AFTER app.js (the class must exist before its
 * prototype can be extended) and before DOMContentLoaded, which is when the
 * instance is built. Not an ES module: the cache-bust rewrites `.js"` in
 * index.html and never sees an `import` inside a .js file.
 *
 * Bodies are the ones that were in the class, unchanged.
 */
/* global NexeUI, alert, FileReader */

// The RAG collections the toggles map to. They moved here with app.js's
// split (#127): nothing outside this cluster reads them any more, and a
// top-level const in a classic script is visible to the scripts that follow.
const NEXE_COLL_MAP = { colMemory: 'personal_memory', colKnowledge: 'user_knowledge', colDocs: 'nexe_documentation' };
const NEXE_ALL_COLLECTIONS = Object.values(NEXE_COLL_MAP);

NexeUI.extend({
    _initCollectionToggles() {
        const saved = localStorage.getItem('nexe_collections');
        if (saved) {
            try {
                const disabled = JSON.parse(saved);
                for (const [id, coll] of Object.entries(NEXE_COLL_MAP)) {
                    const cb = document.getElementById(id);
                    if (cb) cb.checked = !disabled.includes(coll);
                }
            } catch { /* ignore corrupt localStorage */ }
        }
        for (const id of Object.keys(NEXE_COLL_MAP)) {
            const cb = document.getElementById(id);
            if (cb) cb.addEventListener('change', () => {
                this._saveCollectionState();
                this._updateCollectionWarning();
            });
        }
        this._updateCollectionWarning();
    },

    _saveCollectionState() {
        const disabled = [];
        for (const [id, coll] of Object.entries(NEXE_COLL_MAP)) {
            const cb = document.getElementById(id);
            if (cb && !cb.checked) disabled.push(coll);
        }
        localStorage.setItem('nexe_collections', JSON.stringify(disabled));
    },

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
        const disabled = NEXE_ALL_COLLECTIONS.filter(c => !active.includes(c));
        if (disabled.length === 0) {
            warn.style.display = 'none';
            warn.textContent = '';
        } else {
            const names = disabled.map(c => COLL_LABELS[c] || c).join(', ');
            warn.style.display = 'block';
            warn.textContent = this.t('col_warning_prefix') + names + this.t('col_warning_suffix');
        }
    },

    _getActiveCollections() {
        const saved = localStorage.getItem('nexe_collections');
        if (!saved) return NEXE_ALL_COLLECTIONS;
        try {
            const disabled = JSON.parse(saved);
            return NEXE_ALL_COLLECTIONS.filter(c => !disabled.includes(c));
        } catch { return NEXE_ALL_COLLECTIONS; }
    },

    _clearFilePreviewLocal() {
        // Same UI cleanup as removeFilePreview() but WITHOUT the destructive
        // POST /clear-document call. Used when switching sessions so we don't
        // wipe the backend attachment of the session we're leaving.
        if (this.filePreview) {
            this.filePreview.replaceChildren();
            this.filePreview.classList.remove('active');
        }
        if (this._docCard) this._docCard.remove();
        this._docCard = null;
        this.uploadedFile = null;
    },

    async _handleImageSelect(event) {
        const file = event.target.files?.[0];
        if (!file) return;
        await this._attachImageFile(file);
        if (this.imageInput) this.imageInput.value = '';
    },

    async _attachImageFile(file) {
        const allowed = ['image/jpeg', 'image/png', 'image/webp'];
        if (!allowed.includes(file.type)) {
            // #1128: an iPhone photo (HEIC) lands here; say what to do with it.
            alert(this.t('image_unsupported'));
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
    },

    _clearSelectedImage() {
        this._selectedImage = null;
        if (this.imageInput) this.imageInput.value = '';
        if (this.imagePreviewBar) this.imagePreviewBar.style.display = 'none';
        if (this.imagePreviewThumb) this.imagePreviewThumb.src = '';
        if (this.imageBadge) this.imageBadge.style.display = 'none';
    },

    async handleFileUpload(event) {
        const file = event.target.files?.[0] || event;
        if (!file || !file.name) return;

        // If it's an image, redirect to VLM flow instead of document RAG.
        // HEIC/HEIF too (#1128): the image flow refuses it with what to do
        // instead; as a document it only failed the upload.
        const IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'];
        const IMAGE_EXTS = ['.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif'];
        const _ext = '.' + (file.name.split('.').pop() || '').toLowerCase();
        if (IMAGE_TYPES.includes(file.type) || IMAGE_EXTS.includes(_ext)) {
            await this._attachImageFile(file);
            this.fileInput.value = '';
            return;
        }

        await this.uploadFile(file);
        this.fileInput.value = '';
    },

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
                    this._setCurrentSession(data.session_id);
                    this.loadSessions();
                }

                // Bug #17: specific prompt for images vs documents
                const isImage = /\.(jpe?g|png|gif|webp|heic|heif|bmp|tiff?)$/i.test(data.filename || file.name || '');

                // Show image inline in the chat (user bubble) if it's a photo
                if (isImage) {
                    const previewUrl = URL.createObjectURL(file);
                    this.addMessageToChat('user', '', true, null, previewUrl);
                }

                const elapsed = Math.round((Date.now() - t0) / 1000);
                const chunks = data.chunks_saved ? `${data.chunks_saved} ${this.t('doc_fragments')} · ` : '';
                this.addUploadedFile(data, `${chunks}${elapsed}s`);
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
    },

    addUploadedFile(fileData, detail = '') {
        // #1126: the document goes into the conversation. Over the box the user
        // types in, it read as something still waiting to be sent.
        if (this._docCard) this._docCard.remove();
        const sizeKB = (fileData.size / 1024).toFixed(1);
        const card = document.createElement('div');
        card.className = 'doc-card';
        card.innerHTML = `
            <span class="uploaded-file-icon"><i data-lucide="file-text"></i></span>
            <div class="doc-card-body">
                <div>
                    <span class="uploaded-file-name">${this.escapeHtml(fileData.filename)}</span>
                    <span class="uploaded-file-size">(${sizeKB} KB${detail ? ' · ' + this.escapeHtml(detail) : ''})</span>
                </div>
                <div class="uploaded-file-notice">${this.t('doc_in_chat')}</div>
            </div>
            <button class="uploaded-file-remove" title="${this.t('doc_remove')}" onclick="nexeUI.removeFilePreview()">✕</button>
        `;
        this.chatMessages.appendChild(card);
        this._docCard = card;
        if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [card] });
        this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
    },

    removeFilePreview() {
        if (this._docCard) this._docCard.remove();
        this._docCard = null;
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
    },

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
    },
});
