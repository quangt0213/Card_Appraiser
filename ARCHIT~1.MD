# Card Scanner — Architecture & File Journey

A study-and-debugging companion to the codebase. It explains, in plain language,
what every file does, how a scan travels from folder to folder, which language and
libraries each part uses and **why**, and — importantly for debugging — what
alternatives were considered and rejected. The last section covers the current
frontier: getting sharp, high-quality images out of the camera.

Read it top to bottom the first time; after that, jump to the folder you're debugging.

---

## 1. The system at a glance — three devices, three languages

The product is really three small computers cooperating over your home Wi-Fi:

```
   ┌────────────────┐     JPEG over Wi-Fi      ┌────────────────────────┐      renders      ┌──────────────────┐
   │  ESP32-CAM     │  ───────────────────▶    │  Raspberry Pi 4        │  ─────────────▶   │  Touchscreen      │
   │  (the camera)  │   HTTP POST /scan         │  (the brain: Flask)    │   HTML /display   │  (the face)       │
   │  C / C++       │                           │  Python                │                   │  HTML + CSS + JS  │
   └────────────────┘   ◀───────────────────    └────────────────────────┘                   └──────────────────┘
                          JSON result (matched?, price)
```

- **The camera (ESP32-CAM)** is a tiny microcontroller with a lens. Its only job is:
  take a photo and POST the raw JPEG to the Pi, then read back the answer. Written in
  **C/C++** (the Arduino dialect).
- **The brain (Raspberry Pi 4)** runs the whole recognition-and-pricing pipeline as a
  **Python** web service (Flask). This is where 90% of the code lives.
- **The face (touchscreen)** is a full-screen web page the Pi serves to a Chromium
  kiosk. Written as an **HTML/CSS/JavaScript** template.

Everything else in the repo supports these three: a **SQL** schema for the database,
**Bash** scripts to install and boot the Pi, and **STL** 3D-model files for the
physical enclosure.

---

## 2. The languages, and why each was chosen

**C/C++ (Arduino) — only on the ESP32-CAM.** Microcontrollers don't run Python; they
run compiled native code with no operating system. The ESP32 Arduino core gives us
ready-made `WiFi`, `HTTPClient`, and `esp_camera` libraries, so the firmware stays
short. *Alternative considered:* MicroPython (Python on the ESP32). Rejected because the
camera + Wi-Fi drivers are far more mature and memory-efficient in C, and camera
streaming in MicroPython is fiddly on this board.

**Python — the entire Raspberry Pi backend.** This is the natural home for computer
vision and OCR: OpenCV, EasyOCR, NumPy, and RapidFuzz are all first-class in Python,
and Flask makes the web layer tiny. Python's readability also matters for a project
meant to be studied and extended. *Alternative considered:* Node.js. Rejected because
the CV/OCR ecosystem there is thin and would mean shelling out to Python anyway.

**HTML + CSS + JavaScript — the touchscreen page.** The display is just a web page in a
full-screen browser, so the "UI toolkit" is the browser itself — no native GUI
framework to install. The page is rendered by Flask's built-in Jinja2 templating.
*Alternative considered:* a desktop GUI (Tkinter/Qt). Rejected because a browser page is
easier to style beautifully, trivially themeable, and needs nothing extra on the Pi (a
kiosk browser was already required).

**SQL — the database schema.** SQLite understands SQL; the schema file is the one place
that defines tables and indexes. Plain and portable.

**Bash — deployment and boot.** Installing system packages, creating the Python virtual
environment, and wiring up the systemd service and kiosk autostart are all shell chores,
so they live in `.sh` scripts.

**STL — the 3D-printed enclosure.** STL is the standard "mesh" format every slicer and
printer understands; the `models/` folder holds the printable parts.

A recurring Python pattern worth noting once: **every module says
`from __future__ import annotations` and uses type hints** (`def detect(img) -> DetectedCard`).
This makes the code self-documenting and lets editors catch mistakes, without any runtime
cost. Data is passed around as small **`@dataclass`** objects (like `DetectedCard`,
`CandidateCard`, `PriceQuote`) rather than loose dictionaries, so the shape of the data is
always clear.

---

## 3. The journey of one scan (folder to folder)

This is the single most useful mental model. Follow one photo from shutter to price:

