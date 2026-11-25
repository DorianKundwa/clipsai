"""
Backend configuration for ClipsAI Studio.

Service credentials live in the environment (or a project ``.env`` file), never
in the web UI. ``load_env`` is a small stdlib parser so no extra dependency is
needed, and it never overrides variables the process already has.

Environment variables
---------------------
``DEEPSEEK_API_KEY``    DeepSeek key for the AI features
``DEEPSEEK_BASE_URL``   defaults to https://api.deepseek.com
``DEEPSEEK_MODEL``      defaults to deepseek-chat
``HF_TOKEN``            HuggingFace/pyannote token for diarization
``PYANNOTE_AUTH_TOKEN`` accepted as an alias for ``HF_TOKEN``
``INDIEPOST_API_KEY``   IndiePost key for publishing
``INDIEPOST_BASE_URL``  defaults to https://www.indiepost.app
"""

# standard library imports
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-chat"
DEFAULT_INDIEPOST_BASE_URL = "https://www.indiepost.app"

_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_env(path: "str | os.PathLike | None" = None, override: bool = False) -> "dict[str, str]":
    """
    Load ``KEY=VALUE`` pairs from a ``.env`` file into ``os.environ``.

    - Blank lines and ``#`` comments are ignored.
    - A leading ``export`` is accepted.
    - Single or double quotes around the value are removed.
    - An unquoted `` #`` starts an inline comment.
    - Existing environment variables win unless ``override=True``.

    Returns the variables that were actually written. A missing file is not an
    error (an empty dict is returned).
    """
    env_path = Path(path or os.environ.get("CLIPSAI_ENV_FILE") or ".env")
    loaded: "dict[str, str]" = {}
    if not env_path.is_file():
        return loaded

    try:
        raw_text = env_path.read_text(encoding="utf-8-sig")
    except OSError:
        return loaded

    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not _ENV_KEY_RE.match(key):
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        if override or key not in os.environ:
            os.environ[key] = value
            loaded[key] = value
    return loaded


def huggingface_token() -> str:
    """The configured HuggingFace/pyannote token (may be empty)."""
    return (
        os.environ.get("HF_TOKEN", "").strip()
        or os.environ.get("PYANNOTE_AUTH_TOKEN", "").strip()
    )


@dataclass(frozen=True)
class AISettings:
    api_key: str = ""
    base_url: str = DEFAULT_DEEPSEEK_BASE_URL
    model: str = DEFAULT_DEEPSEEK_MODEL

    @classmethod
    def from_env(cls) -> "AISettings":
        return cls(
            api_key=os.environ.get("DEEPSEEK_API_KEY", "").strip(),
            base_url=(
                os.environ.get("DEEPSEEK_BASE_URL", "").strip()
                or DEFAULT_DEEPSEEK_BASE_URL
            ),
            model=(
                os.environ.get("DEEPSEEK_MODEL", "").strip() or DEFAULT_DEEPSEEK_MODEL
            ),
        )

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def describe(self) -> dict:
        """Safe description for the UI: never includes the key itself."""
        return {
            "configured": self.is_configured(),
            "model": self.model,
            "base_url": self.base_url,
            "api_key": "set" if self.api_key else "missing",
        }


@dataclass(frozen=True)
class IndiePostSettings:
    api_key: str = ""
    base_url: str = DEFAULT_INDIEPOST_BASE_URL

    @classmethod
    def from_env(cls) -> "IndiePostSettings":
        return cls(
            api_key=os.environ.get("INDIEPOST_API_KEY", "").strip(),
            base_url=(
                os.environ.get("INDIEPOST_BASE_URL", "").strip()
                or DEFAULT_INDIEPOST_BASE_URL
            ).rstrip("/"),
        )

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def describe(self) -> dict:
        return {
            "configured": self.is_configured(),
            "base_url": self.base_url,
            "api_key": "set" if self.api_key else "missing",
        }


def service_status() -> dict:
    """Readiness of every third-party service ClipsAI Studio can use."""
    ai = AISettings.from_env()
    indiepost = IndiePostSettings.from_env()
    return {
        "deepseek": ai.describe(),
        "huggingface": {"configured": bool(huggingface_token())},
        "indiepost": indiepost.describe(),
    }
