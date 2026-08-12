"""Thin client for the Topaz Labs Image API (async enhance -> status -> download).

Docs: https://developer.topazlabs.com/api-reference/image-api/enhance

The same /enhance endpoint powers both Gigapixel (upscaling) models and Bloom
(creative enhancement) models — you just pass a different `model` name.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://api.topazlabs.com/image/v1"
ENHANCE_ASYNC_URL = f"{BASE_URL}/enhance/async"
STATUS_URL = f"{BASE_URL}/status/{{process_id}}"
DOWNLOAD_URL = f"{BASE_URL}/download/{{process_id}}"

# MIME types for the multipart upload.
_MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}


class TopazError(RuntimeError):
    """Raised when the Topaz API returns an error or a job fails."""


class TopazClient:
    def __init__(
        self,
        api_key: str,
        *,
        poll_interval: float = 2.0,
        timeout: float = 600.0,
        request_timeout: float = 120.0,
    ) -> None:
        if not api_key:
            raise ValueError("A Topaz API key is required.")
        self.api_key = api_key
        self.poll_interval = poll_interval
        self.timeout = timeout  # max seconds to wait for a single job
        self.request_timeout = request_timeout
        self._session = requests.Session()
        self._session.headers.update({"X-API-KEY": api_key})

    # -- public API ---------------------------------------------------------

    def enhance(
        self,
        image_path: str | Path,
        output_path: str | Path,
        *,
        model: str,
        output_format: str = "jpeg",
        output_width: int | None = None,
        output_height: int | None = None,
        params: dict[str, Any] | None = None,
        logger=None,
    ) -> Path:
        """Run one enhance job end-to-end and save the result to output_path.

        `params` may contain any extra enhance fields (strength, face_enhancement,
        face_enhancement_strength, denoise, sharpen, subject_detection, ...).
        """
        image_path = Path(image_path)
        output_path = Path(output_path)
        # Two streams if a RunLogger was passed; else accept a plain callable/None.
        detail = getattr(logger, "detail", None) or logger or (lambda *_: None)
        user = getattr(logger, "user", None) or (lambda *_: None)

        t0 = time.monotonic()
        process_id = self._submit(
            image_path,
            model=model,
            output_format=output_format,
            output_width=output_width,
            output_height=output_height,
            params=params or {},
        )
        detail(f"submitted job {process_id} (model='{model}', out={output_width}x{output_height})")
        user("   Working on it… this can take a little while for large images.")
        self._wait_until_complete(process_id, detail, user, t0)
        detail(f"processing finished in {time.monotonic() - t0:.0f}s; downloading result")
        url = self._download_url(process_id)
        self._save(url, output_path)
        detail(f"saved -> {output_path}")
        return output_path

    # -- steps --------------------------------------------------------------

    def _submit(
        self,
        image_path: Path,
        *,
        model: str,
        output_format: str,
        output_width: int | None,
        output_height: int | None,
        params: dict[str, Any],
    ) -> str:
        data: dict[str, str] = {"model": model, "output_format": output_format}
        if output_width:
            data["output_width"] = str(int(output_width))
        if output_height:
            data["output_height"] = str(int(output_height))
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, bool):
                data[key] = "true" if value else "false"
            else:
                data[key] = str(value)

        mime = _MIME_BY_EXT.get(image_path.suffix.lower(), "application/octet-stream")
        with image_path.open("rb") as fh:
            files = {"image": (image_path.name, fh, mime)}
            resp = self._session.post(
                ENHANCE_ASYNC_URL,
                data=data,
                files=files,
                timeout=self.request_timeout,
            )
        payload = self._json_or_raise(resp, "submit enhance job")
        process_id = payload.get("process_id") or payload.get("processId")
        if not process_id:
            raise TopazError(f"No process_id in response: {payload}")
        return str(process_id)

    def _wait_until_complete(self, process_id: str, detail, user, t0: float,
                             heartbeat: float = 8.0) -> None:
        deadline = time.monotonic() + self.timeout
        last_beat = 0.0
        while True:
            resp = self._session.get(
                STATUS_URL.format(process_id=process_id),
                timeout=self.request_timeout,
            )
            payload = self._json_or_raise(resp, "check status")
            status = str(payload.get("status", "")).lower()
            elapsed = time.monotonic() - t0
            detail(f"status='{status}' ({elapsed:.0f}s)")
            if status in {"completed", "complete", "success", "succeeded"}:
                return
            if status in {"failed", "error", "cancelled", "canceled"}:
                raise TopazError(f"Job {process_id} ended with status '{status}': {payload}")
            if time.monotonic() > deadline:
                raise TopazError(f"Timed out waiting for job {process_id} after {self.timeout}s")
            # Keep the user informed during the long processing wait.
            if elapsed - last_beat >= heartbeat:
                last_beat = elapsed
                user(f"   still working… ({elapsed:.0f}s)")
            time.sleep(self.poll_interval)

    def _download_url(self, process_id: str) -> str:
        resp = self._session.get(
            DOWNLOAD_URL.format(process_id=process_id),
            timeout=self.request_timeout,
        )
        payload = self._json_or_raise(resp, "get download url")
        url = payload.get("url") or payload.get("download_url")
        if not url:
            raise TopazError(f"No download url in response: {payload}")
        return str(url)

    def _save(self, url: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with self._session.get(url, stream=True, timeout=self.request_timeout) as resp:
            if resp.status_code != 200:
                raise TopazError(f"Download failed ({resp.status_code}) from {url}")
            with output_path.open("wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        fh.write(chunk)

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _json_or_raise(resp: requests.Response, action: str) -> dict[str, Any]:
        if resp.status_code >= 400:
            body = resp.text[:500]
            raise TopazError(f"Failed to {action}: HTTP {resp.status_code} — {body}")
        try:
            return resp.json()
        except ValueError as exc:  # not JSON
            raise TopazError(f"Non-JSON response while trying to {action}: {resp.text[:300]}") from exc
