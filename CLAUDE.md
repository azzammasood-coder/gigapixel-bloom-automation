# Gigapixel + Bloom Automation — Project Context

## Client
- **Platform:** Fiverr
- **Client:** Leslie (username: `leseliz`)
- **Client profile:** Non-technical. Runs a digital-art small business, **Golfartstudios.com**.
- **Prior relationship:** I have already built her a **Photoshop framing tool** (used to place finished images into frames for her website), so this is a repeat client.

## Order Status
- **ACCEPTED / ORDER STARTED.** Custom offer sent 22 Jul, 22:45 and accepted.
  - Price: **PKR 43,750.52** (≈ $150).
  - Delivery: **2 Days**.
  - Offer title: "I will do python development and debugging services."
  - Offer scope (verbatim): *Build an image processing automation that streamlines the client's current workflow. The automation will:*
    - *Upscale images using Topaz Gigapixel API.*
    - *Apply Bloom enhancement in Topaz Labs.*
    - *Perform a final Gigapixel upscale to ensure the correct aspect ratio and high-resolution output.*
- Latest message (Me, 23 Jul 21:51): "Thank you for the information, Leslie. Let me review it and get back to you." → **Ball is in my court.**

## What She Wants
Automate the **Gigapixel + Bloom** steps of her workflow. She uploads a **single image or a folder**, and each image is processed automatically. Tool must be **intuitive and easy to use** (she is non-technical).

## Her ACTUAL Workflow (clarified 22–23 Jul — note order differs from my first assumption)
1. Create the image in **Midjourney**, **Higgsfield**, and her **iPad**.
2. **Bloom first** — add more pixels to the digital image so it prints well (upscale/enhance).
3. **Gigapixel second** — ensure the **aspect ratio** is still correct and upscale the image for **print**.
4. Because print files are large, she uploads them to a **Dropbox** folder shared with the printer.
5. Uses my **Photoshop framing tool** to place images into frames for her website.

> ⚠️ Correction: the original brief implied Gigapixel → Bloom → Bloom. Her clarified process is **Bloom → Gigapixel**. The accepted offer wording (Gigapixel → Bloom → final Gigapixel) should be reconciled with this before building. **Confirm the exact intended pipeline order with her.**

## The Core Challenge
She picks settings **per-image, by visual inspection** — no fixed recipe. Agreed solution: an **LLM vision step** looks at each image + her instructions and decides the settings, then feeds them to the processing APIs.

### Automation Workflow #1 (agreed)
```
Select images (single or folder)
      ↓
ChatGPT Vision / free LLM (e.g. OpenRouter) — decides settings
      ↓
Bloom API (enhance / add pixels, painterly-preserving)
      ↓
Gigapixel API (fix aspect ratio + upscale for print)
      ↓
Final Output (print-ready)
```
- **Running cost quoted:** ~$4–$18/month (LLM + API usage).

## ⚠️ Missing step she flagged (26 Jul) — human QC after Bloom
Bloom may change the image slightly — **sometimes fine, sometimes not.** She
**visually scans every Bloom result** to catch surprises *before* it's enlarged
for print. If a Bloom output is bad, she **re-runs Bloom** (or tweaks the original
and re-runs) until she gets one that works. So her real process is:
`Bloom → HUMAN REVIEW/approve (loop until good) → Gigapixel`.
This is a subjective visual check, so a fully hands-off run can't replace it.
**Open design decision:** add a review/approval gate (e.g. Phase 1 produces Bloom
result(s) → she approves/rejects/re-runs → Phase 2 runs the final Gigapixel on
approved images), possibly generating a few Bloom variants for her to pick from.

## Final DPI rule (confirmed 26 Jul)
- **300 DPI** for **painterly** images.
- **200 DPI** for **illustration**-type images.
- She wants this enforced automatically → the AI step should classify
  painterly vs illustration and set DPI accordingly.

