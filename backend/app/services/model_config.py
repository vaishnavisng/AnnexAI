"""Background Gemini model selection + automatic fallback.

There is no user-facing way to switch models. The primary model comes from
``GEMINI_MODEL_NAME`` (env / settings) and the fallback chain is derived from
``GEMINI_MODEL_OPTIONS``. When the primary model is exhausted (rate-limited
or temporarily unavailable), ``llm_client`` walks the chain so the user gets
an uninterrupted experience.
"""

import logging
import threading
import time
from typing import Optional

from app.config.settings import (
    GEMINI_ALLOWED_MODELS,
    GEMINI_DEFAULT_MODEL,
    GEMINI_MODEL_NAME,
    GEMINI_MODEL_OPTIONS,
    LLM_ENABLE_FALLBACK,
)

_logger = logging.getLogger(__name__)

# Diagnostics only: track which model actually served the most recent
# request and whether a fallback had to be used. Useful for logs and tests.
_last_used_lock = threading.Lock()
_last_used: Optional[dict] = None


def _normalize(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    candidate = str(value).strip()
    if candidate in GEMINI_ALLOWED_MODELS:
        return candidate
    return None


def get_primary_model() -> str:
    """Return the configured primary Gemini model id."""
    return _normalize(GEMINI_MODEL_NAME) or GEMINI_DEFAULT_MODEL


def is_fallback_enabled() -> bool:
    return bool(LLM_ENABLE_FALLBACK)


def fallback_chain() -> list[str]:
    """Return the ordered list of models to try.

    Primary model first, followed by the remaining allowed models in the
    order declared in ``GEMINI_MODEL_OPTIONS``. If fallback is disabled,
    only the primary model is returned.
    """
    primary = get_primary_model()
    if not is_fallback_enabled():
        return [primary]

    chain: list[str] = [primary]
    for option in GEMINI_MODEL_OPTIONS:
        candidate = option.get("id")
        if candidate and candidate not in chain and candidate in GEMINI_ALLOWED_MODELS:
            chain.append(candidate)
    return chain


def record_last_used_model(model: str, *, fallback_used: bool, reason: str = "") -> None:
    """Record which model actually served the most recent LLM request."""
    entry = {
        "model": model,
        "fallback_used": bool(fallback_used),
        "reason": reason or "",
        "timestamp": time.time(),
    }
    global _last_used
    with _last_used_lock:
        _last_used = entry

    if fallback_used:
        _logger.info(
            "Gemini fallback served request with %s (reason: %s).",
            model,
            reason or "rate_limited",
        )


def get_last_used_model() -> Optional[dict]:
    with _last_used_lock:
        return dict(_last_used) if _last_used else None
