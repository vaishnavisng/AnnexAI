import json
import logging
import os
import random
import threading
import time
from typing import Any, Iterator, Optional

from google import genai
from google.genai import types

from app.config.settings import (
    GEMINI_API_KEY,
    GEMINI_MODEL_NAME,
    LLM_MIN_REQUEST_INTERVAL,
    LLM_RETRY_ATTEMPTS,
    LLM_RETRY_BASE_DELAY,
)
from app.services.model_config import (
    fallback_chain,
    get_primary_model,
    record_last_used_model,
)


class _ModelExhausted(Exception):
    """Raised internally when a single model can no longer serve the request.

    Triggers the outer fallback loop to try the next model in the chain.
    """

    def __init__(self, model: str, cause: Exception, reason: str):
        super().__init__(f"{model} exhausted ({reason}): {cause}")
        self.model = model
        self.cause = cause
        self.reason = reason

_client: Optional[genai.Client] = None
_client_err: Optional[str] = None
_request_lock = threading.Lock()
_last_request_ts = 0.0
_logger = logging.getLogger(__name__)

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_RETRYABLE_MARKERS = (
    "resource_exhausted",
    "rate limit",
    "too many requests",
    "quota",
    "service unavailable",
    "deadline exceeded",
    "timed out",
    "temporarily unavailable",
)
_RATE_LIMIT_MARKERS = (
    "resource_exhausted",
    "rate limit",
    "too many requests",
    "quota",
)
_QUIZ_THINKING_BUDGET = 1024
_QUIZ_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "required": ["questions"],
    "properties": {
        "questions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "required": ["id", "type", "question", "correct", "explanation"],
                "properties": {
                    "id": {"type": "INTEGER"},
                    "type": {
                        "type": "STRING",
                        "enum": ["mcq", "multi_select", "true_false", "short_answer"],
                    },
                    "question": {"type": "STRING"},
                    "options": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                    },
                    "correct": {
                        "description": "Single answer value or a list of answers for multi_select questions.",
                    },
                    "explanation": {"type": "STRING"},
                },
            },
        }
    },
}


