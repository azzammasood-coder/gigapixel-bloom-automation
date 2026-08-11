"""Two-phase pipeline matching Leslie's real workflow:

    Phase 1 (Bloom):   run Bloom on each image  ->  results land in output/review/
    REVIEW (human):    Leslie inspects each Bloom result, approves the good ones,
                       and re-runs Bloom on any that came out wrong.
    Phase 2 (Finish):  approved images get the final Gigapixel upscale (aspect
                       ratio + print resolution) and are saved print-ready.

Each Bloom result carries a small JSON "sidecar" so Phase 2 knows exactly how to
finish it (source path, image type -> DPI, chosen Gigapixel model).
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import image_utils
from .config import SUPPORTED_INPUT_EXTENSIONS, Config, log_file_path
from .llm_advisor import LLMAdvisor
from .run_logger import RunLogger, ensure_logger
from .topaz_client import TopazClient

Logger = Callable[[str], None]

REVIEW_SUBDIR = "review"
BLOOM_SUFFIX = "__bloom.png"
SIDECAR_SUFFIX = "__bloom.json"


@dataclass
class BloomResult:
    source: Path
    bloom_output: Path | None = None
    sidecar: Path | None = None
    ok: bool = False
    error: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageResult:
    source: Path
    output: Path | None = None            # high-res "Prepress" file (primary)
    placeholder: Path | None = None       # low-res "Placeholder" file
    ok: bool = False
    error: str | None = None
    warnings: list[str] = field(default_factory=list)


def collect_images(input_path: str | Path) -> list[Path]:
    """Return a sorted list of image files from a single file or a folder."""
    p = Path(input_path)
    if p.is_file():
        return [p] if p.suffix.lower() in SUPPORTED_INPUT_EXTENSIONS else []
    if p.is_dir():
        return sorted(
            f for f in p.iterdir()
            if f.is_file() and f.suffix.lower() in SUPPORTED_INPUT_EXTENSIONS
        )
    raise FileNotFoundError(f"Input path does not exist: {input_path}")


class Pipeline:
    def __init__(
        self,
        config: Config,
        *,
        logger=None,
        dry_run: bool = False,
    ) -> None:
        self.config = config
        # A RunLogger gives us both a plain (window/console) and technical (log.txt)
        # stream. Plain callables / None are wrapped for backward compatibility.
        self.log: RunLogger = ensure_logger(logger, log_file_path())
        self.dry_run = dry_run

        secrets = config.secrets
        self.client = None if dry_run else TopazClient(secrets.topaz_api_key)

        self.advisor: LLMAdvisor | None = None
        ai_cfg = config.get("ai", {})
        if ai_cfg.get("enabled") and secrets and secrets.has_llm and not dry_run:
            self.advisor = LLMAdvisor(secrets.llm_api_key, secrets.llm_base_url, secrets.llm_model)

        # Working files (Bloom results + Gigapixel intermediates) live in a temp
        # folder, NOT in the user's output folder — the output folder should only
        # ever contain the final Prepress / Placeholder images.
        self.work_root = Path(tempfile.gettempdir()) / "GigapixelBloom_work"
        self.review_dir = self.work_root / REVIEW_SUBDIR
        self.gigapixel_dir = self.work_root / "gigapixel"

    # ======================================================================
    # Phase 1 — Bloom
    # ======================================================================

    def run_bloom_phase(self, input_path: str | Path, output_dir: str | Path) -> list[BloomResult]:
        images = collect_images(input_path)
        # Fresh review folder each run so old results don't linger (it's in temp).
        if self.review_dir.exists():
            shutil.rmtree(self.review_dir, ignore_errors=True)
        self.review_dir.mkdir(parents=True, exist_ok=True)
        if not images:
            self.log.user("No images found. Please pick an image file or a folder of images.")
            return []

        self.log.banner(f"Step 1 of 2 — Enhancing {len(images)} image(s) with Bloom")
        self.log.detail(f"input={input_path}  review_dir={self.review_dir}")
        results = []
        for i, img in enumerate(images, 1):
            self.log.user(f"[{i} of {len(images)}]  {img.name}")
            results.append(self.bloom_one(img))
        ok = sum(1 for r in results if r.ok)
        self.log.user(f"Bloom finished — {ok} of {len(results)} ready to review.")
        return results

    def bloom_one(
        self,
        image_path: Path,
        *,
        strength_override: float | None = None,
    ) -> BloomResult:
        """Run Bloom on one image and write the result + sidecar into the review dir.

        `strength_override` lets the review UI re-run with a different strength.
        """
        image_path = Path(image_path)
        result = BloomResult(source=image_path)
        self.review_dir.mkdir(parents=True, exist_ok=True)
        stem = image_path.stem
        bloom_out = self.review_dir / f"{stem}{BLOOM_SUFFIX}"
        sidecar = self.review_dir / f"{stem}{SIDECAR_SUFFIX}"
        try:
            settings = self._decide_settings(image_path)
            if strength_override is not None:
                settings["bloom"]["strength"] = float(strength_override)
            result.settings = settings
            self.log.detail(f"settings: {_summarize(settings)}")

            if self.dry_run:
                # No API: copy the original so the review step has something to show.
                shutil.copyfile(image_path, bloom_out)
                self.log.detail("dry-run: copied original as Bloom preview (no API call)")
            else:
                bloom = settings["bloom"]
                self.log.user("   Enhancing with Bloom…")
                self.log.detail(
                    f"Bloom params: model={bloom['model']} strength={bloom['strength']} "
                    f"face={bloom['face_enhancement']}/{bloom['face_enhancement_strength']}")
                self.client.enhance(
                    image_path, bloom_out,
                    model=bloom["model"], output_format="png",
                    params={
                        "strength": bloom["strength"],
                        "face_enhancement": bloom["face_enhancement"],
                        "face_enhancement_strength": bloom["face_enhancement_strength"],
                        "face_enhancement_creativity": bloom["face_enhancement_creativity"],
                    },
                    logger=self.log,
                )

            sidecar.write_text(json.dumps({
                "source": str(image_path),
                "bloom_output": str(bloom_out),
                "image_type": settings["image_type"],
                "gigapixel_model": settings["gigapixel_model"],
                "settings": settings,
            }, indent=2), encoding="utf-8")

            result.bloom_output = bloom_out
            result.sidecar = sidecar
            result.ok = True
            self.log.user("   Done — ready to review.")
        except Exception as exc:  # noqa: BLE001 - per-image, keep batch going
            result.error = str(exc)
            self.log.error(f"couldn't enhance {image_path.name}: {exc}", exc)
        return result

    # ======================================================================
    # Phase 2 — Finish (Gigapixel + print prep)
    # ======================================================================

    def run_finish_phase(
        self,
        output_dir: str | Path,
        *,
        only: list[str] | None = None,
    ) -> list[ImageResult]:
        """Finish approved Bloom results. `only` = list of stems to include
        (default: everything in the review folder)."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        sidecars = sorted(self.review_dir.glob(f"*{SIDECAR_SUFFIX}"))
        if only is not None:
            wanted = {s for s in only}
            sidecars = [s for s in sidecars if s.name[: -len(SIDECAR_SUFFIX)] in wanted]

        if not sidecars:
            self.log.user("Nothing approved to finish.")
            return []

        self.log.banner(f"Step 2 of 2 — Upscaling {len(sidecars)} approved image(s) for print")
        self.log.detail(f"output_dir={output_dir}")
        results = []
        for i, sc in enumerate(sidecars, 1):
            self.log.user(f"[{i} of {len(sidecars)}]  {sc.name[:-len(SIDECAR_SUFFIX)]}")
            results.append(self.finish_one(sc, output_dir))
        ok = sum(1 for r in results if r.ok)
        self.log.user(f"All done — {ok} of {len(results)} print-ready file(s) saved.")
        return results

    def finish_one(self, sidecar_path: Path, output_dir: Path) -> ImageResult:
        sidecar = json.loads(Path(sidecar_path).read_text(encoding="utf-8"))
        source = Path(sidecar["source"])
        bloom_out = Path(sidecar["bloom_output"])
        result = ImageResult(source=source)
        self.gigapixel_dir.mkdir(parents=True, exist_ok=True)
        stem = source.stem
        try:
            final_cfg = self.config["gigapixel_final"]
            out_cfg = self.config["output"]
            ext = _ext(self.config)
            target = int(final_cfg.get("target_long_edge_px", 10800))
            cur_w, cur_h = image_utils.get_size(bloom_out)

            step_final = self.gigapixel_dir / f"{stem}_gigapixel_final.png"
            if self.dry_run:
                self.log.detail("dry-run: skipping Gigapixel, using Bloom image as-is")
                step_final = bloom_out
            elif max(cur_w, cur_h) < target:
                fw, fh = image_utils.size_for_long_edge(cur_w, cur_h, target)
                self.log.user("   Upscaling for print with Gigapixel…")
                self.log.detail(f"Gigapixel {cur_w}x{cur_h} -> {fw}x{fh} "
                                f"(model={sidecar.get('gigapixel_model', final_cfg['model'])})")
                self.client.enhance(
                    bloom_out, step_final,
                    model=sidecar.get("gigapixel_model", final_cfg["model"]),
                    output_format="png",
                    output_width=fw, output_height=fh, logger=self.log,
                )
            else:
                self.log.detail("Gigapixel skipped (already at/above print resolution)")
                step_final = bloom_out

            # Prepress DPI depends on image type: 300 painterly, 200 illustration.
            prepress_dpi = int(
                out_cfg.get("prepress_dpi_illustration", 200)
                if sidecar.get("image_type") == "illustration"
                else out_cfg.get("prepress_dpi_painterly", 300)
            )

            # --- High-res "Prepress" file ---
            prepress_path = output_dir / f"{image_utils.tagged_name(stem, out_cfg.get('prepress_tag', 'Prepress'))}.{ext}"
            image_utils.finalize_for_print(
                step_final, prepress_path,
                fmt=out_cfg.get("format", "jpeg"),
                dpi=prepress_dpi,
                jpeg_quality=int(out_cfg.get("prepress_jpeg_quality", 95)),
            )

            # --- Low-res "Placeholder" file (same pixels, smaller file) ---
            placeholder_path = output_dir / f"{image_utils.tagged_name(stem, out_cfg.get('placeholder_tag', 'Placeholder'))}.{ext}"
            image_utils.finalize_for_print(
                step_final, placeholder_path,
                fmt=out_cfg.get("format", "jpeg"),
                dpi=int(out_cfg.get("placeholder_dpi", 72)),
                jpeg_quality=int(out_cfg.get("placeholder_jpeg_quality", 70)),
            )

            # Tidy up the Gigapixel intermediate (never shown to the user).
            if step_final != bloom_out:
                step_final.unlink(missing_ok=True)

            pre_mb = image_utils.file_size_mb(prepress_path)
            ph_mb = image_utils.file_size_mb(placeholder_path)
            cap = float(out_cfg.get("max_file_size_mb", 100))
            if pre_mb > cap:
                warn = (
                    f"Prepress file is {pre_mb:.0f} MB (> {cap:.0f} MB Lumaprints web cap). "
                    "Upload the order first, then email/WeTransfer/Dropbox the file."
                )
                result.warnings.append(warn)
                self.log.user(f"   Note: {warn}")

            result.output = prepress_path
            result.placeholder = placeholder_path
            result.ok = True
            self.log.user(f"   Saved: {prepress_path.name}  ({pre_mb:.1f} MB, {prepress_dpi} DPI)")
            self.log.user(f"          {placeholder_path.name}  ({ph_mb:.1f} MB, web copy)")
            self.log.detail(f"prepress -> {prepress_path}\nplaceholder -> {placeholder_path}")
        except Exception as exc:  # noqa: BLE001
            result.error = str(exc)
            self.log.error(f"couldn't finish {source.name}: {exc}", exc)
        return result

    # ======================================================================
    # Convenience — run both phases, auto-approving everything (testing / trust)
    # ======================================================================

    def run_auto(self, input_path: str | Path, output_dir: str | Path) -> list[ImageResult]:
        self.run_bloom_phase(input_path, output_dir)
        return self.run_finish_phase(output_dir)

    # -- settings -----------------------------------------------------------

    def _decide_settings(self, image_path: Path) -> dict[str, Any]:
        """Merge config defaults with (optional) AI suggestions for this image."""
        bloom_cfg = dict(self.config["bloom"])
        final_cfg = dict(self.config["gigapixel_final"])
        settings = {
            "image_type": "painterly",             # painterly -> 300 DPI, illustration -> 200
            "gigapixel_model": final_cfg["model"],  # model for the final upscale
            "bloom": {
                "model": bloom_cfg["model"],
                "strength": float(bloom_cfg["strength"]),
                "face_enhancement": bool(bloom_cfg.get("face_enhancement", True)),
                "face_enhancement_strength": float(bloom_cfg.get("face_enhancement_strength", 0.3)),
                "face_enhancement_creativity": float(bloom_cfg.get("face_enhancement_creativity", 0.0)),
            },
            "source": "defaults",
        }

        if self.advisor is not None:
            try:
                instructions = self.config.get("ai", {}).get("instructions", "")
                s = self.advisor.suggest(image_path, instructions)
                settings["image_type"] = s["image_type"]
                settings["gigapixel_model"] = s["gigapixel_model"]
                settings["bloom"]["model"] = s["bloom_model"]
                settings["bloom"]["strength"] = s["bloom_strength"]
                # Note whether faces are present, but do NOT auto-enable face
                # enhancement — it can reshape eyes/gaze (Leslie's rule). The config
                # default (off) wins unless a human turns it on.
                settings["bloom"]["face_enhancement_strength"] = s["face_enhancement_strength"]
                settings["source"] = "ai"
                settings["ai_notes"] = s.get("notes", "")
            except Exception as exc:  # noqa: BLE001 - AI is best-effort; fall back to defaults
                self.log.detail(f"AI step failed, using defaults: {exc}")

        return settings


def _ext(config: Config) -> str:
    fmt = str(config["output"].get("format", "jpeg")).lower()
    return "jpg" if fmt in {"jpg", "jpeg"} else "png"


def _summarize(settings: dict[str, Any]) -> str:
    b = settings["bloom"]
    src = settings.get("source", "defaults")
    return (
        f"[{src}] type={settings['image_type']} "
        f"bloom='{b['model']}' strength={b['strength']:.2f} "
        f"faces={b['face_enhancement']} final_gigapixel='{settings['gigapixel_model']}'"
    )
