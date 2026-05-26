#!/usr/bin/env bash
# compute-plugin-hash.sh — Calcula el SHA-256 d'un plugin segons ADR-0014.
# Us: ./scripts/compute-plugin-hash.sh <plugin_dir>
# Exemple: ./scripts/compute-plugin-hash.sh plugins-dev/rag
#
# Copia l'output al camp `[integrity].sha256` del manifest.toml del plugin.

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <plugin_dir>" >&2
    exit 2
fi

PLUGIN_DIR="$1"
if [[ ! -d "$PLUGIN_DIR" ]]; then
    echo "error: not a directory: $PLUGIN_DIR" >&2
    exit 2
fi

cd "$(dirname "$0")/.."
ABS_PLUGIN="$(cd "$PLUGIN_DIR" && pwd)"

cd src-tauri
cargo run --quiet --bin plugin-hash -- "$ABS_PLUGIN"
