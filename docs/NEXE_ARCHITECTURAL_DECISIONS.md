# Nexe Architectural Decisions

This file is the in-repo pointer for architectural decisions referenced from the
code (`See: docs/NEXE_ARCHITECTURAL_DECISIONS.md`). The canonical, fully reasoned
ADRs live in the project's architecture documentation; this file summarises the
load-bearing decisions a reader of the code needs in order not to misread it.

## ADR-001 — Module system & plugin isolation

**ModuleManager is the single source of truth for all module operations.**
Discovery, loading, the registry, manifests, and lifecycle all go through
`core/modules/`. `core/server/factory_modules.py` only delegates to
it (`discover_and_load_modules` → `ModuleManager.load_plugin_routers`).

`ModuleManager` coordinates: `ConfigManager`, `PathDiscovery`, `ModuleDiscovery`,
`ModuleLoader`, `ModuleRegistry`, `ModuleLifecycleManager`, `SystemLifecycleManager`,
`SyncWrapper`, the event system, metrics and i18n.

### Layering: the module system lives in core/modules — and it is not a kernel

`core/modules/` holds **the module system**: what a module *is* (`protocol.py`,
`manifest_base.py`) and what loads it (discovery, registry, lifecycle, config,
admission). The two halves used to live apart — the contract in `core/loader/`, the
loading in `personality/module_manager/` — which read as *"the loader is the protocol
and the kernel is the loader"*. One package now answers both questions.

**It is deliberately not called a kernel.** It has no privilege boundary, no scheduling
and no resource arbitration: plugins are imported into the same process and the same
address space. Naming it a kernel would point a reader at the wrong place for the
isolation story, which lives elsewhere — the module allowlist (`core/config.py`), the
memory porter with veto (`core.memory_access.get_memory_view`) and the layering gate.
Nor is it minimal, which is what the microkernel pattern means by the word: the
`ModuleManager` façade still takes a dozen collaborators and inherits from a mixin.
Splitting it into mechanism and policy is open work.

**What the move cost, measured.** The frozen layering baseline went from 80 to 101
import-time cross-package edges, reconciled in the same commit as the move. Nine of the
24 new edges are only `personality._logger` and five more are `__init__` imports that had
to become absolute; lowering the logger into `core` would remove nine of them at once,
and that is the obvious next step. The debt is now **visible instead of implied**.

**The "i18n-first" precondition this note used to attach to the move was empty.**
Verified by running a real `I18nManager`, not by reading the loader: the package ships 15
translation files that are never loaded — the lookup expects a literal `location/` path
segment that does not exist — so its messages already came out in English. There was no
live i18n to preserve, and the move did not need to wait for the i18n relocation.

**Related — base config path SSOT (MC-129):** the base server config `personality/server.toml`
triples as the BASE config layer, the repo-root marker, and the runtime write target. The
literal is centralised in `core/paths/constants.py::BASE_CONFIG_RELATIVE` (lowest layer, no
layer inversion); the file itself is **not** moved (it's the repo-root marker). All core-side
consumers reference the constant.

### Intentional scaffolding (do not delete)

The per-module / per-system **lifecycle layer** is scaffolding for the planned
plugin-isolation runtime (ADR-001): isolating the DRAFT plugins into sandboxed
subprocesses with explicit start/stop/health control.

- `core/modules/module_lifecycle.py` — `ModuleLifecycleManager`
  (`load_module` / `start_module` / `stop_module`)
- `core/modules/system_lifecycle.py` — `SystemLifecycleManager`
  (`start_system` / `shutdown_system`)
- `personality/loading/` — the loader/extractor/finder/importer/validator chain

These currently have **zero production callers, and that is expected**: today the
server boots plugins in-process via `factory_modules` → `load_plugin_routers`, and
the lifecycle layer is wired up only when the isolation runtime lands. It is kept
deliberately so the runtime can be built on top of it rather than re-derived.

> Reviewers/auditors: "no production callers" here is **not** dead code — it is
> pre-wired scaffolding for ADR-001. Verify against this note before flagging
> `module_lifecycle` / `system_lifecycle` / `personality/loading/` for removal.
