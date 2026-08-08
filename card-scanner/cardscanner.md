# Card Scanner — Build Journey

**One line:** point a small camera at a trading card and get its real market value in a second — on a self-contained device that costs less than a game console and works without the cloud.

This document is the honest build log for that device. It starts from a single-sentence idea and a blank repository, and walks forward through each decision — what was asked, what was built, and why — up to the working edge-computer-vision system running today. I've kept the original prompts at the end so the trajectory is verifiable.

---

## The problem it solves

Collectors, hobby-shop owners, and resellers value cards constantly, and they do it by hand: eyeball the card, type the name into a marketplace, squint at a price that may be stale, repeat. It's slow, error-prone, and it doesn't scale to a shoebox of a thousand cards.

The goal was a single-purpose appliance that removes that friction entirely — put a card down, read the price — and does it at the edge, so it's cheap to build, private by default, and functional even on a spotty shop Wi-Fi connection. The hard requirement, and the one that shaped every later decision, was that the number on screen had to be a *real, recent* price — what the card is actually selling for — not a guess.

---

## Entry 0 — The bare-bones start

The project began as it should: a README and nothing else. No code, just a one-paragraph description of intent — "identify a trading card from a photo and return its price" — and a rough sketch of the pieces (a camera, a small computer, some way to look up prices). Six loose issues captured the earliest thinking (`OCR.py`, `database.py`, `app.py`, "Rework"). It was an idea with a shape, not a system.

That blank slate turned out to be an advantage. Instead of refactoring a fragile prototype, the rebuild could start from a clean, deliberate architecture.

---

## Entry 1 — From sketch to plan

**Ask:** evaluate the concept and lay out the improvements before writing a line of production code.

The first real work was an architecture review, not typing. It surfaced the decisions that would make or break the product:

- **Where does a *real* price actually come from?** The marketplace most collectors trust closed its public API to new developers years ago, and "most recent sold price" isn't a field you can simply request. This was flagged as the single most important problem to solve honestly, rather than papered over.
- **A photo of a card on a table is not a card.** It's tilted, lit unevenly, and surrounded by background. Any system that skips *finding and flattening the card first* will be flaky no matter how good the later steps are.
- **Reading the tiny set/collector number beats fancy image matching.** Every modern card prints a unique code (e.g. `58/102`, `OP09-036`). Reading that is faster and far more reliable than trying to match artwork.

The output was a prioritized plan: detect-and-flatten up front, lead with cheap and decisive signals, fall back to heavier tools only when needed, and treat pricing as a swappable module because the data source was clearly going to change over time.

---

## Entry 2 — The first working system

**Ask:** build it, modular, on the Raspberry Pi, with the camera uploading over Wi-Fi.

This is where the appliance became real. The architecture is deliberately layered so each concern can be tested and swapped independently:

- **Capture** — an ESP32-CAM posts a JPEG to the Pi over Wi-Fi. The Pi validates it, de-duplicates by content hash, and hands it to a background worker so the web layer never blocks.
- **Detect & flatten** — OpenCV finds the card's four corners and perspective-corrects it to a clean, upright image, then crops the title and number regions for reading.
- **Recognize** — a deliberately ordered cascade (below) that leads with the cheapest, most decisive signal and escalates only when it must.
- **Value** — a pricing layer that turns an identified card into a real, recent price.
- **Remember** — every confident match is written to a local database with a visual fingerprint, so the *next* time that card appears it's recognized instantly and offline.

The whole thing runs as a small Flask service with a touchscreen view for the shop counter, backed by SQLite and a tiered on-disk cache designed to be gentle on the device's memory card. It was verified end to end before shipping: a card is recognized, priced from real sales, and on a second scan resolves instantly from local memory with no duplicate work.

---

## Entry 3 — The recognition cascade

The core insight is that most cards can be identified almost for free, so the system should never do expensive work it doesn't need to. It runs signals cheapest-first and stops the moment it's confident:

1. **Collector-number reading** — read the printed code and match it. Nearly free, and decisive for most modern cards.
2. **Visual fingerprint (perceptual hash)** — a 64-bit hash compared against everything the device has seen before, in microseconds. This is the "I've seen this exact card" fast path, and it works with no network at all.
3. **Feature matching (ORB)** — used only as a tie-breaker over a tiny shortlist, never across the whole library.
4. **Name reading + catalog lookup** — the fallback when the number is unreadable, with fuzzy text matching to bridge imperfect reads to clean catalog data.

