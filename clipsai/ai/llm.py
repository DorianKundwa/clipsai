"""
DeepSeek client for ClipsAI's AI features.

DeepSeek exposes an OpenAI-compatible chat-completions API, so every AI feature
in ClipsAI talks to it through this one small client.

Configuration (environment variables)
-------------------------------------
``DEEPSEEK_API_KEY``   required; create one at https://platform.deepseek.com
``DEEPSEEK_BASE_URL``  optional; defaults to https://api.deepseek.com
``DEEPSEEK_MODEL``     optional; defaults to deepseek-chat

No key is ever logged. If the key is missing, the AI features raise
``MissingAPIKeyError`` with a message telling the user where to set it.
"""

# standard library imports
from __future__ import annotations

import json
import os
import time

# 3rd party imports
import requests

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT = 180
MAX_RETRIES = 3
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}


class LLMError(Exception):
    """Base error for AI features."""


class MissingAPIKeyError(LLMError):
    """Raised when no DeepSeek API key is configured."""


class LLMResponseError(LLMError):
    """Raised when the model returns something unusable."""


def parse_json(text: str):
    """
    Parse the first JSON object/array in ``text``.

    Tolerates code fences and prose around the payload, which small models add
    even when asked for JSON only.
    """
    text = (text or "").strip()
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise LLMResponseError("The model did not return JSON: {}".format(text[:300]))
    start = min(starts)
    try:
        payload, _ = json.JSONDecoder().raw_decode(text[start:])
        return payload
    except json.JSONDecodeError as exc:
        raise LLMResponseError(
            "Could not parse the model's JSON ({}): {}".format(exc, text[start:start + 300])
        ) from exc


class LLMClient:
    """Minimal OpenAI-compatible chat client pointed at DeepSeek."""

    def __init__(
        self,
        api_key: "str | None" = None,
        base_url: "str | None" = None,
        model: "str | None" = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = MAX_RETRIES,
        session: "requests.Session | None" = None,
    ) -> None:
        self.api_key = (api_key or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
        self.base_url = (
            base_url or os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL
        ).strip().rstrip("/")
        self.model = (model or os.environ.get("DEEPSEEK_MODEL") or DEFAULT_MODEL).strip()
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = session or requests.Session()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def assert_ready(self) -> None:
        if not self.api_key:
            raise MissingAPIKeyError(
                "No DeepSeek API key configured. Set DEEPSEEK_API_KEY, or paste a "
                "key in the AI (DeepSeek) tab of ClipsAI Studio."
            )

    def complete(
        self,
        prompt: str,
        system: "str | None" = None,
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> str:
        """Send one chat completion and return the message text."""
        self.assert_ready()

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": "Bearer {}".format(self.api_key),
            "Content-Type": "application/json",
        }
        url = "{}/chat/completions".format(self.base_url)

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._session.post(
                    url, headers=headers, json=payload, timeout=self.timeout
                )
            except requests.RequestException as exc:
                last_error = "request failed: {}".format(exc)
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise LLMError("DeepSeek request failed: {}".format(exc)) from exc

            if response.status_code in RETRY_STATUS and attempt < self.max_retries:
                last_error = "HTTP {}: {}".format(
                    response.status_code, response.text[:200]
                )
                time.sleep(min(2 ** attempt, 8))
                continue

            if response.status_code != 200:
                raise LLMError(
                    "DeepSeek returned HTTP {}: {}".format(
                        response.status_code, (response.text or "").strip()[:500]
                    )
                )

            try:
                data = response.json()
                content = data["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise LLMResponseError(
                    "Unexpected DeepSeek response: {}".format(
                        (response.text or "").strip()[:300]
                    )
                ) from exc

            if not content or not content.strip():
                raise LLMResponseError("DeepSeek returned an empty message.")
            return content

        raise LLMError("DeepSeek request failed: {}".format(last_error))

    def complete_json(
        self,
        prompt: str,
        system: "str | None" = None,
        temperature: float = 0.4,
        max_tokens: int = 4096,
    ):
        """Send a completion in JSON mode and return the parsed payload."""
        content = self.complete(
            prompt,
            system=system,
            json_mode=True,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return parse_json(content)