1. **`firmware/esp32cam_scanner/esp32cam_scanner.ino`** — the camera captures a JPEG and
   does `HTTP POST /scan` with the raw bytes as the body. It then waits for the JSON reply
   and reads the `"matched"` flag.

2. **`routes/scan_routes.py`** (`/scan`) — the Pi's front door. It validates the upload
   (non-empty, not too large, real JPEG magic bytes). If the Pi is currently *holding* a
   previous match (see the gate, step 10), it short-circuits here and returns the held
   result without doing any work. Otherwise it hands the bytes to the pipeline.

3. **`services/job_service.py`** — runs the pipeline on a worker thread with a timeout, so
   one slow scan can't wedge the web server. The route calls `run_blocking(...)` and waits.

4. **`services/scan_pipeline.py`** — the orchestrator that ties everything together. Its
   `process()` method drives the rest of the journey. First it **saves the raw image** to
   `data/scans/` via `storage_manager.py` (so even a failed scan leaves evidence on disk),
   then decodes the JPEG into an OpenCV image.

5. **`services/card_detector.py`** — finds the card's rectangle in the messy photo and
   **perspective-warps** it into a clean, upright, fixed-size card. It also crops the
   **title strip** (top) and **collector-number strip** (bottom). This is the biggest
   accuracy lever: everything downstream sees a flat, framed card instead of a tilted
   photo of a desk.

6. **`services/image_matcher.py`** — computes a **perceptual hash (pHash)** of the warped
   card and compares it (by Hamming distance) against an **in-memory index** of cards
   we've seen before. If a close match exists, we're basically done — no OCR, no network.
   ORB features break ties on a short list. This is the "have I seen this exact card
   before?" fast path.

7. **`services/ocr_service.py`** — only runs if the local match was weak. It uses EasyOCR
   on the *small* title/number crops (not the whole image) to read text. The model is
   loaded once at startup so the first real scan isn't slow.

8. **`services/normalizer.py`** — cleans the raw OCR text with RapidFuzz: repairs the
   collector number, tidies the name, and removes duplicate guesses.

9. **`providers/identity/*`** — searches the card catalog (the local **TCGCSV** mirror by
   default) for candidates matching that name/number. Then **`services/candidate_ranker.py`**
   scores each candidate with `0.5·number + 0.3·name + 0.2·image` and picks a winner only
   if it clears the confidence threshold. **`services/pricing_service.py`** →
   **`providers/price/*`** then fetches the price (recent TCGplayer sales, with market
   price as fallback).

10. **Persist, display, hold.** A confident match is written to SQLite via
    **`database/repository.py`** *with its pHash*, so the **next** scan of that card wins at
    step 6 without any network — the system "learns." **`services/display_service.py`**
    writes the result to `data/cache/display_state.json`. Back in the route,
    **`services/scan_gate.py`** latches the match so the screen holds it. The JSON reply
    goes back to the camera.

11. **`templates/display.html`** — the kiosk page polls the server, notices the state
    changed, and re-renders: the card name, the big price, and a **"Scan next card"**
    button. Tapping it calls `/resume`, which clears the gate and the screen returns to
    idle — and the continuously-scanning camera picks up the next card.

That's the whole loop. Everything below is the detail behind each stop.

---

## 4. Folder-by-folder walkthrough (the Pi app: `card-scanner/`)

### Root files

- **`app.py` — the application factory.** The wiring diagram of the whole program. It
  reads config, opens the database, builds the providers and services, injects them into
  the pipeline, and registers the routes. Nothing here does "real work"; it just decides
  *which* implementation each part uses (real vs mock, TCGCSV vs TCGAPIs) and connects
  them. This is the **dependency-injection** pattern: components receive their
  collaborators instead of creating them, which is what makes the app testable offline.
  *Alternative:* a big `main()` that imports and calls everything directly. Rejected
  because it hard-wires choices and can't be swapped for tests.

- **`config.py` — one place for every setting.** Reads `.env` once into a frozen
  `Config` dataclass with typed helpers (`_b`, `_i`, `_f`). Every other file calls
  `get_config()` instead of touching `os.environ`, so all the knobs (thresholds, provider
  choice, timeouts, paths) are defined and validated in exactly one spot. *Library:*
  `python-dotenv` loads the `.env` file. *Alternative:* scattering `os.getenv` calls
  everywhere. Rejected — it makes settings impossible to find and easy to typo.

