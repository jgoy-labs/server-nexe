/**
 * ============================================
 * Nexe UI — markdown rendering and HTML escaping
 * ============================================
 * Split out of app.js (#127). Pure text in, safe HTML out — no instance state beyond the language. This is the cluster with no ownership question, so it is the first candidate to become a real collaborator rather than a prototype extension.
 *
 * Classic <script>, loaded AFTER app.js (the class must exist before its
 * prototype can be extended) and before DOMContentLoaded, which is when the
 * instance is built. Not an ES module: the cache-bust rewrites `.js"` in
 * index.html and never sees an `import` inside a .js file.
 *
 * Bodies are the ones that were in the class, unchanged.
 */
/* global NexeUI */
NexeUI.extend({
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
            .replace(/\[GEN_TRUNCATED:\d\]/g, '')       // FD-S5 marker (belt-and-braces)
            .replace(/\[MEM_DELETE:[^\]]*\]/g, '')     // [MEM_DELETE: ...]
            .replace(/\[MEMORIA:[^\]]*\]/g, '')        // [MEMORIA: ...] gpt-oss alias
            .trimStart();                               // leading whitespace after strip

        // Use marked.js to render Markdown
        if (typeof marked !== 'undefined' && cleaned) {
            try {
                // Override raw HTML renderer to prevent XSS injection via HTML blocks
                const renderer = new marked.Renderer();
                const _escape = this.escapeHtml.bind(this);
                // WS5-02: escapeHtml() (textContent→innerHTML) does NOT escape quotes,
                // so it is unsafe inside an HTML attribute — a `"`/`'` in a poisoned
                // markdown title/href would break out of the attribute (XSS). Use
                // _escapeAttr for every attribute-context interpolation below.
                const _escapeAttr = this.escapeAttr.bind(this);
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
                    const title = (token && token.title) ? ` title="${_escapeAttr(token.title)}"` : '';
                    return `<a href="${_escapeAttr(href)}"${title} target="_blank" rel="noopener noreferrer">${text}</a>`;
                };
                renderer.image = function(token) {
                    const href = (token && typeof token === 'object') ? (token.href || '') : token;
                    const alt = _escapeAttr((token && token.text) || '');
                    if (!_isSafeHref(href)) return alt;
                    const title = (token && token.title) ? ` title="${_escapeAttr(token.title)}"` : '';
                    return `<img src="${_escapeAttr(href)}" alt="${alt}"${title}>`;
                };
                return marked.parse(cleaned, { breaks: true, gfm: true, renderer });
            } catch (e) {
                console.error('Markdown parsing error:', e);
                return this.escapeHtml(cleaned);
            }
        }
        return this.escapeHtml(cleaned);
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    // WS5-02: escapeHtml() encodes < > & (textContent→innerHTML) but NOT quotes,
    // which is unsafe when the result lands inside an HTML attribute. escapeAttr
    // additionally encodes " and ' so an attacker-controlled markdown title/href
    // cannot break out of the attribute and inject an event handler.
    escapeAttr(text) {
        return this.escapeHtml(text).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    },
});
