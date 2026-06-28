# Nexe Architectural Decisions

This file is the in-repo pointer for architectural decisions referenced from the
code (`See: docs/NEXE_ARCHITECTURAL_DECISIONS.md`). The canonical, fully reasoned
ADRs live in the project's architecture documentation; this file summarises the
load-bearing decisions a reader of the code needs in order not to misread it.

## ADR-001 — Module system & plugin isolation

**ModuleManager is the single source of truth for all module operations.**
Discovery, loading, the registry, manifests, and lifecycle all go through
`personality/module_manager/`. `core/server/factory_modules.py` only delegates to
it (`discover_and_load_modules` → `ModuleManager.load_plugin_routers`).

`ModuleManager` coordinates: `ConfigManager`, `PathDiscovery`, `ModuleDiscovery`,
`ModuleLoader`, `ModuleRegistry`, `ModuleLifecycleManager`, `SystemLifecycleManager`,
`SyncWrapper`, the event system, metrics and i18n.

### Layering: ModuleManager is an infra kernel — its location is historical (MC-130)

`personality/module_manager/` is an **infra kernel** (module discovery / loading /
registry), not a persona/i18n concern, even though it physically lives under
`personality/`. It predates the core/personality split; `core`'s lifespan depends on
it. **Do not read the directory as a domain signal.**

The "right" home is a low layer (e.g. `core/kernel`), but the move is **deliberately
deferred post-1.0.7** and must be done as a single **atomic, i18n-first epic**, not in
isolation:

- Moving the kernel alone would add ~16 new cross-package import edges to the **frozen
  layering baseline** (`scripts/check_layering.py`, ADR below), inflating exactly the
  debt the gate exists to freeze. The current cross-package coupling is broken by
  deferred imports and is a P3 maintainability concern, not a runtime cycle.
- The kernel imports `personality.i18n.I18nManager`, so the **i18n relocation is the
  keystone**: do it first (`personality.i18n → core`), which turns those edges into
  intra-core imports (baseline goes **down**), then config, then the kernel. Sequence:
  **i18n → config → kernel**, three independent commits each re-passing `check_layering.py`.

**Related — base config path SSOT (MC-129):** the base server config `personality/server.toml`
triples as the BASE config layer, the repo-root marker, and the runtime write target. The
literal is centralised in `core/paths/constants.py::BASE_CONFIG_RELATIVE` (lowest layer, no
layer inversion); the file itself is **not** moved (it's the repo-root marker). All core-side
consumers reference the constant.

> **Milestone commitment:** the physical `personality → core` extraction epic should land
> within ~2 sprints after the 1.0.7 release, so this documented P3 debt does not silently
> accrete. Until then it is frozen by the layering gate and explained by this note.

### Intentional scaffolding (do not delete)

The per-module / per-system **lifecycle layer** is scaffolding for the planned
plugin-isolation runtime (ADR-001): isolating the DRAFT plugins into sandboxed
subprocesses with explicit start/stop/health control.

- `personality/module_manager/module_lifecycle.py` — `ModuleLifecycleManager`
  (`load_module` / `start_module` / `stop_module`)
- `personality/module_manager/system_lifecycle.py` — `SystemLifecycleManager`
  (`start_system` / `shutdown_system`)
- `personality/loading/` — the loader/extractor/finder/importer/validator chain

These currently have **zero production callers, and that is expected**: today the
server boots plugins in-process via `factory_modules` → `load_plugin_routers`, and
the lifecycle layer is wired up only when the isolation runtime lands. It is kept
deliberately so the runtime can be built on top of it rather than re-derived.

> Reviewers/auditors: "no production callers" here is **not** dead code — it is
> pre-wired scaffolding for ADR-001. Verify against this note before flagging
> `module_lifecycle` / `system_lifecycle` / `personality/loading/` for removal.
