/*
 * Card Scanner - ESP32-CAM firmware
 * ---------------------------------
 * Connects to Wi-Fi and captures a JPEG on a timer (and/or button press),
 * POSTing it to the Raspberry Pi's  POST /scan  endpoint (raw image/jpeg body).
 * Prints the JSON result to Serial. When the Pi reports a MATCH, auto-scanning
 * pauses and holds the result until re-armed (button press, or MATCH_HOLD_MS).
 *
 * Board: "AI Thinker ESP32-CAM"  (Tools -> Board -> ESP32 Arduino)
 * Partition: "Huge APP (3MB No OTA)"  ·  PSRAM: Enabled
 *
 * Bring-up notes (don't relearn these the hard way):
 *  - XCLK is 10 MHz. At 20 MHz many AI-Thinker boards produce striped /
 *    purple-banded, color-corrupted frames.
 *  - VGA + fb_count=2 + CAMERA_GRAB_LATEST avoids the "cam_dma_config frame
 *    buffer malloc failed" halt and the FB-OVF overflow spam.
 *  - Give the board a solid 5 V supply (powered USB hub or wall adapter, and a
 *    ~1000 uF cap across 5V/GND). The camera + Wi-Fi current spikes brown out a
 *    weak USB port, which shows up as PSRAM/camera init failures.
 */

#include "esp_camera.h"
#include <WiFi.h>
#include <HTTPClient.h>

// ============================ USER CONFIG ============================
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";

const char* PI_HOST   = "192.168.1.50";   // your Raspberry Pi's LAN IP (reserve it on the router)
const int   PI_PORT   = 5000;
const char* PI_PATH   = "/scan";

const int   BUTTON_PIN    = 13;           // momentary button to GND (INPUT_PULLUP); re-arms after a match
const bool  USE_FLASH_LED = false;        // onboard GPIO4 flash. Prefer fixed enclosure lighting; leave false.

// Auto-scan: capture+POST every this many ms with no button needed. 0 = button only.
const unsigned long AUTO_SCAN_INTERVAL_MS = 3000;

// After a match, stop auto-scanning and hold the result until re-armed.
// Re-arm by pressing the button, or automatically after MATCH_HOLD_MS if > 0
// (0 = wait for the button only).
const bool          PAUSE_ON_MATCH = true;
const unsigned long MATCH_HOLD_MS  = 0;
// ====================================================================

// --- AI-Thinker ESP32-CAM pin map ---
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22
#define FLASH_LED_PIN      4

bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;   config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM; config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM; config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;   config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 10000000;         // 10 MHz — 20 MHz corrupts frames on many boards
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode    = CAMERA_GRAB_LATEST;
  config.fb_location  = CAMERA_FB_IN_PSRAM;

  // Double-buffered VGA in PSRAM: clean captures, no FB-OVF, fits easily in 4 MB.
  if (psramFound()) {
    config.frame_size   = FRAMESIZE_VGA;    // 640x480 — plenty for card OCR
    config.jpeg_quality = 12;               // 0(best)..63(worst)
    config.fb_count     = 2;
  } else {
    config.frame_size   = FRAMESIZE_QVGA;
    config.jpeg_quality = 14;
    config.fb_count     = 1;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }
  // A few tweaks that help card OCR: modest sharpness, auto white balance on.
  sensor_t* s = esp_camera_sensor_get();
  if (s) { s->set_whitebal(s, 1); s->set_awb_gain(s, 1); s->set_saturation(s, -1); }
  return true;
}

void connectWiFi() {
  Serial.printf("Wi-Fi: connecting to %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(400); Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) Serial.printf("\nWi-Fi OK, IP %s\n", WiFi.localIP().toString().c_str());
  else Serial.println("\nWi-Fi FAILED (will retry on next scan)");
}

// Capture + POST one frame. Returns: 1 = matched, 0 = no match, -1 = error.
int sendScan() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (WiFi.status() != WL_CONNECTED) return -1;

  if (USE_FLASH_LED) { pinMode(FLASH_LED_PIN, OUTPUT); digitalWrite(FLASH_LED_PIN, HIGH); delay(120); }

  // Drop a stale frame, then grab a fresh one.
  camera_fb_t* fb = esp_camera_fb_get();
  if (fb) { esp_camera_fb_return(fb); fb = esp_camera_fb_get(); }

  if (USE_FLASH_LED) digitalWrite(FLASH_LED_PIN, LOW);

  if (!fb) { Serial.println("Capture failed"); return -1; }

  String url = String("http://") + PI_HOST + ":" + PI_PORT + PI_PATH;
  HTTPClient http;
  http.begin(url);
  http.addHeader("Content-Type", "image/jpeg");
  http.setTimeout(15000);

  Serial.printf("POST %s  (%u bytes)\n", url.c_str(), fb->len);
  int code = http.POST(fb->buf, fb->len);

  int result = -1;                          // -1 error, 0 no match, 1 match
  if (code > 0) {
    String body = http.getString();
    Serial.printf("HTTP %d\n%s\n", code, body.c_str());
    if (code == 200) result = (body.indexOf("\"matched\":true") >= 0) ? 1 : 0;
  } else {
    Serial.printf("POST failed: %s\n", http.errorToString(code).c_str());
  }
  http.end();
  esp_camera_fb_return(fb);
  return result;
}

// Run one scan and pause auto-scanning if it matched.
void handleScan(bool* paused, unsigned long* pausedAt) {
  int r = sendScan();
  if (r == 1 && PAUSE_ON_MATCH) {
    *paused = true;
    *pausedAt = millis();
    Serial.println(">>> MATCH — auto-scan paused. Press button for the next card.");
  }
}

void setup() {
  Serial.begin(115200);
  Serial.printf("PSRAM found=%d size=%u\n", (int)psramFound(), (unsigned)ESP.getPsramSize());
  delay(300);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  if (!initCamera()) { Serial.println("Halting: camera init failed."); }
  connectWiFi();
  Serial.println("Ready. Auto-scanning; a match pauses until you press the button.");
}

void loop() {
  static bool lastHigh = true;
  static unsigned long lastAuto = 0;
  static bool paused = false;
  static unsigned long pausedAt = 0;

  // Button: manual scan when idle, or re-arm after a match.
  bool pressed = (digitalRead(BUTTON_PIN) == LOW);
  if (pressed && lastHigh) {
    if (paused) {
      paused = false;
      Serial.println("re-armed (button) — ready for next card");
    } else {
      Serial.println("--- scan (button) ---");
      handleScan(&paused, &pausedAt);
    }
    delay(400);                            // debounce / rate limit
  }
  lastHigh = !pressed;

  // Optional auto re-arm after a hold window.
  if (paused && MATCH_HOLD_MS > 0 && millis() - pausedAt >= MATCH_HOLD_MS) {
    paused = false;
    Serial.println("re-armed (timeout)");
  }

  // Auto scan on a timer, unless paused on a match.
  if (!paused && AUTO_SCAN_INTERVAL_MS > 0 && millis() - lastAuto >= AUTO_SCAN_INTERVAL_MS) {
    lastAuto = millis();
    Serial.println("--- scan (auto) ---");
    handleScan(&paused, &pausedAt);
  }
  delay(20);
}
