# Power & wiring — single-cable design

Goal: **one power cable leaves the enclosure.** Inside, a single 5 V supply feeds a
shared rail; the Pi and the ESP32-CAM both draw from it. See `wiring_diagram.svg` for
the picture; this is the reasoning and the step-by-step.

## The principle

Think "one 5 V supply → one internal 5 V rail → both devices," not "two gadgets, two
plugs." The Pi is the demanding load (5 V, up to ~3 A); the ESP32-CAM is small
(~250–300 mA with spikes). So: size the supply for the Pi plus headroom, power the Pi
normally, and tap the camera off the same 5 V.

## Recommended wiring (keep WiFi for data)

The camera talks to the Pi over Wi-Fi, so the only thing the wire carries is **power**.

1. **Supply → Pi:** 5 V / 4–5 A supply into the Pi's **USB-C** port (keeps the Pi's own
   input protection in circuit — preferred over back-feeding the GPIO).
2. **Pi 5 V → rail:** from a Pi **5 V GPIO pin (physical pin 2 or 4)** to your 5 V
   distribution node (a screw terminal or a scrap of protoboard).
3. **Pi GND → rail:** from a Pi **GND pin (physical pin 6)** to the node's ground.
4. **Rail → ESP32-CAM:** node 5 V → ESP32-CAM **5V** pin; node GND → ESP32-CAM **GND**.
   Feed the **5V** pin (its onboard regulator makes 3.3 V) — do **not** feed 3V3.
5. **Bulk capacitor:** solder a **1000 µF** electrolytic across the ESP32-CAM's 5V/GND,
   as close to the module as possible (long lead = +, to 5 V; short lead = −, to GND).
6. **Light + screen:** run the LED light and (if 5 V) the touchscreen off the same node;
   the Pi's screen is on micro-HDMI.

Physical-pin reference on the Pi 40-pin header:

```
Pin 2  = 5V     ---> 5V rail  ---> ESP32-CAM 5V   (+ 1000µF cap across 5V/GND)
Pin 4  = 5V          (spare)
Pin 6  = GND    ---> GND rail ---> ESP32-CAM GND
```

## The rules that keep it reliable

- **Common ground is mandatory.** Every device's GND ties to the same node (they do, if
  all grounds meet at the rail).
- **Short, thick 5 V leads to the camera.** Thin/long wire drops voltage exactly when the
  camera spikes, which is what triggers brown-out resets. 22 AWG or thicker, as short as
  practical.
- **Power the Pi via USB-C, not the GPIO 5 V pins.** Injecting 5 V into the GPIO rail
  bypasses the Pi's input fuse/protection. Draw *from* the 5 V pins to feed the camera;
  push *into* the Pi through USB-C.
- **Size the supply for the sum.** 4 A floor, 5 A comfortable. A 3 A Pi brick with the
  camera added is how you get random brown-outs under load.
- **(Product) add a polyfuse.** A ~4 A inline polyfuse on the shared 5 V rail is cheap
  insurance in a sealed unit.

## Button trigger (optional but recommended)

Wire a momentary push button between ESP32-CAM **GPIO 13** and **GND**. The firmware uses
`INPUT_PULLUP`, so pressing it pulls the pin low and fires one scan — cleaner than
free-running capture. (GPIO 13 is free when the ESP32-CAM SD card is unused, which it is
here.) The firmware also pulses the onboard flash LED (GPIO 4) during capture for a brief,
consistent fill light.

## Quick sanity checklist

- [ ] Supply is 5 V and ≥ 4 A.
- [ ] Pi powered via USB-C; camera fed from Pi 5 V pin + GND.
- [ ] 1000 µF cap sitting across the ESP32-CAM 5V/GND.
- [ ] Camera power leads short and ≥ 22 AWG.
- [ ] All grounds common.
- [ ] (Product) inline polyfuse on the 5 V rail.