- **`requirements.txt`** — the Python dependency list (see the library table in §6).
- **`.env.example`** — a documented copy of every setting; you copy it to `.env`.
- **`.gitignore`, `logs/.gitkeep`** — housekeeping (keep the empty logs folder, ignore
  data/venv/caches).
- **`README.md`, `HANDOFF.md`, `cardscanner.md`, `ARCHITECTURE.md`** — docs. README is the
  reference manual, HANDOFF is the "current state" log, `cardscanner.md` is the narrative
  build story for the expo, and this file is the architecture study guide.

### `routes/` — the thin web layer

The rule here is *routes stay thin*: validate input, call a service, return JSON. No logic.

- **`scan_routes.py`** — `/scan` (accept a photo, run the pipeline, or return the held
  match), `/resume` (clear the hold for the "Scan next card" button), `/health` (a status
  JSON used by the kiosk to know when to launch), `/jobs/<id>` (async job status), and
  `/history` (recent scans).
- **`ui_routes.py`** — `/display` (render the touchscreen page from the saved state) and
  `/` (a simpler result page).

*Library:* Flask. *Alternative:* FastAPI. Rejected because we don't need async I/O or
auto-generated API docs here; Flask + Jinja2 also gives us server-side HTML rendering for
free, which the kiosk relies on.

### `services/` — the heart of the app

This folder is where every real decision happens. Each file is one responsibility, so you
can read, test, or replace one without touching the others.

- **`scan_pipeline.py`** — the orchestrator described in §3. It owns the *order* of
  operations and the in-memory pHash index, but delegates each step to the specialist
  services. All its collaborators are injected, so a test can wire mock providers and a
  stub OCR and run the entire pipeline offline.
- **`card_detector.py`** — OpenCV card-finding and perspective warp (Canny edges →
  contours → 4-point quad → `warpPerspective`). Falls back to a plain resize if no clean
  rectangle is found, so the pipeline still runs on an already-tight photo. *Alternative:*
  a machine-learning object detector. Rejected as overkill — classic edge detection is
  faster, needs no training data, and a card is a simple high-contrast rectangle.
- **`image_matcher.py`** — perceptual hashing and ORB feature matching, both via OpenCV.
  pHash is computed natively with OpenCV's DCT, so we avoid an extra `imagehash`
  dependency. Uses a **Hamming-distance threshold** (not exact match) because a foil or a
  differently-lit scan never hashes identically to clean art. *Alternative:* deep-learning
  image embeddings. Rejected — heavy on a Pi and unnecessary when pHash + ORB already
  disambiguate cards well.
- **`ocr_service.py`** — wraps EasyOCR, loaded once at startup, run only on the small
  crops. *Alternative:* Tesseract (via `pytesseract`). EasyOCR was chosen for better
  accuracy on stylized card fonts; the cost is that it pulls in PyTorch (see §6 and the
  CPU-only note).
- **`normalizer.py`** — RapidFuzz-based text cleanup and fuzzy matching; falls back to the
  standard-library `difflib` if needed. *Alternative:* the pure-Python `fuzzywuzzy`.
  Rejected because RapidFuzz is the same idea but dramatically faster (C++ under the hood).
- **`candidate_ranker.py`** — the scoring formula that combines number, name, and image
  signals into one confidence number, with the guard rail that a misread number can't win
  on its own. This is the "brain" that prevents confident wrong answers.
- **`pricing_service.py`** — decides *when* to fetch a price and caches it (at most once
  per card per day via a TTL), then calls a price provider. Keeps network traffic and rate
  pressure low.
- **`scan_gate.py`** — the small thread-safe latch that holds a matched result until the
  user taps "Scan next card." This is what makes the product feel deliberate instead of
  flickering through scans. *Alternative:* a fixed timeout, or pausing on the ESP32.
  Rejected — a timer is bad UX, and putting the pause on the camera would fight the Pi and
  give no on-screen control.
- **`display_service.py`** — writes the latest state to `display_state.json` **atomically**
  (write to a temp file, then rename) so the kiosk never reads a half-written file.
  *Alternative:* pushing updates over a WebSocket. Rejected as more moving parts than a
  single-viewer kiosk needs; a polled JSON file is bulletproof and survives restarts.
