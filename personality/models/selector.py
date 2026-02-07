"""
────────────────────────────────────
Server Nexe
Version: 0.8
Author: Jordi Goy 
Location: personality/models/selector.py
Description: Hardware detection logic and profile selection.

www.jgoy.net
────────────────────────────────────
"""

import psutil
import platform
import logging
import shutil
from typing import Tuple

from personality.i18n.resolve import t_modular

from .profiles import PROFILES, HardwareTier, ModelProfile, EngineType

logger = logging.getLogger(__name__)

class HardwareProfile:
    def __init__(self):
        self.system = platform.system()
        self.processor = platform.processor()
        self.machine = platform.machine() # 'arm64' for Apple Silicon
        self.total_ram_gb = round(psutil.virtual_memory().total / (1024**3), 2)
        self.is_apple_silicon = self.system == "Darwin" and self.machine == "arm64"
        self.has_cuda = False # TODO: Detect NVIDIA

    def __str__(self):
        return (f"Hardware: {self.system} {self.machine}, "
                f"RAM: {self.total_ram_gb}GB, "
                f"Apple Silicon: {self.is_apple_silicon}")

class ModelSelector:
    """Select the best model profile based on hardware."""
    
    def __init__(self):
        self.hw = HardwareProfile()
        
    def analyze(self) -> HardwareProfile:
        return self.hw

    def recommend(self) -> ModelProfile:
        """Return the recommended profile."""
        tier = self._determine_tier()
        profile = PROFILES[tier].model_copy() # Copy to modify engine if needed
        
        # Adjust engine based on real hardware
        if self.hw.is_apple_silicon:
            profile.preferred_engine = EngineType.MLX
        elif self._check_ollama_available():
            profile.preferred_engine = EngineType.OLLAMA
        else:
            profile.preferred_engine = EngineType.LLAMA_CPP # CPU fallback
            
        logger.info(
            t_modular(
                "models.selector.recommended_profile",
                "Recommended Profile: {tier} for {hardware}",
                tier=tier.value,
                hardware=self.hw,
            )
        )
        return profile
    
    def _determine_tier(self) -> HardwareTier:
        ram = self.hw.total_ram_gb
        
        if ram < 8:
            return HardwareTier.MICRO
        elif ram < 16:
            return HardwareTier.CONSUMER
        elif ram < 32:
            return HardwareTier.PRO
        else:
            return HardwareTier.ULTRA

    def _check_ollama_available(self) -> bool:
        return shutil.which("ollama") is not None

    def apply_to_config(self, config: dict, profile: ModelProfile) -> dict:
        """Apply the profile to the loaded configuration (server.toml object)."""
        if "plugins" not in config:
            config["plugins"] = {}
        if "models" not in config["plugins"]:
            config["plugins"]["models"] = {}
            
        models_cfg = config["plugins"]["models"]
        models_cfg["preferred_engine"] = profile.preferred_engine.value
        models_cfg["primary"] = profile.primary_model
        models_cfg["secondary"] = profile.secondary_model
        models_cfg["embedding"] = profile.embedding_model
        models_cfg["max_tokens"] = profile.max_tokens
        models_cfg["context_window"] = profile.context_window
        
        return config
