#!/usr/bin/env python3
"""Point-and-click app for the Gigapixel + Bloom automation (Leslie's workflow).

Screens (they swap in the top content area; the Activity log at the bottom is
always visible so you can follow progress on every screen):
  1. Setup   — pick input + output, Run Bloom.
  2. Review  — see each Bloom result (click to zoom); approve / re-run; Finish.
  3. Output  — see the finished files (click to zoom); optionally upload to Dropbox.

Plain progress shows in the window; full technical detail goes to log.txt.
"""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from PIL import Image, ImageTk

from src.config import app_dir, load_config, log_file_path
from src.pipeline import BLOOM_SUFFIX, Pipeline
from src.run_logger import RunLogger

THUMB = (300, 300)

# --- palette -------------------------------------------------------------
BG = "#f4f5f7"
CARD = "#ffffff"
TEXT = "#1f2430"
MUTED = "#6b7280"
ACCENT = "#4f46e5"
ACCENT_HOVER = "#4338ca"
BORDER = "#e5e7eb"
GREEN_BG = "#dcfce7"
GREEN_FG = "#166534"
GREEN_HOVER = "#bbf7d0"
IDLE_BG = "#eef0f3"
IDLE_HOVER = "#e2e6eb"
LOG_BG = "#0f172a"
LOG_FG = "#e2e8f0"


# =====================================================================
# Main app
# =====================================================================

