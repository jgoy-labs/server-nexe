"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: core/paths/constants.py
Description: Foundational filesystem path constants (no imports — lowest layer).

             SSOT for the base-config file location. The base server config
             physically lives under ``personality/`` for historical reasons
             (it predates the core/personality split); it triples as (a) the
             BASE config layer, (b) the repo-root marker, and (c) the runtime
             write target. Centralising the literal here lets every core-side
             consumer (config, paths/detection+validation, server bootstrap,
             cli writers) reference one place instead of duplicating the string.

             This is the FAÇADE/in-place step of the personality→core layering
             work (MC-129 Fase 0). The physical move is deferred post-1.0.7 as
             an atomic, i18n-first epic — see ADR-001.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

# Relative path (from repo root) of the base server config file.
# Used as: BASE config layer (core/config.py), repo-root marker
# (core/paths/detection.py + validation.py), bootstrap (core/server/factory_i18n.py),
# user-facing banner (core/server/runner.py) and runtime write target (core/cli/cli.py).
BASE_CONFIG_RELATIVE = "personality/server.toml"

__all__ = ["BASE_CONFIG_RELATIVE"]
