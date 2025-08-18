# Lightweight Ollama HTTP client for health, model inventory, and lifecycle actions.

from __future__ import annotations

import os
from typing import Any

import requests
from dateutil import parser

DEFAULT_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

STATUS_CODE_OK = 200


def _url(base: str, path: str) -> str:
    return f"{base.rstrip('/')}{path}"


class OllamaHealth:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or DEFAULT_OLLAMA_BASE_URL).rstrip("/")

    # -------- Health & inventory

    def ping(self, timeout: float = 1.5) -> tuple[bool, str]:
        """Return (ok, detail). ok=True if server responds to /api/tags."""
        try:
            r = requests.get(_url(self.base_url, "/api/tags"), timeout=timeout)
            if r.status_code == STATUS_CODE_OK:
                return True, "Ollama is reachable"
        except requests.ConnectionError as e:
            return False, f"Connection error: {e}"
        except requests.Timeout:
            return False, "Timeout reaching Ollama"
        except Exception as e:
            return False, f"Unexpected error: {e}"
        else:
            return False, f"Ollama responded with HTTP {r.status_code}"

    def list_models(self, timeout: float = 2.5) -> list[str]:
        """All installed models (tags)."""
        r = requests.get(_url(self.base_url, "/api/tags"), timeout=timeout)
        r.raise_for_status()
        data = r.json()
        models: list[str] = []
        for m in data.get("models", []):
            tag = m.get("model") or m.get("name")
            if isinstance(tag, str):
                models.append(tag)
        return sorted(set(models))

    def has_model(self, required: str, timeout: float = 2.5) -> bool:
        """Loose contains check against installed models."""
        try:
            models = self.list_models(timeout=timeout)
        except Exception:
            return False
        req = required.lower()
        return any(req in m.lower() for m in models)

    def list_running(self, timeout: float = 2.0) -> list[dict[str, Any]]:
        """
        Running (loaded) models via /api/ps.

        Returns a list of dicts; keys vary by version; we normalize a few fields.
        """
        r = requests.get(_url(self.base_url, "/api/ps"), timeout=timeout)
        r.raise_for_status()
        data = r.json()
        out: list[dict[str, Any]] = []
        for m in data.get("models", []):
            out.append(
                {
                    "model": m.get("model") or m.get("name"),
                    "size": m.get("size"),
                    "digest": m.get("digest"),
                    "expires_at": m.get("expires_at"),
                },
            )
        return out

    # -------- Lifecycle

    def pull_model(self, name: str, timeout: float = 300.0) -> tuple[bool, str]:
        """
        Pull a model by tag. Uses non-streaming mode for simplicity; may block until complete.

        Returns (ok, detail).
        """
        try:
            r = requests.post(
                _url(self.base_url, "/api/pull"),
                json={"name": name, "stream": False},
                timeout=timeout,
            )
            if r.status_code == STATUS_CODE_OK:
                return True, f"Model pulled: {name}"
            return False, f"Pull failed: HTTP {r.status_code} {r.text[:200]}"
        except Exception as e:
            return False, f"Pull error: {e}"

    def start_model(
        self, name: str, keep_alive: str = "30m", timeout: float = 60.0
    ) -> tuple[bool, str]:
        """
        Load model into memory by issuing a minimal generate with keep_alive.

        keep_alive: e.g., '10m', '1h', or '-1' (never unload).
        """
        try:
            r = requests.post(
                _url(self.base_url, "/api/generate"),
                json={
                    "model": name,
                    "prompt": " ",
                    "stream": False,
                    "keep_alive": keep_alive,
                },
                timeout=timeout,
            )
            if r.status_code == STATUS_CODE_OK:
                return True, f"Model loaded with keep_alive={keep_alive}: {name}"
            return False, f"Start failed: HTTP {r.status_code} {r.text[:200]}"
        except Exception as e:
            return False, f"Start error: {e}"

    def stop_model(self, name: str, timeout: float = 30.0) -> tuple[bool, str]:
        """
        Unload a running model.

        Attempt to unload a running model:
        1) Preferred: /api/stop (mirrors `ollama stop`).
        2) Fallback: a no-op generate with keep_alive=0 to hint unload.
        """
        try:
            r = requests.post(
                _url(self.base_url, "/api/stop"),
                json={"model": name},
                timeout=timeout,
            )
            if r.status_code == STATUS_CODE_OK:
                return True, f"Stopped model: {name}"
            # Fallback
            r2 = requests.post(
                _url(self.base_url, "/api/generate"),
                json={"model": name, "prompt": " ", "stream": False, "keep_alive": 0},
                timeout=timeout,
            )
            if r2.status_code == STATUS_CODE_OK:
                return True, f"Unload requested (keep_alive=0): {name}"
        except Exception as e:
            return False, f"Stop error: {e}"
        else:
            return False, f"Stop failed: HTTP {r.status_code}/{r2.status_code}"

    def is_model_running(
        self,
        name: str,
        timeout: float = 3.0,
    ) -> tuple[bool, str]:
        """
        Checks if the specified model is currently loaded and running in Ollama.

        Uses the /api/ps endpoint via list_running(), which is safe and non-intrusive.

        Returns
        -------
            (True, message) if model is running
            (False, message) otherwise

        """
        try:
            running_models = self.list_running(timeout=timeout)
            running_model_names = [
                m.get("model") for m in running_models if m.get("model")
            ]

            if name in running_model_names:
                return True, f"Model is running: {name}"

        except Exception as e:
            return False, f"Error checking model status: {e}"
        else:
            return False, f"Model not running: {name}"

    def get_model_expiry(self, name: str) -> str:
        expiry = ""
        running_models = self.list_running()
        for m in running_models:
            if m.get("model") == name:
                expiry = m.get("expires_at")
                # Truncate to microseconds (6 digits)
                expiry = expiry[:26] + expiry[35:]
                expiry = parser.isoparse(expiry)
                # Format to readable string
                expiry = expiry.strftime("%b %d, %Y at %I:%M %p")
        return expiry
