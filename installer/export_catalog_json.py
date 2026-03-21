"""
------------------------------------
Server Nexe
Location: installer/export_catalog_json.py
Description: Exporta MODEL_CATALOG de Python a JSON per l'app SwiftUI.
------------------------------------
"""

import json
import sys
import os

# Afegir el directori pare al path per poder importar el modul installer
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from installer.installer_catalog_data import MODEL_CATALOG


def export_catalog(output_path: str):
    """Exporta el cataleg de models a un fitxer JSON compatible amb Swift."""
    # MODEL_CATALOG es un dict amb keys "small", "medium", "large"
    # Cada valor es una llista de dicts amb les dades del model
    catalog = {}
    for size, models in MODEL_CATALOG.items():
        catalog[size] = []
        for m in models:
            catalog[size].append({
                "key": m["key"],
                "name": m["name"],
                "origin": m["origin"],
                "year": m.get("year"),
                "lang": m["lang"],
                "params": m["params"],
                "disk_gb": m["disk_gb"],
                "ram_gb": m["ram_gb"],
                "description": m["description"],
                "mlx": m.get("mlx"),
                "ollama": m.get("ollama"),
                "gguf": m.get("gguf"),
                "chat_format": m["chat_format"],
                "prompt_tier": m["prompt_tier"],
            })

    from pathlib import Path
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)

    print(f"Cataleg exportat a: {output_path}")
    print(f"  small:  {len(catalog.get('small', []))} models")
    print(f"  medium: {len(catalog.get('medium', []))} models")
    print(f"  large:  {len(catalog.get('large', []))} models")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        out = sys.argv[1]
    else:
        out = os.path.join(os.path.dirname(__file__), "swift-wizard", "Resources", "models.json")
    export_catalog(out)
