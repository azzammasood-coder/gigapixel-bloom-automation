# Delivery Notes — Gigapixel + Bloom Automation

## What was ordered
Build an image-processing automation that streamlines the Bloom + Gigapixel steps
of the workflow: upload a single image or a folder, and each image is processed
automatically into a print-ready file.

## What is delivered (complete & working)
- A desktop app (double-click **`Start.bat`**) and a command-line version.
- The full pipeline in the requested order: **Bloom → review → Gigapixel**.
- A **review step**: every Bloom result is shown for approval; any that look wrong
  can be **re-run** (with adjustable strength) before the final upscale — this is the
  visual-check step you flagged.
- **Print-ready output**, automatically:
  - **300 DPI** for painterly art, **200 DPI** for illustration-type images.
  - **JPG/PNG only**, correct aspect ratio, within Lumaprints' 100 MB uploader limit
    (it warns and reminds you of the email/WeTransfer route if a file is bigger).
- Finished files save to **a folder on your computer** (as you requested).
- Optional AI step that can pick per-image settings (off until an LLM key is added;
  sensible defaults are used meanwhile).
- Full instructions in **`README.md`**.

## Verified working
The tool was run end-to-end on one of your own images (the painterly woman portrait).
See **`deliverables/before_after_bloom.jpg`** and **`face_detail_compare.jpg`**: the
brush strokes are preserved and the face is not distorted. The final file came out at
6000×6000, 300 DPI, ~7 MB — print-ready.

## What you need to do to run it at full volume
1. **Install Python 3.10+** (one-time) from python.org — tick "Add Python to PATH".
2. **Add Topaz API credits.** The tool uses your Topaz Labs API. The trial balance
   (~20 credits) is only enough for testing; processing real batches needs a paid
   top-up on your Topaz account. This is the only outside dependency — the software
   itself is complete.
3. **Add your key:** copy `.env.example` to `.env` and paste your Topaz API key.
4. Double-click `Start.bat`.

## Two small preferences you can confirm anytime (already set to safe defaults)
- **Bloom upscaling:** right now Bloom enhances at the original size and Gigapixel
  does all the enlarging for print. If you'd prefer Bloom to also add pixels first,
  it's a quick change.
- **Pipeline order** is set to Bloom → Gigapixel per your described workflow.

Both have working defaults, so nothing is blocked.

## Support
Happy to tweak settings (Bloom strength, target print size, DPI rules) or adjust the
look once you've run it on a few images. Just message me.
