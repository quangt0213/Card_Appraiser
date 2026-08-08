#!/usr/bin/env bash
# Configure the Pi to boot straight into a full-screen Chromium showing the
# scanner's /display page (the Freenove touchscreen view).
#
# Works on Raspberry Pi OS Bookworm (labwc/wayfire Wayland) AND older X/LXDE.
# Run on the Pi:  bash deploy/kiosk-autostart.sh
set -euo pipefail

URL="http://localhost:5000/display"
CHROMIUM="$(command -v chromium-browser || command -v chromium || echo chromium-browser)"
FLAGS="--kiosk --noerrdialogs --disable-infobars --incognito --check-for-update-interval=31536000 $URL"

echo "==> Installing chromium if missing..."
sudo apt-get install -y chromium-browser || sudo apt-get install -y chromium

# --- Wayland (Bookworm default: labwc or wayfire) ---
if [ -f "$HOME/.config/wayfire.ini" ] || [ "${XDG_SESSION_TYPE:-}" = "wayland" ]; then
  mkdir -p "$HOME/.config"
  if ! grep -q "card-scanner-kiosk" "$HOME/.config/wayfire.ini" 2>/dev/null; then
    cat >> "$HOME/.config/wayfire.ini" <<EOF

[autostart]
# card-scanner-kiosk
chromium = $CHROMIUM $FLAGS
screensaver = false
dpms = false
EOF
    echo "==> Added kiosk autostart to ~/.config/wayfire.ini (Wayland)."
  fi
fi

# --- X / LXDE (older Raspberry Pi OS) ---
AUTOSTART_DIR="$HOME/.config/lxsession/LXDE-pi"
mkdir -p "$AUTOSTART_DIR"
AUTOSTART="$AUTOSTART_DIR/autostart"
if ! grep -q "card-scanner-kiosk" "$AUTOSTART" 2>/dev/null; then
  cat >> "$AUTOSTART" <<EOF
# card-scanner-kiosk
@xset s off
@xset -dpms
@xset s noblank
@$CHROMIUM $FLAGS
EOF
  echo "==> Added kiosk autostart for LXDE (X)."
fi

echo "==> Done. Reboot to launch the kiosk:  sudo reboot"
echo "    Make sure the backend service is running first (systemctl status card-scanner)."
