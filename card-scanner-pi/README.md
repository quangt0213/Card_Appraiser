# Card Scanner — Raspberry Pi build kit

Everything you need to turn the `card-scanner/` application into a working, self-contained
device: the **software deployment** layer for the Pi, the **hardware** design (parts,
power, wiring), and the **ESP32-CAM firmware**.

This folder is meant to sit **next to** the application code. On the Pi you'll end up with:

```
~/card-scanner/            <- the application (Flask backend + edge-CV pipeline)
   deploy/                 <- copy the deploy/ files from here into the app folder
~/card-scanner-pi/         <- this kit (hardware docs + firmware live here)
```

## What's in here

```
deploy/
  install.sh              One-shot Pi installer: system libs, venv, deps, DB init
  install_service.sh      Install + enable the systemd service (substitutes your paths)
  card-scanner.service    systemd unit: runs the backend on boot, restarts on failure
  kiosk-autostart.sh      Boot Chromium full-screen onto /display (Wayland + X)
  env.pi.example          Production-leaning .env overrides for the Pi
  README-PI.md            Step-by-step deploy guide + troubleshooting
hardware/
  BILL_OF_MATERIALS.md    Everything to buy, with notes and ballpark prices
  POWER_AND_WIRING.md     Single-cable 5 V design, brown-out fixes, pin-by-pin wiring
  wiring_diagram.svg      Labelled wiring diagram (open in a browser)
firmware/
  esp32cam_scanner/esp32cam_scanner.ino   Capture-on-button, POST JPEG to Pi /scan
  README.md               Arduino board settings + flashing (dock or USB-TTL)
```

## Build order (fastest path to a working unit)

1. **Software** — copy the app to the Pi, `bash deploy/install.sh`, then
   `bash deploy/install_service.sh`. Confirm `http://<pi-ip>:5000/health` → `ok: true`.
   Full steps: [`deploy/README-PI.md`](deploy/README-PI.md).
2. **Kiosk** — `bash deploy/kiosk-autostart.sh && sudo reboot` for the touchscreen.
3. **Hardware** — gather parts from [`hardware/BILL_OF_MATERIALS.md`](hardware/BILL_OF_MATERIALS.md);
   wire power per [`hardware/POWER_AND_WIRING.md`](hardware/POWER_AND_WIRING.md) (see the
   diagram). One 5 V / 4–5 A supply feeds both the Pi and the camera.
4. **Firmware** — flash the ESP32-CAM ([`firmware/README.md`](firmware/README.md)), set your
   Wi-Fi + the Pi's IP, press the button, watch a card get priced.

## The three things people get wrong (so you don't)

- **Underpowering.** Use a **5 V / 4–5 A** supply, not a bare 3 A Pi brick — the Pi plus
  the camera exceeds it under load.
- **Skipping the capacitor.** A **1000 µF** cap across the ESP32-CAM's 5 V/GND is what
  stops the "Brownout detector triggered" resets. Not optional.
- **Bad lighting / loose framing.** A fixed card mount + even diffused light improves
  recognition more than any software tuning. Nail the optics.

## How the pieces talk

```
[Card] --(camera)--> [ESP32-CAM] --Wi-Fi: POST /scan (JPEG)--> [Raspberry Pi backend]
                                                                   | detect+warp
                                                                   | recognize (number/pHash/OCR)
                                                                   | price (recent sales)
                                                                   v
                                                          [Touchscreen /display]
```

Only **power** runs over the internal cable; the camera↔Pi link is Wi-Fi. That's why a
single 5 V rail is all the wiring you need inside the enclosure.
