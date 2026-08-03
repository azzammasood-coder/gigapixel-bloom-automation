# Demo Video — How-To + Script

A short (~2–3 min) screen recording that shows **what the tool looks like** and
**how it works**, end to end. Two versions are described:

- **Version A (recommended):** a real run on 1–2 images. Uses only a few Topaz
  credits (the account still has enough for a short demo). Most convincing.
- **Version B (zero credits):** narrate over the finished before/after results we
  already produced + walk the interface. Use if you don't want to spend any credits.

---

## 1. Before you record

- Close messy windows; set desktop to something clean.
- Have these open/ready:
  - The project folder in File Explorer.
  - `example-images/` (the 4 originals).
  - The finished proof images in `deliverables/`:
    `before_after_bloom.jpg`, `face_detail_compare.jpg`.
  - The final print file in `output/…_print.jpg` (6000×6000, 300 DPI).
- Recording tool (any one):
  - **Windows Game Bar** — press `Win + G`, then the record button. Simplest.
  - **OBS Studio** (free) — for higher quality / webcam bubble.
  - **Loom** (free) — records + gives a shareable link automatically.
- Record at **1080p**, cursor visible. Narrate live, or record silent and add the
  script as captions/voiceover after.

> Tip: rehearse once. Keep it under 3 minutes — buyers skim.

---

## 2. Shot list + narration script

Each row = one on-screen action + what to say.

### Intro (0:00–0:20)
- **Show:** the `before_after_bloom.jpg` full screen.
- **Say:**
  > "Hi Leslie — here's the automation for your Bloom and Gigapixel workflow.
  > On the left is one of your Midjourney originals; on the right is the same image
  > after the tool ran Bloom. The painterly brush strokes are kept, and the face
  > isn't distorted — that's the whole goal."

### The problem it solves (0:20–0:35)
- **Show:** the 4 images in `example-images/`.
- **Say:**
  > "Instead of running each image through Bloom and Gigapixel by hand, you just
  > point the tool at one image or a whole folder, and it does both steps for you —
  > while still letting you approve each result."

### Launch the app (0:35–0:50)
- **Show:** double-click `Start.bat`; the app window opens.
- **Say:**
  > "You open it by double-clicking Start. No coding. You pick an image or a folder,
  > pick where to save, and press Run Bloom."

### Phase 1 — Bloom (0:50–1:20)  *(Version A: real run)*
- **Show:** click **Folder…**, choose `example-images` (or a single image); pick an
  output folder; click **Run Bloom**. Let the progress bar run.
- **Say:**
  > "First it runs Bloom on each image, using the lowest-creative-change setting so
  > it keeps your painted look and doesn't smooth the detail away."
- *(Version B: skip the wait — cut to the already-processed review folder.)*

### The review step (1:20–2:00) — the important part
- **Show:** the review screen with the Bloom thumbnail(s), the **Approve** checkbox,
  and the **Re-run Bloom** button + strength box.
- **Say:**
  > "This is the step you asked for. Bloom can sometimes change an image in a way
  > you don't like — especially faces. So the tool shows you every Bloom result.
  > If one looks wrong, you re-run Bloom right here — you can even nudge the strength —
  > until it's right. You only keep the ones you approve."
- **Show:** (optional) type `0.15` and click **Re-run Bloom** on one image to show it
  updating.

### Phase 2 — Finish for print (2:00–2:30)
- **Show:** click **Finish approved**; when done, open the output folder and
  right-click the `…_print.jpg` → Properties (show size), and open it to show it's sharp.
- **Say:**
  > "When you're happy, click Finish. It runs the final Gigapixel upscale to full
  > print resolution, keeps the correct aspect ratio, and saves a print-ready JPEG —
  > 300 DPI for painterly art, 200 for illustrations — all within Lumaprints' limits."

### Close (2:30–2:45)
- **Show:** the `face_detail_compare.jpg`.
- **Say:**
  > "That's it — drop in a folder, approve the good ones, get print-ready files.
  > Everything saves to a folder on your computer, just like you asked. Let me know
  > if you'd like any tweaks."

---

## 3. Commands (if you prefer showing the terminal instead of the app)

```bash
# no credits — shows the mechanics only (copies originals as stand-ins)
python run.py auto "example-images" -o output --dry-run

# real run on one image (a few credits)
python run.py auto "example-images/<one-file>.png" -o output

# two-step, matching the app:
python run.py bloom "example-images" -o output      # then review output/review/
python run.py finish -o output                       # finish the approved ones
```

## 4. If a live run fails mid-demo
The trial key has limited credits. If a call errors with a credit/quota message,
switch to **Version B**: show the pre-made `deliverables/` before/after images and
the existing `output/…_print.jpg`. The quality proof is the same.
