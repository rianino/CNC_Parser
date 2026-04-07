#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

echo ""
echo "  Analise de Vetorizacao — SRTAP"
echo "  =============================="
echo ""

# -------------------------------------------------------
# 1. Find Python
# -------------------------------------------------------
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" -c "import sys; print(sys.version_info >= (3, 10))" 2>/dev/null || echo "False")
        if [ "$version" = "True" ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "  ERRO: Python 3.10+ nao encontrado."
    echo "  Instalar: sudo apt install python3 python3-venv"
    exit 1
fi

# -------------------------------------------------------
# 2. Create virtual environment on first run
# -------------------------------------------------------
if [ ! -d ".venv" ]; then
    echo "  A criar ambiente virtual..."
    "$PYTHON" -m venv .venv
fi

# -------------------------------------------------------
# 3. Activate venv
# -------------------------------------------------------
source .venv/bin/activate

# -------------------------------------------------------
# 4. Install / update dependencies on first run
# -------------------------------------------------------
if [ ! -f ".venv/.deps_installed" ]; then
    echo "  A instalar dependencias (primeira execucao)..."
    pip install --quiet --upgrade pip
    pip install --quiet -e .
    touch .venv/.deps_installed
    echo "  Dependencias instaladas."
    echo ""
fi

# -------------------------------------------------------
# 5. Copy .env.example if .env does not exist
# -------------------------------------------------------
if [ ! -f "app/.env" ] && [ -f "app/.env.example" ]; then
    cp app/.env.example app/.env
    echo "  Ficheiro app/.env criado a partir do exemplo."
    echo "  Editar app/.env com as credenciais SMTP para enviar emails."
    echo ""
fi

# -------------------------------------------------------
# 6. Launch
# -------------------------------------------------------
echo "  A iniciar servidor..."
echo ""
HOST=127.0.0.1 PORT=5050 python app/server.py
