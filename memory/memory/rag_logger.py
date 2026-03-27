"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: memory/memory/rag_logger.py
Description: RAGLogger - Logging detallat per operacions RAG/Memory.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

class Colors:
  RESET = "\033[0m"
  BOLD = "\033[1m"
  DIM = "\033[2m"

  BLACK = "\033[30m"
  RED = "\033[31m"
  GREEN = "\033[32m"
  YELLOW = "\033[33m"
  BLUE = "\033[34m"
  MAGENTA = "\033[35m"
  CYAN = "\033[36m"
  WHITE = "\033[37m"

  BRIGHT_RED = "\033[91m"
  BRIGHT_GREEN = "\033[92m"
  BRIGHT_YELLOW = "\033[93m"
  BRIGHT_BLUE = "\033[94m"
  BRIGHT_MAGENTA = "\033[95m"
  BRIGHT_CYAN = "\033[96m"

  BG_RED = "\033[41m"
  BG_GREEN = "\033[42m"
  BG_YELLOW = "\033[43m"
  BG_BLUE = "\033[44m"

class RAGEmojis:
  RECALL = "🔍"
  STORE = "💾"
  SEARCH = "🎯"
  EMBEDDING = "✨"

  FLASH = "⚡"
  SQLITE = "🗄️"
  QDRANT = "🔷"
  MEMORY = "📚"

  FOUND = "✅"
  NOT_FOUND = "❌"
  SKIP = "⏭️"
  ERROR = "💥"
  WARNING = "⚠️"

  CLOCK = "⏱️"
  TOKEN = "🎫"
  VECTOR = "📊"
  SCORE = "📈"

  ARROW_RIGHT = "➜"
  ARROW_DOWN = "↓"
  CHECK = "✓"
  CROSS = "✗"
  BRAIN = "🧠"

