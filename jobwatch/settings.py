"""Per-install settings (the public address, how to notify the person), read from small KEY=value files so the code
holds no one's server: ~/.config/jobwatch/settings.env, or the file named by JOBWATCH_SETTINGS, plus google.env next
to it (the Google sign-in client, or the file named by JOBWATCH_GOOGLE_ENV). Real environment variables win."""
from __future__ import annotations

import os
from pathlib import Path

_loaded = False


def _read(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


def load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    path = Path(os.environ.get("JOBWATCH_SETTINGS") or Path.home() / ".config" / "jobwatch" / "settings.env")
    _read(path)
    google = Path(os.environ.get("JOBWATCH_GOOGLE_ENV") or path.parent / "google.env")
    if google != path:
        _read(google)


def get(key: str, default: str = "") -> str:
    load()
    return os.environ.get(key, default)


# The install's default chat model (OpenAI-compatible name). The person may pick per role on the Models page.
DEFAULT_MODEL = get("JOBWATCH_LLM_MODEL", "gpt-4o")