- **`storage_manager.py`** — saves scan images (hash-deduplicated) and manages the on-disk
  tiers. **`cache_policy.py`** and **`maintenance_service.py`** enforce size caps and delete
  old files so the SD card never fills. **`descriptor_store.py`** saves ORB descriptors to
  disk keyed by card. **`job_service.py`** is the tiny thread-pool + timeout runner.

### `providers/` — swappable data sources behind one interface

This is the app's most important design idea. **`base.py`** defines the interfaces
(`IdentityProvider`, `PriceProvider`) and the shared data shapes (`CandidateCard`,
`PriceQuote`). Everything that fetches card data implements one of these, so the pipeline
never knows or cares *which* source it's talking to — you switch sources by changing one
line in `.env`.

- **`tcgcsv_catalog.py` + `identity/tcgcsv_identity.py` + `price/tcgcsv_price.py`** — the
  default: a free, keyless daily mirror of TCGplayer's catalog and market prices
  (`tcgcsv.com`), synced into a local SQLite file so scans hit local disk, not the network.
- **`price/tcgplayer_sales_price.py`** — the default *price* source: the last few real
  TCGplayer sales (an unofficial endpoint), with the TCGCSV market price as automatic
  fallback.
- **`tcgapis_client.py` + `identity/tcgapis_identity.py` + `price/tcgapis_price.py`** — an
  optional paid provider (real completed-sales history), used only if you set
  `CARD_DATA_PROVIDER=tcgapis` and a key.
- **`identity/mock_identity.py` + `price/mock_price.py`** — fake providers with canned data
  so the whole app runs and the tests pass **with no internet and no keys**. This is why
  development is fast and offline.

*Library:* `requests` for the HTTP calls. *Alternative to the whole abstraction:* calling
one hard-coded API directly. Rejected because pricing sources change often (this project
already migrated TCGAPIs → TCGCSV mid-build); the abstraction meant that migration touched
only the provider folder, not the pipeline.

### `database/` — the memory

- **`schema.sql`** — the table and index definitions (cards, scan history), the one file
  that owns the data shape.
- **`repository.py`** — the **only** file allowed to run SQL. Everything else calls methods
  like `get_card`, `upsert_card`, `add_scan`. This "repository pattern" keeps SQL in one
  place, so a schema change never ripples through the app. It also handles the quirk that a
  64-bit pHash is unsigned but SQLite stores signed integers (the `_to_signed64` /
  `_to_unsigned64` helpers).
- **`init_db.py`, `seed_sample_cards.py`** — set up an empty database and load a few sample
  cards for testing.

*Why SQLite:* it's a zero-configuration database that's just a file on disk — perfect for a
single-box appliance. *Alternative:* PostgreSQL/MySQL. Rejected — a server process is
pointless overhead on a one-user Pi. *Alternative:* plain JSON files. Rejected — we need
indexed lookups and safe concurrent writes, which SQLite gives for free.

### `templates/` + `static/` — the face

- **`display.html`** — the kiosk screen: a self-contained page (all CSS inline) themed
  around One Piece, with idle / match states, the big price, an honest "recent sales vs
  market price" tag, and the "Scan next card" button. It's rendered by **Jinja2** (Flask's
  templating), and a small polling script reloads only when the server's state signature
  changes. *No image files, no web fonts* — the compass and waves are hand-drawn SVG — so it
  loads instantly and works fully offline.
- **`result.html`** — a simpler alternate view.
- **`static/styles.css`** — shared styles for the non-kiosk pages.

### `utils/`, `scripts/`, `tests/`

- **`utils/image_utils.py`** — JPEG decode/validate helpers. **`utils/logger.py`** — one
  place to configure logging format and level.
- **`scripts/test_sales_source.py`** — a standalone probe to check the live sales endpoint
  for one product ID, handy when prices look wrong.
- **`tests/`** — a pytest suite (`test_normalizer`, `test_image_matcher`,
  `test_candidate_ranker`, `test_pipeline`) that runs entirely offline against the mock
  providers, plus `conftest.py` for shared fixtures. *Why:* the ranking and normalization
  logic is exactly the kind of subtle code that quietly breaks; tests pin the behavior.

### `models/` + `renders/` — the physical enclosure

- **`models/*.stl`** — the 3D-printable parts: a `camera_pod`, a two-piece display "crown,"
  and a "hat" brim/cover. **`models/ASSEMBLY.md`** explains how they fit together.
