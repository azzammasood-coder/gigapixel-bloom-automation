# Gigapixel + Bloom Automation

Automates Leslie's print-prep workflow: **Bloom → (you review) → Gigapixel**, with
an optional AI step that picks per-image settings. Point it at a single image or a
whole folder; it produces print-ready files (correct aspect ratio, print DPI,
JPG/PNG for Lumaprints).

Because Bloom can occasionally distort an image (especially faces), there is a
**human review step** in the middle: you approve the good Bloom results — and
re-run Bloom on any that look wrong — before the final Gigapixel upscale.

## For Leslie (easy way — no installing anything)

Use the ready-to-run app (the `GigapixelBloom` folder — Windows, no Python needed):

1. Open the `.env` file (right-click → Open with → Notepad), paste your Topaz Labs
   API key after `TOPAZ_API_KEY=`, and save.
2. **Double-click `GigapixelBloom.exe`.**
3. **Run Bloom** on your image/folder → **review** the results (approve or re-run) →
   **Finish approved** to upscale and save the print-ready files.

Keep everything in that folder together. A `log.txt` is written there if anything
goes wrong — send it to your developer for a quick fix. See `READ ME FIRST.txt`.

## For developers (command line)

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
cp .env.example .env                                     # then edit .env

# Phase 1 — Bloom (results land in <output>/review/ for you to inspect)
python run.py bloom "path/to/folder" -o out

# Phase 2 — finish the ones you approve (all, or a subset by name)
python run.py finish -o out
python run.py finish -o out --only golf1,golf2

# Both phases at once, auto-approving everything (testing / trust-the-AI)
python run.py auto "path/to/folder" -o out
python run.py auto "path/to/folder" -o out --dry-run    # no API calls, no credits
```

## Configuration

- **Secrets** live in `.env` (never committed): `TOPAZ_API_KEY`, and optionally
  `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` for the AI step.
- **Behavior** lives in `config.yaml`: Bloom model/strength, final Gigapixel model,
  target print resolution, DPI (300 painterly / 200 illustration), output format,
  and the AI instructions. Leslie's rules (painterly look, lowest creative changes,
  gentle on faces) are encoded there.

If no `LLM_API_KEY` is set, the AI step is skipped and the defaults in
`config.yaml` are used for every image.

## How it works

**Phase 1 — Bloom.** For each image, run Bloom (defaults to `Bloom Realism` at low
strength to keep the painterly look; faces handled gently). Each result is written
to `<output>/review/` next to a small JSON sidecar describing how to finish it.

**Review.** You inspect the Bloom results. Approve the good ones; re-run Bloom
(optionally at a different strength) on any that came out wrong.

**Phase 2 — Finish.** Approved images get the final Gigapixel upscale to the target
print resolution (preserving the original aspect ratio), then DPI is embedded and
the file is saved as JPG/PNG. Warns if a file exceeds the 100 MB Lumaprints
web-uploader cap.

Intermediate/working files are kept under `<output>/.work/` and `<output>/review/`.

## Project layout

```
run.py            CLI (subcommands: bloom / finish / auto)
gui.py            point-and-click app with the review screen
config.yaml       default settings + AI instructions
.env.example      template for secrets
src/
  config.py       loads config.yaml + .env
  topaz_client.py Topaz Image API client (async enhance/status/download)
  llm_advisor.py  optional AI vision step (OpenAI-compatible)
  image_utils.py  sizing, DPI, format helpers (Pillow)
  pipeline.py     orchestrates the two-phase pipeline
```

## Notes

- The Topaz API key is a **live secret** — keep it in `.env`, which is gitignored.
- Topaz API usage consumes credits; test with `--dry-run` first and a single image
  before running large folders.
