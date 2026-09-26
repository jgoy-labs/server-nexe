/**
 * ============================================
 * Nexe UI — the chat turn: send, stream, render, think
 * ============================================
 * Split out of app.js (#127). One user turn from the send button to the finished bubble, including the streaming state machine and the reasoning-block toggle. The biggest cluster by far, and the one whose state (isGenerating, abortController, currentSessionId) is still shared with the rest of the UI — which is why it stays a prototype extension until that ownership is decided.
 *
 * Classic <script>, loaded AFTER app.js (the class must exist before its
 * prototype can be extended) and before DOMContentLoaded, which is when the
 * instance is built. Not an ES module: the cache-bust rewrites `.js"` in
 * index.html and never sees an `import` inside a .js file.
 *
 * Bodies are the ones that were in the class, unchanged.
 */
/* global NexeUI, AbortController, TextDecoder */
NexeUI.extend({
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
    },

    _removeCompactNotice() {
        if (this._compactNotice) {
            this._compactNotice.remove();
            this._compactNotice = null;
        }
    },

    /** #127 follow-up: true iff a still-pending WILL_COMPACT signal belongs
     * to the session we are about to send to. _willCompactNextForSession
     * carries the id of the session the signal was actually FOR, not a bare
     * boolean — a bare flag survived switching to (or starting) a different
     * conversation and wrongly announced "compacting" on a brand-new chat
     * with nothing to compact. Consumes the flag either way, so a stale
     * signal from a different conversation never lingers into a third turn. */
    _consumePendingCompactNotice() {
        if (!this._willCompactNextForSession) return false;
        const forThisSession = this._willCompactNextForSession === this.currentSessionId;
        this._willCompactNextForSession = null;
        return forThisSession;
    },

    setAiState(state) {
        document.documentElement.setAttribute('data-ai-state', state);
        // The wait the notice announced is over the moment anything else happens —
        // tokens arriving, the turn finishing, or the turn failing.
        if (state !== 'thinking') {
            this._removeCompactNotice();
        }
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
    },

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
    },

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
    },

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
    },

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
    },

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
    },

    // Clean special model tags (GPT-OSS, etc.). Promoted out of sendMessage
    // (#127): pure, and a closure cannot be reached by tests/frontend/.
    _cleanModelTags(buf) {
        buf = buf.replace(/<\|[^|]+\|>/g, '');
        buf = buf.replace(/[◁◀][^▷▶]*[▷▶]/g, '');
        return buf;
    },

    // Parseja thinking/content post-streaming (DeepSeek, GPT-OSS, etc.).
    // Promoted out of sendMessage (#127) for the same reason.
    _parseThinkingChannels(text) {
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
    },

    // The streaming chunk state machine, lifted out of sendMessage (#127).
    // `st` is the machine's own state — the nine variables it mutates; `ctx`
    // is what it needs but never rebinds. They are separate on purpose: the
    // nine ARE the machine, and lumping them with the environment is what
    // made this unreadable as a closure.
    // The [MEM_SAVE: ...] tags a model emits, pulled out of a piece of text.
    // FOUR copies of this replace lived inside sendMessage (#127) — two in the
    // chunk machine, two in the final render — and they had to stay in
    // agreement, because the facts drive the memory badge while the stripped
    // text is what the user actually reads. Now there is one.
    // Duplicates are NOT removed here: the final-render caller de-duplicates
    // for the badge, the streaming callers deliberately keep every occurrence.
    _extractMemSave(text) {
        const facts = [];
        const stripped = text.replace(/\[MEM_SAVE:\s*(.+?)\]\s*/g, (_, f) => {
            facts.push(f);
            return '';
        });
        return { text: stripped, facts };
    },

    // What memory kept this turn, as the SERVER confirms it (#1098):
    // [MEM:n:fact1|fact2] (n = stored new), [MEM:n] from the continue path,
    // [MEM:0] = looked, kept nothing. `mem` is {saved, facts} so far; returns
    // it updated plus the chunk without the sentinel. The only way the badge
    // learns anything — a model's own [MEM_SAVE:] is a request, not a save.
    _readMemSentinel(chunk, mem) {
        let saved = mem.saved;
        let facts = mem.facts;
        const rest = chunk.replace(/\x00\[MEM:?(\d*)(?::(.*?))?\]\x00/g, (match, n, listed) => { // eslint-disable-line no-control-regex
            const kept = listed ? listed.split('|').filter(Boolean) : [];
            facts = [...new Set(facts.concat(kept))];
            saved = saved || kept.length > 0 || parseInt(n || '1', 10) > 0;
            return '';
        });
        return { chunk: rest, saved, facts, seen: rest !== chunk };
    },

    // Control tags that leak into the visible answer. The patterns do not
    // overlap, so order does not matter — but the SET does: anything missing
    // here reaches the user as literal [MODEL:...] noise in the message.
    _stripLeakedTags(text) {
        text = text.replace(/\[ACTION\]:\s*[^\n]*/g, '');
        text = text.replace(/\[MODEL:[^\]]+\]/g, '');
        text = text.replace(/\[MEM:\d+(?::[^\]]*)?\]/g, '');
        text = text.replace(/\[MEM\]/g, '');
        // Strip [DEL:N:...] tokens from final render
        text = text.replace(/\[DEL:\d+:.+?\]/g, '');
        return text;
    },

    _processChunk(st, ctx, raw) {
            st.tBuf += raw;
            while (st.tBuf.length > 0) {
                if (st.tMode === 'init') {
                    const s = st.tBuf.indexOf('<think>');
                    if (s >= 0) {
                        st.tMode = 'thinking';
                        st.tBuf = st.tBuf.slice(s + 7);
                        ctx.startThinkBlock();
                    } else if (!st.tGptOssChecked && st.fullResponse.length + st.tBuf.length >= 30) {
                        // Check for GPT-OSS "analysis...final" format
                        st.tGptOssChecked = true;
                        const combined = (st.fullResponse + st.tBuf).toLowerCase().trimStart();
                        if (combined.startsWith('analysis')) {
                            st.tIsGptOss = true;
                            st.tMode = 'thinking';
                            st.tContent = st.fullResponse + st.tBuf;
                            st.fullResponse = '';
                            st.tBuf = '';
                            ctx.startThinkBlock();
                            if (st.tTextEl) st.tTextEl.textContent = st.tContent.replace(/^analysis\s*/i, '');
                            st.tTok = Math.ceil(st.tContent.length / 4);
                            break;
                        } else {
                            // Not GPT-OSS — direct response
                            st.tMode = 'responding';
                            this.setAiState('streaming');
                            this._startStreamStats();
                        }
                    } else if (st.tGptOssChecked && st.tBuf.trimStart().length > 0 && !st.tBuf.trimStart().startsWith('<')) {
                        // First char is not a tag — direct response
                        st.tMode = 'responding';
                        this.setAiState('streaming');
                        this._startStreamStats();
                    } else if (st.tBuf.length > 7 && st.tGptOssChecked) {
                        // Large buffer without <think> — direct response
                        st.tMode = 'responding';
                        this.setAiState('streaming');
                        this._startStreamStats();
                    } else if (st.tBuf.trimStart().length > 0 && !st.tBuf.trimStart().startsWith('<') && st.tBuf.length < 30 && !st.tGptOssChecked) {
                        // Could be GPT-OSS — wait for more data
                        st.fullResponse += st.tBuf;
                        st.tBuf = '';
                        break;
                    } else {
                        break; // wait for more data
                    }
                } else if (st.tMode === 'thinking' && st.tIsGptOss) {
                    // GPT-OSS thinking mode: accumulate and look for end marker
                    st.tContent += st.tBuf;
                    st.tBuf = '';
                    const displayContent = st.tContent.replace(/^analysis\s*/i, '');
                    if (st.tTextEl) {
                        st.tTextEl.textContent = displayContent;
                        st.tTextEl.scrollTop = st.tTextEl.scrollHeight;
                    }
                    st.tTok = Math.ceil(st.tContent.length / 4);
                    const tokEl = st.tBlock?.querySelector('.think-tokens');
                    if (tokEl) tokEl.textContent = `~${st.tTok} tok`;
                    // Look for end marker: "assistantfinal" or standalone "final"
                    const endMatch = st.tContent.match(/(assistant\s*final|(?<!\w)final)(.*)$/is);
                    if (endMatch) {
                        const markerIdx = st.tContent.lastIndexOf(endMatch[1]);
                        let thinkText = st.tContent.substring(0, markerIdx).replace(/^analysis\s*/i, '').trim();
                        // Extract MEM_SAVE from thinking → move to st.fullResponse for badge
                        const _gpt = this._extractMemSave(thinkText);
                        const _memGpt = _gpt.facts;
                        thinkText = _gpt.text;
                        if (st.tTextEl) st.tTextEl.textContent = thinkText;
                        st.tTok = Math.ceil(thinkText.length / 4);
                        ctx.closeThinkBlock();
                        st.tMode = 'responding';
                        st.fullResponse = endMatch[2].trimStart();
                        // Inject MEM_SAVE AFTER st.fullResponse assignment (not before — it overwrites)
                        if (_memGpt.length > 0) {
                            st.fullResponse += '\n' + _memGpt.map(f => `[MEM_SAVE: ${f}]`).join('\n');
                        }
                        this.setAiState('streaming');
                        this._startStreamStats();
                        if (st.fullResponse) {
                            this._streamTokens += Math.ceil(st.fullResponse.length / 4);
                            this._scheduleRender(ctx.assistantMessageDiv, st.fullResponse);
                        }
                    }
                    break;
                } else if (st.tMode === 'thinking') {
                    const e = st.tBuf.indexOf('</think>');
                    if (e >= 0) {
                        st.tContent += st.tBuf.slice(0, e);
                        // Extract MEM_SAVE from thinking → move to st.fullResponse for badge
                        const _memInThink = [];
                        const _think = this._extractMemSave(st.tContent);
                        st.tContent = _think.text;
                        _memInThink.push(..._think.facts);
                        if (_memInThink.length > 0) {
                            st.fullResponse += _memInThink.map(f => `[MEM_SAVE: ${f}]`).join('\n') + '\n';
                        }
                        st.tTok += Math.ceil(st.tContent.length / 4);
                        if (st.tTextEl) st.tTextEl.textContent = st.tContent;
                        st.tBuf = st.tBuf.slice(e + 8).replace(/^\n+/, '');
                        st.tMode = 'responding';
                        ctx.closeThinkBlock();
                        this.setAiState('streaming');
                        this._startStreamStats();
                    } else {
                        // Keep possible partial tag at end
                        const partial = Math.min(8, st.tBuf.length);
                        let keepFrom = st.tBuf.length;
                        for (let i = partial; i > 0; i--) {
                            if ('</think>'.startsWith(st.tBuf.slice(-i))) { keepFrom = st.tBuf.length - i; break; }
                        }
                        st.tContent += st.tBuf.slice(0, keepFrom);
                        if (st.tTextEl) {
                            st.tTextEl.textContent = st.tContent;
                            st.tTextEl.scrollTop = st.tTextEl.scrollHeight;
                        }
                        st.tTok = Math.ceil(st.tContent.length / 4);
                        const tokEl = st.tBlock?.querySelector('.think-tokens');
                        if (tokEl) tokEl.textContent = `~${st.tTok} tok`;
                        st.tBuf = st.tBuf.slice(keepFrom);
                        break;
                    }
                } else { // responding
                    // Detect retroactive </think> (DeepSeek without opening <think>)
                    const closIdx = st.tBuf.indexOf('</think>');
                    if (closIdx >= 0 && !st.tContent) {
                        const thinkPart = st.fullResponse + st.tBuf.slice(0, closIdx);
                        if (thinkPart.trim().length > 10) {
                            st.tContent = thinkPart.trim();
                            st.tTok = Math.ceil(st.tContent.length / 4);
                            ctx.startThinkBlock();
                            if (st.tTextEl) st.tTextEl.textContent = st.tContent;
                            ctx.closeThinkBlock();
                            st.fullResponse = '';
                            this._streamTokens = 0;
                            st.tBuf = st.tBuf.slice(closIdx + 8).replace(/^\n+/, '');
                            continue;
                        }
                    }
                    // [MEM_SAVE: ...] tags pass through — stripped at final render (post-streaming)
                    st.tBuf = this._cleanModelTags(st.tBuf);
                    st.fullResponse += st.tBuf;
                    this._streamTokens += Math.ceil(st.tBuf.length / 4);
                    this._scheduleRender(ctx.assistantMessageDiv, st.fullResponse);
                    st.tBuf = '';
                }
            }
    },

    async sendMessage(continueState = null) {
        if (this.isGenerating) return;
        // FD-S6: continueState = {sessionId, raw, bubble, backend, model} —
        // resume the last truncated assistant turn instead of a new message.
        if (continueState && continueState.sessionId !== this.currentSessionId) return;
        const message = continueState ? '' : this.messageInput.value.trim();
        if (!continueState && !message) return;
        // A NEW message invalidates any pending Continue (stale button = no-op).
        this._clearTruncState();

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

        // #859: the previous turn told us THAT SESSION compacts first. That is
        // a full LLM summarisation before a single token of the answer (~100 s
        // on 8 GB), and until now it looked like the app had frozen. Say it up
        // front; the notice is removed as soon as the answer starts arriving.
        this._removeCompactNotice();
        if (this._consumePendingCompactNotice()) {
            const notice = document.createElement('div');
            notice.className = 'trunc-notice compact-notice';
            notice.textContent = this.t('compacting_notice');
            this.chatMessages.appendChild(notice);
            this._compactNotice = notice;
            this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
        }

        // Create AbortController for this request
        this.abortController = new AbortController();

        // Capture selected image before clearing VLM state
        const pendingImage = this._selectedImage ? { ...this._selectedImage } : null;
        this._clearSelectedImage();

        // Add user message to chat — if there is an attached image, show it inline
        if (!continueState) {
            const userImageUrl = pendingImage ? `data:${pendingImage.type};base64,${pendingImage.b64}` : null;
            this.addMessageToChat('user', message, true, null, userImageUrl);
            this.messageInput.value = '';
            this.messageInput.style.height = 'auto';
        }

        try {
            const ragSlider = document.getElementById('ragThresholdSlider');
            // F-D block 3: only override when the user has actually moved the
            // slider away from the default (persisted in localStorage across
            // reloads, same as before). Sending it unconditionally would mean
            // the backend's 3 tuned per-collection thresholds (the point of
            // this block) never apply in the UI — the slider always carries
            // a value even untouched.
            const RAG_DEFAULT_THRESHOLD = 0.35;
            const ragThreshold = ragSlider ? parseFloat(ragSlider.value) : null;
            const backendSel = document.getElementById('backendSelect');
            const modelSel = document.getElementById('modelSelect');
            // Collection toggles — build list of active collections
            const ragCollections = this._getActiveCollections();
            const chatBody = continueState ? {
                continue: true,
                session_id: continueState.sessionId,
                stream: true,
                backend: continueState.backend,
                model: continueState.model,
            } : {
                message: message,
                session_id: this.currentSessionId,
                stream: true,
                rag_threshold: (ragThreshold !== null && ragThreshold !== RAG_DEFAULT_THRESHOLD) ? ragThreshold : undefined,
                rag_collections: ragCollections.length < 3 ? ragCollections : undefined,
                backend: backendSel ? backendSel.value : undefined,
                model: modelSel ? modelSel.value : undefined,
                ...(pendingImage ? { image_b64: pendingImage.b64, image_type: pendingImage.type } : {})
            };
            let response = await this.fetchWithCsrf('/ui/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(chatBody),
                signal: this.abortController.signal
            });

            if (response.status === 401) {
                this._handleUnauthorized();
                return;
            }

            // C2.3 (ADR-007 §9/I9): this session is open elsewhere — never a
            // silent race between two writers. Ask, and only on "yes" resend
            // once with force_lease: true (an explicit takeover, never
            // automatic). A "no" leaves the turn unsent, exactly as if the
            // user had not pressed send.
            if (response.status === 409) {
                let detail = null;
                try { detail = (await response.json()).detail; } catch { /* non-JSON error body */ }
                if (detail && detail.code === 'session_leased' && detail.lease) {
                    const since = new Date(detail.lease.since);
                    const timeStr = isNaN(since) ? detail.lease.since : since.toLocaleTimeString();
                    const msg = this.t('session_leased_confirm')
                        .replace('{where}', detail.lease.where || '?')
                        .replace('{time}', timeStr);
                    if (window.confirm(msg)) {
                        response = await this.fetchWithCsrf('/ui/chat', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ ...chatBody, force_lease: true }),
                            signal: this.abortController.signal
                        });
                    } else {
                        this.setAiState('idle');
                        return;
                    }
                }
            }

            if (response.ok) {
                // Adopt the session the server actually stored this turn in.
                // It is normally the one we sent, but if our id was lost or the
                // server minted one for us, this is the only way to learn it —
                // without it the next message opens yet another conversation.
                const servedSession = response.headers.get('X-Session-Id');
                if (servedSession && servedSession !== this.currentSessionId) {
                    this._setCurrentSession(servedSession);
                    this.loadSessions();
                }
                // The session THIS turn's stream belongs to — used below to
                // scope [WILL_COMPACT:1] to the right conversation (#127
                // follow-up). Not this.currentSessionId at read-time: that
                // would drift if the user switches chats while this stream
                // is still arriving.
                const turnSessionId = servedSession || this.currentSessionId;
                let assistantMessageDiv = null;
                let memorySaved = false;
                // #1098: the facts the SERVER says memory kept ([MEM:n:f1|f2]).
                // The model's own [MEM_SAVE:] text is a request, never this.
                let memFacts = [];
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

                // Think state machine. One object, not nine `let`s: these nine ARE
                // the machine, and _processChunk mutates every one of them. As
                // closure variables they could not be handed to a method, and that
                // is the only reason the machine lived inside sendMessage (#127).
                // Declared BEFORE the Continue seed: slice 2 assigned
                // `st.fullResponse` above this `const` (TDZ ReferenceError on
                // Continue with the bubble still in the DOM).
                const st = {
                    tMode: 'init',          // 'init' | 'thinking' | 'responding'
                    tBuf: '',               // partial tag buffer
                    tContent: '',           // accumulated think text
                    tTok: 0,                // think token count
                    tBlock: null,           // .think-block DOM element
                    tTextEl: null,          // .think-text inside block
                    tGptOssChecked: false,  // GPT-OSS format detection done?
                    tIsGptOss: false,       // GPT-OSS thinking mode active?
                    fullResponse: '',       // seeded just below for the continue case
                };

                // Add empty message for assistant — or, on Continue, resume
                // INSIDE the same bubble: st.fullResponse is seeded with the raw
                // first half so every re-render paints the full markdown
                // across the seam (a code block split by the cut renders whole).
                let lastMsg;
                if (continueState && continueState.bubble && continueState.bubble.isConnected) {
                    lastMsg = continueState.bubble;
                    st.fullResponse = continueState.raw || '';
                } else {
                    this.addMessageToChat('assistant', '', true);
                    const messages = this.chatMessages.querySelectorAll('.message.assistant');
                    lastMsg = messages[messages.length - 1];
                }
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

                // Check if thinking blocks should be shown (toggle checked)
                const _thinkToggle = document.getElementById('thinkingToggle');
                const _showThinking = _thinkToggle && _thinkToggle.checked;

                const startThinkBlock = () => {
                    // If thinking toggle is OFF, don't create DOM — still parse tags to strip from output
                    if (!_showThinking) {
                        st.tBlock = null;
                        st.tTextEl = null;
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
                    st.tBlock = lastMsg.querySelector('.think-block');
                    st.tTextEl = st.tBlock.querySelector('.think-text');
                    if (typeof lucide !== 'undefined') lucide.createIcons({ nodes: [st.tBlock.querySelector('.think-header')] });
                };

                const closeThinkBlock = () => {
                    if (!st.tBlock) return;
                    st.tBlock.querySelector('.think-label').textContent = this.t('reasoning');
                    st.tBlock.querySelector('.think-tokens').textContent = `~${st.tTok} tok`;
                    st.tBlock.removeAttribute('open'); // auto-collapse
                };

                // What the machine needs but never rebinds. assistantMessageDiv is
                // assigned once, above, and the two think-block closures write into
                // `st` — so a snapshot here is the whole environment.
                const ctx = { assistantMessageDiv, startThinkBlock, closeThinkBlock };


                // A sentinel cut between two reads would leak as text and never
                // match: hold an unclosed \x00[ tail until the next read.
                let sentinelCarry = '';
                try {
                    while (true) {
                        const { value, done } = await reader.read();
                        if (done) break;

                        let chunk = sentinelCarry + decoder.decode(value, { stream: true });
                        sentinelCarry = '';
                        const openAt = chunk.lastIndexOf('\x00[');
                        if (openAt !== -1 && chunk.indexOf(']\x00', openAt) === -1) {
                            sentinelCarry = chunk.slice(openAt);
                            chunk = chunk.slice(0, openAt);
                        }

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

                        // #859: the server tells us this session will be compacted
                        // before the NEXT turn generates anything. Compaction is a
                        // full summarisation inside the critical path (~100 s on
                        // 8 GB) and it runs before that response has headers, so
                        // this is the last chance to warn: remember it and say it
                        // when the user sends, not when the wait is already over.
                        if (chunk.match(/\x00\[WILL_COMPACT:1\]\x00/)) { // eslint-disable-line no-control-regex
                            chunk = chunk.replace(/\x00\[WILL_COMPACT:1\]\x00/g, ''); // eslint-disable-line no-control-regex
                            this._willCompactNextForSession = turnSessionId;
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

                        // FD-S5: generation cut by the max_tokens ceiling.
                        // GEN_TRUNCATED:1 = resumable (FD-S6 wires the Continue
                        // button to this flag); :0 = informative only.
                        const genTruncMatch = chunk.match(/\x00\[GEN_TRUNCATED:(\d)\]\x00/); // eslint-disable-line no-control-regex
                        if (genTruncMatch) {
                            chunk = chunk.replace(/\x00\[GEN_TRUNCATED:\d\]\x00/, ''); // eslint-disable-line no-control-regex
                            const genNotice = document.createElement('div');
                            genNotice.className = 'trunc-notice';
                            genNotice.textContent = this.t('gen_truncated');
                            lastMsg.querySelector('.message-content').insertBefore(genNotice, assistantMessageDiv);
                            this._genTruncContinuable = genTruncMatch[1] === '1';
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
                        // What memory kept this turn, as the server confirms it (#1098).
                        const memRead = this._readMemSentinel(chunk, { saved: memorySaved, facts: memFacts });
                        if (memRead.seen) {
                            ({ saved: memorySaved, facts: memFacts, chunk } = memRead);
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

                        this._processChunk(st, ctx, chunk);
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
                    if (st.tMode !== 'thinking' && !st.tContent) {
                        const parsed = this._parseThinkingChannels(st.fullResponse);
                        if (parsed.thinking) {
                            // Show thinking block retroactively
                            startThinkBlock();
                            // Extract MEM_SAVE from thinking → move to content for badge
                            const _retro = this._extractMemSave(parsed.thinking);
                            const _cleanThink = _retro.text;
                            const _memRetro = _retro.facts;
                            if (st.tTextEl) st.tTextEl.textContent = _cleanThink;
                            const tokEl = st.tBlock?.querySelector('.think-tokens');
                            if (tokEl) tokEl.textContent = `~${Math.ceil(_cleanThink.length / 4)} tok`;
                            closeThinkBlock();
                            st.fullResponse = parsed.content + (_memRetro.length > 0 ? '\n' + _memRetro.map(f => `[MEM_SAVE: ${f}]`).join('\n') : '');
                        } else {
                            st.fullResponse = this._cleanModelTags(st.fullResponse);
                        }
                    }
                    // Strip the model's [MEM_SAVE: ...] from the final render. Only
                    // strip: whether anything was SAVED is the server's word
                    // (memFacts, from [MEM:n:...]) — #1098, the badge used to
                    // say "saved" for tags the server had refused.
                    const _main = this._extractMemSave(st.fullResponse);
                    st.fullResponse = _main.text;
                    if (_main.facts.length > 0) {
                        // Clean up orphaned MEM_SAVE remnants (intro lines ending in ":", lone dots)
                        st.fullResponse = st.fullResponse.replace(/\n[^\n]*:\s*\n\s*\.\s*\n/g, '\n');
                        st.fullResponse = st.fullResponse.replace(/\n\s*\.\s*\n/g, '\n');
                        st.fullResponse = st.fullResponse.replace(/\n{3,}/g, '\n\n');
                    }
                    // An answer that was only tags: the backend re-prompts (#856).
                    // No "✅ facts" stand-in here any more — it claimed a save
                    // the server had not confirmed (#1098).
                    if (!st.fullResponse.trim() && _main.facts.length > 0) {
                        console.info('[nexe] Empty response after MEM_SAVE — backend should have re-prompted.');
                    }
                    // Strip model tags that leak into visible text
                    st.fullResponse = this._stripLeakedTags(st.fullResponse);
                    // Note: renderMarkdown escapes HTML + attributes via a custom marked.js renderer (no raw HTML)
                    // Guard: if for some reason _scheduleRender was never entered,
                    // clean the placeholder class here (not visible but we remove it).
                    if (assistantMessageDiv.classList.contains('thinking-placeholder')) {
                        assistantMessageDiv.classList.remove('thinking-placeholder');
                    }
                    // FD-S5 fallback (live-verified 2026-07-23 on the 8 GB smoke):
                    // TCP does not honour the backend's yield boundaries — the
                    // marker can arrive SPLIT across two reads, the per-chunk
                    // regex misses it, and the render strip silently eats the
                    // pieces (no notice, no residue). st.fullResponse accumulates
                    // the stream verbatim, so the marker always ends up whole
                    // here: catch it at end-of-stream and strip it from the text.
                    {
                        const lateTrunc = st.fullResponse.match(/\x00?\[GEN_TRUNCATED:(\d)\]\x00?/); // eslint-disable-line no-control-regex
                        if (lateTrunc) {
                            st.fullResponse = st.fullResponse.replace(/\x00?\[GEN_TRUNCATED:\d\]\x00?/g, ''); // eslint-disable-line no-control-regex
                            if (!lastMsg.querySelector('.trunc-notice')) {
                                const genNotice = document.createElement('div');
                                genNotice.className = 'trunc-notice';
                                genNotice.textContent = this.t('gen_truncated');
                                lastMsg.querySelector('.message-content').insertBefore(genNotice, assistantMessageDiv);
                            }
                            this._genTruncContinuable = lateTrunc[1] === '1';
                        }
                    }
                    assistantMessageDiv.innerHTML = this.renderMarkdown(st.fullResponse);
                    if (st.tMode !== 'responding' && st.tMode !== 'init') closeThinkBlock();
                    // FD-S6: the stream ended cut-by-ceiling and resumable —
                    // offer Continue. OUTSIDE the stats block (a cut inside
                    // think yields 0 visible tokens and stats never render).
                    if (this._genTruncContinuable) {
                        this._genTruncContinuable = false;
                        const backendSel2 = document.getElementById('backendSelect');
                        const modelSel2 = document.getElementById('modelSelect');
                        this._truncState = {
                            sessionId: this.currentSessionId,
                            raw: st.fullResponse,
                            bubble: lastMsg,
                            backend: backendSel2 ? backendSel2.value : undefined,
                            model: modelSel2 ? modelSel2.value : undefined,
                        };
                        const contBtn = document.createElement('button');
                        contBtn.className = 'continue-btn';
                        contBtn.textContent = this.t('continue_btn');
                        contBtn.addEventListener('click', () => {
                            const st = this._truncState;
                            this._clearTruncState();
                            if (st && !this.isGenerating) this.sendMessage(st);
                        });
                        const notice = lastMsg.querySelector('.trunc-notice:last-of-type');
                        (notice || lastMsg.querySelector('.message-content')).appendChild(contBtn);
                    }
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
                        if (st.tMode === 'thinking') closeThinkBlock();
                        assistantMessageDiv.innerHTML = this.renderMarkdown(st.fullResponse + `\n\n*[${this.t('generation_stopped')}]*`);
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
    },

    stopGeneration() {
        if (this.abortController && this.isGenerating) {
            this.abortController.abort();
        }
    },

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
                textDiv.innerHTML = this.renderMarkdown(content); // renderMarkdown escapes HTML + attributes (custom renderer, no raw HTML)
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
    },

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
    },

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
            el.innerHTML = _rendered;  // renderMarkdown escapes HTML blocks + attribute values (custom renderer, no raw HTML)
        }, 80);
    },

    // FD-S6: drop any pending Continue affordance (new message, session
    // change, or the button itself was used). Removes stale buttons so a
    // click can never resume against the wrong context.
    _clearTruncState() {
        this._truncState = null;
        this._genTruncContinuable = false;
        document.querySelectorAll('.continue-btn').forEach((b) => b.remove());
    },
});