- **`renders/*.png`** — preview images of those parts.

These are the enclosure that will eventually hold the camera at a fixed distance over the
card — which ties directly into the image-quality work in §8.

---

## 5. The Pi kit (`card-scanner-pi/`)

Where the app lives on the Pi and how it boots. Kept separate from the app code so the
application stays clean and portable.

- **`deploy/install.sh`** — installs system libraries and Python deps, and crucially
  installs **CPU-only PyTorch first** (a plain `pip install torch` on the Pi's ARM chip
  pulls ~5–7 GB of unusable NVIDIA GPU libraries and fills the card).
- **`deploy/card-scanner.service` + `install_service.sh`** — a **systemd** service so the
  backend starts on boot and restarts if it crashes.
- **`deploy/kiosk-autostart.sh`** — configures the **labwc** (Wayland) autostart to launch
  full-screen Chromium at `/display`, but only *after* the backend answers `/health` (the
  app is slow to start because it loads the OCR model first; opening the browser too early
  showed a white screen).
- **`deploy/live_view.py`** — a tiny standalone web server that shows the newest captured
  frame, auto-refreshing, for aiming and focusing the camera. Purely a setup/debugging aid.
- **`deploy/env.pi.example`, `README-PI.md`** — Pi-tuned settings and the deployment guide.
- **`firmware/esp32cam_scanner/esp32cam_scanner.ino`** — the camera firmware (see §3 and
  the language notes in §2), plus `firmware/README.md`.
- **`hardware/BILL_OF_MATERIALS.md`, `POWER_AND_WIRING.md`, `wiring_diagram.svg`,
  `SCAN_CHAMBER.md`** — the parts list, the single-cable 5 V power design, and the
  enclosed-slot lighting design.

---

## 6. Library reference — what, why, and the alternative

| Library | Where | What it does | Why this one (vs. the alternative) |
| --- | --- | --- | --- |
| **Flask** | routes, app | Web server + Jinja2 HTML templating | Tiny and synchronous; also renders the kiosk page. *vs FastAPI:* we don't need async or auto-docs. |
| **OpenCV** (`opencv-python-headless`) | detector, matcher, image utils | JPEG decode, card detection, perspective warp, pHash (DCT), ORB features | The CV workhorse. *headless* = no GUI libs, lighter on the Pi. *vs Pillow-only:* Pillow can't do geometry/features. |
| **NumPy** | everywhere images are touched | Fast array math under OpenCV | The universal array type; not optional with OpenCV. |
| **EasyOCR** | ocr_service | Reads text from the card crops | Better on stylized fonts. *vs Tesseract:* more accurate, but pulls in PyTorch. |
| **PyTorch** (via EasyOCR) | (transitive) | Neural-network engine EasyOCR runs on | Required by EasyOCR. Must be the **CPU build** on the Pi. |
| **RapidFuzz** | normalizer, ranker | Fuzzy string matching + cleanup | Same API idea as fuzzywuzzy but far faster (C++). |
| **requests** | providers | HTTP calls to TCGCSV / sales endpoints | Simple, ubiquitous. *vs httpx:* we don't need async. |
| **python-dotenv** | config | Loads `.env` into the environment | Standard way to keep settings out of code. |
| **sqlite3** (stdlib) | repository | The local database | Built into Python; zero setup. |
| **pytest** | tests | Runs the offline test suite | The Python testing standard. |
| **esp_camera / WiFi / HTTPClient** | firmware (C++) | Camera capture, Wi-Fi, HTTP POST | The ESP32 Arduino core — mature drivers for this exact board. |

---

## 7. The big architecture decisions (and the roads not taken)

- **OpenCV-first, escalate only as needed.** The pipeline leads with the cheapest, most
  discriminative signals (collector number + perceptual hash) and only reaches for heavy
  tools (EasyOCR, network lookups) when the cheap ones don't settle it. *Road not taken:*
  "OCR everything, every time." Rejected — slow, and unnecessary once a card is known.
- **Learn as you go.** Every confident remote match is written back to SQLite with its
  pHash, so the second sighting of a card resolves locally and offline. The device gets
  faster and more self-reliant the more it's used.
- **Provider abstraction.** Data sources hide behind `IdentityProvider` / `PriceProvider`,
  so swapping or adding one is a `.env` change, not a rewrite. This already paid for itself
  when pricing migrated mid-project.
