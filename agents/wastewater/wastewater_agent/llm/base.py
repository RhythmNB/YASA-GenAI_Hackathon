"""Provider protocol shared by the planner and writer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(RuntimeError):
    pass


class ProviderUnavailable(ProviderError):
    """Unreachable or malformed; callers fall back to the offline provider."""


class ProviderUnauthorized(ProviderError):
    """401/403; callers must not fall back silently."""


@dataclass
class Completion:
    text: str
    provider: str
    receipt_id: str | None = None
    routed_model: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class Provider(Protocol):
    name: str

    def complete(
        self, messages: list[dict[str, str]], *, json_mode: bool = False, max_tokens: int = 400
    ) -> Completion: ...
