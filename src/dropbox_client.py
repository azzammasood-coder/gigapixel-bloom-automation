"""Minimal Dropbox client (OAuth2 refresh-token flow) using the HTTP API.

We avoid the heavy official SDK to keep the packaged .exe small. Only three
operations are needed: refresh an access token, list folders (for the picker),
and upload a file.
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
LIST_URL = "https://api.dropboxapi.com/2/files/list_folder"
LIST_CONTINUE_URL = "https://api.dropboxapi.com/2/files/list_folder/continue"
UPLOAD_URL = "https://content.dropboxapi.com/2/files/upload"
UPLOAD_SESSION_START = "https://content.dropboxapi.com/2/files/upload_session/start"
UPLOAD_SESSION_APPEND = "https://content.dropboxapi.com/2/files/upload_session/append_v2"
UPLOAD_SESSION_FINISH = "https://content.dropboxapi.com/2/files/upload_session/finish"

SINGLE_SHOT_LIMIT = 140 * 1024 * 1024   # Dropbox allows up to 150 MB per single upload
CHUNK = 8 * 1024 * 1024


class DropboxError(RuntimeError):
    pass


def exchange_code_for_refresh_token(app_key: str, app_secret: str, code: str) -> dict:
    """One-time: turn an authorization code into a long-lived refresh token."""
    resp = requests.post(TOKEN_URL, data={
        "code": code,
        "grant_type": "authorization_code",
        "client_id": app_key,
        "client_secret": app_secret,
    }, timeout=30)
    if resp.status_code >= 400:
        raise DropboxError(f"Code exchange failed: HTTP {resp.status_code} — {resp.text[:300]}")
    return resp.json()


class DropboxClient:
    def __init__(self, app_key: str, app_secret: str, refresh_token: str, *, timeout: float = 60.0) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.refresh_token = refresh_token
        self.timeout = timeout
        self._access_token: str | None = None

    # -- auth ---------------------------------------------------------------

    def _token(self) -> str:
        if self._access_token:
            return self._access_token
        resp = requests.post(TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
            "client_id": self.app_key,
            "client_secret": self.app_secret,
        }, timeout=self.timeout)
        if resp.status_code >= 400:
            raise DropboxError(f"Could not refresh Dropbox token: HTTP {resp.status_code} — {resp.text[:200]}")
        self._access_token = resp.json()["access_token"]
        return self._access_token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}"}

    def check(self) -> None:
        """Raises if the credentials don't work."""
        self._token()

    # -- folders ------------------------------------------------------------

    def list_folders(self, path: str = "") -> list[str]:
        """Return sub-folder paths under `path` (root = "")."""
        headers = {**self._headers(), "Content-Type": "application/json"}
        resp = requests.post(LIST_URL, headers=headers,
                             data=json.dumps({"path": path, "recursive": False}), timeout=self.timeout)
        if resp.status_code >= 400:
            raise DropboxError(f"Could not list Dropbox folders: HTTP {resp.status_code} — {resp.text[:200]}")
        folders, payload = [], resp.json()
        while True:
            for entry in payload.get("entries", []):
                if entry.get(".tag") == "folder":
                    folders.append(entry["path_display"])
            if not payload.get("has_more"):
                break
            resp = requests.post(LIST_CONTINUE_URL, headers=headers,
                                 data=json.dumps({"cursor": payload["cursor"]}), timeout=self.timeout)
            payload = resp.json()
        return sorted(folders)

    # -- upload -------------------------------------------------------------

    def upload(self, local_path: str | Path, dropbox_path: str) -> None:
        """Upload one file to dropbox_path (e.g. "/Golf prints/Amanda Prepress AR 1x1.jpg")."""
        local_path = Path(local_path)
        size = local_path.stat().st_size
        dropbox_path = "/" + dropbox_path.lstrip("/")
        if size <= SINGLE_SHOT_LIMIT:
            self._upload_single(local_path, dropbox_path)
        else:
            self._upload_session(local_path, dropbox_path, size)

    def _upload_single(self, local_path: Path, dropbox_path: str) -> None:
        headers = {
            **self._headers(),
            "Content-Type": "application/octet-stream",
            "Dropbox-API-Arg": json.dumps({"path": dropbox_path, "mode": "overwrite", "mute": True}),
        }
        with local_path.open("rb") as fh:
            resp = requests.post(UPLOAD_URL, headers=headers, data=fh, timeout=self.timeout * 5)
        if resp.status_code >= 400:
            raise DropboxError(f"Upload failed for {local_path.name}: HTTP {resp.status_code} — {resp.text[:200]}")

    def _upload_session(self, local_path: Path, dropbox_path: str, size: int) -> None:
        with local_path.open("rb") as fh:
            # start
            first = fh.read(CHUNK)
            r = requests.post(UPLOAD_SESSION_START,
                              headers={**self._headers(), "Content-Type": "application/octet-stream",
                                       "Dropbox-API-Arg": json.dumps({"close": False})},
                              data=first, timeout=self.timeout * 5)
            if r.status_code >= 400:
                raise DropboxError(f"Upload start failed: HTTP {r.status_code} — {r.text[:200]}")
            session_id = r.json()["session_id"]
            offset = len(first)
            # append
            while True:
                chunk = fh.read(CHUNK)
                if not chunk:
                    break
                cursor = {"session_id": session_id, "offset": offset}
                r = requests.post(UPLOAD_SESSION_APPEND,
                                  headers={**self._headers(), "Content-Type": "application/octet-stream",
                                           "Dropbox-API-Arg": json.dumps({"cursor": cursor, "close": False})},
                                  data=chunk, timeout=self.timeout * 5)
                if r.status_code >= 400:
                    raise DropboxError(f"Upload append failed: HTTP {r.status_code} — {r.text[:200]}")
                offset += len(chunk)
            # finish
            arg = {"cursor": {"session_id": session_id, "offset": offset},
                   "commit": {"path": dropbox_path, "mode": "overwrite", "mute": True}}
            r = requests.post(UPLOAD_SESSION_FINISH,
                              headers={**self._headers(), "Content-Type": "application/octet-stream",
                                       "Dropbox-API-Arg": json.dumps(arg)},
                              data=b"", timeout=self.timeout * 5)
            if r.status_code >= 400:
                raise DropboxError(f"Upload finish failed: HTTP {r.status_code} — {r.text[:200]}")
