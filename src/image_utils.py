"""Small image helpers built on Pillow (dimensions, print DPI, format, size)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

# Allow very large print files without Pillow's decompression-bomb warning tripping.
Image.MAX_IMAGE_PIXELS = None


def get_size(image_path: str | Path) -> tuple[int, int]:
    """Return (width, height) in pixels."""
    with Image.open(image_path) as img:
        return img.size


def scaled_size(width: int, height: int, scale: float) -> tuple[int, int]:
    return max(1, round(width * scale)), max(1, round(height * scale))


def size_for_long_edge(width: int, height: int, target_long_edge: int) -> tuple[int, int]:
    """Dimensions that make the longest edge == target, preserving aspect ratio."""
    if width >= height:
        return target_long_edge, max(1, round(target_long_edge * height / width))
    return max(1, round(target_long_edge * width / height)), target_long_edge


def finalize_for_print(
    src_path: str | Path,
    dst_path: str | Path,
    *,
    fmt: str = "jpeg",
    dpi: int = 300,
    jpeg_quality: int = 95,
) -> Path:
    """Re-save an image in the print format with embedded DPI metadata.

    Returns the destination path. DPI metadata does not change pixels; it tells
    the printer the intended physical size.
    """
    src_path = Path(src_path)
    dst_path = Path(dst_path)
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = fmt.lower()
    pil_format = "JPEG" if fmt in {"jpg", "jpeg"} else "PNG"

    with Image.open(src_path) as img:
        save_kwargs: dict = {"dpi": (dpi, dpi)}
        if pil_format == "JPEG":
            if img.mode in {"RGBA", "P", "LA"}:
                img = img.convert("RGB")
            save_kwargs.update(quality=jpeg_quality, subsampling=0)
        img.save(dst_path, format=pil_format, **save_kwargs)
    return dst_path


def file_size_mb(path: str | Path) -> float:
    return Path(path).stat().st_size / (1024 * 1024)
