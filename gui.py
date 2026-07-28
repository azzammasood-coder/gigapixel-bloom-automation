#!/usr/bin/env python3
"""Point-and-click app for the Gigapixel + Bloom automation (Leslie's workflow).

Flow:
  1. Pick an image or folder + an output folder, click "Run Bloom".
  2. Review screen: see each Bloom result. Uncheck any you don't want, or
     "Re-run Bloom" (optionally at a different strength) on ones that look wrong.
  3. Click "Finish approved" to run the final Gigapixel upscale + save print-ready.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from PIL import Image, ImageTk

from src.config import load_config
from src.pipeline import BLOOM_SUFFIX, Pipeline

THUMB = (220, 220)


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Gigapixel + Bloom Automation")
        root.geometry("860x640")
        root.minsize(720, 560)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(Path.cwd() / "output"))
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.worker: threading.Thread | None = None

        self.pipeline: Pipeline | None = None
        self._thumbs: list[ImageTk.PhotoImage] = []   # keep refs alive
        self.rows: dict[str, dict] = {}               # stem -> widgets/vars

        self.container = ttk.Frame(root)
        self.container.pack(fill="both", expand=True)
        self._build_setup_screen()
        self.root.after(100, self._drain_log)

    # ==================================================================
    # Screen 1 — setup
    # ==================================================================

    def _build_setup_screen(self) -> None:
        self._clear_container()
        pad = {"padx": 8, "pady": 6}
        frm = ttk.Frame(self.container, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="1. Choose an image or a folder of images:").grid(
            row=0, column=0, columnspan=3, sticky="w")
        ttk.Entry(frm, textvariable=self.input_var).grid(row=1, column=0, sticky="ew", **pad)
        ttk.Button(frm, text="Image…", command=self._pick_file).grid(row=1, column=1, **pad)
        ttk.Button(frm, text="Folder…", command=self._pick_folder).grid(row=1, column=2, **pad)

        ttk.Label(frm, text="2. Choose where to save the print-ready files:").grid(
            row=2, column=0, columnspan=3, sticky="w")
        ttk.Entry(frm, textvariable=self.output_var).grid(row=3, column=0, sticky="ew", **pad)
        ttk.Button(frm, text="Save to…", command=self._pick_output).grid(row=3, column=1, **pad)

        self.start_btn = ttk.Button(frm, text="3.  Run Bloom  →", command=self._start_bloom)
        self.start_btn.grid(row=4, column=0, columnspan=3, sticky="ew", **pad)

        self.progress = ttk.Progressbar(frm, mode="indeterminate")
        self.progress.grid(row=5, column=0, columnspan=3, sticky="ew", **pad)

        self.log_box = scrolledtext.ScrolledText(frm, height=16, state="disabled", wrap="word")
        self.log_box.grid(row=6, column=0, columnspan=3, sticky="nsew", **pad)

        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(6, weight=1)

    def _pick_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose an image",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.tif *.tiff *.webp *.bmp"), ("All files", "*.*")])
        if path:
            self.input_var.set(path)

    def _pick_folder(self) -> None:
        path = filedialog.askdirectory(title="Choose a folder of images")
        if path:
            self.input_var.set(path)

    def _pick_output(self) -> None:
        path = filedialog.askdirectory(title="Choose an output folder")
        if path:
            self.output_var.set(path)

    # ==================================================================
    # Phase 1 — Bloom (background)
    # ==================================================================

    def _start_bloom(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        input_path = self.input_var.get().strip()
        output_path = self.output_var.get().strip()
        if not input_path:
            messagebox.showwarning("Missing input", "Please choose an image or a folder first.")
            return
        if not output_path:
            messagebox.showwarning("Missing output", "Please choose where to save the results.")
            return

        self.start_btn.config(state="disabled")
        self.progress.start(12)
        self._clear_log()
        self.worker = threading.Thread(
            target=self._run_bloom, args=(input_path, output_path), daemon=True)
        self.worker.start()

    def _run_bloom(self, input_path: str, output_path: str) -> None:
        def log(msg: str) -> None:
            self.log_queue.put(msg)
        try:
            config = load_config()
            self.pipeline = Pipeline(config, logger=log)
            self.pipeline.run_bloom_phase(input_path, output_path)
            self.log_queue.put("__BLOOM_DONE__")
        except Exception as exc:  # noqa: BLE001
            self.log_queue.put(f"__ERROR__ {exc}")

    # ==================================================================
    # Screen 2 — review
    # ==================================================================

    def _build_review_screen(self) -> None:
        self._clear_container()
        self._thumbs.clear()
        self.rows.clear()

        top = ttk.Frame(self.container, padding=(12, 10))
        top.pack(fill="x")
        ttk.Label(top, text="Review the Bloom results. Uncheck any you don't want, "
                            "or re-run Bloom on ones that look wrong.",
                  wraplength=800).pack(side="left")

        # Scrollable list of results.
        mid = ttk.Frame(self.container)
        mid.pack(fill="both", expand=True, padx=12)
        canvas = tk.Canvas(mid, highlightthickness=0)
        scroll = ttk.Scrollbar(mid, orient="vertical", command=canvas.yview)
        self.list_frame = ttk.Frame(canvas)
        self.list_frame.bind("<Configure>",
                             lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        review_dir = Path(self.output_var.get()) / "review"
        blooms = sorted(review_dir.glob(f"*{BLOOM_SUFFIX}"))
        if not blooms:
            ttk.Label(self.list_frame, text="No Bloom results found.").pack(pady=20)
        for bloom_path in blooms:
            self._add_review_row(bloom_path)

        bottom = ttk.Frame(self.container, padding=(12, 10))
        bottom.pack(fill="x")
        self.finish_btn = ttk.Button(bottom, text="Finish approved  →  (Gigapixel + save)",
                                     command=self._start_finish)
        self.finish_btn.pack(side="right")
        ttk.Button(bottom, text="← Back", command=self._build_setup_screen).pack(side="left")
        self.review_progress = ttk.Progressbar(bottom, mode="indeterminate")
        self.review_progress.pack(side="left", fill="x", expand=True, padx=12)

    def _add_review_row(self, bloom_path: Path) -> None:
        stem = bloom_path.name[: -len(BLOOM_SUFFIX)]
        row = ttk.Frame(self.list_frame, padding=6, relief="groove", borderwidth=1)
        row.pack(fill="x", pady=4)

        # Thumbnail
        try:
            with Image.open(bloom_path) as im:
                im = im.convert("RGB")
                im.thumbnail(THUMB)
                photo = ImageTk.PhotoImage(im)
            self._thumbs.append(photo)
            ttk.Label(row, image=photo).pack(side="left", padx=6)
        except Exception:  # noqa: BLE001
            ttk.Label(row, text="[preview unavailable]").pack(side="left", padx=6)

        right = ttk.Frame(row)
        right.pack(side="left", fill="x", expand=True)
        ttk.Label(right, text=stem, font=("", 10, "bold")).pack(anchor="w")

        approve_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text="Approve for print", variable=approve_var).pack(anchor="w")

        rerun = ttk.Frame(right)
        rerun.pack(anchor="w", pady=4)
        ttk.Label(rerun, text="Bloom strength:").pack(side="left")
        strength_var = tk.StringVar(value="0.25")
        ttk.Entry(rerun, textvariable=strength_var, width=6).pack(side="left", padx=4)
        btn = ttk.Button(rerun, text="Re-run Bloom",
                         command=lambda s=stem: self._rerun_bloom(s))
        btn.pack(side="left", padx=4)

        status = ttk.Label(right, text="", foreground="gray")
        status.pack(anchor="w")

        self.rows[stem] = {
            "approve": approve_var, "strength": strength_var,
            "status": status, "thumb_label": row, "rerun_btn": btn,
        }

    def _rerun_bloom(self, stem: str) -> None:
        if self.worker and self.worker.is_alive():
            return
        info = self.rows[stem]
        try:
            strength = float(info["strength"].get())
        except ValueError:
            messagebox.showwarning("Invalid strength", "Strength must be a number like 0.25.")
            return
        info["status"].config(text="re-running Bloom…", foreground="blue")
        info["rerun_btn"].config(state="disabled")

        def work():
            try:
                review_dir = Path(self.output_var.get()) / "review"
                src = _read_source_for_stem(review_dir, stem)
                self.pipeline.bloom_one(src, review_dir, strength_override=strength)
                self.log_queue.put(f"__RERUN_DONE__ {stem}")
            except Exception as exc:  # noqa: BLE001
                self.log_queue.put(f"__RERUN_ERR__ {stem} :: {exc}")

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    # ==================================================================
    # Phase 2 — Finish (background)
    # ==================================================================

    def _start_finish(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        approved = [stem for stem, info in self.rows.items() if info["approve"].get()]
        if not approved:
            messagebox.showwarning("Nothing approved", "Tick at least one image to finish.")
            return
        self.finish_btn.config(state="disabled")
        self.review_progress.start(12)

        def work():
            def log(msg: str) -> None:
                self.log_queue.put(msg)
            try:
                self.pipeline.log = log
                self.pipeline.run_finish_phase(self.output_var.get(), only=approved)
                self.log_queue.put(f"__FINISH_DONE__ {len(approved)}")
            except Exception as exc:  # noqa: BLE001
                self.log_queue.put(f"__ERROR__ {exc}")

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    # ==================================================================
    # log / message plumbing
    # ==================================================================

    def _drain_log(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg == "__BLOOM_DONE__":
                    self.progress.stop()
                    self.start_btn.config(state="normal")
                    self._build_review_screen()
                elif msg.startswith("__RERUN_DONE__"):
                    self._rerun_finished(msg.split(" ", 1)[1], ok=True)
                elif msg.startswith("__RERUN_ERR__"):
                    stem, err = msg[len("__RERUN_ERR__ "):].split(" :: ", 1)
                    self._rerun_finished(stem, ok=False, err=err)
                elif msg.startswith("__FINISH_DONE__"):
                    n = msg.split(" ", 1)[1]
                    self.review_progress.stop()
                    self.finish_btn.config(state="normal")
                    messagebox.showinfo("Done", f"Saved {n} print-ready image(s) to:\n{self.output_var.get()}")
                elif msg.startswith("__ERROR__"):
                    self.progress.stop()
                    try:
                        self.review_progress.stop()
                    except Exception:  # noqa: BLE001
                        pass
                    self.start_btn.config(state="normal")
                    messagebox.showerror("Error", msg[len("__ERROR__ "):])
                elif hasattr(self, "log_box") and self.log_box.winfo_exists():
                    self._append(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log)

    def _rerun_finished(self, stem: str, *, ok: bool, err: str = "") -> None:
        info = self.rows.get(stem)
        if not info:
            return
        info["rerun_btn"].config(state="normal")
        if ok:
            info["status"].config(text="Bloom updated — reopen to view", foreground="green")
            # refresh thumbnail
            review_dir = Path(self.output_var.get()) / "review"
            bloom_path = review_dir / f"{stem}{BLOOM_SUFFIX}"
            try:
                with Image.open(bloom_path) as im:
                    im = im.convert("RGB"); im.thumbnail(THUMB)
                    photo = ImageTk.PhotoImage(im)
                self._thumbs.append(photo)
                for child in info["thumb_label"].winfo_children():
                    if isinstance(child, ttk.Label) and child.cget("image"):
                        child.config(image=photo)
                        break
            except Exception:  # noqa: BLE001
                pass
        else:
            info["status"].config(text=f"re-run failed: {err}", foreground="red")

    def _clear_container(self) -> None:
        for child in self.container.winfo_children():
            child.destroy()

    def _clear_log(self) -> None:
        self.log_box.config(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.config(state="disabled")

    def _append(self, text: str) -> None:
        self.log_box.config(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")


def _read_source_for_stem(review_dir: Path, stem: str) -> Path:
    """Look up the original source image path from the Bloom sidecar."""
    import json
    sidecar = review_dir / f"{stem}__bloom.json"
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    return Path(data["source"])


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
