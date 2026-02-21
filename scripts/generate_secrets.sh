#!/usr/bin/env bash
# Script per generar secrets segurs per Nexe Server
# Usage: ./scripts/generate_secrets.sh

set -e

echo "🔐 Generant secrets segurs per Nexe Server..."
echo ""

# Generar NEXE_PRIMARY_API_KEY
PRIMARY_KEY=$(openssl rand -hex 32)
echo "NEXE_PRIMARY_API_KEY=${PRIMARY_KEY}"

# Generar NEXE_CSRF_SECRET
CSRF_SECRET=$(openssl rand -hex 32)
echo "NEXE_CSRF_SECRET=${CSRF_SECRET}"

echo ""
echo "✅ Secrets generats correctament!"
echo ""
echo "📋 Afegeix aquests valors al teu fitxer .env"
echo ""
echo "⚠️  IMPORTANT:"
echo "   - NO comparteixis aquests secrets"
echo "   - NO els pugis al repositori"
echo "   - Guarda'ls en un gestor de contrasenyes segur"
echo ""
