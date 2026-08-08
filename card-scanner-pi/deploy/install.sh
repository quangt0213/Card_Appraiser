#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Card Scanner - Raspberry Pi installer
# Run from inside the card-scanner application folder:
#     cd ~/card-scanner
#     bash deploy/install.sh
# It sets up system libs, a Python venv, the app deps, the database, and the
# first TCGCSV catalog sync. Idempotent: safe to re-run.
# ---------------------------------------------------------------------------
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$APP_DIR/.venv"
PY="${PYTHON:-python3}"

echo "==> App directory: $APP_DIR"

# 1. System packages (OpenCV runtime libs + venv + build basics)
echo "==> Installing system packages (sudo)..."
sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-pip \
  libgl1 libglib2.0-0 libatlas-base-dev \
  libjpeg-dev zlib1g-dev

# 2. Python virtual environment
if [ ! -d "$VENV" ]; then
  echo "==> Creating virtualenv at $VENV"
  "$PY" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip wheel

# 3. Python dependencies (EasyOCR pulls in torch -- this is the slow step)
echo "==> Installing Python dependencies (this can take a while: torch)..."
pip install -r "$APP_DIR/requirements.txt"

# 4. Environment file
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "==> Created .env from .env.example -- review it (games, thresholds, provider)."
fi

# 5. Database
echo "==> Initializing database..."
python "$APP_DIR/database/init_db.py"
python "$APP_DIR/database/seed_sample_cards.py" || true

# 6. Kick a first catalog sync note (the app also syncs in the background on boot)
echo ""
echo "==> Install complete."
echo "    Start it now with:   source .venv/bin/activate && python app.py"
echo "    Or install the service:   bash deploy/install_service.sh"
echo ""
echo "    NOTE: the first TCGCSV catalog sync downloads a few hundred small JSON"
echo "    files and can take a few minutes on a Pi. It runs in the background on"
echo "    first boot; identity/pricing get more complete as it finishes."