## Her Settings Preferences / Rules (critical for the LLM prompt)
- **Style = painterly.** Most of her art is very painterly; she wants brush strokes and fine detail **preserved**, to look painted (not like a photo/illustration).
- **Bloom: use the LOWEST creative changes** setting. Bloom often over-smooths detail — she does NOT want detail smoothed out.
- **Faces are a known failure mode.** Bloom distorts faces (example: a Japanese man's eyes were made round). Sometimes she has to request multiple Bloom versions to get an acceptable one.
- **"Finished" =** the Bloom image preserves the painterly look correctly; then she upscales in Gigapixel for print.
- **Gigapixel's job at the end:** guarantee correct **aspect ratio** and **high resolution** for print.

## Print Requirements — Lumaprints (her printer, Lumaprints.com)
- **Max file size:** web uploader caps at **100 MB**. For files > 100 MB: upload the order first, then email the large file to **contact@lumaprints.com** referencing the order number, or send via **WeTransfer / Dropbox**.
- **Resolution (DPI):** Canvas prints ≥ **200 DPI**; fine art paper = **300 DPI**.
- **File format:** **JPG, JPEG, or PNG only.**
- Reference she shared: Lumaprints webinar "Preparing your image file for a successful print" — https://www.lumaprints.com/blog/webinar-preparing-your-image-file-for-a-successful-print/#_Checking_the_Quality

## Assets from Client
- **Topaz Labs** provides BOTH tools. **Bloom is an app inside Topaz Labs** (unified "Topaz Image Web" workspace, alongside **Astra**; Gigapixel upscaler also there). Gigapixel is also her installed desktop app which links to `https://app.topazlabs.com/`.
- She **created a Topaz Labs API key** (none existed before). Account shows a small API credit balance (~**20**) — likely needs a paid top-up for volume.
- **Bloom example image** she sent (23 Jul 17:59, "Bloom Exam...", 307 kB): a before/after golf scene — "original blurry low-res" vs an upscaled version — illustrating the painterly-vs-smoothed distinction. She will try to send more examples.

### Credentials received (SENSITIVE — do NOT commit)
- **Topaz Labs API key:** stored ONLY in the local, gitignored `.env` file — **redacted
  here on purpose so it never enters git history.** The value was sent by Leslie in
  the Fiverr chat (22 Jul, 19:19). To continue on another machine, copy `.env.example`
  to `.env` and paste the key from that Fiverr message.
  - ⚠️ Live secret. Never commit/push. Recommend asking Leslie to rotate after delivery.

## Open Questions / To Confirm
1. **Confirm pipeline order** (Bloom→Gigapixel per her clarification vs offer's Gigapixel→Bloom→Gigapixel).
2. Does the **Bloom/Topaz API** actually let us enforce final **aspect ratio** + **file size/DPI**, or must Gigapixel do that final pass? (Her main worry.)
3. Which **LLM** for the vision step (ChatGPT Vision vs OpenRouter free model) + finalize the instruction prompt encoding her rules above (painterly, lowest creative changes, face-safety).
4. Exact **Topaz API endpoints & parameter schemas** for both Bloom enhance and Gigapixel upscale.
5. Are the ~20 Topaz API credits enough, or does she need a plan upgrade?
6. Get **more before/after examples** with the settings she chose (requested; she'll try to provide).
7. ~~Should the tool also handle the **Dropbox hand-off**~~ → **ANSWERED (29 Jul): save finished files to a folder on her computer** (no Dropbox integration needed; local output is the default). Still enforce Lumaprints specs (≥200/300 DPI, ≤100 MB, JPG/PNG).

## Test images received (29 Jul)
Leslie sent **4 Midjourney originals** (~1 MP each, 1024×1024 and 896×1344),
stored in `example-images/`: a golf bag, an elegant African-American figure,
a painterly woman portrait, and two golfers. At least 3 contain **faces** — good
for testing the face-safety behavior. These are the real inputs for the live test.

## Conversation Timeline (key points)
- 13 Jul 22:29 — Me: asked for (1) sample images, (2) instructions/desired look, (3) API keys (how to generate for Bloom & Topaz).
- 13 Jul 22:31 — Leslie: "OK. I will ask about API Keys." + screenshot.
- 14 Jul — Me: proposed Workflow #1, pricing $4–$18/mo. Leslie asked if Bloom API ensures aspect ratio + final size.
- 16 Jul — Me: est. $150, 1–2 days. Leslie agreed, out of town until Monday.
- 21 Jul — Me: follow-up. 22 Jul 19:19–19:25 — Leslie sent **Topaz Labs API key** + screenshots + Gigapixel upscaler URL.
- 22 Jul 22:45 — Me: custom offer (PKR 43,750.52, 2 days) → **accepted**. 22:51 — Me: sent 5+ clarifying questions.
- 23 Jul 17:38–18:29 — Leslie: detailed answers (business, process, painterly/Bloom preferences, Lumaprints specs, example image). Will send more examples.
- 23 Jul 21:51 — Me: thanked her, will review and get back.
