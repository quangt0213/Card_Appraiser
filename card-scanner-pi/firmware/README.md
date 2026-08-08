# ESP32-CAM firmware — flashing guide

The sketch in `esp32cam_scanner/esp32cam_scanner.ino` captures a JPEG on a button press
and POSTs it to the Pi's `/scan` endpoint. It matches the backend, which accepts a raw
`image/jpeg` body.

## 1. Arduino IDE setup (once)

1. Install the **Arduino IDE**.
2. **File → Preferences → Additional Boards Manager URLs**, add:
   `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
3. **Tools → Board → Boards Manager**, install **esp32 by Espressif**.
4. Open `esp32cam_scanner/esp32cam_scanner.ino`.

## 2. Board settings (Tools menu)

- **Board:** AI Thinker ESP32-CAM
- **Partition Scheme:** Huge APP (3MB No OTA/1MB SPIFFS)
- **PSRAM:** Enabled
- **Upload Speed:** 115200 (raise later if stable)

## 3. Configure the sketch

Edit the `USER CONFIG` block at the top:

```cpp
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
const char* PI_HOST   = "192.168.1.50";   // the Pi's LAN IP (reserve it on your router)
const int   PI_PORT   = 5000;
```

## 4. Flash it

The ESP32-CAM has no USB. Use one of:

- **ESP32-CAM-MB dock (easiest):** seat the board on it, plug in USB, pick the COM port,
  hit Upload.
- **USB-TTL adapter (CP2102/FTDI):**
  - Adapter **5V → 5V**, **GND → GND**, **TX → U0R (GPIO3)**, **RX → U0T (GPIO1)**.
  - **Hold GPIO0 to GND** to enter flash mode (jumper IO0↔GND).
  - Press Upload; when it says "Connecting…", tap the RST button.
  - Remove the IO0↔GND jumper and press RST to run.

Open **Serial Monitor at 115200**. You should see Wi-Fi connect and `Ready. Press the
button to scan a card.`

## 5. Test end-to-end

1. Make sure the Pi backend is up: `http://<pi-ip>:5000/health` returns `ok: true`.
2. Put a card under the camera and press the button (GPIO13 ↔ GND).
3. The Serial Monitor prints the HTTP 200 JSON: card name, price, confidence, source.
4. The Pi's `/display` screen updates with the result.

## Notes

- The onboard flash LED (GPIO4) pulses during capture for consistent lighting — pair it
  with the diffused light in the enclosure for best OCR.
- Default capture is 800×600 (SVGA) at good quality — a small payload that still resolves
  card names and collector numbers. Bump `FRAMESIZE_*` in the sketch if you mount the
  camera farther from the card.
- If uploads fail intermittently or the board resets on capture, it's almost always
  **power** — see `../hardware/POWER_AND_WIRING.md` (bulk capacitor + thicker 5 V leads).