def _coerce_status_code(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value

    raw_value = getattr(value, "value", value)
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _extract_status_code(error: Exception) -> Optional[int]:
    for attr in ("status_code", "code", "http_status"):
        status_code = _coerce_status_code(getattr(error, attr, None))
        if status_code is not None:
            return status_code

    response = getattr(error, "response", None)
    if response is not None:
        status_code = _coerce_status_code(getattr(response, "status_code", None))
        if status_code is not None:
            return status_code

    return None


def _error_text(error: Exception) -> str:
    return str(error).lower()


def _is_rate_limited_error(error: Exception) -> bool:
    status_code = _extract_status_code(error)
    if status_code == 429:
        return True

    text = _error_text(error)
    return any(marker in text for marker in _RATE_LIMIT_MARKERS)


def _is_retryable_error(error: Exception) -> bool:
    status_code = _extract_status_code(error)
    if status_code in _RETRYABLE_STATUS_CODES:
        return True

    text = _error_text(error)
    return any(marker in text for marker in _RETRYABLE_MARKERS)


def _wait_for_request_slot() -> None:
    interval = max(0.0, float(LLM_MIN_REQUEST_INTERVAL))
    if interval <= 0.0:
        return

    global _last_request_ts
    with _request_lock:
        now = time.monotonic()
        wait_seconds = interval - (now - _last_request_ts)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
            now = time.monotonic()
        _last_request_ts = now


def _retry_delay_seconds(attempt_number: int) -> float:
    base_delay = max(0.1, float(LLM_RETRY_BASE_DELAY))
    exp_delay = base_delay * (2 ** max(0, attempt_number - 1))
    jitter = random.uniform(0.0, min(1.0, base_delay))
    return min(60.0, exp_delay + jitter)


def _get_gemini_client() -> genai.Client:
    global _client, _client_err

    if _client is not None:
        return _client

    api_key = os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY
    if not api_key:
        _client_err = (
            "Gemini API key is not configured. Set GEMINI_API_KEY "
            "in your environment or in a local .env file."
        )
        raise RuntimeError(_client_err)

    try:
        _client = genai.Client(api_key=api_key)
        return _client
    except Exception as e:
        _client_err = str(e)
        raise RuntimeError(f"Failed to create Gemini client: {_client_err}") from e


def _resolve_model(task_type: str) -> str:
    """Return the primary Gemini model id (kept for backward compat)."""
    try:
        return get_primary_model()
    except Exception as exc:  # fall back to the env/default if anything fails
        _logger.debug("Falling back to configured Gemini model: %s", exc)
        return GEMINI_MODEL_NAME


def _resolve_chain(task_type: str) -> list[str]:
    """Return the ordered list of models to try for a given task."""
    try:
        chain = fallback_chain()
    except Exception as exc:
        _logger.debug("Falling back to configured Gemini model chain: %s", exc)
        chain = [GEMINI_MODEL_NAME]
    return chain or [GEMINI_MODEL_NAME]


def _build_generation_config(
    system_prompt: str,
    max_output_tokens: int,
    temperature: float,
    task_type: str,
) -> types.GenerateContentConfig:
    config_kwargs: dict[str, Any] = {
        "system_instruction": system_prompt,
        "max_output_tokens": max(1, int(max_output_tokens)),
        "temperature": float(temperature),
    }
    advanced_keys = []

    if task_type in {"quiz", "quiz_eval"}:
        config_kwargs["response_mime_type"] = "application/json"

    if task_type == "quiz":
        thinking_config_cls = getattr(types, "ThinkingConfig", None)
        if thinking_config_cls is not None:
            try:
                config_kwargs["thinking_config"] = thinking_config_cls(
                    thinking_budget=_QUIZ_THINKING_BUDGET,
                )
                advanced_keys.append("thinking_config")
            except Exception as exc:
                _logger.debug("Unable to set quiz thinking config: %s", exc)

        config_kwargs["response_schema"] = _QUIZ_RESPONSE_SCHEMA
        advanced_keys.append("response_schema")

    try:
        return types.GenerateContentConfig(**config_kwargs)
    except Exception as exc:
        if not advanced_keys:
            raise

        fallback_kwargs = dict(config_kwargs)
        for key in advanced_keys:
            fallback_kwargs.pop(key, None)

        _logger.warning(
            "GenerateContentConfig rejected quiz-specific config (%s); "
            "retrying without %s.",
            exc,
            ", ".join(advanced_keys),
        )
        return types.GenerateContentConfig(**fallback_kwargs)


def _extract_response_text(response: Any, strip: bool = True) -> str:
    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        if isinstance(parsed, (dict, list)):
            return json.dumps(parsed, ensure_ascii=False)
        parsed_text = str(parsed)
        if strip:
            parsed_text = parsed_text.strip()
        if parsed_text:
            return parsed_text

    text = getattr(response, "text", None)
    if text is not None:
        text_value = str(text)
        if strip:
            text_value = text_value.strip()
        if text_value:
            return text_value

    parts = []
    for candidate in getattr(response, "candidates", []) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", []) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                parts.append(str(part_text))

    joined = "\n".join(parts)
    return joined.strip() if strip else joined


def _stream_text_delta(text: str, accumulated_text: str) -> tuple[str, str]:
    if not text:
        return "", accumulated_text

    if accumulated_text and text.startswith(accumulated_text):
        return text[len(accumulated_text) :], text

    if accumulated_text.endswith(text):
        return "", accumulated_text

    return text, accumulated_text + text


def _describe_empty_response(response: Any) -> str:
    details = []

    prompt_feedback = getattr(response, "prompt_feedback", None)
    if prompt_feedback is not None:
        block_reason = getattr(prompt_feedback, "block_reason", None)
        if block_reason:
            details.append(f"prompt_block_reason={block_reason}")

    finish_reasons = []
    for candidate in getattr(response, "candidates", []) or []:
        reason = getattr(candidate, "finish_reason", None)
        if not reason:
            continue
        name = getattr(reason, "name", None)
        finish_reasons.append(str(name or reason))

    if finish_reasons:
        details.append("finish_reasons=" + ", ".join(finish_reasons))

    return "; ".join(details) if details else "no text parts or parsed payload"


def _invoke_single_model(
    client: genai.Client,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
    temperature: float,
    task_type: str,
) -> str:
    """Run a non-streaming call against a single model with retries.

    Raises ``_ModelExhausted`` when the model is rate-limited/quota-exceeded
    (or retries were exhausted on retryable errors) so the caller can fall
    back to another model. Raises ``RuntimeError`` for non-retryable errors.
    """
    max_attempts = max(1, int(LLM_RETRY_ATTEMPTS))

    for attempt in range(1, max_attempts + 1):
        try:
            _wait_for_request_slot()
            resp = client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=_build_generation_config(
                    system_prompt=system_prompt,
                    max_output_tokens=max_output_tokens,
                    temperature=temperature,
                    task_type=task_type,
                ),
            )
        except Exception as exc:
            is_retryable = _is_retryable_error(exc)
            is_rate_limited = _is_rate_limited_error(exc)

            if not is_retryable or attempt >= max_attempts:
                if is_rate_limited or is_retryable:
                    reason = "rate_limited" if is_rate_limited else "transient_error"
                    raise _ModelExhausted(model, exc, reason) from exc
                raise RuntimeError(f"Gemini request failed: {exc}") from exc

            delay = _retry_delay_seconds(attempt)
            _logger.warning(
                "Gemini call to %s failed (attempt %s/%s): %s. Retrying in %.1fs.",
                model,
                attempt,
                max_attempts,
                exc,
                delay,
            )
            time.sleep(delay)
            continue

        text = _extract_response_text(resp)
        if text:
            return text

        raise RuntimeError(
            f"Gemini ({model}) returned no text response ({_describe_empty_response(resp)})."
        )

    raise _ModelExhausted(
        model,
        RuntimeError("Repeated transient errors"),
        "transient_error",
    )


