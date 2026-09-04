# Card Scanner — Run & Debug Guide

Everything you need to run the scanner on the Raspberry Pi and, crucially, to open the
**debug monitor** from any computer on the same network to see the images the camera is
sending and why each scan did or didn't match.

For the deep, file-by-file architecture, see `ARCHITECTURE.md`. This guide is the
practical "how do I run it and watch it work" companion.

---

## What the project does

A physical trading-card scanner. An **ESP32-CAM** photographs a card and POSTs the JPEG
over Wi-Fi to a **Flask backend on a Raspberry Pi 4**, which identifies the card and shows
its market value on a **touchscreen**. Target game is One Piece TCG (Pokémon also
supported).

The recognition flow, in order: the Pi saves the incoming image, detects and
perspective-corrects the card, tries a fast local **perceptual-hash** match against cards
it has seen before, and only if that's inconclusive runs **EasyOCR** on the name/number,
cleans the text with **RapidFuzz**, looks the card up in a local catalog, ranks the
candidates, and fetches a price. A confident match is saved (with its hash) so the next
scan of that card resolves instantly and offline — the device "learns."

The screen holds a matched result until the user taps **Scan next card**; anything that
isn't a confident match just shows the idle screen.

---

## Key design choices (short version)

- **OpenCV-first, escalate only as needed.** Cheap, discriminative signals (collector
  number + perceptual hash) run first; heavy tools (OCR, network lookups) only when needed.
- **Learn as you go.** Confident matches are cached to SQLite with their hash, so repeat
  scans are local and offline.
- **Swappable data sources.** Card data and pricing sit behind provider interfaces, so you
  change sources with one `.env` line. Default is the free, keyless TCGCSV mirror; a mock
  provider lets the whole app run offline for tests.
- **The Pi paces the scan, the screen controls it.** The camera scans continuously; the Pi
  holds a match and the touchscreen's "Scan next card" button resumes it. No timers.
- **A polled JSON file drives the display** (atomic writes), so it's restart-safe and needs
  no websocket plumbing.

Full reasoning and the rejected alternatives are in `ARCHITECTURE.md`.

---

## Tech stack

| Layer | Tech | Role |
| --- | --- | --- |
| Camera firmware | **C/C++** (ESP32 Arduino core: `esp_camera`, `WiFi`, `HTTPClient`) | Capture a JPEG, POST it to the Pi |
| Backend | **Python 3** + **Flask** | Web API + server-rendered pages |
| Computer vision | **OpenCV** (headless) + **NumPy** | Card detection, perspective warp, perceptual hash, ORB |
| OCR | **EasyOCR** (on CPU-only **PyTorch**) | Read the card name / number |
| Text matching | **RapidFuzz** | Normalize + fuzzy-match OCR text |
| Data / pricing | **requests** → TCGCSV (default) / TCGplayer sales / TCGAPIs (optional) | Catalog + market price |
| Storage | **SQLite** (stdlib `sqlite3`) | Card cache, scan history, learned hashes |
| Display | **HTML + CSS + JS** (Jinja2 templates) in kiosk **Chromium** | Touchscreen UI + debug monitor |
| Deploy / boot | **Bash**, **systemd**, **labwc** autostart | Install, run on boot, kiosk |
| Enclosure | **STL** models | 3D-printed camera pod + housing |

---

## Running the backend on the Pi

The backend normally runs as a **systemd service** that starts on boot:

```bash
sudo systemctl status card-scanner      # is it running?
sudo systemctl restart card-scanner     # apply code/template changes
journalctl -u card-scanner -f           # live logs (Ctrl+C to stop watching)
```

To run it by hand instead (useful for watching logs directly while debugging):

```bash
cd ~/card-scanner
source .venv/bin/activate
python app.py
```

Either way it listens on **all interfaces, port 5000** (`HOST=0.0.0.0`, `PORT=5000` in
`.env`), so it's reachable from other machines on your network.

