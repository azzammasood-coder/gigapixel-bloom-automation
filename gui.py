#!/usr/bin/env python3
"""Point-and-click app for the Gigapixel + Bloom automation (Leslie's workflow).

Flow:
  1. Pick an image or folder + an output folder, click "Run Bloom".
  2. Review screen: see each Bloom result. Uncheck any you don't want, or
     "Re-run Bloom" (optionally at a different strength) on ones that look wrong.
  3. Click "Finish approved" to run the final Gigapixel upscale + save print-ready.

Plain progress is shown in the window; full technical detail is written to
log.txt next to the app for troubleshooting.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from PIL import Image, ImageTk

from src.config import app_dir, load_config, log_file_path
from src.pipeline import BLOOM_SUFFIX, Pipeline
from src.run_logger import RunLogger

THUMB = (210, 210)

# --- palette -------------------------------------------------------------
BG = "#f4f5f7"
CARD = "#ffffff"
TEXT = "#1f2430"
MUTED = "#6b7280"
ACCENT = "#4f46e5"
ACCENT_HOVER = "#4338ca"
BORDER = "#e5e7eb"
LOG_BG = "#0f172a"
LOG_FG = "#e2e8f0"


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Gigapixel + Bloom Automation")
        root.geometry("880x660")
        root.minsize(760, 580)
        root.configure(bg=BG)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(app_dir() / "output"))
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.worker: threading.Thread | None = None

        self.pipeline: Pipeline | None = None
        self._thumbs: list[ImageTk.PhotoImage] = []
        self.rows: dict[str, dict] = {}

        self._init_fonts()
        self._init_style()

        self.container = tk.Frame(root, bg=BG)
        self.container.pack(fill="both", expand=True)
        self._build_setup_screen()
        self.root.after(100, self._drain_log)

    # ==================================================================
    # theme
    # ==================================================================

    def _init_fonts(self) -> None:
        self.f_body = tkfont.Font(family="Segoe UI", size=10)
        self.f_section = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.f_title = tkfont.Font(family="Segoe UI Semibold", size=17)
        self.f_subtitle = tkfont.Font(family="Segoe UI", size=10)
        self.f_btn = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.f_mono = tkfont.Font(family="Consolas", size=9)

    def _init_style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("TLabel", background=BG, foreground=TEXT, font=self.f_body)
        style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=self.f_body)
        style.configure("Section.TLabel", background=CARD, foreground=TEXT, font=self.f_section)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=self.f_subtitle)

        style.configure("TEntry", fieldbackground="#ffffff", bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER, foreground=TEXT, padding=6)

        # Secondary (subtle) button
        style.configure("TButton", background="#eef0f3", foreground=TEXT,
                        font=self.f_body, borderwidth=0, focusthickness=0, padding=(12, 7))
        style.map("TButton", background=[("active", "#e2e6eb")])

        # Primary (accent) button
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                        font=self.f_btn, borderwidth=0, focusthickness=0, padding=(14, 11))
        style.map("Accent.TButton",
                  background=[("active", ACCENT_HOVER), ("disabled", "#c7cbd1")],
                  foreground=[("disabled", "#eef0f3")])

        # Progress bar (determinate look, accent fill)
        style.configure("Accent.Horizontal.TProgressbar",
                        troughcolor="#e9eaee", background=ACCENT,
                        bordercolor="#e9eaee", lightcolor=ACCENT, darkcolor=ACCENT,
                        thickness=8)
        style.configure("TCheckbutton", background=CARD, foreground=TEXT, font=self.f_body)
        style.map("TCheckbutton", background=[("active", CARD)])

    def _card(self, parent) -> tk.Frame:
        outer = tk.Frame(parent, bg=BORDER)          # 1px border effect
        inner = tk.Frame(outer, bg=CARD)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        return outer, inner

    # ==================================================================
    # Screen 1 — setup
    # ==================================================================

    def _build_setup_screen(self) -> None:
        self._clear_container()
        wrap = tk.Frame(self.container, bg=BG)
        wrap.pack(fill="both", expand=True, padx=22, pady=18)

        # Header
        header = tk.Frame(wrap, bg=BG)
        header.pack(fill="x", pady=(0, 14))
        tk.Label(header, text="Gigapixel + Bloom Automation", bg=BG, fg=TEXT,
                 font=self.f_title).pack(anchor="w")
        tk.Label(header, text="Enhance and upscale your art into print-ready files.",
                 bg=BG, fg=MUTED, font=self.f_subtitle).pack(anchor="w", pady=(2, 0))

        # Input card
        _, card = self._card(wrap)
        card.master.pack(fill="x")
        pad = {"padx": 16}
        tk.Label(card, text="1.  Choose an image or a folder of images",
                 bg=CARD, fg=TEXT, font=self.f_section).grid(row=0, column=0, columnspan=3,
                                                             sticky="w", padx=16, pady=(14, 2))
        e1 = ttk.Entry(card, textvariable=self.input_var)
        e1.grid(row=1, column=0, sticky="ew", padx=16, pady=6)
        ttk.Button(card, text="Image…", command=self._pick_file).grid(row=1, column=1, padx=(0, 6), pady=6)
        ttk.Button(card, text="Folder…", command=self._pick_folder).grid(row=1, column=2, padx=(0, 16), pady=6)

        tk.Label(card, text="2.  Choose where to save the print-ready files",
                 bg=CARD, fg=TEXT, font=self.f_section).grid(row=2, column=0, columnspan=3,
                                                             sticky="w", padx=16, pady=(10, 2))
        e2 = ttk.Entry(card, textvariable=self.output_var)
        e2.grid(row=3, column=0, sticky="ew", padx=16, pady=6)
        ttk.Button(card, text="Save to…", command=self._pick_output).grid(row=3, column=1, padx=(0, 6), pady=6)

        self.start_btn = ttk.Button(card, text="Run Bloom  →", style="Accent.TButton",
                                    command=self._start_bloom)
        self.start_btn.grid(row=4, column=0, columnspan=3, sticky="ew", padx=16, pady=(12, 8))

        self.progress = ttk.Progressbar(card, style="Accent.Horizontal.TProgressbar",
                                        mode="determinate", value=0)
        self.progress.grid(row=5, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 14))
        self.progress.grid_remove()   # hidden until working (fixes the resting green block)

        card.columnconfigure(0, weight=1)

        # Activity log card
        tk.Label(wrap, text="Activity", bg=BG, fg=MUTED, font=self.f_section).pack(
            anchor="w", pady=(16, 4))
        _, logcard = self._card(wrap)
        logcard.master.pack(fill="both", expand=True)
        self.log_box = tk.Text(logcard, height=12, state="disabled", wrap="word",
                               bg=LOG_BG, fg=LOG_FG, insertbackground=LOG_FG,
                               relief="flat", font=self.f_mono, padx=14, pady=12,
                               highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(logcard, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_box.pack(side="left", fill="both", expand=True)

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
    # busy indicator
    # ==================================================================

    @staticmethod
    def _busy_start(bar: ttk.Progressbar) -> None:
        bar.configure(mode="indeterminate")
        bar.start(14)

    @staticmethod
    def _busy_stop(bar: ttk.Progressbar) -> None:
        bar.stop()
        bar.configure(mode="determinate", value=0)

    # ==================================================================
    # Phase 1 — Bloom (background)
    # ==================================================================

    def _make_logger(self) -> RunLogger:
        return RunLogger(log_file_path(), ui_callback=lambda m: self.log_queue.put(m))

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
        self.progress.grid()
        self._busy_start(self.progress)
        self._clear_log()
        self.worker = threading.Thread(
            target=self._run_bloom, args=(input_path, output_path), daemon=True)
        self.worker.start()

    def _run_bloom(self, input_path: str, output_path: str) -> None:
        try:
            config = load_config()
            self.pipeline = Pipeline(config, logger=self._make_logger())
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

        wrap = tk.Frame(self.container, bg=BG)
        wrap.pack(fill="both", expand=True, padx=22, pady=18)

        tk.Label(wrap, text="Review the Bloom results", bg=BG, fg=TEXT,
                 font=self.f_title).pack(anchor="w")
        tk.Label(wrap, text="Keep the good ones checked. Re-run Bloom on any that look "
                            "wrong, then finish to upscale for print.",
                 bg=BG, fg=MUTED, font=self.f_subtitle, justify="left").pack(anchor="w", pady=(2, 12))

        # Scrollable list
        listwrap, listcard = self._card(wrap)
        listwrap.pack(fill="both", expand=True)
        canvas = tk.Canvas(listcard, highlightthickness=0, bg=CARD)
        scroll = ttk.Scrollbar(listcard, orient="vertical", command=canvas.yview)
        self.list_frame = tk.Frame(canvas, bg=CARD)
        self.list_frame.bind("<Configure>",
                             lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.list_frame, anchor="nw", width=780)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        review_dir = Path(self.output_var.get()) / "review"
        blooms = sorted(review_dir.glob(f"*{BLOOM_SUFFIX}"))
        if not blooms:
            tk.Label(self.list_frame, text="No Bloom results found.", bg=CARD, fg=MUTED).pack(pady=20)
        for bloom_path in blooms:
            self._add_review_row(bloom_path)

        bottom = tk.Frame(wrap, bg=BG)
        bottom.pack(fill="x", pady=(12, 0))
        ttk.Button(bottom, text="←  Back", command=self._build_setup_screen).pack(side="left")
        self.finish_btn = ttk.Button(bottom, text="Finish approved  →", style="Accent.TButton",
                                     command=self._start_finish)
        self.finish_btn.pack(side="right")
        self.review_progress = ttk.Progressbar(bottom, style="Accent.Horizontal.TProgressbar",
                                               mode="determinate", value=0)

    def _add_review_row(self, bloom_path: Path) -> None:
        stem = bloom_path.name[: -len(BLOOM_SUFFIX)]
        row = tk.Frame(self.list_frame, bg=CARD, highlightbackground=BORDER,
                       highlightthickness=1)
        row.pack(fill="x", padx=10, pady=6)

        try:
            with Image.open(bloom_path) as im:
                im = im.convert("RGB")
                im.thumbnail(THUMB)
                photo = ImageTk.PhotoImage(im)
            self._thumbs.append(photo)
            tk.Label(row, image=photo, bg=CARD).pack(side="left", padx=10, pady=10)
        except Exception:  # noqa: BLE001
            tk.Label(row, text="[preview unavailable]", bg=CARD, fg=MUTED).pack(side="left", padx=10)

        right = tk.Frame(row, bg=CARD)
        right.pack(side="left", fill="x", expand=True, pady=10)
        tk.Label(right, text=stem, bg=CARD, fg=TEXT, font=self.f_section,
                 wraplength=430, justify="left").pack(anchor="w")

        approve_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text="Approve for print", variable=approve_var).pack(anchor="w", pady=(4, 4))

        rerun = tk.Frame(right, bg=CARD)
        rerun.pack(anchor="w")
        tk.Label(rerun, text="Bloom strength:", bg=CARD, fg=MUTED, font=self.f_body).pack(side="left")
        strength_var = tk.StringVar(value="0.25")
        ttk.Entry(rerun, textvariable=strength_var, width=6).pack(side="left", padx=6)
        btn = ttk.Button(rerun, text="Re-run Bloom", command=lambda s=stem: self._rerun_bloom(s))
        btn.pack(side="left", padx=4)

        status = tk.Label(right, text="", bg=CARD, fg=MUTED, font=self.f_body)
        status.pack(anchor="w", pady=(4, 0))

        self.rows[stem] = {"approve": approve_var, "strength": strength_var,
                           "status": status, "row": row, "rerun_btn": btn}

    def _rerun_bloom(self, stem: str) -> None:
        if self.worker and self.worker.is_alive():
            return
        info = self.rows[stem]
        try:
            strength = float(info["strength"].get())
        except ValueError:
            messagebox.showwarning("Invalid strength", "Strength must be a number like 0.25.")
            return
        info["status"].config(text="re-running Bloom…", fg=ACCENT)
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
        self.review_progress.pack(side="left", fill="x", expand=True, padx=12)
        self._busy_start(self.review_progress)

        def work():
            try:
                self.pipeline.run_finish_phase(self.output_var.get(), only=approved)
                self.log_queue.put(f"__FINISH_DONE__ {len(approved)}")
            except Exception as exc:  # noqa: BLE001
                self.log_queue.put(f"__ERROR__ {exc}")

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    # ==================================================================
    # message plumbing
    # ==================================================================

    def _drain_log(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg == "__BLOOM_DONE__":
                    self._busy_stop(self.progress)
                    self.progress.grid_remove()
                    self.start_btn.config(state="normal")
                    self._build_review_screen()
                elif msg.startswith("__RERUN_DONE__"):
                    self._rerun_finished(msg.split(" ", 1)[1], ok=True)
                elif msg.startswith("__RERUN_ERR__"):
                    stem, err = msg[len("__RERUN_ERR__ "):].split(" :: ", 1)
                    self._rerun_finished(stem, ok=False, err=err)
                elif msg.startswith("__FINISH_DONE__"):
                    n = msg.split(" ", 1)[1]
                    self._busy_stop(self.review_progress)
                    self.review_progress.pack_forget()
                    self.finish_btn.config(state="normal")
                    messagebox.showinfo(
                        "Done", f"Saved {n} print-ready image(s) to:\n{self.output_var.get()}")
                elif msg.startswith("__ERROR__"):
                    if self.progress.winfo_exists():
                        self._busy_stop(self.progress)
                        self.progress.grid_remove()
                    if hasattr(self, "review_progress") and self.review_progress.winfo_exists():
                        self._busy_stop(self.review_progress)
                        self.review_progress.pack_forget()
                    if hasattr(self, "start_btn") and self.start_btn.winfo_exists():
                        self.start_btn.config(state="normal")
                    if hasattr(self, "finish_btn") and self.finish_btn.winfo_exists():
                        self.finish_btn.config(state="normal")
                    detail = msg[len("__ERROR__ "):]
                    messagebox.showerror(
                        "Something went wrong",
                        f"{detail}\n\nTechnical details were written to:\n{log_file_path()}")
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
            info["status"].config(text="Bloom updated ✓", fg="#16a34a")
            review_dir = Path(self.output_var.get()) / "review"
            bloom_path = review_dir / f"{stem}{BLOOM_SUFFIX}"
            try:
                with Image.open(bloom_path) as im:
                    im = im.convert("RGB"); im.thumbnail(THUMB)
                    photo = ImageTk.PhotoImage(im)
                self._thumbs.append(photo)
                for child in info["row"].winfo_children():
                    if isinstance(child, tk.Label) and child.cget("image"):
                        child.config(image=photo)
                        break
            except Exception:  # noqa: BLE001
                pass
        else:
            info["status"].config(text=f"re-run failed — see log.txt", fg="#dc2626")

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