class RAGLogger:
  """
  Logger verbose per operacions RAG/Memory.

  Escriu a rag.log amb format visual detallat.
  Usar amb: tail -f ~/Nexe-Logs/rag.log

  O crear alias:
  alias nexe-rag='tail -f ~/Nexe-Logs/rag.log'
  """

  def __init__(self, enabled: bool = True):
    self.enabled = enabled
    self.log_path = self._get_writable_log_path()
    self._setup_logger()

  def _get_writable_log_path(self) -> Path:
    """Troba una ruta writable pel log."""
    import os as _os
    primary_path = Path(_os.environ.get("NEXE_LOGS_DIR", str(Path.home() / "Nexe-Logs"))) / "rag.log"
    try:
      primary_path.parent.mkdir(exist_ok=True)
      test_file = primary_path.parent / ".write_test_rag"
      test_file.touch()
      test_file.unlink()
      return primary_path
    except (PermissionError, OSError):
      pass

    project_path = Path(__file__).parent.parent.parent.parent / "storage" / "logs" / "rag.log"
    try:
      project_path.parent.mkdir(parents=True, exist_ok=True)
      return project_path
    except (PermissionError, OSError):
      pass

    tmp_path = Path("/tmp/nexe-logs/rag.log")
    try:
      tmp_path.parent.mkdir(parents=True, exist_ok=True)
      return tmp_path
    except (PermissionError, OSError):
      pass

    self.enabled = False
    return primary_path

  def _setup_logger(self):
    """Configura el logger per escriure al fitxer"""
    self.logger = logging.getLogger("nexe.rag")
    self.logger.setLevel(logging.DEBUG)

    if not self.logger.handlers:
      fh = logging.FileHandler(self.log_path, mode='a')
      fh.setLevel(logging.DEBUG)
      formatter = logging.Formatter('%(message)s')
      fh.setFormatter(formatter)
      self.logger.addHandler(fh)

  def _write(self, message: str):
    """Escriu al log si enabled"""
    if self.enabled:
      self.logger.info(message)

  def _timestamp(self) -> str:
    """Retorna timestamp formatat"""
    return datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3]

  def _timing(self, ms: float) -> str:
    """Formata timing amb color segons rendiment"""
    if ms < 50:
      color = Colors.BRIGHT_GREEN
    elif ms < 200:
      color = Colors.GREEN
    elif ms < 500:
      color = Colors.YELLOW
    elif ms < 1000:
      color = Colors.BRIGHT_YELLOW
    else:
      color = Colors.BRIGHT_RED
    return f"{color}{ms:.1f}ms{Colors.RESET}"

  def _score_color(self, score: float) -> str:
    """Color segons score de similaritat"""
    if score > 0.8:
      return Colors.BRIGHT_GREEN
    elif score > 0.6:
      return Colors.GREEN
    elif score > 0.4:
      return Colors.YELLOW
    elif score > 0.2:
      return Colors.BRIGHT_YELLOW
    else:
      return Colors.DIM

  def _truncate(self, text: str, max_len: int = 80) -> str:
    """Trunca text afegint ... si cal"""
    if len(text) > max_len:
      return text[:max_len] + "..."
    return text

  def recall_start(self, query: Optional[str], limit: int, entry_type: Optional[str], person_id: str = "default"):
    """Log the start of a recall operation."""
    self._write("")
    self._write(f"{Colors.BRIGHT_CYAN}{'═' * 70}{Colors.RESET}")
    self._write(f"{RAGEmojis.RECALL} {Colors.BOLD}{Colors.BRIGHT_CYAN}MEMORY RECALL{Colors.RESET} [{self._timestamp()}]")
    self._write(f"{Colors.BRIGHT_CYAN}{'═' * 70}{Colors.RESET}")
    self._write("")
    self._write(f" {Colors.DIM}Params:{Colors.RESET}")
    self._write(f"   limit: {limit}")
    self._write(f"   entry_type: {entry_type or 'all'}")
    self._write(f"   person_id: {person_id}")
    if query:
      self._write(f"   query: \"{self._truncate(query, 60)}\"")
    self._write("")

  def recall_step_flash(self, found: int, timing_ms: float):
    """Log cerca a FlashMemory"""
    self._write(f" {RAGEmojis.FLASH} {Colors.YELLOW}STEP 1: FlashMemory (RAM){Colors.RESET}")
    if found > 0:
      self._write(f"   {RAGEmojis.FOUND} {Colors.GREEN}TROBAT:{Colors.RESET} {found} entrades")
    else:
      self._write(f"   {RAGEmojis.NOT_FOUND} {Colors.DIM}Buit - continuant a SQLite{Colors.RESET}")
    self._write(f"   {RAGEmojis.CLOCK} {self._timing(timing_ms)}")
    self._write("")

  def recall_step_sqlite(self, found: int, timing_ms: float, cached_to_flash: int = 0):
    """Log cerca a SQLite"""
    self._write(f" {RAGEmojis.SQLITE} {Colors.BLUE}STEP 2: SQLite (persistence){Colors.RESET}")
    if found > 0:
      self._write(f"   {RAGEmojis.FOUND} {Colors.GREEN}TROBAT:{Colors.RESET} {found} entrades")
      if cached_to_flash > 0:
        self._write(f"   {RAGEmojis.FLASH} Cached {cached_to_flash} entrades a FlashMemory")
    else:
      self._write(f"   {RAGEmojis.NOT_FOUND} {Colors.DIM}Buit - continuant a Qdrant{Colors.RESET}")
    self._write(f"   {RAGEmojis.CLOCK} {self._timing(timing_ms)}")
    self._write("")

  def recall_step_qdrant(self, found: int, timing_ms: float, results: Optional[List[Dict]] = None):
    """Log a semantic search step in Qdrant."""
    self._write(f" {RAGEmojis.QDRANT} {Colors.MAGENTA}STEP 3: Qdrant (semantic search){Colors.RESET}")
    if found > 0:
      self._write(f"   {RAGEmojis.FOUND} {Colors.GREEN}TROBAT:{Colors.RESET} {found} resultats")
      if results:
        for i, r in enumerate(results[:3]):
          score = r.get("score", 0)
          content = self._truncate(r.get("content", ""), 50)
          self._write(f"    [{self._score_color(score)}{score:.3f}{Colors.RESET}] \"{content}\"")
    else:
      self._write(f"   {RAGEmojis.NOT_FOUND} {Colors.DIM}Cap resultat{Colors.RESET}")
    self._write(f"   {RAGEmojis.CLOCK} {self._timing(timing_ms)}")
    self._write("")

  def recall_complete(self, source: str, total_entries: int, context_chars: int, total_ms: float):
    """Log final del recall"""
    self._write(f"{Colors.DIM}{'─' * 70}{Colors.RESET}")
    self._write(f" {RAGEmojis.CHECK} {Colors.BOLD}{Colors.GREEN}RECALL COMPLETE{Colors.RESET}")
    self._write(f"   Font: {Colors.CYAN}{source}{Colors.RESET}")
    self._write(f"   Entrades: {total_entries}")
    self._write(f"   Context: {context_chars} chars (~{context_chars // 4} tokens)")
    self._write(f"   {RAGEmojis.CLOCK} Total: {self._timing(total_ms)}")
    self._write(f"{Colors.BRIGHT_CYAN}{'═' * 70}{Colors.RESET}")
    self._write("")

  def recall_error(self, error: str):
    """Log error en recall"""
    self._write(f" {RAGEmojis.ERROR} {Colors.RED}ERROR:{Colors.RESET} {error}")
    self._write(f"{Colors.BRIGHT_RED}{'═' * 70}{Colors.RESET}")
    self._write("")

  def store_start(self, content_type: str, content_preview: str, person_id: str = "default"):
    """Log the start of a store operation."""
    self._write("")
    self._write(f"{Colors.BRIGHT_BLUE}{'═' * 70}{Colors.RESET}")
    self._write(f"{RAGEmojis.STORE} {Colors.BOLD}{Colors.BRIGHT_BLUE}MEMORY STORE{Colors.RESET} [{self._timestamp()}]")
    self._write(f"{Colors.BRIGHT_BLUE}{'═' * 70}{Colors.RESET}")
    self._write("")
    self._write(f" {Colors.DIM}Tipus:{Colors.RESET} {content_type}")
    self._write(f" {Colors.DIM}Person:{Colors.RESET} {person_id}")
    self._write(f" {Colors.DIM}Preview:{Colors.RESET} \"{self._truncate(content_preview, 60)}\"")
    self._write("")

  def store_embedding(self, model: str, dimensions: int, timing_ms: float, text_chars: int):
    """Log embedding generation."""
    tokens_approx = text_chars // 4
    self._write(f" {RAGEmojis.EMBEDDING} {Colors.YELLOW}EMBEDDING{Colors.RESET}")
    self._write(f"   Model: {model}")
    self._write(f"   {RAGEmojis.VECTOR} Dimensions: {dimensions}")
    self._write(f"   {RAGEmojis.TOKEN} Input: ~{tokens_approx} tokens ({text_chars} chars)")
    self._write(f"   {RAGEmojis.CLOCK} {self._timing(timing_ms)}")
    self._write("")

  def store_sqlite(self, entry_id: str, timing_ms: float):
    """Log guardat a SQLite"""
    self._write(f" {RAGEmojis.SQLITE} {Colors.BLUE}SQLite{Colors.RESET}")
    self._write(f"   {RAGEmojis.CHECK} Guardat: {entry_id[:16]}...")
    self._write(f"   {RAGEmojis.CLOCK} {self._timing(timing_ms)}")
    self._write("")

  def store_qdrant(self, entry_id: str, timing_ms: float, collection: str = "nexe_memory"):
    """Log guardat a Qdrant"""
    self._write(f" {RAGEmojis.QDRANT} {Colors.MAGENTA}Qdrant{Colors.RESET}")
    self._write(f"   Collection: {collection}")
    self._write(f"   {RAGEmojis.CHECK} Vector upserted: {entry_id[:16]}...")
    self._write(f"   {RAGEmojis.CLOCK} {self._timing(timing_ms)}")
    self._write("")

  def store_flash(self, timing_ms: float):
    """Log cached to FlashMemory"""
    self._write(f" {RAGEmojis.FLASH} {Colors.YELLOW}FlashMemory{Colors.RESET}")
    self._write(f"   {RAGEmojis.CHECK} Cached for fast access")
    self._write(f"   {RAGEmojis.CLOCK} {self._timing(timing_ms)}")
    self._write("")

  def store_complete(self, entry_id: str, total_ms: float, destinations: List[str]):
    """Log store completion"""
    self._write(f"{Colors.DIM}{'─' * 70}{Colors.RESET}")
    self._write(f" {RAGEmojis.CHECK} {Colors.BOLD}{Colors.GREEN}STORE COMPLETE{Colors.RESET}")
    self._write(f"   Entry ID: {entry_id}")
    self._write(f"   Destinations: {', '.join(destinations)}")
    self._write(f"   {RAGEmojis.CLOCK} Total: {self._timing(total_ms)}")
    self._write(f"{Colors.BRIGHT_BLUE}{'═' * 70}{Colors.RESET}")
    self._write("")

  def store_error(self, error: str, destination: str = ""):
    """Log error en store"""
    dest_info = f" ({destination})" if destination else ""
    self._write(f" {RAGEmojis.ERROR} {Colors.RED}ERROR{dest_info}:{Colors.RESET} {error}")

  def memory_search_start(self, query: str, max_tokens: int):
    """Log inici cerca MEMORY"""
    self._write("")
    self._write(f"{Colors.BRIGHT_MAGENTA}{'═' * 70}{Colors.RESET}")
    self._write(f"{RAGEmojis.MEMORY} {Colors.BOLD}{Colors.BRIGHT_MAGENTA}MEMORY CONTEXT{Colors.RESET} [{self._timestamp()}]")
    self._write(f"{Colors.BRIGHT_MAGENTA}{'═' * 70}{Colors.RESET}")
    self._write("")
    self._write(f" {Colors.DIM}Query:{Colors.RESET} \"{self._truncate(query, 60)}\"")
    self._write(f" {Colors.DIM}Max tokens:{Colors.RESET} {max_tokens}")
    self._write("")

  def memory_route(self, collections: List[str], timing_ms: float):
    """Log routing MEMORY"""
    self._write(f" {RAGEmojis.SEARCH} {Colors.YELLOW}ROUTING{Colors.RESET}")
    if collections:
      self._write(f"   {RAGEmojis.FOUND} Selected: {', '.join(collections)}")
    else:
      self._write(f"   {RAGEmojis.NOT_FOUND} Cap col·lecció seleccionada")
    self._write(f"   {RAGEmojis.CLOCK} {self._timing(timing_ms)}")
    self._write("")

  def memory_collection_search(self, collection: str, results: int, timing_ms: float, top_results: Optional[List[Dict]] = None):
    """Log a search in a specific collection."""
    self._write(f" {RAGEmojis.QDRANT} {Colors.CYAN}{collection}{Colors.RESET}")
    self._write(f"   {RAGEmojis.FOUND} Resultats: {results}")
    if top_results:
      for r in top_results[:2]:
        score = r.get("score", 0)
        title = self._truncate(r.get("title", r.get("content", "")), 40)
        self._write(f"    [{self._score_color(score)}{score:.3f}{Colors.RESET}] {title}")
    self._write(f"   {RAGEmojis.CLOCK} {self._timing(timing_ms)}")

  def memory_memory_search(self, results: int, timing_ms: float, top_results: Optional[List[Dict]] = None):
    """Log cerca a nexe_memory"""
    self._write(f" {RAGEmojis.BRAIN} {Colors.BLUE}nexe_memory{Colors.RESET}")
    self._write(f"   {RAGEmojis.FOUND} Converses similars: {results}")
    if top_results:
      for r in top_results[:2]:
        score = r.get("score", 0)
        content = self._truncate(r.get("content", ""), 40)
        self._write(f"    [{self._score_color(score)}{score:.3f}{Colors.RESET}] \"{content}\"")
    self._write(f"   {RAGEmojis.CLOCK} {self._timing(timing_ms)}")
    self._write("")

  def memory_complete(self, total_sources: int, context_chars: int, total_ms: float):
    """Log final cerca MEMORY"""
    self._write(f"{Colors.DIM}{'─' * 70}{Colors.RESET}")
    self._write(f" {RAGEmojis.CHECK} {Colors.BOLD}{Colors.GREEN}MEMORY COMPLETE{Colors.RESET}")
    self._write(f"   Fonts: {total_sources}")
    self._write(f"   Context: {context_chars} chars (~{context_chars // 4} tokens)")
    self._write(f"   {RAGEmojis.CLOCK} Total: {self._timing(total_ms)}")
    self._write(f"{Colors.BRIGHT_MAGENTA}{'═' * 70}{Colors.RESET}")
    self._write("")

  def embedding_generate(self, text_preview: str, model: str, dimensions: int, timing_ms: float):
    """Log a standalone embedding generation."""
    self._write(f" {RAGEmojis.EMBEDDING} {Colors.YELLOW}EMBEDDING{Colors.RESET}")
    self._write(f"   Text: \"{self._truncate(text_preview, 50)}\"")
    self._write(f"   Model: {model}")
    self._write(f"   {RAGEmojis.VECTOR} Output: {dimensions} dimensions")
    self._write(f"   {RAGEmojis.CLOCK} {self._timing(timing_ms)}")
    self._write("")

  def embedding_error(self, error: str, model: str = ""):
    """Log an error during embedding generation."""
    model_info = f" ({model})" if model else ""
    self._write(f" {RAGEmojis.ERROR} {Colors.RED}EMBEDDING ERROR{model_info}:{Colors.RESET} {error}")

  def qdrant_search(self, collection: str, vector_size: int, limit: int, score_threshold: float):
    """Log a semantic search in Qdrant."""
    self._write(f" {RAGEmojis.QDRANT} {Colors.MAGENTA}QDRANT SEARCH{Colors.RESET}")
    self._write(f"   Collection: {collection}")
    self._write(f"   Vector: {vector_size}d")
    self._write(f"   Limit: {limit}, threshold: {score_threshold}")

  def qdrant_results(self, results: List[Dict], timing_ms: float):
    """Log resultats Qdrant"""
    self._write(f"   {RAGEmojis.FOUND} Resultats: {len(results)}")
    for i, r in enumerate(results[:3]):
      score = r.get("score", 0)
      entry_id = r.get("id", "")[:12]
      self._write(f"    {i+1}. [{self._score_color(score)}{score:.3f}{Colors.RESET}] {entry_id}...")
    self._write(f"   {RAGEmojis.CLOCK} {self._timing(timing_ms)}")

  def qdrant_upsert(self, collection: str, point_id: str, timing_ms: float):
    """Log upsert a Qdrant"""
    self._write(f" {RAGEmojis.QDRANT} {Colors.MAGENTA}QDRANT UPSERT{Colors.RESET}")
    self._write(f"   Collection: {collection}")
    self._write(f"   Point ID: {point_id[:16]}...")
    self._write(f"   {RAGEmojis.CLOCK} {self._timing(timing_ms)}")

  def stats_summary(self, stats: Dict[str, Any]):
    """Log a summary of statistics."""
    self._write("")
    self._write(f"{Colors.BRIGHT_GREEN}{'═' * 70}{Colors.RESET}")
    self._write(f"{RAGEmojis.VECTOR} {Colors.BOLD}{Colors.BRIGHT_GREEN}RAG STATS{Colors.RESET} [{self._timestamp()}]")
    self._write(f"{Colors.BRIGHT_GREEN}{'═' * 70}{Colors.RESET}")
    self._write("")

    if "sqlite" in stats:
      s = stats["sqlite"]
      self._write(f" {RAGEmojis.SQLITE} SQLite:")
      self._write(f"   Total entries: {s.get('total', 0)}")
      self._write(f"   Episodic: {s.get('episodic', 0)}")
      self._write(f"   Semantic: {s.get('semantic', 0)}")

    if "qdrant" in stats:
      q = stats["qdrant"]
      self._write(f" {RAGEmojis.QDRANT} Qdrant:")
      self._write(f"   Collection: {q.get('collection', 'nexe_memory')}")
      self._write(f"   Vectors: {q.get('vectors', 0)}")
      self._write(f"   Dimensions: {q.get('dimensions', 768)}")

    if "flash" in stats:
      f = stats["flash"]
      self._write(f" {RAGEmojis.FLASH} FlashMemory:")
      self._write(f"   Cached: {f.get('entries', 0)}")
      self._write(f"   TTL: {f.get('ttl', 1800)}s")

    self._write(f"{Colors.BRIGHT_GREEN}{'═' * 70}{Colors.RESET}")
    self._write("")

_rag_logger: Optional[RAGLogger] = None

def get_rag_logger(enabled: bool = True) -> RAGLogger:
  """Get the singleton instance of the RAG logger."""
  global _rag_logger
  if _rag_logger is None:
    _rag_logger = RAGLogger(enabled=enabled)
  return _rag_logger

__all__ = ["RAGLogger", "get_rag_logger", "Colors", "RAGEmojis"]