Two real-world failure modes are handled on purpose rather than hoped away. A misread number can *confidently* point at the wrong card, so a number match never wins alone — it has to be corroborated by the name and the image before the system trusts it. And a hash taken of a glossy, brightly lit card drifts from the clean reference art, so matching uses a distance threshold rather than demanding an exact match. These guard rails are the difference between a demo and something you'd put on a counter.

---

## Entry 4 — Pricing that's real, free, and resilient

This is where the product matured from "works" to "shippable." The first version proved the concept using a paid sales-history API. The problem: a device meant to be cheap and self-contained shouldn't depend on a per-call subscription to answer its one question.

So the pricing layer was reworked into something better on every axis that matters for a product:

- **Real recent sales, by default.** The system prices a card from its **last few completed marketplace sales** — the same feed shoppers see on the product page — and reduces them with a median so a single outlier can't skew the number. That is exactly the "what is it actually selling for right now" answer the product promised.
- **Free and keyless.** Card identity and a reliable market-price backstop come from a free, daily mirror of the marketplace catalog, synced into local storage in the background. After the first sync, recognition and pricing run entirely against the device — no network on the scan path, no rate limits, no bill.
- **Fails safe, always.** Because the live-sales feed is unofficial, every failure — an error, a block, an empty result — silently falls back to the cached market price, and the result is labeled so the interface can tell the two apart. The device never shows nothing.
- **Cached with a daily refresh**, so at most one lookup per card per day, which also keeps the experience snappy and the data source unbothered.

The result is a device that gives a real, recent valuation, costs nothing per scan, and keeps working offline between syncs. Pricing is a swappable module, so the premium sales-history API is still available as an option for anyone who wants it — but nobody *needs* it.

---

## Entry 5 — Toward a product you can hold

**Ask:** the camera and the Pi are powered separately today — can one cable run both, so this can become a single sealed product?

Yes, and this is the step that turns two dev boards on a bench into an appliance. The plan is a single 5 V supply feeding a shared internal power rail: one cable leaves the enclosure, the Pi draws from it, and the camera taps the same rail — with a bulk capacitor at the camera to absorb the current spikes that otherwise cause the notorious brown-out resets, short heavy leads to prevent voltage sag, and a common ground throughout. It's the unglamorous engineering that makes the difference between a prototype and something a shop owner can plug in and forget.

---

## What makes it interesting

- **It's an edge appliance, not a cloud app.** The intelligence lives on a sub-$100 computer. That means it's cheap to make, private by default, and doesn't stop working when the internet does.
- **It gets smarter as it's used.** Every card it confirms becomes a local fingerprint, so a busy counter recognizes its regular inventory instantly and offline.
- **It's honest about the number.** Real recent sales, with a clearly-labeled fallback — never a made-up figure dressed as a live price.
- **It's built to be swapped, not rewritten.** Games, data sources, and pricing strategies are modules behind clean interfaces, so supporting a new card game or a new marketplace is a plug-in, not a rebuild.

---

## The stack, briefly

Raspberry Pi 4 + ESP32-CAM · Python · Flask · OpenCV (detection, perceptual hashing, feature matching) · EasyOCR · RapidFuzz · SQLite (WAL) with a tiered on-disk cache · a free daily marketplace-catalog mirror for identity and backstop pricing, plus a real recent-sales feed for live valuation.

---

## Where it goes next

The near-term roadmap is about turning the working core into a finished object: the single-cable power design above, a proper enclosure with the camera fixed at a known distance (which makes detection even more reliable), broader game coverage, and a batch mode for valuing a stack of cards in one pass. The architecture was built for exactly this kind of growth — each of those is an addition, not a teardown.

---

## Appendix — the prompts, in order

Kept verbatim-in-spirit to show the path from idea to appliance:

1. *"Access my card scanner project, evaluate it, and rebuild it as a modular Python edge computer-vision app — camera upload, a service on the Pi, OpenCV-first matching with an OCR fallback, and local caching. Show me the improvements first."*
2. *"Perform the build. I want the price derived from real recent sales, and I want it to stay accurate. Keep OCR for accuracy. The confidence/tie-breaker approach is good."*
3. *(Own iteration)* Reworked pricing to a free, keyless catalog mirror for identity and market backstop, with real recent marketplace sales as the default valuation and an automatic fall-back — removing the per-call dependency and enabling offline operation.
4. *"The camera and the Pi are powered separately — is there a way to run both from one cable so I can put them in a product?"*
5. *"Write this up as a build journey — start bare-bones and work up — that I can submit to a startup for an expo invite."*
