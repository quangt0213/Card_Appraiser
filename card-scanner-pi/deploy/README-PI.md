# Raspberry Pi deployment guide

This gets the Card Scanner backend running on a Raspberry Pi 4 and booting straight
into the touchscreen view. It assumes the application code (the `card-scanner/`
project) is already copied onto the Pi.

## 0. Prerequisites

- Raspberry Pi 4 (2 GB is enough; 4 GB comfortable) running Raspberry Pi OS (64-bit
  recommended — EasyOCR/torch wheels are much easier on 64-bit).
- The `card-scanner/` app folder on the Pi, e.g. at `/home/pi/card-scanner`.
- Network access for the first install and the first catalog sync.

Copy the app across (from your dev machine):

```bash
rsync -av --exclude '.venv' --exclude 'data' card-scanner/ pi@raspberrypi.local:~/card-scanner/
# then copy these deployment files in beside it:
rsync -av card-scanner-pi/deploy/ pi@raspberrypi.local:~/card-scanner/deploy/
```

## 1. Install

```bash
cd ~/card-scanner
bash deploy/install.sh
```

This installs system libs (`libgl1`, `libglib2.0-0`, …), creates `.venv`, installs
`requirements.txt` (EasyOCR/torch is the slow part), creates `.env`, and initializes
the database.

Then apply the Pi-tuned settings on top of your `.env`:

```bash
# review and merge the production-leaning values:
cat deploy/env.pi.example >> .env   # or hand-merge; later keys win
nano .env
```

## 2. Run it (foreground, to confirm it works)

```bash
source .venv/bin/activate
python app.py
# visit http://<pi-ip>:5000/health  and  http://<pi-ip>:5000/display
```

`/health` should return JSON with `ok: true`. The first TCGCSV catalog sync runs in
the background; identity/pricing coverage fills in over the next few minutes.

## 3. Run on boot (systemd)

```bash
bash deploy/install_service.sh          # substitutes your user + path, enables the service
systemctl status card-scanner
journalctl -u card-scanner -f           # live logs
```

## 4. Touchscreen kiosk

With the backend running, make Chromium boot full-screen onto `/display`:

```bash
bash deploy/kiosk-autostart.sh
sudo reboot
```

The script handles both Bookworm (Wayland/labwc/wayfire) and older X/LXDE, and
disables screen blanking so the display stays on.

## 5. Point the ESP32-CAM at the Pi

In `firmware/esp32cam_scanner/esp32cam_scanner.ino`, set:

```cpp
const char* PI_HOST = "192.168.1.50";   // your Pi's LAN IP
const int   PI_PORT = 5000;
```

Give the Pi a static/reserved IP on your router so this never drifts. Test the endpoint
from any machine before wiring the camera in:

```bash
curl -X POST -H "Content-Type: image/jpeg" --data-binary @sample-card.jpg \
  http://<pi-ip>:5000/scan
```

## Troubleshooting

- **First scan is slow / times out.** EasyOCR loads its model on first use. The service
  file allows 120 s to start, and the app warms the model at boot — give it a minute
  after a fresh start.
- **`ImportError: libGL.so.1`.** Install `libgl1 libglib2.0-0` (the installer does this).
- **Torch won't install.** Use 64-bit Raspberry Pi OS; 32-bit lacks easy torch wheels.
- **Prices show `market_fallback:...`.** The live-sales lookup failed for that card and
  the system fell back to the cached market price — expected and safe.
- **Camera resets / "Brownout detector triggered".** Power problem — see
  `../hardware/POWER_AND_WIRING.md` (add the bulk capacitor, use thicker/shorter 5 V leads).
- **SD-card wear.** Keep `DEBUG=false`; optionally point `CANDIDATE_TEMP_DIR` at `/dev/shm`.