def call_llm(
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int = 2048,
    temperature: float = 0.3,
    task_type: str = "qa",
) -> str:
    """Call Gemini and return the answer text.

    Automatically falls back to the next model in ``fallback_chain()`` when
    the preferred model is rate-limited or temporarily unavailable, so the
    user experience stays uninterrupted even when one model's quota is hit.
    """
    client = _get_gemini_client()
    chain = _resolve_chain(task_type)
    last_exhaustion: Optional[_ModelExhausted] = None

    for idx, model in enumerate(chain):
        try:
            text = _invoke_single_model(
                client,
                model,
                system_prompt,
                user_prompt,
                max_output_tokens,
                temperature,
                task_type,
            )
        except _ModelExhausted as exc:
            last_exhaustion = exc
            if idx + 1 < len(chain):
                _logger.warning(
                    "Model %s exhausted (%s); falling back to %s.",
                    model,
                    exc.reason,
                    chain[idx + 1],
                )
                continue
            break

        record_last_used_model(
            model,
            fallback_used=idx > 0,
            reason=(last_exhaustion.reason if last_exhaustion else ""),
        )
        return text

    assert last_exhaustion is not None  # only path that reaches here
    cause = last_exhaustion.cause
    if last_exhaustion.reason == "rate_limited":
        raise RuntimeError(
            "All available Gemini models are currently rate-limited. "
            "Please wait a minute and try again."
        ) from cause
    raise RuntimeError(
        f"Gemini request failed on every available model: {cause}"
    ) from cause


