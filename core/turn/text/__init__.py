"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/turn/text/__init__.py
Description: The model's text format, cleaned in the core (C4.4, ADR-007).

What a model writes besides its answer — <think> blocks, gpt-oss harmony
channels, <|…|> and ◁▷ tags, echoed context headers — is the same for every
door. It was cleaned inside the web UI plugin, so /v1 streamed it raw. The
door keeps only its alphabet (sentinels, LaTeX, error wording); knowing the
model's format is the core's.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""
