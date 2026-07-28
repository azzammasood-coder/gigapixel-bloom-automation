"""Optional AI vision step: look at an image and pick per-image settings.

Uses any OpenAI-compatible chat/vision endpoint (OpenRouter by default). If no
LLM key is configured, callers should skip this and use config defaults.

The advisor only *adjusts* a handful of safe fields; it can never pick an unknown
model or push Bloom past the guardrails. Its output is validated and clamped.
"""

from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path
from typing import Any

import requests

# Models the AI is allowed to choose from (must exist in the Topaz API).
ALLOWED_GIGAPIXEL_MODELS = {
    "Standard V2",
    "High Fidelity V2",
    "Low Resolution V2",
    "Faces",
    "CGI",
    "Detail",
}
ALLOWED_BLOOM_MODELS = {"Bloom Realism", "Bloom Creative"}


def _encode_image(image_path: Path) -> tuple[str, str]:
    mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return mime, data


SYSTEM_PROMPT = """\
You are an image-processing assistant for a painterly digital-art print shop.
You look at ONE image and choose safe enhancement settings for a
Gigapixel -> Bloom -> Gigapixel pipeline. You must return ONLY a JSON object
(no prose) with these keys:

{
  "image_type": one of ["painterly","illustration"],
  "gigapixel_model": one of ["Standard V2","High Fidelity V2","Low Resolution V2","Faces","CGI","Detail"],
  "bloom_model": one of ["Bloom Realism","Bloom Creative"],
  "bloom_strength": number 0.05-0.6,
  "has_faces": true/false,
  "face_enhancement_strength": number 0.0-0.6,
  "notes": short string explaining your choices
}

Rules:
- Classify image_type: "painterly" if it has visible brush strokes / a hand-painted
  look, "illustration" for flat/graphic/vector-like art. When unsure, use "painterly".
- The art is usually painterly. Preserve brush strokes and detail; avoid smoothing.
- Strongly prefer "Bloom Realism" and a LOW bloom_strength (creative changes minimal).
- Only use "Bloom Creative" if the image is very low quality and clearly needs it.
- If human faces are present, set has_faces=true and keep face settings gentle
  so faces/eyes are not reshaped.
- Use "Low Resolution V2" for small/blurry inputs, "Faces" only when a face is the
  main subject, otherwise "High Fidelity V2".
"""


class LLMAdvisor:
    def __init__(self, api_key: str, base_url: str, model: str, *, timeout: float = 90.0) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def suggest(self, image_path: str | Path, extra_instructions: str = "") -> dict[str, Any]:
        """Return validated settings for one image. Raises on hard failure."""
        image_path = Path(image_path)
        mime, b64 = _encode_image(image_path)
        user_text = "Choose settings for this image."
        if extra_instructions.strip():
            user_text += "\n\nAdditional context from the artist:\n" + extra_instructions.strip()

        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                },
            ],
        }
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=body,
            timeout=self.timeout,
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"LLM request failed: HTTP {resp.status_code} — {resp.text[:300]}")
        content = resp.json()["choices"][0]["message"]["content"]
        return self._validate(_extract_json(content))

    @staticmethod
    def _validate(raw: dict[str, Any]) -> dict[str, Any]:
        def clamp(x, lo, hi, default):
            try:
                return max(lo, min(hi, float(x)))
            except (TypeError, ValueError):
                return default

        gp = raw.get("gigapixel_model")
        if gp not in ALLOWED_GIGAPIXEL_MODELS:
            gp = "High Fidelity V2"
        bloom = raw.get("bloom_model")
        if bloom not in ALLOWED_BLOOM_MODELS:
            bloom = "Bloom Realism"
        image_type = raw.get("image_type")
        if image_type not in {"painterly", "illustration"}:
            image_type = "painterly"
        return {
            "image_type": image_type,
            "gigapixel_model": gp,
            "bloom_model": bloom,
            "bloom_strength": clamp(raw.get("bloom_strength"), 0.05, 0.6, 0.25),
            "has_faces": bool(raw.get("has_faces", False)),
            "face_enhancement_strength": clamp(raw.get("face_enhancement_strength"), 0.0, 0.6, 0.3),
            "notes": str(raw.get("notes", ""))[:400],
        }


def _extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of an LLM response (handles ```json fences)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in LLM response: {text[:200]}")
    return json.loads(text[start : end + 1])
