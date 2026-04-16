#!/usr/bin/env python3
"""Generate server-nexe white paper PDF for Desktop."""

from pathlib import Path
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
    HRFlowable, KeepTogether,
)

OUTPUT_PATH = Path.home() / "Desktop" / "server-nexe_white-paper.pdf"
TODAY = date.today().isoformat()
VERSION = "0.9.7"

W, H = A4
ACCENT = colors.HexColor("#1a73e8")
DARK = colors.HexColor("#1a1a2e")
LIGHT_BG = colors.HexColor("#f8f9ff")
MID_GRAY = colors.HexColor("#555566")
LIGHT_GRAY = colors.HexColor("#e8eaf0")
CODE_BG = colors.HexColor("#f4f4f8")
WHITE = colors.white


def styles():
    s = getSampleStyleSheet()

    def add(name, **kw):
        s.add(ParagraphStyle(name, **kw))

    add("Cover_Title",
        fontName="Helvetica-Bold", fontSize=32, textColor=WHITE,
        leading=40, alignment=TA_CENTER, spaceAfter=0.3*cm)
    add("Cover_Subtitle",
        fontName="Helvetica", fontSize=14, textColor=colors.HexColor("#c8d8ff"),
        leading=20, alignment=TA_CENTER, spaceAfter=0.2*cm)
    add("Cover_Meta",
        fontName="Helvetica", fontSize=10, textColor=colors.HexColor("#99aacc"),
        leading=15, alignment=TA_CENTER, spaceAfter=0.15*cm)
    add("H1",
        fontName="Helvetica-Bold", fontSize=18, textColor=DARK,
        leading=24, spaceBefore=0.8*cm, spaceAfter=0.3*cm)
    add("H2",
        fontName="Helvetica-Bold", fontSize=13, textColor=ACCENT,
        leading=18, spaceBefore=0.6*cm, spaceAfter=0.2*cm)
    add("H3",
        fontName="Helvetica-Bold", fontSize=11, textColor=DARK,
        leading=15, spaceBefore=0.4*cm, spaceAfter=0.15*cm)
    add("Body",
        fontName="Helvetica", fontSize=10, textColor=colors.HexColor("#222233"),
        leading=15, alignment=TA_JUSTIFY, spaceAfter=0.2*cm)
    add("BulletItem",
        fontName="Helvetica", fontSize=10, textColor=colors.HexColor("#222233"),
        leading=15, leftIndent=0.8*cm, bulletIndent=0.2*cm, spaceAfter=0.1*cm)
    add("CodeBlock",
        fontName="Courier", fontSize=8.5, textColor=colors.HexColor("#1a1a2e"),
        leading=13, leftIndent=0.5*cm, spaceBefore=0.1*cm, spaceAfter=0.1*cm,
        backColor=CODE_BG)
    add("Caption",
        fontName="Helvetica-Oblique", fontSize=8.5, textColor=MID_GRAY,
        leading=12, alignment=TA_CENTER, spaceAfter=0.3*cm)
    add("Footer",
        fontName="Helvetica", fontSize=8, textColor=MID_GRAY,
        leading=11, alignment=TA_CENTER)
    add("Callout",
        fontName="Helvetica", fontSize=10, textColor=DARK,
        leading=15, leftIndent=0.5*cm, rightIndent=0.5*cm,
        backColor=LIGHT_BG, borderColor=ACCENT, borderWidth=1,
        borderPadding=8, spaceAfter=0.3*cm)

    return s


def hr(color=LIGHT_GRAY):
    return HRFlowable(width="100%", thickness=1, color=color, spaceAfter=0.2*cm)


def bullet(text, st):
    return Paragraph(f"• &nbsp; {text}", st["BulletItem"])


def table(data, col_widths, header_row=True):
    t = Table(data, colWidths=col_widths)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), DARK),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [WHITE, LIGHT_BG]),
        ("GRID", (0, 0), (-1, -1), 0.5, LIGHT_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]
    if header_row:
        style += [
            ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ]
    t.setStyle(TableStyle(style))
    return t


