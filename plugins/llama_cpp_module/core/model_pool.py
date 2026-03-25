# -*- coding: utf-8 -*-
"""
ModelPool - Pool d'instàncies Llama vives amb LRU eviction.

PRINCIPI CLAU: El KV cache persistent ve de mantenir la instància VIVA.
NO fem save_state/load_state (massa car). Una sessió = una instància.

Funcionament:
1. Cada session_id té la seva instància Llama
2. Si system_hash canvia → reset (destruir i recrear)
3. LRU eviction quan max_sessions superat
4. gc.collect() per alliberar VRAM

"""
import gc
import threading
import logging
from typing import Dict, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from llama_cpp import Llama

from .config import LlamaCppConfig

logger = logging.getLogger(__name__)


class ModelPool:
    """
    Pool d'instàncies Llama vives amb LRU eviction.

    Attributes:
        config: Configuració del pool
        _instances: Dict session_id → Llama instance
        _hashes: Dict session_id → system_hash (per detectar canvis)
        _lru: Lista ordenada per ús (últim = més recent)
        _lock: Lock per thread-safety
    """

    def __init__(self, config: LlamaCppConfig):
        """
        Inicialitza el pool.

        Args:
            config: Configuració amb model_path, n_ctx, etc.
        """
        self.config = config
        self._instances: Dict[str, "Llama"] = {}
        self._hashes: Dict[str, str] = {}
        self._lru: List[str] = []
        self._lock = threading.Lock()

        logger.info(
            "ModelPool initialized: max_sessions=%d, model=%s",
            config.max_sessions,
            config.model_path[-40:] if config.model_path else "(empty)"
        )

    def get_or_create(self, session_id: str, system_hash: str) -> Tuple["Llama", bool]:
        """
        Retorna instància existent si system_hash coincideix.
        Si no, destrueix i crea nova (reset).

        Args:
            session_id: Identificador de la sessió
            system_hash: Hash del system prompt (de prompt_builder)

        Returns:
            Tuple (instància Llama, reused: bool)
            reused=True si s'ha reutilitzat instància existent (cache hit)
        """
        with self._lock:
            # Cas 1: Sessió existent amb mateix hash → reutilitzar
            if session_id in self._instances:
                if self._hashes[session_id] == system_hash:
                    logger.debug(
                        "ModelPool: reusing instance for session %s (hash match)",
                        session_id[:8]
                    )
                    self._touch_lru(session_id)
                    return self._instances[session_id], True  # Cache HIT
                else:
                    # Hash canviat → reset sessió
                    logger.info(
                        "ModelPool: hash changed for session %s, resetting",
                        session_id[:8]
                    )
                    self._destroy(session_id)

            # Cas 2: Eviction LRU si massa sessions
            while len(self._instances) >= self.config.max_sessions:
                if not self._lru:
                    break
                oldest = self._lru[0]
                logger.info(
                    "ModelPool: LRU eviction, removing session %s",
                    oldest[:8]
                )
                self._destroy(oldest)

            # Cas 3: Crear nova instància
            logger.info(
                "ModelPool: creating new instance for session %s",
                session_id[:8]
            )
            instance = self._create_instance()
            self._instances[session_id] = instance
            self._hashes[session_id] = system_hash
            self._lru.append(session_id)

            logger.info(
                "ModelPool: active sessions=%d/%d",
                len(self._instances),
                self.config.max_sessions
            )

            return instance, False  # Cache MISS

    def _create_instance(self) -> "Llama":
        """
        Crea una nova instància Llama amb la configuració completa.

        Returns:
            Nova instància Llama
        """
        # Import lazy per evitar carregar la lib si no s'usa
        from llama_cpp import Llama

        logger.info(
            "ModelPool: loading model %s (n_ctx=%d, n_batch=%d, gpu_layers=%d, "
            "mlock=%s, mmap=%s, flash_attn=%s)",
            self.config.model_path[-40:],
            self.config.n_ctx,
            self.config.n_batch,
            self.config.n_gpu_layers,
            self.config.use_mlock,
            self.config.use_mmap,
            self.config.flash_attn
        )

        instance = Llama(
            model_path=self.config.model_path,
            n_ctx=self.config.n_ctx,
            n_batch=self.config.n_batch,          # IMPORTANT: més alt = més tok/s
            n_gpu_layers=self.config.n_gpu_layers,
            n_threads=self.config.n_threads,
            chat_format=self.config.chat_format,
            use_mlock=self.config.use_mlock,      # Mantenir a RAM
            use_mmap=self.config.use_mmap,        # Memory-map eficient
            flash_attn=self.config.flash_attn,    # Flash attention
            verbose=False,  # Silenciar output de llama.cpp
        )

        logger.info("ModelPool: model loaded successfully")
        return instance

    def _touch_lru(self, session_id: str) -> None:
        """
        Mou sessió al final de l'LRU (més recent).

        Args:
            session_id: Sessió a actualitzar
        """
        if session_id in self._lru:
            self._lru.remove(session_id)
            self._lru.append(session_id)

    def _destroy(self, session_id: str) -> None:
        """
        Allibera memòria de la instància.

        Args:
            session_id: Sessió a destruir
        """
        if session_id in self._instances:
            instance = self._instances[session_id]

            # Tancar instància si suporta close()
            if hasattr(instance, "close"):
                try:
                    instance.close()
                except Exception as e:
                    logger.warning(
                        "ModelPool: error closing instance: %s", e
                    )

            del self._instances[session_id]
            del self._hashes[session_id]

            if session_id in self._lru:
                self._lru.remove(session_id)

            # Forçar garbage collection per alliberar VRAM
            gc.collect()

            logger.debug(
                "ModelPool: destroyed session %s, gc.collect() called",
                session_id[:8]
            )

    def destroy_all(self) -> None:
        """Destrueix totes les instàncies (cleanup)."""
        with self._lock:
            session_ids = list(self._instances.keys())
            for session_id in session_ids:
                self._destroy(session_id)
            logger.info("ModelPool: all instances destroyed")

    @property
    def active_sessions(self) -> int:
        """Retorna el nombre de sessions actives."""
        return len(self._instances)

    def get_stats(self) -> Dict:
        """Retorna estadístiques del pool."""
        return {
            "active_sessions": len(self._instances),
            "max_sessions": self.config.max_sessions,
            "session_ids": list(self._instances.keys()),
            "lru_order": self._lru.copy(),
        }