class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("Gigapixel + Bloom Automation")
        root.geometry("920x760")
        root.minsize(820, 660)
        root.configure(bg=BG)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(app_dir() / "output"))
        self.prepress_folder_var = tk.StringVar(value="")
        self.placeholder_folder_var = tk.StringVar(value="")
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.worker: threading.Thread | None = None

        self.pipeline: Pipeline | None = None
        try:
            self._test_mode = bool(load_config(load_env=False).get("test_mode", False))
        except Exception:  # noqa: BLE001
            self._test_mode = False
        self._thumbs: list[ImageTk.PhotoImage] = []
        self.rows: dict[str, dict] = {}
        self._finish_results: list = []
        self.out_rows: dict[str, dict] = {}

        self._init_fonts()
        self._init_style()

        # --- persistent layout: swappable content on top, Activity log always at bottom ---
        self.content = tk.Frame(root, bg=BG)
        self.content.pack(side="top", fill="both", expand=True)
        self._build_statusbar(root)

        self._build_setup_screen()
        self.root.after(100, self._drain_log)

    # ------------------------------------------------------------------ theme
    def _init_fonts(self) -> None:
        self.f_body = tkfont.Font(family="Segoe UI", size=10)
        self.f_section = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        self.f_title = tkfont.Font(family="Segoe UI Semibold", size=17)
        self.f_subtitle = tkfont.Font(family="Segoe UI", size=10)
        self.f_btn = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self.f_mono = tkfont.Font(family="Consolas", size=9)

    def _init_style(self) -> None:
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TFrame", background=BG)
        s.configure("TLabel", background=BG, foreground=TEXT, font=self.f_body)
        s.configure("TEntry", fieldbackground="#ffffff", bordercolor=BORDER,
                    lightcolor=BORDER, darkcolor=BORDER, foreground=TEXT, padding=6)
        s.configure("TButton", background=IDLE_BG, foreground=TEXT, font=self.f_body,
                    borderwidth=0, focusthickness=0, padding=(12, 7))
        s.map("TButton", background=[("active", IDLE_HOVER)])
        s.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", font=self.f_btn,
                    borderwidth=0, focusthickness=0, padding=(14, 11))
        s.map("Accent.TButton", background=[("active", ACCENT_HOVER), ("disabled", "#c7cbd1")],
              foreground=[("disabled", "#eef0f3")])
        s.configure("Accent.Horizontal.TProgressbar", troughcolor="#e9eaee", background=ACCENT,
                    bordercolor="#e9eaee", lightcolor=ACCENT, darkcolor=ACCENT, thickness=8)
        s.configure("TCombobox", padding=5)

    def _card(self, parent):
        outer = tk.Frame(parent, bg=BORDER)
        inner = tk.Frame(outer, bg=CARD)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        return outer, inner

    def _toggle_button(self, parent, var: tk.BooleanVar, on_text: str, off_text: str) -> tk.Button:
        """A clear pill toggle (green when on) instead of a tiny checkbox."""
        btn = tk.Button(parent, bd=0, relief="flat", cursor="hand2", font=self.f_btn, padx=16, pady=8)

        def refresh():
            if var.get():
                btn.config(text=on_text, bg=GREEN_BG, fg=GREEN_FG,
                           activebackground=GREEN_HOVER, activeforeground=GREEN_FG)
            else:
                btn.config(text=off_text, bg=IDLE_BG, fg=TEXT,
                           activebackground=IDLE_HOVER, activeforeground=TEXT)

        def toggle():
            var.set(not var.get()); refresh()

        btn.config(command=toggle); refresh()
        return btn

    # --------------------------------------------------- persistent status bar
    def _build_statusbar(self, root) -> None:
        bar = tk.Frame(root, bg=BG)
        bar.pack(side="bottom", fill="x")
        self.progress = ttk.Progressbar(bar, style="Accent.Horizontal.TProgressbar",
                                        mode="determinate", value=0)
        # (packed only while busy)
        head = tk.Frame(bar, bg=BG)
        self._status_head = head
        head.pack(fill="x", padx=22)
        tk.Label(head, text="Activity", bg=BG, fg=MUTED, font=self.f_section).pack(side="left", pady=(4, 2))
        self.hint_label = tk.Label(head, text="", bg=BG, fg=MUTED, font=self.f_body)
        self.hint_label.pack(side="right")
        _, logcard = self._card(bar)
        logcard.master.pack(fill="x", padx=22, pady=(0, 14))
        self.log_box = tk.Text(logcard, height=8, state="disabled", wrap="word", bg=LOG_BG, fg=LOG_FG,
                               insertbackground=LOG_FG, relief="flat", font=self.f_mono, padx=14, pady=10,
                               highlightthickness=0, borderwidth=0)
        sb = ttk.Scrollbar(logcard, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log_box.pack(side="left", fill="both", expand=True)

    def _busy(self, on: bool) -> None:
        if on:
            self.progress.pack(fill="x", padx=22, pady=(8, 2), before=self._status_head)
            self.progress.configure(mode="indeterminate"); self.progress.start(14)
        else:
            self.progress.stop(); self.progress.configure(mode="determinate", value=0)
            self.progress.pack_forget()

    # ================================================================ setup
    def _build_setup_screen(self) -> None:
        self._clear_content()
        wrap = tk.Frame(self.content, bg=BG)
        wrap.pack(fill="both", expand=True, padx=22, pady=18)
        tk.Label(wrap, text="Gigapixel + Bloom Automation", bg=BG, fg=TEXT, font=self.f_title).pack(anchor="w")
        tk.Label(wrap, text="Enhance and upscale your art into print-ready files.",
                 bg=BG, fg=MUTED, font=self.f_subtitle).pack(anchor="w", pady=(2, 6))
        if self._test_mode:
            tk.Label(wrap, text="  ●  TEST MODE — practice run, no APIs called, no credits used  ",
                     bg="#fef3c7", fg="#92400e", font=self.f_btn).pack(anchor="w", pady=(0, 10))
        else:
            tk.Frame(wrap, bg=BG, height=6).pack()

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
        self.start_btn.grid(row=4, column=0, columnspan=3, sticky="ew", padx=16, pady=(12, 16))
        card.columnconfigure(0, weight=1)
        self._set_hint("")

    def _pick_file(self) -> None:
        p = filedialog.askopenfilename(title="Choose an image",
            filetypes=[("Images", "*.jpg *.jpeg *.png *.tif *.tiff *.webp *.bmp"), ("All files", "*.*")])
        if p:
            self.input_var.set(p)

    def _pick_folder(self) -> None:
        p = filedialog.askdirectory(title="Choose a folder of images")
        if p:
            self.input_var.set(p)

    def _pick_output(self) -> None:
        p = filedialog.askdirectory(title="Choose an output folder")
        if p:
            self.output_var.set(p)

    def _make_logger(self) -> RunLogger:
        return RunLogger(log_file_path(), ui_callback=lambda m: self.log_queue.put(m))

    # ================================================================ phase 1
    def _start_bloom(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        input_path, output_path = self.input_var.get().strip(), self.output_var.get().strip()
        if not input_path:
            messagebox.showwarning("Missing input", "Please choose an image or a folder first.")
            return
        if not output_path:
            messagebox.showwarning("Missing output", "Please choose where to save the results.")
            return
        self.start_btn.config(state="disabled")
        self._busy(True); self._set_hint("Enhancing with Bloom…"); self._clear_log()
        self.worker = threading.Thread(target=self._run_bloom, args=(input_path, output_path), daemon=True)
        self.worker.start()

    def _run_bloom(self, input_path: str, output_path: str) -> None:
        try:
            # Peek test_mode from config first; in test mode we don't need API keys.
            settings_only = load_config(load_env=False)
            self._test_mode = bool(settings_only.get("test_mode", False))
            config = settings_only if self._test_mode else load_config(load_env=True)
            logger = self._make_logger()
            if self._test_mode:
                logger.user("TEST MODE — no Topaz or Dropbox calls will be made (no credits used).")
            self.pipeline = Pipeline(config, logger=logger, dry_run=self._test_mode)
            self.pipeline.run_bloom_phase(input_path, output_path)
            self.log_queue.put("__BLOOM_DONE__")
        except Exception as exc:  # noqa: BLE001
            self.log_queue.put(f"__ERROR__ {exc}")

    # ================================================================ review
    def _build_review_screen(self) -> None:
        self._clear_content(); self._thumbs.clear(); self.rows.clear()
        wrap = tk.Frame(self.content, bg=BG)
        wrap.pack(fill="both", expand=True, padx=22, pady=18)
        tk.Label(wrap, text="Review the Bloom results", bg=BG, fg=TEXT, font=self.f_title).pack(anchor="w")
        tk.Label(wrap, text="Click any image to open it in your photo viewer (zoom in there). Keep the "
                            "good ones approved; re-run Bloom on any that look wrong, then finish.",
                 bg=BG, fg=MUTED, font=self.f_subtitle, justify="left", wraplength=850).pack(anchor="w", pady=(2, 12))
        self._scroll_list(wrap)
        blooms = sorted(self.pipeline.review_dir.glob(f"*{BLOOM_SUFFIX}"))
        if not blooms:
            tk.Label(self.list_frame, text="No Bloom results found.", bg=CARD, fg=MUTED).pack(pady=20)
        for b in blooms:
            self._add_review_row(b)
        bottom = tk.Frame(wrap, bg=BG); bottom.pack(fill="x", pady=(12, 0))
        ttk.Button(bottom, text="←  Back", command=self._build_setup_screen).pack(side="left")
        self.finish_btn = ttk.Button(bottom, text="Finish approved  →", style="Accent.TButton", command=self._start_finish)
        self.finish_btn.pack(side="right")
        self._set_hint("")

    def _scroll_list(self, parent):
        wrapper, card = self._card(parent)
        wrapper.pack(fill="both", expand=True)
        canvas = tk.Canvas(card, highlightthickness=0, bg=CARD)
        scroll = ttk.Scrollbar(card, orient="vertical", command=canvas.yview)
        self.list_frame = tk.Frame(canvas, bg=CARD)
        self.list_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        win = canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=scroll.set)
        # let the mouse wheel scroll the list
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 120), "units")
                        if canvas.winfo_exists() else None)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        return card

    def _open_external(self, path: Path) -> None:
        """Open the image in the operating system's default photo viewer."""
        import os
        import subprocess
        import sys
        p = str(path)
        try:
            if sys.platform.startswith("win"):
                os.startfile(p)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", p])
            else:
                subprocess.Popen(["xdg-open", p])
        except Exception:  # noqa: BLE001
            messagebox.showinfo("Open image", p)

    def _thumb_label(self, parent, image_path: Path):
        try:
            with Image.open(image_path) as im:
                im = im.convert("RGB"); im.thumbnail(THUMB)
                photo = ImageTk.PhotoImage(im)
            self._thumbs.append(photo)
            lbl = tk.Label(parent, image=photo, bg=CARD, cursor="hand2")
            lbl.bind("<Button-1>", lambda e, p=image_path: self._open_external(p))
            return lbl
        except Exception:  # noqa: BLE001
            return tk.Label(parent, text="[preview unavailable]", bg=CARD, fg=MUTED)

    def _add_review_row(self, bloom_path: Path) -> None:
        stem = bloom_path.name[: -len(BLOOM_SUFFIX)]
        row = tk.Frame(self.list_frame, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        row.pack(fill="x", padx=10, pady=6)
        self._thumb_label(row, bloom_path).pack(side="left", padx=10, pady=10)
        right = tk.Frame(row, bg=CARD); right.pack(side="left", fill="x", expand=True, pady=10)
        tk.Label(right, text=stem, bg=CARD, fg=TEXT, font=self.f_section, wraplength=420, justify="left").pack(anchor="w")

        approve_var = tk.BooleanVar(value=True)
        self._toggle_button(right, approve_var, "✓  Approved for print", "Approve for print").pack(anchor="w", pady=(8, 6))

        rerun = tk.Frame(right, bg=CARD); rerun.pack(anchor="w")
        tk.Label(rerun, text="Bloom strength:", bg=CARD, fg=MUTED, font=self.f_body).pack(side="left")
        strength_var = tk.StringVar(value="0.25")
        ttk.Entry(rerun, textvariable=strength_var, width=6).pack(side="left", padx=6)
        btn = ttk.Button(rerun, text="Re-run Bloom", command=lambda s=stem: self._rerun_bloom(s))
        btn.pack(side="left", padx=4)
        status = tk.Label(right, text="", bg=CARD, fg=MUTED, font=self.f_body); status.pack(anchor="w", pady=(6, 0))
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
        self._busy(True); self._set_hint(f"Re-running Bloom on {stem}…")

        def work():
            try:
                src = _read_source_for_stem(self.pipeline.review_dir, stem)
                self.pipeline.bloom_one(src, strength_override=strength)
                self.log_queue.put(f"__RERUN_DONE__ {stem}")
            except Exception as exc:  # noqa: BLE001
                self.log_queue.put(f"__RERUN_ERR__ {stem} :: {exc}")

        self.worker = threading.Thread(target=work, daemon=True); self.worker.start()

    # ================================================================ phase 2
    def _start_finish(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        approved = [stem for stem, info in self.rows.items() if info["approve"].get()]
        if not approved:
            messagebox.showwarning("Nothing approved", "Approve at least one image to finish.")
            return
        self.finish_btn.config(state="disabled")
        self._busy(True); self._set_hint("Upscaling for print…")

        def work():
            try:
                results = self.pipeline.run_finish_phase(self.output_var.get(), only=approved)
                self._finish_results = [r for r in results if r.ok]
                self.log_queue.put(f"__FINISH_DONE__ {len(self._finish_results)}")
            except Exception as exc:  # noqa: BLE001
                self.log_queue.put(f"__ERROR__ {exc}")

        self.worker = threading.Thread(target=work, daemon=True); self.worker.start()

    # ================================================================ output
    def _build_output_screen(self) -> None:
        self._clear_content(); self._thumbs.clear(); self.out_rows.clear()
        wrap = tk.Frame(self.content, bg=BG)
        wrap.pack(fill="both", expand=True, padx=22, pady=18)
        tk.Label(wrap, text="Finished — print-ready files", bg=BG, fg=TEXT, font=self.f_title).pack(anchor="w")
        tk.Label(wrap, text=f"Saved to:  {self.output_var.get()}    ·    click any image to open it",
                 bg=BG, fg=MUTED, font=self.f_subtitle, wraplength=850, justify="left").pack(anchor="w", pady=(2, 12))
        self._scroll_list(wrap)
        for r in self._finish_results:
            self._add_output_row(r)

        dbcard_outer, dbcard = self._card(wrap)
        dbcard_outer.pack(fill="x", pady=(12, 0))
        has_db = self._test_mode or bool(
            self.pipeline and self.pipeline.config.secrets
            and self.pipeline.config.secrets.has_dropbox
            and self.pipeline.config.get("dropbox", {}).get("enabled"))
        db_title = "Upload to Dropbox (optional)"
        if self._test_mode:
            db_title += "   —   TEST MODE: uploads are simulated"
        tk.Label(dbcard, text=db_title, bg=CARD, fg=TEXT,
                 font=self.f_section).pack(anchor="w", padx=14, pady=(12, 6))
        if has_db:
            grid = tk.Frame(dbcard, bg=CARD); grid.pack(fill="x", padx=14, pady=(0, 6))
            tk.Label(grid, text="High-res (Prepress) folder:", bg=CARD, fg=MUTED,
                     font=self.f_body).grid(row=0, column=0, sticky="w", pady=3)
            self.prepress_combo = ttk.Combobox(grid, textvariable=self.prepress_folder_var, width=48, values=[""])
            self.prepress_combo.grid(row=0, column=1, sticky="w", padx=8, pady=3)
            tk.Label(grid, text="Low-res (Placeholder) folder:", bg=CARD, fg=MUTED,
                     font=self.f_body).grid(row=1, column=0, sticky="w", pady=3)
            self.placeholder_combo = ttk.Combobox(grid, textvariable=self.placeholder_folder_var, width=48, values=[""])
            self.placeholder_combo.grid(row=1, column=1, sticky="w", padx=8, pady=3)
            ttk.Button(grid, text="Refresh folders", command=self._load_dropbox_folders).grid(
                row=0, column=2, rowspan=2, padx=8)
            self.dropbox_status = tk.Label(dbcard, text="Choose a folder for each (or type a path). "
                                                        "Blank = your Dropbox root.",
                                           bg=CARD, fg=MUTED, font=self.f_body, wraplength=800, justify="left")
            self.dropbox_status.pack(anchor="w", padx=14, pady=(2, 6))
            rowf = tk.Frame(dbcard, bg=CARD); rowf.pack(fill="x", padx=14, pady=(0, 12))
            self.upload_btn = ttk.Button(rowf, text="Upload selected  →", style="Accent.TButton",
                                         command=self._start_upload)
            self.upload_btn.pack(side="right")
            self._load_dropbox_folders()
        else:
            tk.Label(dbcard, text="Dropbox isn't set up. Add DROPBOX_APP_KEY, DROPBOX_APP_SECRET and "
                                  "DROPBOX_REFRESH_TOKEN to the .env file to enable one-click upload.",
                     bg=CARD, fg=MUTED, font=self.f_body, wraplength=800, justify="left").pack(
                         anchor="w", padx=14, pady=(0, 12))

        bottom = tk.Frame(wrap, bg=BG); bottom.pack(fill="x", pady=(12, 0))
        ttk.Button(bottom, text="←  Start over", command=self._build_setup_screen).pack(side="left")
        ttk.Button(bottom, text="Open output folder", command=self._open_output).pack(side="left", padx=8)
        self._set_hint("")

    def _add_output_row(self, result) -> None:
        prepress = Path(result.output)
        stem = prepress.stem
        row = tk.Frame(self.list_frame, bg=CARD, highlightbackground=BORDER, highlightthickness=1)
        row.pack(fill="x", padx=10, pady=6)
        self._thumb_label(row, prepress).pack(side="left", padx=10, pady=10)
        right = tk.Frame(row, bg=CARD); right.pack(side="left", fill="x", expand=True, pady=10)
        tk.Label(right, text=stem, bg=CARD, fg=TEXT, font=self.f_section, wraplength=440, justify="left").pack(anchor="w")
        try:
            with Image.open(prepress) as im:
                dims = f"{im.size[0]} × {im.size[1]}"
        except Exception:  # noqa: BLE001
            dims = ""
        ph = f"   +   {Path(result.placeholder).name}" if result.placeholder else ""
        tk.Label(right, text=f"{dims}{ph}", bg=CARD, fg=MUTED, font=self.f_body,
                 wraplength=440, justify="left").pack(anchor="w", pady=(2, 4))
        upload_var = tk.BooleanVar(value=True)
        self._toggle_button(right, upload_var, "✓  Will upload", "Skip upload").pack(anchor="w", pady=(2, 0))
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
        if self._test_mode:
            mock = ["", "/LumaPrints High Res (test)", "/Lumaprints Low Res Place holders (test)",
                    "/Golf Art Studios (test)"]
            self.log_queue.put("__DBFOLDERS__ " + "\n".join(mock))
            return

        log = self.pipeline.log if self.pipeline else None

        def work():
            try:
                if log:
                    log.detail("Dropbox: listing folders")
                folders = self._dropbox_client().list_folders("")
                if log:
                    log.detail(f"Dropbox: found {len(folders)} folder(s)")
                self.log_queue.put("__DBFOLDERS__ " + "\n".join([""] + folders))
            except Exception as exc:  # noqa: BLE001
                if log:
                    log.error(f"Dropbox folder listing failed: {exc}", exc)
                self.log_queue.put(f"__DBERR__ {exc}")
        threading.Thread(target=work, daemon=True).start()

    def _apply_dropbox_folders(self, folders: list[str]) -> None:
        # Populate both dropdowns. No auto-selection — the user picks.
        if hasattr(self, "prepress_combo") and self.prepress_combo.winfo_exists():
            self.prepress_combo.configure(values=folders)
            self.placeholder_combo.configure(values=folders)

    def _start_upload(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        selected = [info["result"] for info in self.out_rows.values() if info["upload"].get()]
        if not selected:
            messagebox.showwarning("Nothing selected", "Choose at least one image to upload.")
            return
        prepress_folder = self.prepress_folder_var.get().strip()
        placeholder_folder = self.placeholder_folder_var.get().strip()
        upload_placeholder = bool(self.pipeline.config.get("dropbox", {}).get("upload_placeholder", True))
        self.upload_btn.config(state="disabled")
        self._busy(True); self._set_hint("Uploading to Dropbox…")
        log = self.pipeline.log

        def dest_for(folder: str, name: str) -> str:
            return (folder.rstrip("/") + "/" + name) if folder else ("/" + name)

        test_mode = self._test_mode

        def work():
            try:
                if test_mode:
                    log.banner("Uploading to Dropbox (TEST MODE — simulated)")
                else:
                    log.banner("Uploading to Dropbox")
                client = None if test_mode else self._dropbox_client()
                if client is not None:
                    client.check()
                t0 = time.monotonic(); count = 0
                for r in selected:
                    jobs = [(Path(r.output), prepress_folder)]
                    if upload_placeholder and r.placeholder:
                        jobs.append((Path(r.placeholder), placeholder_folder))
                    for f, folder in jobs:
                        dest = dest_for(folder, f.name)
                        if test_mode:
                            log.user(f"   [simulated] would upload {f.name} → {folder or '/'}")
                            log.detail(f"TEST MODE upload skipped: {f} -> {dest}")
                            time.sleep(0.3)
                        else:
                            log.user(f"   Uploading {f.name} → {folder or '/'}")
                            log.detail(f"upload {f} -> {dest}")
                            client.upload(f, dest)
                        count += 1
                verb = "Simulated upload of" if test_mode else "Uploaded"
                log.user(f"{verb} {count} file(s) in {time.monotonic() - t0:.0f}s.")
                self.log_queue.put(f"__UPLOAD_DONE__ {count}")
            except Exception as exc:  # noqa: BLE001
                log.error(f"Dropbox upload failed: {exc}", exc)
                self.log_queue.put(f"__UPLOAD_ERR__ {exc}")

        self.worker = threading.Thread(target=work, daemon=True); self.worker.start()

    # ================================================================ plumbing
    def _drain_log(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                if msg == "__BLOOM_DONE__":
                    self._busy(False); self.start_btn.config(state="normal"); self._build_review_screen()
                elif msg.startswith("__RERUN_DONE__"):
                    self._busy(False); self._set_hint(""); self._rerun_finished(msg.split(" ", 1)[1], ok=True)
                elif msg.startswith("__RERUN_ERR__"):
                    self._busy(False); self._set_hint("")
                    stem, err = msg[len("__RERUN_ERR__ "):].split(" :: ", 1)
                    self._rerun_finished(stem, ok=False, err=err)
                elif msg.startswith("__FINISH_DONE__"):
                    self._busy(False); self._build_output_screen()
                elif msg.startswith("__DBFOLDERS__"):
                    self._apply_dropbox_folders(msg[len("__DBFOLDERS__"):].split("\n"))
                elif msg.startswith("__DBERR__"):
                    if hasattr(self, "dropbox_status") and self.dropbox_status.winfo_exists():
                        self.dropbox_status.config(
                            text="Couldn't list your folders. You can still type a folder path and upload.",
                            fg="#b45309")
                elif msg.startswith("__UPLOAD_DONE__"):
                    n = msg.split(" ", 1)[1]
                    self._busy(False); self._set_hint(""); self.upload_btn.config(state="normal")
                    if self._test_mode:
                        messagebox.showinfo("Test mode", f"Simulated uploading {n} file(s) — nothing was "
                                                         f"actually sent to Dropbox (test mode).")
                    else:
                        messagebox.showinfo("Uploaded", f"Uploaded {n} file(s) to Dropbox.")
                elif msg.startswith("__UPLOAD_ERR__"):
                    self._busy(False); self._set_hint(""); self.upload_btn.config(state="normal")
                    messagebox.showerror("Upload failed",
                                         f"{msg[len('__UPLOAD_ERR__ '):]}\n\nDetails in {log_file_path()}")
                elif msg.startswith("__ERROR__"):
                    self._busy(False); self._set_hint("")
                    for name in ("start_btn", "finish_btn", "upload_btn"):
                        b = getattr(self, name, None)
                        if b is not None and b.winfo_exists():
                            b.config(state="normal")
                    messagebox.showerror("Something went wrong",
                                         f"{msg[len('__ERROR__ '):]}\n\nTechnical details in:\n{log_file_path()}")
                else:
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
            info["status"].config(text="Bloom updated — click image to view", fg=GREEN_FG)
            bloom_path = self.pipeline.review_dir / f"{stem}{BLOOM_SUFFIX}"
            try:
                with Image.open(bloom_path) as im:
                    im = im.convert("RGB"); im.thumbnail(THUMB)
                    photo = ImageTk.PhotoImage(im)
                self._thumbs.append(photo)
                for child in info["row"].winfo_children():
                    if isinstance(child, tk.Label) and child.cget("image"):
                        child.config(image=photo)
                        child.bind("<Button-1>", lambda e, p=bloom_path: self._open_external(p))
                        break
            except Exception:  # noqa: BLE001
                pass
        else:
            info["status"].config(text="re-run failed — see log.txt", fg="#dc2626")

    # ------------------------------------------------------------- helpers
    def _clear_content(self) -> None:
        for child in self.content.winfo_children():
            child.destroy()

    def _set_hint(self, text: str) -> None:
        if hasattr(self, "hint_label"):
            self.hint_label.config(text=text)

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
