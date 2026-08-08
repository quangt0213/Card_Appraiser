# Bill of materials

Everything needed to build one self-contained scanner. Prices are rough USD ballparks
(2026) for planning, not quotes.

## Core electronics

| # | Component | Qty | Notes | ~Price |
| --- | --- | --- | --- | --- |
| 1 | Raspberry Pi 4 Model B (2 GB or 4 GB) | 1 | The brain. 4 GB gives EasyOCR more headroom. | $45–65 |
| 2 | microSD card, 32–64 GB, **A2 / U3** | 1 | A2-rated matters for random-IO speed and wear. 64 GB fits the storage plan. | $10–15 |
| 3 | ESP32-CAM (AI-Thinker) w/ OV2640 | 1 | The camera + Wi-Fi module. | $8–12 |
| 4 | USB-TTL programmer (CP2102/FTDI) **or** ESP32-CAM-MB dock | 1 | Needed once to flash firmware; the MB dock is the easy option. | $4–8 |

## Power (single-cable design — see POWER_AND_WIRING.md)

| # | Component | Qty | Notes | ~Price |
| --- | --- | --- | --- | --- |
| 5 | **5 V / 4–5 A** USB-C power supply | 1 | Sized for the Pi (up to 3 A) **plus** the camera. Don't reuse a bare 3 A brick. | $12–18 |
| 6 | 1000 µF / 10 V (or 16 V) electrolytic capacitor | 1–2 | Bulk cap across the ESP32-CAM 5 V/GND — cures brown-out resets. | $0.50 |
| 7 | 22 AWG (or thicker) silicone hookup wire, red/black | 1 m | Short, thick 5 V + GND leads to the camera minimize voltage sag. | $3 |
| 8 | JST-XH / Dupont connectors or a small screw terminal | few | The internal 5 V distribution node. | $3 |

## Display

| # | Component | Qty | Notes | ~Price |
| --- | --- | --- | --- | --- |
| 9 | Freenove 5" HDMI touchscreen (or any small HDMI/DSI touch panel) | 1 | Runs the `/display` kiosk page. Pick one powered from the same rail if possible. | $30–45 |
| 10 | micro-HDMI ↔ HDMI cable (short) | 1 | Pi 4 uses micro-HDMI. | $5 |

## Optical / mechanical (this is what makes the CV reliable)

| # | Component | Qty | Notes | ~Price |
| --- | --- | --- | --- | --- |
| 11 | Diffused white LED strip or small ring light | 1 | **Consistent lighting is a force-multiplier for recognition** — flat, even light, no glare. Run it off the 5 V rail. | $5–10 |
| 12 | Card cradle / fixed mount | 1 | Hold the card at a **fixed distance and angle** under the camera. Consistency here beats any algorithm tuning. | 3D-print / $ |
| 13 | Momentary push button (NO) | 1 | Trigger a scan on demand (wired to the ESP32). Better UX than free-running capture. | $1 |
| 14 | Enclosure | 1 | Houses Pi + camera + light + screen; one power cable in. 3D-printed or project box. | $ |

## Optional

| # | Component | Qty | Notes |
| --- | --- | --- | --- |
| 15 | Small heatsink / fan for the Pi | 1 | EasyOCR bursts are CPU-heavy; keeps thermals sane in a sealed box. |
| 16 | Inline 5 V polyfuse (e.g. 4 A) | 1 | Cheap protection on the shared rail if you're productizing. |

## Notes on choices

- **Why 5 V / 4–5 A:** the Pi 4 alone can pull ~3 A under load; the ESP32-CAM adds
  ~250–300 mA with spikes during Wi-Fi TX. A 4 A supply is the safe floor, 5 A comfortable.
- **Why the capacitor is not optional:** the ESP32-CAM is infamous for resetting
  ("Brownout detector was triggered") when the camera and Wi-Fi draw at once. A bulk cap
  right at its 5 V pin is the standard, reliable fix.
- **Lighting > algorithms:** a fixed mount + even diffused light removes glare and
  perspective variance at the source, which improves every downstream step more cheaply
  than any software change.