def cover_page(st):
    """Build cover page as a full-bleed colored block using a table."""
    cover_content = [
        Spacer(1, 2.5*cm),
        Paragraph("server-nexe", st["Cover_Title"]),
        Paragraph("Local AI Server with Persistent Memory", st["Cover_Subtitle"]),
        Spacer(1, 0.5*cm),
        Paragraph(f"Version {VERSION} — White Paper", st["Cover_Meta"]),
        Paragraph(f"Date: {TODAY}", st["Cover_Meta"]),
        Spacer(1, 1.5*cm),
        Paragraph(
            "A privacy-first, fully local AI inference server with RAG memory,<br/>"
            "multi-backend support, and a modular plugin architecture.",
            st["Cover_Subtitle"],
        ),
        Spacer(1, 2*cm),
        Paragraph("Jordi Goy · Barcelona · Apache 2.0", st["Cover_Meta"]),
        Paragraph("server-nexe.org · server-nexe.com", st["Cover_Meta"]),
        PageBreak(),
    ]
    return cover_content


def build(output: Path):
    doc = SimpleDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=2*cm,
        rightMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm,
        title="server-nexe White Paper",
        author="Jordi Goy",
        subject="Local AI Server with Persistent Memory",
    )

    st = styles()
    story = []

    # --- COVER ---
    story += cover_page(st)

    # --- TABLE OF CONTENTS (manual) ---
    story.append(Paragraph("Contents", st["H1"]))
    toc_items = [
        "1. Executive Summary",
        "2. What is server-nexe",
        "3. Core Features",
        "4. Architecture",
        "5. Technology Stack",
        "6. Recommended Models",
        "7. Installation",
        "8. API & Integration",
        "9. Security",
        "10. Limitations & Roadmap",
    ]
    for item in toc_items:
        story.append(bullet(item, st))
    story.append(PageBreak())

    # --- 1. EXECUTIVE SUMMARY ---
    story.append(Paragraph("1. Executive Summary", st["H1"]))
    story.append(hr())
    story.append(Paragraph(
        "server-nexe is a fully local AI inference server built on FastAPI and Qdrant. "
        "It runs entirely on the user's device — no cloud calls, no telemetry, no external API keys. "
        "Conversations, documents, and embeddings never leave the machine.",
        st["Body"],
    ))
    story.append(Paragraph(
        "Its design philosophy is privacy by architecture: memory is local, inference is local, "
        "and the OpenAI-compatible API makes it a drop-in replacement for cloud LLM services in "
        "tools like Cursor, Continue, or Zed.",
        st["Body"],
    ))
    story.append(Paragraph(
        "Key differentiators:",
        st["Body"],
    ))
    for item in [
        "<b>Persistent RAG memory</b> — context survives across sessions using Qdrant vector search",
        "<b>Automatic memory extraction</b> (MEM_SAVE) — facts saved with zero extra latency",
        "<b>Multi-backend</b> — MLX (Apple Silicon), llama.cpp (GGUF), Ollama — same API",
        "<b>Modular plugin system</b> — security, UI, backends are independent plugins",
        "<b>Full i18n</b> — Catalan, Spanish, English across UI, CLI, system prompts",
        "<b>Encryption at rest</b> — AES-256-GCM, SQLCipher, default auto",
    ]:
        story.append(bullet(item, st))

    # --- 2. WHAT IS SERVER-NEXE ---
    story.append(Paragraph("2. What is server-nexe", st["H1"]))
    story.append(hr())
    story.append(Paragraph(
        "server-nexe is designed for users who want the power of large language models "
        "without surrendering their data to third-party servers. It targets developers, "
        "researchers, and privacy-conscious professionals who need a persistent AI assistant "
        "that learns from conversations and documents over time.",
        st["Body"],
    ))

    story.append(Paragraph("Disambiguation", st["H2"]))
    story.append(Paragraph(
        "server-nexe is <i>not</i> npm-nexe (a Node.js compiler), "
        "not a Windows server product, and not a replacement for Ollama — "
        "it can use Ollama as one of several backends.",
        st["Body"],
    ))

    story.append(Paragraph("Origin", st["H2"]))
    story.append(Paragraph(
        "Started as a learning-by-doing project, server-nexe evolved through multiple "
        "refactors into a minimal, agnostic, modular core. The goal: security and memory "
        "solved at the base layer, so building on top is fast. "
        "Developed in human-AI collaboration.",
        st["Body"],
    ))

    # --- 3. CORE FEATURES ---
    story.append(Paragraph("3. Core Features", st["H1"]))
    story.append(hr())

    features = [
        ("100 % Local & Private",
         "All inference, memory and storage happen on-device. Zero cloud dependency. "
         "Conversations and documents never leave the machine."),
        ("Persistent RAG Memory",
         "Remembers context across sessions using Qdrant vector search with 768-dimensional "
         "embeddings. Three collections: nexe_documentation (system docs), "
         "user_knowledge (uploaded documents), personal_memory (conversation facts)."),
        ("Automatic Memory (MEM_SAVE)",
         "The model extracts facts from conversations and saves them automatically — "
         "name, job, preferences. Zero extra latency (same LLM call). "
         "Supports save, delete, and recall intents in 3 languages."),
        ("Multi-Backend Inference",
         "MLX (Apple Silicon native, fastest on M-series), llama.cpp (GGUF, universal "
         "with Metal acceleration), Ollama (managed models, easiest setup). "
         "Same OpenAI-compatible API regardless of backend. Auto-fallback if a backend goes down."),
        ("Web UI",
         "Vanilla JS interface with real-time streaming, RAG weight visualization, "
         "collapsible sidebar, session management, dark/light mode, document upload, "
         "and model size indicators."),
        ("Document Upload",
         "Upload .pdf, .txt, .md via the Web UI. Indexed into Qdrant with session isolation — "
         "documents are only visible within the uploading session."),
        ("Modular Plugin System",
         "Security, web UI, RAG, each backend — all are independent plugins with manifests. "
         "Auto-discovered at startup. Adding a new backend = writing a new plugin."),
        ("Multilingual (ca/es/en)",
         "Full i18n across UI, system prompts, RAG context labels, error messages, and installer. "
         "Language selector in the footer. Server is source of truth."),
        ("Encryption at Rest",
         "AES-256-GCM encryption for SQLite (SQLCipher), chat sessions (.enc), "
         "and RAG document text (TextStore). Activates automatically if sqlcipher3 is available."),
        ("macOS Tray App",
         "Menu bar icon with server start/stop, Web UI shortcut, real-time RAM and uptime, "
         "log viewer. Auto-starts at login when installed via DMG."),
    ]

    for title, desc in features:
        story.append(KeepTogether([
            Paragraph(title, st["H3"]),
            Paragraph(desc, st["Body"]),
        ]))

    # --- 4. ARCHITECTURE ---
    story.append(PageBreak())
    story.append(Paragraph("4. Architecture", st["H1"]))
    story.append(hr())

    story.append(Paragraph("Project Structure", st["H2"]))
    arch_lines = [
        "server-nexe/",
        "├── core/                  # FastAPI server, endpoints, CLI, crypto",
        "│   ├── endpoints/         # REST API (chat split into 8 submodules)",
        "│   ├── crypto/            # Encryption at rest (AES-256-GCM, SQLCipher)",
        "│   ├── cli/               # CLI commands (chat, memory, knowledge…)",
        "│   ├── server/            # Factory pattern, lifespan management",
        "│   └── ingest/            # Document ingestion pipeline",
        "├── plugins/               # Modular plugin system",
        "│   ├── mlx_module/        # Apple Silicon MLX backend",
        "│   ├── llama_cpp_module/  # GGUF universal backend",
        "│   ├── ollama_module/     # Ollama bridge + auto-start",
        "│   ├── security/          # Auth, rate limiting, injection detection",
        "│   └── web_ui_module/     # Web interface + session management",
        "├── memory/                # RAG system (Qdrant + embeddings + TextStore)",
        "├── knowledge/             # Documentation for RAG ingestion (ca/es/en)",
        "├── personality/           # System prompts, i18n, server.toml",
        "├── installer/             # SwiftUI DMG wizard + headless installer",
        "├── storage/               # Runtime data (models, logs, vectors)",
        "└── tests/                 # Test suite (4770 test functions)",
    ]
    for line in arch_lines:
        story.append(Paragraph(line.replace(" ", "&nbsp;"), st["CodeBlock"]))

    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph("Data Flow", st["H2"]))
    flow_lines = [
        "User → CLI / API / Web UI",
        "    → Auth (X-API-Key)  → Rate Limit  → Validate Input",
        "    → RAG context retrieval (Qdrant similarity search)",
        "    → System prompt assembly (i18n + memory context)",
        "    → LLM inference (MLX / llama.cpp / Ollama)",
        "    → MEM_SAVE extraction (same call, zero extra latency)",
        "    → Streaming response → Client",
    ]
    for line in flow_lines:
        story.append(Paragraph(line.replace(" ", "&nbsp;"), st["CodeBlock"]))

    story.append(Spacer(1, 0.4*cm))
    story.append(Paragraph("Plugin Protocol", st["H2"]))
    story.append(Paragraph(
        "Each plugin implements a standard protocol: manifest (metadata, version, dependencies), "
        "health check, module lifecycle (startup/shutdown), optional CLI commands, "
        "and optional API routes. The core loads plugins at startup via auto-discovery — "
        "no hardcoded imports.",
        st["Body"],
    ))

    # --- 5. TECHNOLOGY STACK ---
    story.append(Paragraph("5. Technology Stack", st["H1"]))
    story.append(hr())

    stack_data = [
        ["Component", "Technology"],
        ["Language", "Python 3.11+ (bundled 3.12 in installer)"],
        ["Web framework", "FastAPI 0.115+"],
        ["Vector database", "Qdrant (embedded, no external process)"],
        ["LLM backends", "MLX · llama-cpp-python · Ollama"],
        ["Embeddings", "nomic-embed-text (Ollama) / paraphrase-multilingual-mpnet-base-v2"],
        ["Embedding dimensions", "768"],
        ["Encryption", "AES-256-GCM · HKDF-SHA256 · SQLCipher (default auto)"],
        ["CLI", "Click + Rich"],
        ["API compatibility", "OpenAI /v1/chat/completions"],
        ["Authentication", "X-API-Key (dual-key with rotation)"],
        ["Security layer", "6 injection detectors · 47 jailbreak patterns · rate limiting · CSP"],
        ["Test suite", "4770 test functions"],
        ["Platforms", "macOS Apple Silicon & Intel · Linux x86_64 (partial)"],
    ]
    story.append(table(stack_data, [5*cm, 12*cm]))

    # --- 6. RECOMMENDED MODELS ---
    story.append(PageBreak())
    story.append(Paragraph("6. Recommended Models", st["H1"]))
    story.append(hr())

    story.append(Paragraph(
        "16 empirically tested models across 4 RAM tiers. "
        "Icons: 👁 = vision support · 🧠 = thinking/reasoning tokens.",
        st["Body"],
    ))

    tiers = [
        ("8 GB RAM", [
            ("👁 🧠 Gemma 3 4B", "Google DeepMind 2025", "MLX + Ollama", "Recommended MLX"),
            ("👁 🧠 Qwen3.5 4B", "Alibaba 2026", "Ollama", "Recommended Ollama"),
            ("Qwen3 4B", "Alibaba 2025", "MLX + Ollama", ""),
        ]),
        ("16 GB RAM", [
            ("👁 🧠 Gemma 4 E4B", "Google 2026", "MLX + Ollama", "Recommended MLX"),
            ("Salamandra 7B", "BSC/AINA 2025", "Ollama + GGUF", "Best for Catalan"),
            ("👁 🧠 Qwen3.5 9B", "Alibaba 2026", "Ollama", "Recommended Ollama"),
            ("👁 🧠 Gemma 3 12B", "Google DeepMind 2025", "MLX + Ollama", ""),
        ]),
        ("24 GB RAM", [
            ("👁 🧠 Gemma 4 31B", "Google 2026", "MLX + Ollama", "Recommended"),
            ("🧠 Qwen3 14B", "Alibaba 2025", "MLX + Ollama", "Recommended"),
            ("🧠 GPT-OSS 20B", "OpenAI 2025 (Apache 2.0)", "MLX + Ollama", ""),
        ]),
        ("32 GB RAM", [
            ("👁 🧠 Gemma 4 31B", "Google 2026", "MLX + Ollama", "Recommended MLX"),
            ("👁 🧠 Gemma 3 27B", "Google DeepMind 2025", "MLX + GGUF", ""),
            ("🧠 DeepSeek R1 Distill 32B", "DeepSeek 2025", "Ollama + GGUF", ""),
            ("ALIA-40B Instruct", "BSC 2026 (9 Iberian languages)", "Ollama + GGUF", "Recommended Iberian"),
        ]),
    ]

    for tier_name, models in tiers:
        story.append(Paragraph(tier_name, st["H2"]))
        m_data = [["Model", "Source / Year", "Backends", "Notes"]]
        for row in models:
            m_data.append(list(row))
        story.append(table(m_data, [4.5*cm, 4.5*cm, 3.5*cm, 4.5*cm]))
        story.append(Spacer(1, 0.3*cm))

    # --- 7. INSTALLATION ---
    story.append(Paragraph("7. Installation", st["H1"]))
    story.append(hr())

    story.append(Paragraph("macOS DMG Installer (recommended)", st["H2"]))
    story.append(Paragraph(
        "SwiftUI native wizard with 6 screens: welcome, destination, model selection "
        "(auto-detects RAM tier), confirmation, progress, completion. "
        "Bundles Python 3.12. Installs the macOS tray app automatically.",
        st["Body"],
    ))

    story.append(Paragraph("CLI Headless", st["H2"]))
    for line in [
        "git clone https://github.com/jgoy-labs/server-nexe",
        "cd server-nexe",
        "./setup.sh",
        "./nexe go    # → http://127.0.0.1:9119",
    ]:
        story.append(Paragraph(line, st["CodeBlock"]))

    story.append(Paragraph("CLI Quick Reference", st["H2"]))
    cli_data = [
        ["Command", "Description"],
        ["./nexe go", "Start server (Qdrant + FastAPI + tray)"],
        ["./nexe chat", "Interactive CLI chat"],
        ["./nexe chat --rag", "Chat with RAG memory enabled"],
        ["./nexe status", "Server status"],
        ["./nexe memory store \"text\"", "Save text to memory"],
        ["./nexe memory recall \"query\"", "Search memory"],
        ["./nexe knowledge ingest", "Index knowledge/ documents (server must be stopped)"],
        ["./nexe encryption status", "Check encryption status"],
        ["./nexe encryption export-key", "Export master key for backup"],
    ]
    story.append(table(cli_data, [7*cm, 10*cm]))

    # --- 8. API & INTEGRATION ---
    story.append(PageBreak())
    story.append(Paragraph("8. API & Integration", st["H1"]))
    story.append(hr())

    story.append(Paragraph(
        "server-nexe exposes an OpenAI-compatible REST API. "
        "Any tool that supports a custom OpenAI endpoint works out of the box: "
        "Cursor, Continue, Zed, LangChain, and custom scripts.",
        st["Body"],
    ))

    story.append(Paragraph("Chat completion (curl)", st["H2"]))
    for line in [
        'curl -X POST http://127.0.0.1:9119/v1/chat/completions \\',
        '  -H "X-API-Key: YOUR_KEY" \\',
        '  -H "Content-Type: application/json" \\',
        "  -d '{\"messages\": [{\"role\": \"user\", \"content\": \"Hello\"}], \"use_rag\": true}'",
    ]:
        story.append(Paragraph(line, st["CodeBlock"]))

    story.append(Paragraph("Key endpoints", st["H2"]))
    ep_data = [
        ["Endpoint", "Method", "Description"],
        ["/v1/chat/completions", "POST", "Chat with streaming (OpenAI-compatible)"],
        ["/v1/memory/store", "POST", "Save text to a memory collection"],
        ["/v1/memory/search", "POST", "Semantic search over memory"],
        ["/v1/sessions", "GET", "List chat sessions"],
        ["/v1/sessions/{id}", "PATCH", "Rename a session"],
        ["/v1/upload", "POST", "Upload document (.pdf/.txt/.md)"],
        ["/ui/lang", "POST", "Change UI language (server source of truth)"],
        ["/health", "GET", "Health check"],
        ["/docs", "GET", "Interactive Swagger UI"],
    ]
    story.append(table(ep_data, [5.5*cm, 2.5*cm, 9*cm]))

    # --- 9. SECURITY ---
    story.append(Paragraph("9. Security", st["H1"]))
    story.append(hr())

    story.append(Paragraph(
        "Security is solved at the base layer — all requests go through the same "
        "validation pipeline regardless of whether they arrive via API, CLI, or Web UI.",
        st["Body"],
    ))

    sec_items = [
        "<b>Dual API key rotation</b> — primary and secondary keys, zero-downtime rotation",
        "<b>Rate limiting</b> — per-IP and per-key request throttling",
        "<b>Input validation</b> — validate_string_input on all string fields",
        "<b>6 injection detectors</b> — prompt injection, SQL injection, path traversal, "
        "XSS, command injection, SSRF — with Unicode normalization",
        "<b>47 jailbreak patterns</b> — regex-based detection and sanitization",
        "<b>CSP headers</b> — strict Content-Security-Policy on all responses",
        "<b>Encryption at rest</b> — AES-256-GCM (SQLite via SQLCipher, "
        "chat sessions .enc, RAG TextStore). Default: auto (activates if sqlcipher3 available)",
        "<b>No telemetry</b> — zero outbound network calls by design",
    ]
    for item in sec_items:
        story.append(bullet(item, st))

    # --- 10. LIMITATIONS & ROADMAP ---
    story.append(Paragraph("10. Limitations & Roadmap", st["H1"]))
    story.append(hr())

    story.append(Paragraph("Current Limitations", st["H2"]))
    lim_items = [
        "Local models are less capable than GPT-4, Claude, etc. — privacy is the trade-off",
        "RAG requires initial indexing time; empty memory = no RAG context",
        "No multi-device sync (all data is local)",
        "No model fine-tuning",
        "API partially compatible with OpenAI (missing /v1/embeddings, /v1/models)",
        "Encryption at rest defaults to auto — new feature, not yet battle-tested",
        "Linux: unit tests pass, not production-tested",
        "Windows: not yet supported",
        "Single developer project with AI-assisted audits, not formally audited",
    ]
    for item in lim_items:
        story.append(bullet(item, st))

    story.append(Paragraph("Roadmap Directions", st["H2"]))
    road_items = [
        "Workflow engine plugin — orchestrate multi-step agent flows",
        "ICATIA governance — associació that will govern server-nexe",
        "Windows support",
        "Linux production testing",
        "Plugin marketplace",
        "Multi-device sync (opt-in, encrypted)",
    ]
    for item in road_items:
        story.append(bullet(item, st))

    # --- BACK PAGE ---
    story.append(PageBreak())
    story.append(Spacer(1, 3*cm))
    story.append(Paragraph("Links & Resources", st["H1"]))
    story.append(hr())

    links_data = [
        ["Resource", "URL"],
        ["Source code", "github.com/jgoy-labs/server-nexe"],
        ["Documentation", "server-nexe.org"],
        ["Commercial site", "server-nexe.com"],
        ["Author", "jgoy.net"],
        ["Support (GitHub Sponsors)", "github.com/sponsors/jgoy-labs"],
        ["Support (Ko-fi)", "ko-fi.com/jgoylabs"],
    ]
    story.append(table(links_data, [5*cm, 12*cm]))

    story.append(Spacer(1, 1.5*cm))
    story.append(Paragraph(
        f"server-nexe {VERSION} · Jordi Goy · Barcelona · {TODAY} · Apache 2.0",
        st["Footer"],
    ))

    doc.build(story)
    return output


def main():
    print("server-nexe — White Paper PDF")
    print(f"Destí: {OUTPUT_PATH}")
    build(OUTPUT_PATH)
    size = OUTPUT_PATH.stat().st_size / 1024
    print(f"✓ Generat: {OUTPUT_PATH}  ({size:.0f} KB)")


if __name__ == "__main__":
    main()
