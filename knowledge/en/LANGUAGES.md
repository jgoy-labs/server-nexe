# === METADATA RAG ===
versio: "1.0"
data: 2026-05-29
id: nexe-languages
collection: nexe_documentation

# === RAG CONTENT (REQUIRED) ===
abstract: "How server-nexe handles languages: it detects the language of each user message (about 75 languages, offline detection with lingua) and replies in that same language, not in the install language (NEXE_LANG). Explains the detection pipeline and the reply directive, the role of NEXE_LANG as a fallback, and the behaviour on short messages or language switches. Documents the fix for the bug where, up to 1.0.4, it always replied in the fixed install language (Catalan by default); automatic detection was added in 1.0.5."
tags: [languages, language, i18n, multilingual, detection, lingua, nexe-lang, multi-language]
chunk_size: 600
priority: P2

# === OPTIONAL ===
lang: en
type: docs
author: "Jordi Goy with AI collaboration"
expires: null
---

# Languages — server-nexe 1.0.6

## Which languages you can use with Nexe

You can write to Nexe in any of the world's main languages (about 75: Catalan, Spanish, English, French, German, Italian, Portuguese, Dutch, Russian, Chinese, Japanese, Arabic…). Nexe **detects the language of your message and replies in that same language**, with no configuration needed.

Response quality depends on the local model loaded: large models master more languages; small ones (4B) reply best in the most common languages.

## How it picks the language (pipeline)

For every message you send:

1. **Detection.** Nexe detects the language of your message with `lingua` (a detection library that works 100% offline, no connection). It is accurate even on short text and on close languages (Catalan, Spanish, Portuguese…). Before detecting, it strips code blocks and URLs so they don't skew the result.
2. **Prompt selection.** It picks the system prompt in your language (Catalan, Spanish or English); for any other language it uses English as the base.
3. **Reply directive.** It adds a clear instruction for the model to reply in the detected language. The instruction is reinforced at the end of the prompt, because small models follow the instruction closest to generation best.
4. **Reply.** The model generates the response in your language.

If the message is too short or ambiguous (for example "ok", "thanks") or is just code, Nexe keeps the configured language to avoid guessing wrong.

## The install language (NEXE_LANG)

`NEXE_LANG` is the installation's default language. It is only used as a **fallback** when detection is not reliable. It **does not limit** the language of replies: even if you install Nexe in Catalan, it will reply in English if you write to it in English.

## Notes

- **Switching language mid-conversation:** you can switch language anytime and Nexe adapts. Within a conversation already started in one language, the switch may be a bit harder (the conversation history weighs in); for a clean switch, start a new conversation.
- **Fix (1.0.5):** up to version 1.0.4, Nexe always replied in the fixed install language (Catalan by default) even when the user wrote in another language. This was **fixed in 1.0.5** with automatic detection of the message language.
