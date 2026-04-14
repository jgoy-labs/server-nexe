"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy
Location: memory/memory/config.py
Description: Hardware profiles and memory system configuration.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

from dataclasses import dataclass, field
from typing import Optional

from memory.embeddings.constants import DEFAULT_EMBEDDING_MODEL, DEFAULT_VECTOR_SIZE


@dataclass
class ExtractionConfig:
    llm_enabled: bool = False
    llm_threshold: float = 0.8
    session_extractor: str = "end_only"


@dataclass
class StagingConfig:
    ttl_hours: int = 48


@dataclass
class DreamingConfig:
    interval_minutes: int = 15


@dataclass
class BudgetConfig:
    profile_max: int = 200
    episodic_max: int = 1000
    notebooks_max: int = 20
    plugin_max_per_ns: int = 200


@dataclass
class RetrieveConfig:
    base_threshold: float = 0.40
    floor_threshold: float = 0.45
    ceiling_threshold: float = 0.65
    fallback_threshold: float = 0.55
    max_tokens_ratio: float = 0.10
    max_tokens_cap: int = 800


@dataclass
class GCConfig:
    episodic_half_life_days: int = 60
    full_gc_interval_hours: int = 24
    tombstone_ttl_days: int = 90
    access_boost_max: float = 3.0


@dataclass
class IngestConfig:
    """Ingest pipeline tunables (SSOT for batch sizes and strategy flags).

    Defaults preserve the historical hardcoded behaviour exactly:
    - store_batch_size=50 matched BATCH_SIZE=50 at ingest_knowledge.py:281
      and plugins/web_ui_module/core/memory_helper.py:724.
    - embed_batch_size=None means we do NOT pass batch_size kwarg to
      fastembed.TextEmbedding.embed(...), so FastEmbed keeps its own
      internal default (preserving prior behaviour).
    - pre_warm=False and mega_batch=False keep the loop-per-doc path
      historically in place. These flags exist so bug #16 can iterate
      without re-touching production code paths.
    - perf_logging=False means MemoryAPI does not accumulate timing
      counters (zero overhead in production). Benchmarks flip it on
      to collect per-phase timings without touching production code.
    - embed_threads=6 caps the ORT CPU intra-op thread count that
      fastembed forwards to ONNX Runtime. Bug #16 investigation found
      that the fastembed default (auto = all cores) pulls E-cores into
      the work and incurs context-switching penalties on Apple Silicon.
      Six threads maps well to M4 Pro P-cores; set to None to restore
      fastembed auto behaviour.
    """

    store_batch_size: int = 50
    embed_batch_size: Optional[int] = None
    embed_threads: Optional[int] = None
    pre_warm: bool = False
    mega_batch: bool = False
    perf_logging: bool = False


@dataclass
class MemoryConfig:
    """Complete memory system configuration."""

    profile_name: str = "m1_8gb"
    extraction: ExtractionConfig = field(default_factory=ExtractionConfig)
    staging: StagingConfig = field(default_factory=StagingConfig)
    dreaming: DreamingConfig = field(default_factory=DreamingConfig)
    budgets: BudgetConfig = field(default_factory=BudgetConfig)
    retrieve: RetrieveConfig = field(default_factory=RetrieveConfig)
    gc: GCConfig = field(default_factory=GCConfig)
    ingest: IngestConfig = field(default_factory=IngestConfig)
    db_path: Optional[str] = None
    qdrant_path: str = "storage/vectors"
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    vector_size: int = DEFAULT_VECTOR_SIZE
    dedup_refresh_threshold: float = 0.92


# Pre-built profiles
PROFILES = {
    "m1_8gb": MemoryConfig(
        profile_name="m1_8gb",
        extraction=ExtractionConfig(
            llm_enabled=False,
            llm_threshold=0.8,
            session_extractor="end_only",
        ),
        budgets=BudgetConfig(
            profile_max=200,
            episodic_max=1000,
            notebooks_max=20,
            plugin_max_per_ns=200,
        ),
        retrieve=RetrieveConfig(max_tokens_cap=800),
        gc=GCConfig(episodic_half_life_days=60),
    ),
    "m1_16gb": MemoryConfig(
        profile_name="m1_16gb",
        extraction=ExtractionConfig(
            llm_enabled=True,
            llm_threshold=0.6,
            session_extractor="every_10_turns",
        ),
        budgets=BudgetConfig(
            profile_max=300,
            episodic_max=2000,
            notebooks_max=30,
            plugin_max_per_ns=200,
        ),
        retrieve=RetrieveConfig(max_tokens_cap=1200),
    ),
    "server_gpu": MemoryConfig(
        profile_name="server_gpu",
        extraction=ExtractionConfig(
            llm_enabled=True,
            llm_threshold=0.3,
            session_extractor="every_5_turns",
        ),
        budgets=BudgetConfig(
            profile_max=500,
            episodic_max=5000,
            notebooks_max=50,
            plugin_max_per_ns=1000,
        ),
        retrieve=RetrieveConfig(max_tokens_cap=2000),
        gc=GCConfig(episodic_half_life_days=90),
    ),
}


def get_config(profile_name: str = "m1_8gb") -> MemoryConfig:
    """Get a memory configuration by profile name."""
    if profile_name not in PROFILES:
        raise ValueError(
            f"Unknown profile '{profile_name}'. "
            f"Available: {list(PROFILES.keys())}"
        )
    return PROFILES[profile_name]


def resolve_ingest_config(memory_api) -> IngestConfig:
    """Safely resolve the IngestConfig of a MemoryAPI-like object.

    Bug #16: returns the IngestConfig attached to the given `memory_api`
    if present and of the correct type, otherwise returns a fresh
    IngestConfig() with default values. This keeps a single source of
    truth (the dataclass defaults in this module) and tolerates test
    doubles like MagicMock that do not wire up `ingest_config` explicitly.

    Production MemoryAPI always initialises `ingest_config` to a real
    IngestConfig instance, so in production this helper is a pass-through.
    """
    cfg = getattr(memory_api, "ingest_config", None)
    if isinstance(cfg, IngestConfig):
        return cfg
    return IngestConfig()


__all__ = [
    "MemoryConfig",
    "ExtractionConfig",
    "StagingConfig",
    "DreamingConfig",
    "BudgetConfig",
    "RetrieveConfig",
    "GCConfig",
    "IngestConfig",
    "PROFILES",
    "get_config",
    "resolve_ingest_config",
]