Confirm it's up (from the Pi or another computer):

```bash
curl http://<pi-ip>:5000/health         # e.g. http://10.0.0.64:5000/health -> {"ok": true, ...}
```

> After editing any template (`display.html`, `debug.html`) you must
> `sudo systemctl restart card-scanner` — Flask caches templates outside debug mode.

---

## The debug monitor (open it on your computer)

The backend serves a browser-friendly monitor at **`/debug`**. It looks like the Pi's home
screen but also shows the **exact image the ESP32-CAM last sent**, plus every recognition
detail — so you can aim and focus the camera and see why a scan matched or didn't, all from
your desk.

**Open it from any computer on the same Wi-Fi:**

```
http://<pi-ip>:5000/debug
```

### What you see

- **Left — Last image received by the Pi:** the newest non-empty JPEG the camera POSTed,
  auto-refreshing about once a second, with its filename, size, and age.
- **Right — Recognition result:** Match / Idle verdict, card name, set and collector
  number, the big price, and a details table: confidence, source (local vs remote),
  method, price basis, the no-match reason, the raw OCR text, and the update time.

### How to use it to debug

1. Point the camera at a card and watch the left panel. Adjust distance, rotate the lens
   barrel to focus, and fix lighting until the card fills most of the frame, is sharp, and
   has no glare on the name or number.
2. Read the right panel:
   - **Image looks good but "no candidates"** → framing/OCR problem: get the collector
     number larger and sharper, reduce glare.
   - **A low-confidence best guess** → it's close; consider lowering
     `REMOTE_MATCH_THRESHOLD` in `.env` (default 0.60), or improve the image.
   - **Match with a price** → done; confidence and source tell you if it was a local
     (learned) hit or a fresh lookup.
3. The image endpoint is also directly viewable / linkable:
   `http://<pi-ip>:5000/debug/latest.jpg`, and the raw state as JSON at
   `http://<pi-ip>:5000/debug/state`.

> Note: while a match is being *held* on the touchscreen, the Pi ignores new frames until
> you tap "Scan next card," so the debug image won't change during a hold. Tap it (or scan
> a new card) to resume the live stream of frames.

### Deploying these debug files

The monitor is two files in the app — copy them to the Pi (FileZilla) and restart:

- `routes/ui_routes.py`  → `~/card-scanner/routes/ui_routes.py`
- `templates/debug.html` → `~/card-scanner/templates/debug.html`

```bash
sudo systemctl restart card-scanner
# then open http://<pi-ip>:5000/debug on your computer
```

---

## Quick troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| `/debug` unreachable from your PC | Backend not running (`systemctl status card-scanner`), wrong Pi IP, or firewall. Test `curl http://<pi-ip>:5000/health`. |
| Debug image is 0 bytes / not updating | Camera sending failed/empty frames — check the ESP32 serial monitor; see the camera notes in `../card-scanner-pi/firmware`. |
| Image blurry / dark / striped | Optics, not software — focus the lens, add light, and see the "blurry cameras" section in `ARCHITECTURE.md`. |
| Good image but "no candidates" | Framing/OCR — enlarge and sharpen the collector number; ensure the catalog finished syncing. |
| Prices tagged `market_fallback` | Live-sales lookup failed for that card; it fell back to the cached market price. Expected and safe. |
| Template edits not showing | `sudo systemctl restart card-scanner` (Flask caches templates). |

---

## Handy URLs (replace `<pi-ip>`, e.g. `10.0.0.64`)

- `http://<pi-ip>:5000/display` — the touchscreen home screen
- `http://<pi-ip>:5000/debug` — the debug monitor (this guide)
- `http://<pi-ip>:5000/debug/latest.jpg` — the newest received frame
- `http://<pi-ip>:5000/debug/state` — current state as JSON
- `http://<pi-ip>:5000/health` — service health
- `http://<pi-ip>:5000/history?limit=25` — recent scans as JSON