- **Everything injected, mocks included.** Because `app.py` wires implementations in, the
  whole system runs offline on mock providers — which is why there's a real test suite.
- **Pi holds, screen resumes.** The match latch (`scan_gate`) and the "Scan next card"
  button put pacing and control on the touchscreen, where the user actually is, rather than
  on the headless camera.
- **A polled JSON file for the display**, not a live socket. One viewer, atomic writes,
  survives restarts, trivially debuggable.
- **SQLite, not a database server.** It's a single-box appliance; a file is the right
  amount of database.

---

## 8. Next steps — fixing blurry cameras and ensuring image quality

Everything above works; the remaining accuracy ceiling is **optics**. Recognition can only
be as good as the picture it's given, and the ESP32-CAM is the weakest link. Here are the
causes of blur/poor quality and concrete fixes, roughly in order of impact.

**A. Fixed focus (the #1 cause of blur).** The ESP32-CAM's small lens ships focused near
infinity, so a card 12–16 cm away is soft. The lens is on a threaded mount:
- Rotate the lens barrel while watching `deploy/live_view.py` until the collector number is
  crisp, then lock it with a tiny dab of glue so it never drifts.
- If the thread is glued from the factory, break it loose gently first.
- Consider swapping the stock OV2640 lens for one with a closer fixed focus, or an
  **autofocus OV2640/OV5640 module** if you want hands-off sharpness.

**B. A fixed, repeatable card position.** Blur is often *motion* or *wrong distance*, not
just focus. The `SCAN_CHAMBER.md` design solves this: seat the card in a fixed slot at the
exact distance the lens is focused to, every time. This turns "focus once" into "always in
focus." The `models/` enclosure parts exist to hold the camera rigidly — any wobble
reintroduces blur.

**C. Lighting = effective sharpness.** In dim light the sensor lengthens exposure and
raises gain, which produces both motion blur and speckle noise (you saw the green, grainy
frames). Bright, even, **diffused** light lets the sensor use a fast exposure and low gain,
which looks dramatically sharper:
- Add the neutral-white (~4000–5000 K) LED strip from `SCAN_CHAMBER.md`, bounced off white
  walls so foils don't glare.
- Enclose the chamber so room light can't change the exposure between scans.

**D. Camera register tuning (free, in firmware).** The OV2640 exposes sensor controls via
`esp_camera_sensor_get()`. In `initCamera()` you can nudge quality:
- Raise sharpness: `s->set_sharpness(s, 1..2)`.
- Cap gain to reduce noise in decent light: `s->set_gainceiling(s, GAINCEILING_2X)` and
  `s->set_agc_gain(s)` limits.
- Keep auto-exposure/white-balance on (already set), and let the sensor settle by discarding
  a couple of frames before the keeper (the firmware already drops one stale frame — bump it
  to two or three if the first shot after wake looks off).
- Once lighting is fixed and stable, you can safely raise resolution back toward SVGA for
  more detail on the collector number, as long as capture stays reliable.

**E. Make the software forgiving of imperfect frames.** Two cheap wins in the pipeline:
- In `card_detector.py`, add a **blur check** (variance of the Laplacian): if a frame is too
  blurry, skip it and wait for the next auto-scan instead of trying to OCR mush. This alone
  removes most bad reads.
- Sharpen the OCR crops slightly (an unsharp mask) before EasyOCR, and/or upscale the small
  number crop so the digits are larger for the recognizer.
- If a card is *known*, remember the pipeline already skips OCR entirely (pHash tolerates
  moderate blur far better than OCR), so improving the **first** clean capture of each card
  pays off on every later scan.

**F. Diagnosing which problem you have.** Use `live_view.py` and ask:
- Sharp but dark/green → **lighting** (C).
- Evenly lit but soft everywhere → **focus** (A).
- Sharp in the center, soft at the edges, or striped/purple → **optics/board** (lens seating,
  or the XCLK/power fixes already applied).
- Good single frames but random bad ones → add the **blur check** (E) so only good frames
  are used.

The through-line: fix the picture in hardware first (focus, fixed distance, light), then let
the software reject the occasional bad frame. Do those and the recognition rate climbs on its
own, because every stage downstream — detection, hashing, OCR — was always limited by the
quality of that first photo.
