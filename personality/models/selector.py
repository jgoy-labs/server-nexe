"""
────────────────────────────────────
Server Nexe
Author: Jordi Goy 
Location: personality/models/selector.py
Description: Hardware detection logic and profile selection.

www.jgoy.net · https://server-nexe.org
────────────────────────────────────
"""

import psutil
import platform
import logging
import shutil

from .profiles import PROFILES, HardwareTier, ModelProfile, EngineType

logger = logging.getLogger(__name__)

class HardwareProfile:
    """Snapshot of the host machine's hardware capabilities."""
    def __init__(self):
        self.system = platform.system()
        self.processor = platform.processor()
        self.machine = platform.machine() # 'arm64' for apple silicon
        self.total_ram_gb = round(psutil.virtual_memory().total / (1024**3), 2)
        self.is_apple_silicon = self.system == "Darwin" and self.machine == "arm64"
        self.has_cuda = False  # NVIDIA detection not implemented

    def __str__(self):
        return (f"Hardware: {self.system} {self.machine}, "
                f"RAM: {self.total_ram_gb}GB, "
                f"Apple Silicon: {self.is_apple_silicon}")

class ModelSelector:
    """Selects the best model profile based on the hardware."""
    
    def __init__(self):
        """Initialize the selector with a fresh hardware profile."""
        self.hw = HardwareProfile()
        
    def analyze(self) -> HardwareProfile:
        """Return the detected hardware profile."""
        return self.hw

    def recommend(self) -> ModelProfile:
        """Return the recommended profile."""
        tier = self._determine_tier()
        profile = PROFILES[tier].model_copy() # Copy to modify engine if needed

        # Adjust engine based on actual hardware
        if self.hw.is_apple_silicon:
            profile.preferred_engine = EngineType.MLX
        elif self._check_ollama_available():
            profile.preferred_engine = EngineType.OLLAMA
        else:
            profile.preferred_engine = EngineType.LLAMA_CPP # CPU fallback
            
        logger.info(f"Recommended Profile: {tier.value} for {self.hw}")
        return profile
    
    def _determine_tier(self) -> HardwareTier:
        """Determine the hardware tier based on total RAM."""
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
        """Check whether the Ollama binary is available on PATH."""
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
        # #1002: `max_tokens` and `context_window` are NOT written back. The
        # profile still carries them (they describe the hardware tier and the
        # CLI prints them), but nothing reads them out of server.toml — the
        # window is asked of the live engine (#965). Writing them created a
        # key that looked authoritative and governed nothing.

        return config
