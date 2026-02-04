"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: core/metrics/registry.py
Description: Prometheus metrics registry per Nexe 0.8.

www.jgoy.net
────────────────────────────────────
"""

import logging
import threading
from typing import Optional

from prometheus_client import (
  CollectorRegistry,
  Counter,
  Histogram,
  Gauge,
  REGISTRY,
)

logger = logging.getLogger(__name__)

_registry_lock = threading.Lock()
_registry: Optional[CollectorRegistry] = None

HTTP_REQUESTS_TOTAL = Counter(
  "core_http_requests_total",
  "Total HTTP requests",
  ["method", "path", "status"],
  registry=REGISTRY,
)

HTTP_REQUEST_DURATION = Histogram(
  "core_http_request_duration_seconds",
  "HTTP request duration in seconds",
  ["method", "path"],
  buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
  registry=REGISTRY,
)

HTTP_ERRORS_TOTAL = Counter(
  "core_http_errors_total",
  "Total HTTP errors",
  ["method", "path", "error_type"],
  registry=REGISTRY,
)

ACTIVE_CONNECTIONS = Gauge(
  "core_active_connections",
  "Number of active HTTP connections",
  registry=REGISTRY,
)

MODULE_HEALTH_STATUS = Gauge(
  "core_module_health_status",
  "Module health status (1=healthy, 0.5=degraded, 0=unhealthy)",
  ["module"],
  registry=REGISTRY,
)

RATE_LIMIT_HITS = Counter(
  "core_rate_limit_hits_total",
  "Total rate limit hits",
  ["limit_type", "path"],
  registry=REGISTRY,
)

MEMORY_OPERATIONS = Counter(
  "core_memory_operations_total",
  "Total memory operations",
  ["operation"],
  registry=REGISTRY,
)

MEMORY_STORE_SIZE = Gauge(
  "core_memory_store_size",
  "Current memory store size",
  ["store_type"],
  registry=REGISTRY,
)

RAG_SEARCHES = Counter(
  "core_rag_searches_total",
  "Total RAG searches",
  ["source"],
  registry=REGISTRY,
)

RAG_SEARCH_DURATION = Histogram(
  "core_rag_search_duration_seconds",
  "RAG search duration in seconds",
  ["source"],
  buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
  registry=REGISTRY,
)

CHAT_ENGINE_REQUESTS = Counter(
  "core_chat_engine_requests_total",
  "Total chat requests by engine",
  ["engine", "status"],
  registry=REGISTRY,
)

CHAT_ENGINE_DURATION = Histogram(
  "core_chat_engine_duration_seconds",
  "Chat processing duration by engine",
  ["engine"],
  buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
  registry=REGISTRY,
)

EMBEDDING_OPERATIONS = Counter(
  "core_embedding_operations_total",
  "Total embedding operations",
  ["operation"],
  registry=REGISTRY,
)

EMBEDDING_CACHE_HITS = Counter(
  "core_embedding_cache_hits_total",
  "Embedding cache hits",
  registry=REGISTRY,
)

EMBEDDING_CACHE_MISSES = Counter(
  "core_embedding_cache_misses_total",
  "Embedding cache misses",
  registry=REGISTRY,
)

def get_metrics_registry() -> CollectorRegistry:
  """
  Retorna el registry global de Prometheus.

  Returns:
    CollectorRegistry: Registry amb totes les mètriques
  """
  return REGISTRY

def reset_metrics() -> None:
  """
  Reset all metrics (for testing).

  Warning: Only use in tests!
  """
  logger.warning("Metrics reset requested - only for testing")

def normalize_path(path: str) -> str:
  """
  Normalitza path per mètriques (evita alta cardinalitat).

  Args:
    path: Path original

  Returns:
    Path normalitzat
  """
  if "?" in path:
    path = path.split("?")[0]

  parts = path.split("/")
  normalized = []

  for i, part in enumerate(parts):
    if not part:
      continue
    if _looks_like_id(part):
      normalized.append("{id}")
    else:
      normalized.append(part)

  return "/" + "/".join(normalized) if normalized else "/"

def _looks_like_id(part: str) -> bool:
  """Check if part looks like an ID."""
  if len(part) == 36 and part.count("-") == 4:
    return True
  if len(part) == 32 and all(c in "0123456789abcdef" for c in part.lower()):
    return True
  if part.isdigit() and len(part) > 4:
    return True
  return False

def set_module_health(module: str, status: str) -> None:
  """
  Actualitza l'estat de salut d'un mòdul.

  Args:
    module: Nom del mòdul
    status: healthy, degraded, unhealthy
  """
  status_map = {
    "healthy": 1.0,
    "degraded": 0.5,
    "unhealthy": 0.0,
  }
  value = status_map.get(status.lower(), 0.0)
  MODULE_HEALTH_STATUS.labels(module=module).set(value)

def increment_rate_limit(limit_type: str, path: str) -> None:
  """
  Incrementa el comptador de rate limit hits.

  Args:
    limit_type: Tipus de limit (ip, api_key, composite)
    path: Path afectat
  """
  RATE_LIMIT_HITS.labels(limit_type=limit_type, path=normalize_path(path)).inc()
