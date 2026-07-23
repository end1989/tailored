from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

# backend/app/config.py -> parents[2] == project root (tailored/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_USER_SETTINGS = {
    "default_template": "slate",
    "default_depth": "standard",
    "page_size": "Letter",
}

_UNSET = object()


class Settings:
    """Simple settings object. Reads env once at construction; keyword
    arguments override the environment (used by tests / fixtures)."""

    def __init__(
        self,
        anthropic_api_key: object = _UNSET,
        data_dir: Path | str | None = None,
        fake_mode: bool | None = None,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        if anthropic_api_key is _UNSET:
            self.anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY") or None
        else:
            self.anthropic_api_key = anthropic_api_key  # type: ignore[assignment]

        if data_dir is not None:
            self.data_dir = Path(data_dir)
        else:
            env_data_dir = os.environ.get("TAILORED_DATA_DIR", "")
            self.data_dir = Path(env_data_dir) if env_data_dir else PROJECT_ROOT / "data"

        if fake_mode is not None:
            self.fake_mode = fake_mode
        else:
            self.fake_mode = os.environ.get("TAILORED_FAKE") == "1"

        self.host = host if host is not None else (os.environ.get("TAILORED_HOST") or "127.0.0.1")

        if port is not None:
            self.port = port
        else:
            env_port = os.environ.get("TAILORED_PORT", "")
            try:
                self.port = int(env_port) if env_port else 8547
            except ValueError:
                self.port = 8547


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def load_user_settings(data_dir: Path) -> dict:
    """Read <data_dir>/settings.json merged over defaults. Unknown or
    malformed content falls back to defaults. Always returns a fresh dict."""
    path = Path(data_dir) / "settings.json"
    values = dict(DEFAULT_USER_SETTINGS)
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            stored = {}
        if isinstance(stored, dict):
            values.update({k: v for k, v in stored.items() if k in DEFAULT_USER_SETTINGS})
    return values


def save_user_settings(data_dir: Path, values: dict) -> dict:
    """Merge known keys from `values` into the persisted settings and return
    the resulting full settings dict."""
    path = Path(data_dir) / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    current = load_user_settings(data_dir)
    current.update({k: v for k, v in values.items() if k in DEFAULT_USER_SETTINGS})
    path.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current
