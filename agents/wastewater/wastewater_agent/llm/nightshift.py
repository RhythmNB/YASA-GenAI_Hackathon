"""Meterless Nightshift provider (OpenAI-compatible chat, compute receipts)."""

from __future__ import annotations

import json
import re
import time
from typing import Any

import httpx

from ..config import NIGHTSHIFT_APP, NIGHTSHIFT_MODELS
from .base import Completion, ProviderUnauthorized, ProviderUnavailable

_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)
_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S)
_CLOSE_THINK = "</think>"


class NightshiftProvider:
    name = "nightshift"

    def __init__(
        self,
        base_url: str,
        token: str | None,
        *,
        app: str = NIGHTSHIFT_APP,
        model: str | None = None,
        models: tuple[str, ...] | list[str] | None = None,
        timeout: float = 180.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.app = app
        # `model` pins a single route (the judge does this); otherwise the
        # chain is tried in order and a failing route is skipped for a while.
        self.models: tuple[str, ...] = (model,) if model else tuple(models or NIGHTSHIFT_MODELS)
        self.model = self.models[0]
        self.timeout = timeout
        self._skip_until: dict[str, float] = {}
        # Optional progress sink: called with {"stage": "route", "state": start|done|failed, ...}
        # for every route attempt. The agent sets it for the duration of one question.
        self.on_event = None

    ROUTE_SKIP_SECONDS = 300.0

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token or ''}",
            "meterless-app": self.app,
            "meterless-scope": "user",
            "Content-Type": "application/json",
        }

    # -- readiness ---------------------------------------------------------

    def readiness(self) -> tuple[str, list[dict[str, Any]]]:
        """Return ('online' | 'unauthorized' | 'offline', models)."""
        if not self._token:
            return "unauthorized", []
        try:
            r = httpx.get(f"{self.base_url}/models", headers=self._headers(), timeout=10.0)
        except httpx.HTTPError:
            return "offline", []
        if r.status_code in (401, 403):
            return "unauthorized", []
        if r.status_code != 200:
            return "offline", []
        try:
            data = r.json().get("data", [])
        except ValueError:
            return "offline", []
        models = [
            {
                "id": m.get("id"),
                "owned_by": m.get("owned_by"),
                "availability": (m.get("meterless") or {}).get("availability"),
            }
            for m in data
            if isinstance(m, dict)
        ]
        if not any(str(m["id"]).startswith("meterless/") for m in models):
            return "offline", models
        return "online", models

    # -- chat --------------------------------------------------------------

    def complete(
        self, messages: list[dict[str, str]], *, json_mode: bool = False, max_tokens: int = 400
    ) -> Completion:
        """Try each route in turn; a route that fails is skipped for a few minutes."""
        now = time.monotonic()
        order = [m for m in self.models if self._skip_until.get(m, 0.0) <= now] or list(self.models)
        errors: list[str] = []
        for model in order:
            self._emit({"stage": "route", "state": "start", "model": model})
            try:
                completion = self._complete_with(model, messages, json_mode=json_mode, max_tokens=max_tokens)
            except ProviderUnavailable as e:
                errors.append(f"{model}: {e}")
                self._emit({"stage": "route", "state": "failed", "model": model, "error": str(e)[:160]})
                if "unreachable" in str(e):
                    break  # the proxy itself is down; other routes cannot help
                self._skip_until[model] = time.monotonic() + self.ROUTE_SKIP_SECONDS
                continue
            self._emit({"stage": "route", "state": "done", "model": completion.routed_model or model,
                        "receipt": completion.receipt_id})
            return completion
        raise ProviderUnavailable(errors[0] if len(errors) == 1 else "all routes failed: " + " | ".join(errors))

    def _emit(self, event: dict[str, Any]) -> None:
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception:  # a progress sink must never break a completion
                pass

    def _complete_with(
        self, model: str, messages: list[dict[str, str]], *, json_mode: bool, max_tokens: int
    ) -> Completion:
        body = {
            "model": model,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": messages,
            # Nemotron honours this and answers without a reasoning preamble
            # (verified 2026-10-24); other routes ignore it, and the
            # reasoning strip below still applies.
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            r = httpx.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                json=body,
                timeout=self.timeout,
            )
        except httpx.HTTPError as e:
            raise ProviderUnavailable(f"nightshift unreachable: {e.__class__.__name__}") from e
        if r.status_code in (401, 403):
            raise ProviderUnauthorized(f"nightshift returned HTTP {r.status_code}; check the token file")
        if r.status_code != 200:
            raise ProviderUnavailable(f"nightshift returned HTTP {r.status_code}: {r.text[:200]}")
        try:
            data = r.json()
            choice = data["choices"][0]
            content = choice["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError) as e:
            raise ProviderUnavailable("nightshift returned a malformed completion") from e
        receipt = data.get("meterless") or {}
        finish = choice.get("finish_reason")
        text = extract_json(content) if json_mode else strip_reasoning(content)
        if not text:
            raise ProviderUnavailable(
                "nightshift output was cut off before the answer (finish_reason=length)"
                if finish == "length"
                else "nightshift returned no usable content"
            )
        if not json_mode and finish == "length" and _CLOSE_THINK not in content:
            raise ProviderUnavailable("nightshift output was cut off before the answer (finish_reason=length)")
        return Completion(
            text=text,
            provider=self.name,
            receipt_id=receipt.get("receipt_id"),
            routed_model=receipt.get("routed_model") or data.get("model"),
            raw={"receipt": receipt, "usage": data.get("usage"), "model": data.get("model"), "requested_model": model},
        )


# -- reasoning-model output handling ----------------------------------------


_REASONING_OPENERS = ("The user", "Let me", "I need", "I should", "I'll ", "Okay", "First,", "Looking at")


def strip_reasoning(content: str) -> str:
    """Drop <think>...</think>, anything before a bare closing </think>, and
    leading paragraphs that narrate the task ("The user ...", "Let me ...").

    If no </think> is present and the whole text reads as reasoning (every
    paragraph starts with a reasoning opener), nothing usable is returned."""
    text = _THINK_BLOCK.sub("", content)
    if _CLOSE_THINK in text:
        text = text.rsplit(_CLOSE_THINK, 1)[1]
    text = text.strip()
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    while paragraphs and paragraphs[0].lstrip().startswith(_REASONING_OPENERS):
        paragraphs.pop(0)
    if paragraphs and _CLOSE_THINK not in content and paragraphs[0].lstrip().startswith(("-", "*", "Rules")):
        return ""  # a bulleted analysis of the fact sheet, not an answer
    return "\n\n".join(paragraphs).strip()


def extract_json(content: str) -> str:
    """The last fenced JSON block, else the last balanced {...} object."""
    text = content
    if _CLOSE_THINK in text:
        text = text.rsplit(_CLOSE_THINK, 1)[1]
    fenced = _FENCED_JSON.findall(text)
    if fenced:
        return fenced[-1]
    obj = _last_balanced_object(text)
    if obj is None and text is not content:
        obj = _last_balanced_object(content)
    return obj or ""


def _last_balanced_object(text: str) -> str | None:
    """Return the last top-level {...} substring that parses as JSON.

    Quotes are tracked only inside objects first (prose may contain stray
    quotes); if that finds nothing, quotes are tracked everywhere."""
    return _scan_objects(text, quotes_everywhere=False) or _scan_objects(text, quotes_everywhere=True)


def _scan_objects(text: str, *, quotes_everywhere: bool) -> str | None:
    found: list[str] = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, c in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"' and (depth > 0 or quotes_everywhere):
            in_str = True
        elif c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start != -1:
                candidate = text[start : i + 1]
                try:
                    json.loads(candidate)
                    found.append(candidate)
                except ValueError:
                    pass
                start = -1
    return found[-1] if found else None
