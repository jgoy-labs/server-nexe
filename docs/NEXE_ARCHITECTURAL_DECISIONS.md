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
import-time cross-package edges, reconciled in the same commit as the move — since dropped
to **100** by 62b713f3, which removed one edge without touching this text (#938; the live
count is `scripts/layering_baseline.json`, not this paragraph). Nine of the
24 new edges are only `personality._logger` and five more are `__init__` imports that had
to become absolute; lowering the logger into `core` would remove nine of them at once,
and that is the obvious next step. The debt is now **visible instead of implied**.

**The "i18n-first" precondition this note used to attach to the move was empty AT THE
TIME.** Verified by running a real `I18nManager`, not by reading the loader: the package
shipped 15 translation files that were never loaded — the lookup expected a literal
`location/` path segment that did not exist — so its messages already came out in English.
There was no live i18n to preserve, and the move did not need to wait for the i18n
relocation. **Fixed 30 minutes later the same night** (0eb6c7b9, #938): all 11 components
load today, verified live.

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

## ADR-006 — Context window: the engine answers, one resolver asks, two ratios that must not collide

**The live engine is the only authority on its own context window.** Each engine
module implements `get_context_window()` (`ollama_module`, `mlx_module`,
`llama_cpp_module`) and answers from its own memory story: Ollama sizes by RAM, MLX
by RAM *and* real model weights, llama.cpp by RAM via `auto_n_ctx()` (#965 — it was
the only engine with a flat 8192 default). Adding a fourth engine means teaching that
engine, not editing core.

**One resolver, `core/context_window.py::resolve_context_window`, is the single place
that asks.** It never invents a number: when nothing live can answer (no module, a
pre-contract module, one that raised) it falls back to `DEFAULT_CONTEXT_WINDOW`.
Detection is a convenience — it must never be the reason a chat turn fails.

**MLX: the model's own limit is applied inside `auto_max_kv_size()`, not to the
reported number.** `max_position_embeddings` caps the RAM-derived value, and the 8192
floor wins over the cap (a 2048-position model must degrade, not drive the budget
negative). Because the cap lives in the calculation, every consumer — truncator,
cache, RAM guard — inherits the same value.

**The turn budget and the compaction trigger split the same total from different
files, and their ratios must not collide.** `PROMPT_BUDGET_RATIO = 0.7`
(`core/context_budget.py` — it lived in `plugins/web_ui_module/core/` until F-D
block 4 moved it, so that `/v1` budgets a turn with the same arithmetic; the two
routes still differ in their history floor and in what they do when the budget
is spent) is the share of the window the
assembled prompt may use; `ChatSession.COMPACT_AT_RATIO = 0.45`
(`session_manager.py`) is where compaction triggers — by tokens against the live
window, not every N turns (`COMPACT_EVERY = 200` is a hard guard only, never the
trigger). When both were 0.7, history filled the whole prompt budget exactly when a
conversation reached compaction size, the available context went negative, and RAG
and documents were silently dropped on every engine — while every unit test stayed
green, because each tested one piece and none tested the interaction.

**Invariant, defended by mutation tests: the assembled prompt never exceeds the
engine's window.** llama.cpp does not truncate an oversized prompt — it raises
`ValueError` and the turn dies. For the same reason no artificial floor may inflate
a small engine's budget (`MIN_BUDGET_WINDOW_TOKENS` was tried and reverted: at
n_ctx=2048 it turned degradation into a crash). Degrading always beats dying.

**Where the invariant is enforced (#976, closed):** the budget decides what a turn
may KEEP; `fit_prompt_to_window` (`core/context_budget.py`) checks what was actually
ASSEMBLED, at both doors, and drops whole turns from the oldest end until it fits.
The two are not the same measurement — the budget knows nothing about the history
the caller prepends afterwards, the on-demand clock line, or the untrusted-context
wrapper. A newest turn that overflows on its own is trimmed rather than dropped (an
empty prompt is not a degradation), keeping its head and its tail for a user turn
and its end for an assistant one, which is the continue path resuming where the
generation stopped.

Its limit, stated rather than implied: the check counts CHARS at
`CHARS_PER_TOKEN_ESTIMATE`, because the core may not reach a plugin's tokenizer
(the layering gate keeps core → plugins at zero). The estimate undercounts Catalan
and Spanish, so the margin is the greater of 256 tokens and 5% of the window. That
converts "over the window by any amount" into "within the estimate's error of it";
it is not a proof.

Open edges are tracked as findings, not here: the degenerate truncation branch when
the budget reaches ≤0 (#979) and the wrapper around retrieved context — nonce'd
delimiters plus an assistant ack turn — which the budget does not count, so the
assembled prompt runs slightly past it (#999). `NEXE_HISTORY_CONTEXT_RATIO` (#977)
is closed: it is validated like its siblings now, and it applies to `/ui/chat` only.
