# -*- coding: utf-8 -*-
"""
LlamaCppConfig - Configuració centralitzada per llama-cpp-python.

Totes les opcions es poden configurar via variables d'entorn:
- NEXE_LLAMA_CPP_MODEL: Ruta al fitxer .gguf
- NEXE_LLAMA_CPP_N_CTX: Context window (default: 8192)
- NEXE_LLAMA_CPP_N_BATCH: Batch size per generació (default: 512) - MÉS ALT = MÉS RÀPID
- NEXE_LLAMA_CPP_GPU_LAYERS: Capes a GPU, -1=tot (default: -1)
- NEXE_LLAMA_CPP_THREADS: CPU threads (default: 8)
- NEXE_LLAMA_CPP_MAX_SESSIONS: Sessions actives màxim (default: 1)
- NEXE_LLAMA_CPP_CHAT_FORMAT: Format del chat (default: gemma)
- NEXE_LLAMA_CPP_USE_MLOCK: Mantenir model a RAM (default: true)
- NEXE_LLAMA_CPP_USE_MMAP: Memory-map del model (default: true)
- NEXE_LLAMA_CPP_FLASH_ATTN: Flash attention (default: true)

"""
import os
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class LlamaCppConfig:
    """
    Configuració per llama-cpp-python.

    Attributes:
        model_path: Ruta absoluta al fitxer .gguf
        n_ctx: Context window en tokens (conservador per 27B)
        n_batch: Batch size per generació (512-2048, més alt = més ràpid)
        n_gpu_layers: Capes a carregar a GPU (-1 = totes, Metal)
        n_threads: Threads de CPU per inferència
        max_sessions: Màxim de sessions actives (LRU eviction)
        chat_format: Format del chat template (gemma, llama-2, chatml, mistral)
        use_mlock: Mantenir model a RAM (evita swapping)
        use_mmap: Memory-map del model (més eficient)
        flash_attn: Flash attention (més ràpid si suportat)
    """

    model_path: str = ""
    n_ctx: int = 8192
    n_batch: int = 512  # IMPORTANT: més alt = més tok/s
    n_gpu_layers: int = -1
    n_threads: int = 0  # 0 = auto (llama.cpp usarà tots els cores)
    max_sessions: int = 2  # 2 per defecte: permet canvi de system_hash sense reload
    chat_format: str = "chatml"  # chatml és compatible amb Phi-3.5, Llama 3, Salamandra
    use_mlock: bool = True
    use_mmap: bool = True
    flash_attn: bool = True

    def __post_init__(self):
        """Valida la configuració després de crear-la."""
        if not self.model_path:
            logger.warning(
                "LlamaCppConfig: model_path buit. "
                "Configura NEXE_LLAMA_CPP_MODEL o passa model_path."
            )
        # Expandir ~ a home directory
        if self.model_path.startswith("~"):
            self.model_path = os.path.expanduser(self.model_path)
        # Resolve relative paths based on project root
        elif not os.path.isabs(self.model_path):
            from pathlib import Path
            project_root = Path(__file__).parents[2]  # From plugins/llama_cpp_module/ to project root
            self.model_path = str(project_root / self.model_path)

    @classmethod
    def from_env(cls) -> "LlamaCppConfig":
        """
        Carrega configuració de variables d'entorn.

        Returns:
            LlamaCppConfig amb valors de l'entorn o defaults.
        """
        config = cls(
            model_path=os.getenv("NEXE_LLAMA_CPP_MODEL", ""),
            n_ctx=int(os.getenv("NEXE_LLAMA_CPP_N_CTX", "8192")),
            n_batch=int(os.getenv("NEXE_LLAMA_CPP_N_BATCH", "512")),
            n_gpu_layers=int(os.getenv("NEXE_LLAMA_CPP_GPU_LAYERS", "-1")),
            n_threads=int(os.getenv("NEXE_LLAMA_CPP_THREADS", str(os.cpu_count() or 8))),
            max_sessions=int(os.getenv("NEXE_LLAMA_CPP_MAX_SESSIONS", "2")),
            chat_format=os.getenv("NEXE_LLAMA_CPP_CHAT_FORMAT", "chatml"),
            use_mlock=os.getenv("NEXE_LLAMA_CPP_USE_MLOCK", "true").lower() == "true",
            use_mmap=os.getenv("NEXE_LLAMA_CPP_USE_MMAP", "true").lower() == "true",
            flash_attn=os.getenv("NEXE_LLAMA_CPP_FLASH_ATTN", "true").lower() == "true",
        )

        logger.info(
            "LlamaCppConfig loaded: model=%s, n_ctx=%d, n_batch=%d, gpu_layers=%d, "
            "threads=%d, mlock=%s, mmap=%s, flash_attn=%s",
            config.model_path[-40:] if config.model_path else "(empty)",
            config.n_ctx,
            config.n_batch,
            config.n_gpu_layers,
            config.n_threads,
            config.use_mlock,
            config.use_mmap,
            config.flash_attn,
        )

        return config

    def validate(self) -> bool:
        """
        Valida que la configuració és correcta.

        Returns:
            True si la config és vàlida, False si no.
        """
        if not self.model_path:
            logger.error("LlamaCppConfig: model_path is required")
            return False

        if not os.path.exists(self.model_path):
            logger.error(
                "LlamaCppConfig: model_path no existeix: %s",
                self.model_path
            )
            return False

        if self.n_ctx < 512:
            logger.error("LlamaCppConfig: n_ctx minimum is 512")
            return False

        if self.max_sessions < 1:
            logger.error("LlamaCppConfig: max_sessions minimum is 1")
            return False

        valid_formats = {"gemma", "llama-2", "llama-3", "chatml", "mistral", "alpaca", "phi-3"}
        if self.chat_format not in valid_formats:
            logger.warning(
                "LlamaCppConfig: chat_format '%s' no reconegut. "
                "Formats vàlids: %s",
                self.chat_format,
                valid_formats
            )

        return True
