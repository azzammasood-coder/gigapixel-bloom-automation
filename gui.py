#!/usr/bin/env python3
"""Point-and-click app for the Gigapixel + Bloom automation (Leslie's workflow).

Screens:
  1. Setup   — pick input + output, Run Bloom.
  2. Review  — see each Bloom result (click to open a zoomable viewer); approve
               the good ones or Re-run Bloom on ones that look wrong; Finish.
  3. Output  — see the finished print-ready images (click to zoom); optionally
               upload selected ones to a Dropbox folder.

Plain progress shows in the window; full technical detail goes to log.txt.
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

THUMB = (300, 300)
VIEWER_MAX = 2600   # cap the pixels loaded into the zoom viewer (keeps RAM sane)

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


# =====================================================================
# Zoomable image viewer (used from both the review and output screens)
# =====================================================================

class ImageViewer(tk.Toplevel):
    def __init__(self, parent, image_path: Path, title: str = "") -> None:
        super().__init__(parent)
        self.title(title or Path(image_path).name)
        self.configure(bg="#111318")
        self.geometry("1000x760")
        self.minsize(500, 400)

        # Load (capped) once; zoom re-renders from this base image.
        img = Image.open(image_path).convert("RGB")
        if max(img.size) > VIEWER_MAX:
            img.thumbnail((VIEWER_MAX, VIEWER_MAX))
        self._base = img
        self._scale = 1.0
        self._fit_scale = 1.0
        self._photo: ImageTk.PhotoImage | None = None

        bar = tk.Frame(self, bg="#191c22")
        bar.pack(fill="x")
        for txt, cmd in [("−  Zoom out", lambda: self._zoom(0.8)),
                         ("＋  Zoom in", lambda: self._zoom(1.25)),
                         ("Fit", self._fit),
                         ("100%", self._actual)]:
            tk.Button(bar, text=txt, command=cmd, bg="#2a2f3a", fg="#e2e8f0",
                      activebackground="#3a4150", activeforeground="#fff", relief="flat",
                      bd=0, padx=12, pady=6).pack(side="left", padx=4, pady=6)
        tk.Button(bar, text="Close", command=self.destroy, bg="#2a2f3a", fg="#e2e8f0",
                  activebackground="#3a4150", relief="flat", bd=0, padx=12, pady=6).pack(side="right", padx=6)

        self.canvas = tk.Canvas(self, bg="#111318", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self._img_id = self.canvas.create_image(0, 0, anchor="center")

        # interactions
        self.canvas.bind("<MouseWheel>", self._on_wheel)               # Windows/mac
        self.canvas.bind("<ButtonPress-1>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B1-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.bind("<Configure>", lambda e: self._maybe_initial_fit())
        self.bind("<Escape>", lambda e: self.destroy())

        self._did_fit = False
        self.after(50, self._maybe_initial_fit)
        self.transient(parent)

    def _maybe_initial_fit(self) -> None:
        if not self._did_fit and self.canvas.winfo_width() > 10:
            self._did_fit = True
            self._fit()

    def _render(self) -> None:
        w = max(1, int(self._base.width * self._scale))
        h = max(1, int(self._base.height * self._scale))
        resized = self._base.resize((w, h), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(resized)
        self.canvas.itemconfigure(self._img_id, image=self._photo)
        self.canvas.coords(self._img_id, self.canvas.winfo_width() // 2, self.canvas.winfo_height() // 2)
        self.canvas.configure(scrollregion=(0, 0, w, h))

    def _zoom(self, factor: float) -> None:
        self._scale = max(0.05, min(8.0, self._scale * factor))
        self._render()

    def _fit(self) -> None:
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        self._fit_scale = min(cw / self._base.width, ch / self._base.height)
        self._scale = self._fit_scale
        self._render()

    def _actual(self) -> None:
        self._scale = 1.0
        self._render()

    def _on_wheel(self, event) -> None:
        self._zoom(1.1 if event.delta > 0 else 0.9)


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Gigapixel + Bloom Automation")
        root.geometry("900x680")
        root.minsize(780, 600)
        root.configure(bg=BG)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(app_dir() / "output"))
        self.prepress_folder_var = tk.StringVar(value="")
        self.placeholder_folder_var = tk.StringVar(value="")
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.worker: threading.Thread | None = None

        self.pipeline: Pipeline | None = None
        self._thumbs: list[ImageTk.PhotoImage] = []
        self.rows: dict[str, dict] = {}
        self._finish_results: list = []
        self.out_rows: dict[str, dict] = {}

        self._init_fonts()
        self._init_style()

        self.container = tk.Frame(root, bg=BG)
        self.container.pack(fill="both", expand=True)
        self._build_setup_screen()
        self.root.after(100, self._drain_log)

    # ------------------------------------------------------------------ theme
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
        style.configure("TLabel", background=BG, foreground=TEXT, font=self.f_body)
        style.configure("TEntry", fieldbackground="#ffffff", bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER, foreground=TEXT, padding=6)
        style.configure("TButton", background="#eef0f3", foreground=TEXT,
                        font=self.f_body, borderwidth=0, focusthickness=0, padding=(12, 7))
        style.map("TButton", background=[("active", "#e2e6eb")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff",
                        font=self.f_btn, borderwidth=0, focusthickness=0, padding=(14, 11))
        style.map("Accent.TButton",
                  background=[("active", ACCENT_HOVER), ("disabled", "#c7cbd1")],
                  foreground=[("disabled", "#eef0f3")])
        style.configure("Accent.Horizontal.TProgressbar",
                        troughcolor="#e9eaee", background=ACCENT,
                        bordercolor="#e9eaee", lightcolor=ACCENT, darkcolor=ACCENT, thickness=8)
        style.configure("TCheckbutton", background=CARD, foreground=TEXT, font=self.f_body)
        style.map("TCheckbutton", background=[("active", CARD)])
        style.configure("TCombobox", padding=5)

    def _card(self, parent):
        outer = tk.Frame(parent, bg=BORDER)
        inner = tk.Frame(outer, bg=CARD)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        return outer, inner

    # ================================================================ setup
    def _build_setup_screen(self) -> None:
        self._clear_container()
        wrap = tk.Frame(self.container, bg=BG)
        wrap.pack(fill="both", expand=True, padx=22, pady=18)

        header = tk.Frame(wrap, bg=BG)
        header.pack(fill="x", pady=(0, 14))
        tk.Label(header, text="Gigapixel + Bloom Automation", bg=BG, fg=TEXT,
                 font=self.f_title).pack(anchor="w")
        tk.Label(header, text="Enhance and upscale your art into print-ready files.",
                 bg=BG, fg=MUTED, font=self.f_subtitle).pack(anchor="w", pady=(2, 0))

        _, card = self._card(wrap)
        card.master.pack(fill="x")
        tk.Label(card, text="1.  Choose an image or a folder of images", bg=CARD, fg=TEXT,
                 font=self.f_section).grid(row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(14, 2))
        ttk.Entry(card, textvariable=self.input_var).grid(row=1, column=0, sticky="ew", padx=16, pady=6)
        ttk.Button(card, text="Image…", command=self._pick_file).grid(row=1, column=1, padx=(0, 6), pady=6)
        ttk.Button(card, text="Folder…", command=self._pick_folder).grid(row=1, column=2, padx=(0, 16), pady=6)

        tk.Label(card, text="2.  Choose where to save the print-ready files", bg=CARD, fg=TEXT,
                 font=self.f_section).grid(row=2, column=0, columnspan=3, sticky="w", padx=16, pady=(10, 2))
        ttk.Entry(card, textvariable=self.output_var).grid(row=3, column=0, sticky="ew", padx=16, pady=6)
        ttk.Button(card, text="Save to…", command=self._pick_output).grid(row=3, column=1, padx=(0, 6), pady=6)

        self.start_btn = ttk.Button(card, text="Run Bloom  →", style="Accent.TButton", command=self._start_bloom)
        self.start_btn.grid(row=4, column=0, columnspan=3, sticky="ew", padx=16, pady=(12, 8))
        self.progress = ttk.Progressbar(card, style="Accent.Horizontal.TProgressbar", mode="determinate", value=0)
        self.progress.grid(row=5, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 14))
        self.progress.grid_remove()
        card.columnconfigure(0, weight=1)

        tk.Label(wrap, text="Activity", bg=BG, fg=MUTED, font=self.f_section).pack(anchor="w", pady=(16, 4))
        _, logcard = self._card(wrap)
        logcard.master.pack(fill="both", expand=True)
        self.log_box = tk.Text(logcard, height=11, state="disabled", wrap="word", bg=LOG_BG, fg=LOG_FG,
                               insertbackground=LOG_FG, relief="flat", font=self.f_mono, padx=14, pady=12,
                               highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(logcard, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_box.pack(side="left", fill="both", expand=True)

    def _pick_file(self) -> None:
        path = filedialog.askopenfilename(title="Choose an image",
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

    # -------------------------------------------------------------- busy bar
    @staticmethod
    def _busy_start(bar: ttk.Progressbar) -> None:
        bar.configure(mode="indeterminate"); bar.start(14)

    @staticmethod
    def _busy_stop(bar: ttk.Progressbar) -> None:
        bar.stop(); bar.configure(mode="determinate", value=0)

    def _make_logger(self) -> RunLogger:
        return RunLogger(log_file_path(), ui_callback=lambda m: self.log_queue.put(m))

    # ============================================================ phase 1
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
        self.progress.grid(); self._busy_start(self.progress)
        self._clear_log()
        self.worker = threading.Thread(target=self._run_bloom, args=(input_path, output_path), daemon=True)
        self.worker.start()

    def _run_bloom(self, input_path: str, output_path: str) -> None:
        try:
            config = load_config()
            self.pipeline = Pipeline(config, logger=self._make_logger())
            self.pipeline.run_bloom_phase(input_path, output_path)
            self.log_queue.put("__BLOOM_DONE__")
        except Exception as exc:  # noqa: BLE001
            self.log_queue.put(f"__ERROR__ {exc}")

    # ============================================================ review
    def _build_review_screen(self) -> None:
        self._clear_container(); self._thumbs.clear(); self.rows.clear()
        wrap = tk.Frame(self.container, bg=BG)
        wrap.pack(fill="both", expand=True, padx=22, pady=18)
        tk.Label(wrap, text="Review the Bloom results", bg=BG, fg=TEXT, font=self.f_title).pack(anchor="w")
        tk.Label(wrap, text="Click any image to view it full-screen and zoom in. Keep the good ones "
                            "checked; re-run Bloom on any that look wrong, then finish.",
                 bg=BG, fg=MUTED, font=self.f_subtitle, justify="left", wraplength=820).pack(anchor="w", pady=(2, 12))

        listcard = self._scroll_list(wrap)
        review_dir = self.pipeline.review_dir
        blooms = sorted(review_dir.glob(f"*{BLOOM_SUFFIX}"))
        if not blooms:
            tk.Label(self.list_frame, text="No Bloom results found.", bg=CARD, fg=MUTED).pack(pady=20)
        for bloom_path in blooms:
            self._add_review_row(bloom_path)

        bottom = tk.Frame(wrap, bg=BG); bottom.pack(fill="x", pady=(12, 0))
        ttk.Button(bottom, text="←  Back", command=self._build_setup_screen).pack(side="left")
        self.finish_btn = ttk.Button(bottom, text="Finish approved  →", style="Accent.TButton", command=self._start_finish)
        self.finish_btn.pack(side="right")
        self.review_progress = ttk.Progressbar(bottom, style="Accent.Horizontal.TProgressbar", mode="determinate", value=0)

    def _scroll_list(self, parent):
        wrapper, card = self._card(parent)
        wrapper.pack(fill="both", expand=True)
        canvas = tk.Canvas(card, highlightthickness=0, bg=CARD)
        scroll = ttk.Scrollbar(card, orient="vertical", command=canvas.yview)
        self.list_frame = tk.Frame(canvas, bg=CARD)
        self.list_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.list_frame, anchor="nw", width=800)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return card

    def _thumb_label(self, parent, image_path: Path):
        try:
            with Image.open(image_path) as im:
                im = im.convert("RGB"); im.thumbnail(THUMB)
                photo = ImageTk.PhotoImage(im)
            self._thumbs.append(photo)
            lbl = tk.Label(parent, image=photo, bg=CARD, cursor="hand2")
            lbl.bind("<Button-1>", lambda e, p=image_path: ImageViewer(self.root, p))
            return lbl
        except Exception:  # noqa: BLE001
            return tk.Label(parent, text="[preview unavailable]", bg=CARD, fg=MUTED)

    def _add_review_row(self, bloom_path: Path) -> None:
        stem = bloom_path.name[: -len(BLOOM_SUFFIX)]
        row = tk.Frame(self.list_frame, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        row.pack(fill="x", padx=10, pady=6)
        self._thumb_label(row, bloom_path).pack(side="left", padx=10, pady=10)

        right = tk.Frame(row, bg=CARD); right.pack(side="left", fill="x", expand=True, pady=10)
        tk.Label(right, text=stem, bg=CARD, fg=TEXT, font=self.f_section, wraplength=380, justify="left").pack(anchor="w")
        tk.Label(right, text="Click the image to zoom.", bg=CARD, fg=MUTED, font=self.f_body).pack(anchor="w")
        approve_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text="Approve for print", variable=approve_var).pack(anchor="w", pady=(4, 4))
        rerun = tk.Frame(right, bg=CARD); rerun.pack(anchor="w")
        tk.Label(rerun, text="Bloom strength:", bg=CARD, fg=MUTED, font=self.f_body).pack(side="left")
        strength_var = tk.StringVar(value="0.25")
        ttk.Entry(rerun, textvariable=strength_var, width=6).pack(side="left", padx=6)
        btn = ttk.Button(rerun, text="Re-run Bloom", command=lambda s=stem: self._rerun_bloom(s))
        btn.pack(side="left", padx=4)
        status = tk.Label(right, text="", bg=CARD, fg=MUTED, font=self.f_body); status.pack(anchor="w", pady=(4, 0))
        self.rows[stem] = {"approve": approve_var, "strength": strength_var, "status": status,
                           "row": row, "rerun_btn": btn}

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
                src = _read_source_for_stem(self.pipeline.review_dir, stem)
                self.pipeline.bloom_one(src, strength_override=strength)
                self.log_queue.put(f"__RERUN_DONE__ {stem}")
            except Exception as exc:  # noqa: BLE001
                self.log_queue.put(f"__RERUN_ERR__ {stem} :: {exc}")

        self.worker = threading.Thread(target=work, daemon=True); self.worker.start()

    # ============================================================ phase 2
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
                results = self.pipeline.run_finish_phase(self.output_var.get(), only=approved)
                self._finish_results = [r for r in results if r.ok]
                self.log_queue.put(f"__FINISH_DONE__ {len(self._finish_results)}")
            except Exception as exc:  # noqa: BLE001
                self.log_queue.put(f"__ERROR__ {exc}")

        self.worker = threading.Thread(target=work, daemon=True); self.worker.start()

    # ============================================================ output
    def _build_output_screen(self) -> None:
        self._clear_container(); self._thumbs.clear(); self.out_rows.clear()
        wrap = tk.Frame(self.container, bg=BG)
        wrap.pack(fill="both", expand=True, padx=22, pady=18)
        tk.Label(wrap, text="Finished — print-ready files", bg=BG, fg=TEXT, font=self.f_title).pack(anchor="w")
        tk.Label(wrap, text=f"Saved to:  {self.output_var.get()}    (click any image to zoom)",
                 bg=BG, fg=MUTED, font=self.f_subtitle, wraplength=820, justify="left").pack(anchor="w", pady=(2, 12))

        self._scroll_list(wrap)
        for r in self._finish_results:
            self._add_output_row(r)

        # Dropbox section
        dbcard_outer, dbcard = self._card(wrap)
        dbcard_outer.pack(fill="x", pady=(12, 0))
        has_db = bool(self.pipeline and self.pipeline.config.secrets
                      and self.pipeline.config.secrets.has_dropbox
                      and self.pipeline.config.get("dropbox", {}).get("enabled"))
        tk.Label(dbcard, text="Upload to Dropbox (optional)", bg=CARD, fg=TEXT,
                 font=self.f_section).pack(anchor="w", padx=14, pady=(12, 4))
        if has_db:
            grid = tk.Frame(dbcard, bg=CARD); grid.pack(fill="x", padx=14, pady=(0, 6))
            tk.Label(grid, text="High-res (Prepress) folder:", bg=CARD, fg=MUTED,
                     font=self.f_body).grid(row=0, column=0, sticky="w", pady=3)
            self.prepress_combo = ttk.Combobox(grid, textvariable=self.prepress_folder_var, width=46, values=[""])
            self.prepress_combo.grid(row=0, column=1, sticky="w", padx=8, pady=3)
            tk.Label(grid, text="Low-res (Placeholder) folder:", bg=CARD, fg=MUTED,
                     font=self.f_body).grid(row=1, column=0, sticky="w", pady=3)
            self.placeholder_combo = ttk.Combobox(grid, textvariable=self.placeholder_folder_var, width=46, values=[""])
            self.placeholder_combo.grid(row=1, column=1, sticky="w", padx=8, pady=3)
            ttk.Button(grid, text="Refresh folders", command=self._load_dropbox_folders).grid(
                row=0, column=2, rowspan=2, padx=8)

            rowf = tk.Frame(dbcard, bg=CARD); rowf.pack(fill="x", padx=14, pady=(2, 6))
            self.upload_btn = ttk.Button(rowf, text="Upload selected  →", style="Accent.TButton",
                                         command=self._start_upload)
            self.upload_btn.pack(side="right")
            self.upload_progress = ttk.Progressbar(dbcard, style="Accent.Horizontal.TProgressbar",
                                                   mode="determinate", value=0)
            self.dropbox_status = tk.Label(dbcard, text="Pick folders above (or type a path like /Prints). "
                                                        "Blank = your Dropbox root.",
                                           bg=CARD, fg=MUTED, font=self.f_body, wraplength=780, justify="left")
            self.dropbox_status.pack(anchor="w", padx=14, pady=(0, 12))
            self._load_dropbox_folders()
        else:
            tk.Label(dbcard, text="Dropbox isn't set up yet. Add DROPBOX_APP_KEY, DROPBOX_APP_SECRET and "
                                  "DROPBOX_REFRESH_TOKEN to the .env file to enable one-click upload.",
                     bg=CARD, fg=MUTED, font=self.f_body, wraplength=780, justify="left").pack(
                         anchor="w", padx=14, pady=(0, 12))

        bottom = tk.Frame(wrap, bg=BG); bottom.pack(fill="x", pady=(12, 0))
        ttk.Button(bottom, text="←  Start over", command=self._build_setup_screen).pack(side="left")
        ttk.Button(bottom, text="Open output folder", command=self._open_output).pack(side="left", padx=8)

    def _add_output_row(self, result) -> None:
        prepress = Path(result.output)
        stem = prepress.stem
        row = tk.Frame(self.list_frame, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        row.pack(fill="x", padx=10, pady=6)
        self._thumb_label(row, prepress).pack(side="left", padx=10, pady=10)
        right = tk.Frame(row, bg=CARD); right.pack(side="left", fill="x", expand=True, pady=10)
        tk.Label(right, text=stem, bg=CARD, fg=TEXT, font=self.f_section, wraplength=420, justify="left").pack(anchor="w")
        try:
            with Image.open(prepress) as im:
                dims = f"{im.size[0]} × {im.size[1]}"
        except Exception:  # noqa: BLE001
            dims = ""
        ph = f"  +  {Path(result.placeholder).name}" if result.placeholder else ""
        tk.Label(right, text=f"{dims}{ph}", bg=CARD, fg=MUTED, font=self.f_body,
                 wraplength=420, justify="left").pack(anchor="w")
        upload_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(right, text="Include in Dropbox upload", variable=upload_var).pack(anchor="w", pady=(4, 0))
        self.out_rows[stem] = {"result": result, "upload": upload_var}

    def _open_output(self) -> None:
        import os
        try:
            os.startfile(self.output_var.get())  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            messagebox.showinfo("Output folder", self.output_var.get())

    # ------------------------------------------------------------- dropbox
    def _dropbox_client(self):
        from src.dropbox_client import DropboxClient
        s = self.pipeline.config.secrets
        return DropboxClient(s.dropbox_app_key, s.dropbox_app_secret, s.dropbox_refresh_token)

    def _load_dropbox_folders(self) -> None:
        def work():
            try:
                folders = self._dropbox_client().list_folders("")
                self.log_queue.put("__DBFOLDERS__ " + "\n".join([""] + folders))
            except Exception as exc:  # noqa: BLE001
                self.log_queue.put(f"__DBERR__ {exc}")
        threading.Thread(target=work, daemon=True).start()

    def _apply_dropbox_folders(self, folders: list[str]) -> None:
        """Fill both folder dropdowns and auto-select the best match for each."""
        if not (hasattr(self, "prepress_combo") and self.prepress_combo.winfo_exists()):
            return
        self.prepress_combo.configure(values=folders)
        self.placeholder_combo.configure(values=folders)

        db_cfg = self.pipeline.config.get("dropbox", {}) if self.pipeline else {}
        pre_hint = str(db_cfg.get("prepress_folder_hint", "high res")).lower()
        ph_hint = str(db_cfg.get("placeholder_folder_hint", "placeholder")).lower()

        def norm(s: str) -> str:
            return "".join(ch for ch in s.lower() if ch.isalnum())

        def best_match(hint: str) -> str:
            h = norm(hint)
            for f in folders:
                if f and h in norm(f):   # e.g. "placeholder" matches "Place holders"
                    return f
            return ""

        if not self.prepress_folder_var.get():
            self.prepress_folder_var.set(best_match(pre_hint))
        if not self.placeholder_folder_var.get():
            self.placeholder_folder_var.set(best_match(ph_hint))
        if hasattr(self, "dropbox_status") and self.dropbox_status.winfo_exists():
            self.dropbox_status.config(
                text="Folders loaded — high-res and low-res auto-selected. Change them if needed.",
                fg=MUTED)

    def _start_upload(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        selected = [info["result"] for info in self.out_rows.values() if info["upload"].get()]
        if not selected:
            messagebox.showwarning("Nothing selected", "Tick at least one image to upload.")
            return
        prepress_folder = self.prepress_folder_var.get().strip()
        placeholder_folder = self.placeholder_folder_var.get().strip()
        self.upload_btn.config(state="disabled")
        self.upload_progress.pack(fill="x", padx=14, pady=(0, 12))
        self._busy_start(self.upload_progress)
        upload_placeholder = bool(self.pipeline.config.get("dropbox", {}).get("upload_placeholder", True))

        def dest_for(folder: str, name: str) -> str:
            return (folder.rstrip("/") + "/" + name) if folder else ("/" + name)

        def work():
            try:
                client = self._dropbox_client()
                client.check()
                count = 0
                for r in selected:
                    jobs = [(Path(r.output), prepress_folder)]           # Prepress -> high-res folder
                    if upload_placeholder and r.placeholder:
                        jobs.append((Path(r.placeholder), placeholder_folder))  # Placeholder -> low-res folder
                    for f, folder in jobs:
                        self.log_queue.put(f"Uploading {f.name} …")
                        client.upload(f, dest_for(folder, f.name))
                        count += 1
                self.log_queue.put(f"__UPLOAD_DONE__ {count}")
            except Exception as exc:  # noqa: BLE001
                self.log_queue.put(f"__UPLOAD_ERR__ {exc}")

        self.worker = threading.Thread(target=work, daemon=True); self.worker.start()

    # ============================================================ plumbing
    def _drain_log(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg == "__BLOOM_DONE__":
                    self._busy_stop(self.progress); self.progress.grid_remove()
                    self.start_btn.config(state="normal"); self._build_review_screen()
                elif msg.startswith("__RERUN_DONE__"):
                    self._rerun_finished(msg.split(" ", 1)[1], ok=True)
                elif msg.startswith("__RERUN_ERR__"):
                    stem, err = msg[len("__RERUN_ERR__ "):].split(" :: ", 1)
                    self._rerun_finished(stem, ok=False, err=err)
                elif msg.startswith("__FINISH_DONE__"):
                    self._busy_stop(self.review_progress)
                    self._build_output_screen()
                elif msg.startswith("__DBFOLDERS__"):
                    folders = msg[len("__DBFOLDERS__"):].split("\n")
                    self._apply_dropbox_folders(folders)
                elif msg.startswith("__DBERR__"):
                    # Non-fatal: uploading still works, folder LISTING just failed
                    # (usually a missing files.metadata.read scope). Let them type a path.
                    if hasattr(self, "dropbox_status") and self.dropbox_status.winfo_exists():
                        self.dropbox_status.config(
                            text="Couldn't list your folders (folder-listing permission not granted). "
                                 "You can still type a folder path like /Prints and upload.", fg="#b45309")
                elif msg.startswith("__UPLOAD_DONE__"):
                    n = msg.split(" ", 1)[1]
                    self._busy_stop(self.upload_progress); self.upload_progress.pack_forget()
                    self.upload_btn.config(state="normal")
                    messagebox.showinfo("Uploaded", f"Uploaded {n} file(s) to Dropbox.")
                elif msg.startswith("__UPLOAD_ERR__"):
                    self._busy_stop(self.upload_progress); self.upload_progress.pack_forget()
                    self.upload_btn.config(state="normal")
                    messagebox.showerror("Upload failed", f"{msg[len('__UPLOAD_ERR__ '):]}\n\nDetails in {log_file_path()}")
                elif msg.startswith("__ERROR__"):
                    self._reset_bars()
                    messagebox.showerror("Something went wrong",
                                         f"{msg[len('__ERROR__ '):]}\n\nTechnical details in:\n{log_file_path()}")
                elif hasattr(self, "log_box") and self.log_box.winfo_exists():
                    self._append(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_log)

    def _reset_bars(self) -> None:
        for name in ("progress", "review_progress", "upload_progress"):
            bar = getattr(self, name, None)
            if bar is not None and bar.winfo_exists():
                self._busy_stop(bar)
        if hasattr(self, "progress") and self.progress.winfo_exists():
            self.progress.grid_remove()
        for name in ("start_btn", "finish_btn", "upload_btn"):
            b = getattr(self, name, None)
            if b is not None and b.winfo_exists():
                b.config(state="normal")

    def _rerun_finished(self, stem: str, *, ok: bool, err: str = "") -> None:
        info = self.rows.get(stem)
        if not info:
            return
        info["rerun_btn"].config(state="normal")
        if ok:
            info["status"].config(text="Bloom updated — click image to view", fg="#16a34a")
            bloom_path = self.pipeline.review_dir / f"{stem}{BLOOM_SUFFIX}"
            try:
                with Image.open(bloom_path) as im:
                    im = im.convert("RGB"); im.thumbnail(THUMB)
                    photo = ImageTk.PhotoImage(im)
                self._thumbs.append(photo)
                for child in info["row"].winfo_children():
                    if isinstance(child, tk.Label) and child.cget("image"):
                        child.config(image=photo)
                        child.bind("<Button-1>", lambda e, p=bloom_path: ImageViewer(self.root, p))
                        break
            except Exception:  # noqa: BLE001
                pass
        else:
            info["status"].config(text="re-run failed — see log.txt", fg="#dc2626")

    def _clear_container(self) -> None:
        for child in self.container.winfo_children():
            child.destroy()

    def _clear_log(self) -> None:
        self.log_box.config(state="normal"); self.log_box.delete("1.0", "end"); self.log_box.config(state="disabled")

    def _append(self, text: str) -> None:
        self.log_box.config(state="normal"); self.log_box.insert("end", text + "\n")
        self.log_box.see("end"); self.log_box.config(state="disabled")


def _read_source_for_stem(review_dir: Path, stem: str) -> Path:
    import json
    data = json.loads((review_dir / f"{stem}__bloom.json").read_text(encoding="utf-8"))
    return Path(data["source"])


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
