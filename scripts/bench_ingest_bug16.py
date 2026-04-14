#!/usr/bin/env python3
"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: scripts/bench_ingest_bug16.py
Description: Modular benchmark harness for bug #16 (ingest KB <10s).

Runs the real ingest pipeline inside isolated Python subprocesses, one
per measurement, so each run starts with a fresh interpreter and clean
ONNX Runtime state. Parses the [PERF_INGEST] JSON line produced by the
instrumentation added in commit d782842.

Features:
- Two ingest modes: `knowledge` (knowledge/<lang>/*.md) and `pdf`
  (arbitrary PDF staged in a temp dir, collection=user_knowledge).
- Two cold scenarios: `cold-typical` (clear Qdrant collection only;
  model stays cached — realistic re-install cost) and `cold-total`
  (also wipes the HuggingFace model cache — simulates first-ever run,
  requires re-downloading ~1 GB of model weights, slow).
- IngestConfig parameter sweep via CLI (--embed-batch, --store-batch,
  --pre-warm, --mega-batch). Defaults preserve production behaviour.
- N runs per scenario (default 3); reports median, p95, min, max, stddev.
- Peak RSS captured via resource.getrusage(RUSAGE_CHILDREN) between runs.
- Structured JSON output in diari/bench/bug16/ + human table to stdout.

Usage:
  scripts/bench_ingest_bug16.py --mode knowledge --runs 3
  scripts/bench_ingest_bug16.py --mode pdf --pdf ~/Desktop/doc.pdf --runs 3
  scripts/bench_ingest_bug16.py --mode knowledge --embed-batch 128 \\
      --mega-batch --runs 5 --label "mega+b128"

Internal flag:
  --_run-child  runs a single ingest with the given IngestConfig in this
               process (invoked by the parent via subprocess); emits the
               [PERF_INGEST] JSON line on stdout.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import resource
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
# Benchmark artefacts live at the repo top level (tracked). The diari/
# subtree is deliberately gitignored for private dev notes, so reproducible
# benchmark data does not belong there.
BENCH_OUT_DIR = REPO_ROOT / "bench" / "bug16"
QDRANT_COLLECTIONS_DIR = REPO_ROOT / "storage" / "vectors" / "collection"
HF_HUB_CACHE = Path.home() / ".cache" / "huggingface" / "hub"
PERF_PREFIX = "[PERF_INGEST] "

# ---------------------------------------------------------------------------
# Child-run mode: executed by the parent via `python scripts/bench_ingest_bug16.py --_run-child ...`
# ---------------------------------------------------------------------------

async def _child_run(args: argparse.Namespace) -> int:
    """Execute a single ingest with the given IngestConfig overrides.

    Emits [PERF_INGEST] on stdout via the instrumentation already in place
    at core/ingest/ingest_knowledge.py. We inject the config by
    monkey-patching MemoryAPI.__init__ so production code stays untouched.
    """
    sys.path.insert(0, str(REPO_ROOT))

    # Silence noisy loggers so the [PERF_INGEST] line is easy to parse.
    logging.basicConfig(level=logging.WARNING, format="%(message)s")

    from memory.memory.api import MemoryAPI as _MemAPI
    from memory.memory.config import IngestConfig

    cfg = IngestConfig(
        store_batch_size=args.store_batch,
        embed_batch_size=args.embed_batch if args.embed_batch > 0 else None,
        pre_warm=args.pre_warm,
        mega_batch=args.mega_batch,
        perf_logging=True,
    )

    _orig_init = _MemAPI.__init__

    def _patched_init(self, *a, **kw):
        if kw.get("ingest_config") is None:
            kw["ingest_config"] = cfg
        _orig_init(self, *a, **kw)

    _MemAPI.__init__ = _patched_init

    from core.ingest.ingest_knowledge import ingest_knowledge

    if args.mode == "knowledge":
        ok = await ingest_knowledge(folder=None)
    elif args.mode == "pdf":
        pdf_path = Path(args.pdf).expanduser().resolve()
        if not pdf_path.is_file():
            print(json.dumps({"error": f"PDF not found: {pdf_path}"}), file=sys.stderr)
            return 2
        # Stage the PDF in a temp folder; ingest_knowledge treats the folder
        # as the source, routes to target_collection=user_knowledge.
        with tempfile.TemporaryDirectory(prefix="bench_bug16_") as tmp:
            staged = Path(tmp) / pdf_path.name
            shutil.copy2(pdf_path, staged)
            ok = await ingest_knowledge(
                folder=Path(tmp),
                target_collection="user_knowledge",
            )
    else:
        print(json.dumps({"error": f"unknown mode {args.mode}"}), file=sys.stderr)
        return 2

    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Parent-run mode: orchestrates subprocesses + aggregates results
# ---------------------------------------------------------------------------

def _wipe_qdrant_collections(names: list[str]) -> None:
    """Remove the given Qdrant collection directories (embedded local mode).

    Safe if the directories do not exist.
    """
    for name in names:
        target = QDRANT_COLLECTIONS_DIR / name
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)


def _snapshot_hf_cache(target: Path) -> bool:
    """Move the HF hub cache aside so a `cold-total` run starts from scratch.

    Returns True if a snapshot was taken (so we can restore later). Skip
    gracefully if the cache does not exist.
    """
    if not HF_HUB_CACHE.exists():
        return False
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    shutil.move(str(HF_HUB_CACHE), str(target))
    return True


def _restore_hf_cache(source: Path) -> None:
    """Move a previously snapshotted HF cache back in place."""
    if not source.exists():
        return
    if HF_HUB_CACHE.exists():
        shutil.rmtree(HF_HUB_CACHE, ignore_errors=True)
    shutil.move(str(source), str(HF_HUB_CACHE))


def _prepare_scenario(scenario: str, mode: str, hf_snapshot_dir: Path | None) -> None:
    """Clean state before one measurement run according to scenario."""
    # Always clear the target collection so each run truly ingests fresh.
    if mode == "knowledge":
        _wipe_qdrant_collections(["nexe_documentation"])
    elif mode == "pdf":
        _wipe_qdrant_collections(["user_knowledge"])

    if scenario == "cold-total" and hf_snapshot_dir is not None:
        # Ensure the HF cache is empty — triggers a full re-download in the
        # child run. Snapshot has already been taken by the orchestrator at
        # the top level, so we only clear the live location here.
        if HF_HUB_CACHE.exists():
            shutil.rmtree(HF_HUB_CACHE, ignore_errors=True)


def _run_subprocess(args: argparse.Namespace) -> dict[str, Any]:
    """Run one child ingest in a subprocess and return parsed perf record.

    The child writes a [PERF_INGEST] JSON line; we capture and return it,
    plus wall-clock of the subprocess from the parent's perspective and
    peak RSS of the child (best-effort via ru_maxrss on macOS).
    """
    script = Path(__file__).resolve()
    cmd = [
        sys.executable,
        str(script),
        "--_run-child",
        "--mode", args.mode,
        "--store-batch", str(args.store_batch),
        "--embed-batch", str(args.embed_batch),
    ]
    if args.pre_warm:
        cmd.append("--pre-warm")
    if args.mega_batch:
        cmd.append("--mega-batch")
    if args.mode == "pdf":
        cmd.extend(["--pdf", str(args.pdf)])

    t_wall_start = time.perf_counter_ns()
    rusage_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=600,
    )
    t_wall_total = time.perf_counter_ns() - t_wall_start
    rusage_after = resource.getrusage(resource.RUSAGE_CHILDREN)

    # On macOS ru_maxrss is already in bytes; on Linux it is in kilobytes.
    # sys.platform lets us normalise to bytes.
    maxrss_child = rusage_after.ru_maxrss
    if sys.platform != "darwin":
        maxrss_child *= 1024  # linux kB → bytes
    # Delta against prior child runs in the same parent process.
    rss_delta_bytes = maxrss_child - (
        rusage_before.ru_maxrss * (1 if sys.platform == "darwin" else 1024)
    )

    perf_line = None
    for line in proc.stdout.splitlines():
        if line.startswith(PERF_PREFIX):
            perf_line = line[len(PERF_PREFIX):]
            break

    if perf_line is None:
        return {
            "ok": False,
            "returncode": proc.returncode,
            "stderr_tail": proc.stderr[-400:],
            "stdout_tail": proc.stdout[-400:],
            "wall_ns": t_wall_total,
        }

    try:
        record = json.loads(perf_line)
    except json.JSONDecodeError as e:
        return {
            "ok": False,
            "parse_error": str(e),
            "perf_line": perf_line,
            "wall_ns": t_wall_total,
        }

    record.update({
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "wall_ns_parent": t_wall_total,
        "rss_peak_bytes": max(maxrss_child, 0),
        "rss_delta_bytes": max(rss_delta_bytes, 0),
    })
    return record


def _aggregate(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute median/p95/min/max/stddev on the per-phase timings."""
    good = [r for r in runs if r.get("ok")]
    if not good:
        return {"ok_runs": 0, "total_runs": len(runs)}

    def stats(values: list[int]) -> dict[str, float]:
        vals = sorted(values)
        return {
            "min": vals[0],
            "max": vals[-1],
            "median": statistics.median(vals),
            "mean": statistics.fmean(vals),
            "stdev": statistics.stdev(vals) if len(vals) > 1 else 0.0,
            "p95": vals[int(len(vals) * 0.95)] if len(vals) > 1 else vals[-1],
        }

    keys = [
        "total_ns", "model_init_ns", "chunking_ns", "embed_ns",
        "store_total_ns", "upsert_ns_derived", "warmup_ns",
        "wall_ns_parent", "rss_peak_bytes",
    ]
    agg: dict[str, Any] = {"ok_runs": len(good), "total_runs": len(runs), "phases": {}}
    for k in keys:
        vs = [r.get(k, 0) for r in good]
        agg["phases"][k] = stats(vs)

    # Constant across runs (validated).
    first = good[0]
    agg["total_chunks"] = first.get("total_chunks")
    agg["docs_processed"] = first.get("docs_processed")
    agg["lang"] = first.get("lang")
    agg["target_collection"] = first.get("target_collection")
    return agg


def _fmt_ns(ns: float) -> str:
    """Format nanoseconds as human-readable seconds or ms."""
    if ns >= 1_000_000_000:
        return f"{ns/1_000_000_000:.2f}s"
    if ns >= 1_000_000:
        return f"{ns/1_000_000:.0f}ms"
    if ns >= 1_000:
        return f"{ns/1_000:.0f}µs"
    return f"{ns:.0f}ns"


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TiB"


def _print_human_table(agg: dict[str, Any], label: str, scenario: str) -> None:
    print()
    print("=" * 72)
    print(f"Benchmark bug #16 — label={label!r} scenario={scenario!r}")
    if "total_chunks" in agg:
        print(f"  docs={agg.get('docs_processed')} chunks={agg.get('total_chunks')} "
              f"lang={agg.get('lang')} coll={agg.get('target_collection')}")
    ok = agg.get("ok_runs", 0)
    total = agg.get("total_runs", 0)
    print(f"  runs: {ok}/{total} ok")
    print("-" * 72)
    if ok == 0:
        print("  NO SUCCESSFUL RUNS — see JSON output for diagnostics.")
        print("=" * 72)
        return
    phases = agg["phases"]
    header_keys = [
        ("total_ns",          "total"),
        ("model_init_ns",     "model_init"),
        ("embed_ns",          "embed"),
        ("upsert_ns_derived", "upsert(derived)"),
        ("chunking_ns",       "chunking"),
        ("warmup_ns",         "warmup"),
        ("wall_ns_parent",    "subprocess wall"),
    ]
    print(f"  {'phase':<18} {'min':>9} {'median':>9} {'p95':>9} {'max':>9} {'stdev':>9}")
    for k, label_k in header_keys:
        s = phases[k]
        print(f"  {label_k:<18} "
              f"{_fmt_ns(s['min']):>9} "
              f"{_fmt_ns(s['median']):>9} "
              f"{_fmt_ns(s['p95']):>9} "
              f"{_fmt_ns(s['max']):>9} "
              f"{_fmt_ns(s['stdev']):>9}")
    rss = phases["rss_peak_bytes"]
    print(f"  {'peak RSS (child)':<18} "
          f"{_fmt_bytes(rss['min']):>9} "
          f"{_fmt_bytes(rss['median']):>9} "
          f"{_fmt_bytes(rss['p95']):>9} "
          f"{_fmt_bytes(rss['max']):>9} "
          f"{_fmt_bytes(rss['stdev']):>9}")
    # Pass/fail gate against target.
    median_total = phases["total_ns"]["median"] / 1_000_000_000
    target_m4 = 10.0
    target_m1 = 15.0
    print("-" * 72)
    print(f"  target M4 Pro: <{target_m4:.0f}s  →  median {median_total:.2f}s  "
          f"{'PASS' if median_total < target_m4 else 'FAIL'}")
    print(f"  target M1 8GB: <{target_m1:.0f}s  →  median {median_total:.2f}s  "
          f"{'PASS' if median_total < target_m1 else 'FAIL'} "
          f"(indicatiu — M1 real mesurar-se per separat)")
    print("=" * 72)


def _save_json(agg: dict[str, Any], runs: list[dict[str, Any]], args: argparse.Namespace) -> Path:
    BENCH_OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    fname = (
        f"{ts}_{args.mode}_{args.scenario}_"
        f"sb{args.store_batch}_eb{args.embed_batch}"
        f"_pw{int(args.pre_warm)}_mb{int(args.mega_batch)}.json"
    )
    out = BENCH_OUT_DIR / fname
    payload = {
        "schema_version": 1,
        "bug": 16,
        "timestamp_utc": ts,
        # Intentionally omit absolute paths (repo root, home dir, PDF
        # paths) to avoid leaking usernames or private document names
        # when these JSONs are committed and synced to gitoss. Only
        # portable host metadata goes here.
        "host": {
            "platform": sys.platform,
            "python": sys.version.split()[0],
        },
        "config": {
            "mode": args.mode,
            "scenario": args.scenario,
            "runs_requested": args.runs,
            "store_batch_size": args.store_batch,
            "embed_batch_size": args.embed_batch if args.embed_batch > 0 else None,
            "pre_warm": args.pre_warm,
            "mega_batch": args.mega_batch,
            "label": args.label,
            # For PDF mode we record only the basename so the JSON stays
            # reproducible across machines without leaking user directory
            # layout (e.g. Desktop paths).
            "pdf_basename": Path(args.pdf).name if args.mode == "pdf" and args.pdf else None,
        },
        "aggregate": agg,
        "runs": runs,
    }
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return out


def _parent_run(args: argparse.Namespace) -> int:
    # Snapshot HF cache only when user asked for cold-total (heavyweight).
    hf_snapshot = None
    if args.scenario == "cold-total":
        hf_snapshot = Path(tempfile.mkdtemp(prefix="bench_bug16_hfcache_"))
        took = _snapshot_hf_cache(hf_snapshot)
        if not took:
            hf_snapshot = None

    runs: list[dict[str, Any]] = []
    try:
        for i in range(args.runs):
            _prepare_scenario(args.scenario, args.mode, hf_snapshot)
            print(f"[bench] run {i+1}/{args.runs} ({args.scenario}) ...", flush=True)
            rec = _run_subprocess(args)
            rec["run_index"] = i
            runs.append(rec)
            ok = rec.get("ok", False)
            total_ns = rec.get("total_ns", 0)
            print(f"[bench] run {i+1}: ok={ok} total={_fmt_ns(total_ns)}", flush=True)
    finally:
        if hf_snapshot is not None:
            _restore_hf_cache(hf_snapshot)

    agg = _aggregate(runs)
    out_path = _save_json(agg, runs, args)
    _print_human_table(agg, args.label or "(no-label)", args.scenario)
    print(f"\n[bench] JSON written to {out_path.relative_to(REPO_ROOT)}")
    return 0 if agg.get("ok_runs", 0) == args.runs else 1


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Bug #16 ingest benchmark harness (AAA+++ modular).",
    )
    p.add_argument("--_run-child", action="store_true", help=argparse.SUPPRESS)
    p.add_argument(
        "--mode",
        choices=["knowledge", "pdf"],
        default="knowledge",
        help="Ingest corpus selector.",
    )
    p.add_argument(
        "--pdf",
        type=str,
        default=None,
        help=(
            "Path to a PDF (REQUIRED when --mode=pdf). No default is "
            "provided so the script never embeds an absolute path to a "
            "machine-specific document."
        ),
    )
    p.add_argument(
        "--scenario",
        choices=["cold-typical", "cold-total"],
        default="cold-typical",
        help=(
            "cold-typical: wipe Qdrant collection only (model in cache). "
            "cold-total: also wipe the HF hub cache (~1GB re-download)."
        ),
    )
    p.add_argument("--runs", type=int, default=3, help="Measurement runs (default 3).")
    p.add_argument(
        "--store-batch", type=int, default=50,
        help="IngestConfig.store_batch_size (default 50, production).",
    )
    p.add_argument(
        "--embed-batch", type=int, default=0,
        help=(
            "IngestConfig.embed_batch_size (0 = None → FastEmbed default). "
            "Positive values are passed as batch_size kwarg to fastembed."
        ),
    )
    p.add_argument(
        "--pre-warm", action="store_true",
        help="Enable IngestConfig.pre_warm.",
    )
    p.add_argument(
        "--mega-batch", action="store_true",
        help="Enable IngestConfig.mega_batch (honoured once Fase 4 wires it up).",
    )
    p.add_argument(
        "--label", type=str, default="",
        help="Free-form tag stored in the JSON output for this benchmark.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    # `--pdf` is mandatory when mode is pdf; there is no default on purpose
    # (see --pdf help string).
    if args.mode == "pdf" and not args.pdf:
        print(
            "error: --pdf is required when --mode pdf (no default provided)",
            file=sys.stderr,
        )
        return 2
    if getattr(args, "_run_child", False):
        return asyncio.run(_child_run(args))
    return _parent_run(args)


if __name__ == "__main__":
    sys.exit(main())