def call_llm_stream(
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int = 2048,
    temperature: float = 0.3,
    task_type: str = "qa",
) -> Iterator[str]:
    """Streaming variant with automatic fallback.

    The fallback is only attempted **before** any tokens have been streamed to
    the client. Once partial output has been emitted, switching models mid-
    stream would produce a confusing response, so a late failure is surfaced
    as an error to the caller.
    """
    client = _get_gemini_client()
    chain = _resolve_chain(task_type)
    max_attempts = max(1, int(LLM_RETRY_ATTEMPTS))
    last_exhaustion: Optional[_ModelExhausted] = None

    for idx, model in enumerate(chain):
        try:
            yield from _stream_single_model(
                client,
                model,
                system_prompt,
                user_prompt,
                max_output_tokens,
                temperature,
                task_type,
                max_attempts,
                fallback_used=idx > 0,
                previous_reason=(
                    last_exhaustion.reason if last_exhaustion else ""
                ),
            )
            return
        except _ModelExhausted as exc:
            last_exhaustion = exc
            if idx + 1 < len(chain):
                _logger.warning(
                    "Streaming model %s exhausted (%s); falling back to %s.",
                    model,
                    exc.reason,
                    chain[idx + 1],
                )
                continue
            break

    assert last_exhaustion is not None
    cause = last_exhaustion.cause
    if last_exhaustion.reason == "rate_limited":
        raise RuntimeError(
            "All available Gemini models are currently rate-limited. "
            "Please wait a minute and try again."
        ) from cause
    raise RuntimeError(
        f"Gemini streaming request failed on every available model: {cause}"
    ) from cause


def _stream_single_model(
    client: genai.Client,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int,
    temperature: float,
    task_type: str,
    max_attempts: int,
    *,
    fallback_used: bool,
    previous_reason: str,
) -> Iterator[str]:
    """Stream from one model with retries.

    Raises ``_ModelExhausted`` if the model can't serve the request AND no
    tokens have been streamed yet (so the caller can cleanly fall back).
    Any failure after partial output is raised as a ``RuntimeError``.
    """
    recorded_last_used = False

    for attempt in range(1, max_attempts + 1):
        accumulated_text = ""
        yielded_any = False

        try:
            _wait_for_request_slot()
            stream = client.models.generate_content_stream(
                model=model,
                contents=user_prompt,
                config=_build_generation_config(
                    system_prompt=system_prompt,
                    max_output_tokens=max_output_tokens,
                    temperature=temperature,
                    task_type=task_type,
                ),
            )

            for chunk in stream:
                text = _extract_response_text(chunk, strip=False)
                delta, accumulated_text = _stream_text_delta(text, accumulated_text)
                if not delta:
                    continue

                if not recorded_last_used:
                    record_last_used_model(
                        model,
                        fallback_used=fallback_used,
                        reason=previous_reason,
                    )
                    recorded_last_used = True

                yielded_any = True
                yield delta

            if yielded_any or accumulated_text:
                return

            raise RuntimeError(f"Gemini ({model}) returned no text response in stream.")
        except Exception as exc:
            is_retryable = _is_retryable_error(exc)
            is_rate_limited = _is_rate_limited_error(exc)

            if yielded_any:
                if is_rate_limited:
                    raise RuntimeError(
                        "Gemini API rate limit interrupted the stream. "
                        "Please wait a minute and try again."
                    ) from exc
                raise RuntimeError(f"Gemini streaming request failed: {exc}") from exc

            if not is_retryable or attempt >= max_attempts:
                if is_rate_limited or is_retryable:
                    reason = "rate_limited" if is_rate_limited else "transient_error"
                    raise _ModelExhausted(model, exc, reason) from exc
                raise RuntimeError(f"Gemini streaming request failed: {exc}") from exc

            delay = _retry_delay_seconds(attempt)
            _logger.warning(
                "Gemini streaming call to %s failed (attempt %s/%s): %s. Retrying in %.1fs.",
                model,
                attempt,
                max_attempts,
                exc,
                delay,
            )
            time.sleep(delay)

    raise _ModelExhausted(
        model,
        RuntimeError("Repeated transient errors"),
        "transient_error",
    )
