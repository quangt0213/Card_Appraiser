#!/usr/bin/env bash
# Install + enable the systemd services (backend + optional kiosk display).
# Run from the app folder:  bash deploy/install_service.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(whoami)"

echo "==> Rendering unit for user=$USER_NAME, dir=$APP_DIR"

# Backend service, with paths/user substituted to match this machine.
sed -e "s|/home/pi/card-scanner|$APP_DIR|g" \
    -e "s|^User=pi|User=$USER_NAME|" \
    "$APP_DIR/deploy/card-scanner.service" | sudo tee /etc/systemd/system/card-scanner.service >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable --now card-scanner
echo "==> Backend service enabled. Status:  systemctl status card-scanner"
echo "    Logs:  journalctl -u card-scanner -f"
echo ""
echo "For the touchscreen kiosk, see deploy/README-PI.md (section 'Touchscreen kiosk')."
