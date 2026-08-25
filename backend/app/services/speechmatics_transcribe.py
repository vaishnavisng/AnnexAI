import os
import ssl
from typing import Any, Dict, List

from speechmatics.batch_client import BatchClient
from speechmatics.models import ConnectionSettings

from app.config.settings import SPEECHMATICS_API_KEY, SPEECHMATICS_API_URL


def _is_ssl_verify_error(exc: Exception) -> bool:
    message = str(exc).lower()
    reason = getattr(exc, "reason", None)
    return "certificate verify failed" in message or "certificate verify failed" in str(reason).lower()


def _normalize_language(language: str | None) -> str:
    if not language:
        return "auto"
    cleaned = language.strip().lower()
    if not cleaned:
        return "auto"
    return cleaned.split("-", 1)[0].split("_", 1)[0]


def _extract_segments(payload: Dict[str, Any]) -> List[Dict]:
    out: List[Dict] = []
    for item in payload.get("results", []):
        if item.get("type") not in {"word", "entity"}:
            continue
        alternatives = item.get("alternatives") or []
        if not alternatives:
            continue
        text = str(alternatives[0].get("content") or "").strip()
        if not text:
            continue
        start = float(item.get("start_time", 0.0))
        end = float(item.get("end_time", start))
        out.append({"text": text, "start": start, "end": end})

    if not out:
        raise RuntimeError("Speechmatics returned no transcript segments.")
    return out


def _submit_batch_job(
    audio_path: str,
    api_key: str,
    language: str,
    verify_ssl: bool,
) -> Dict[str, Any]:
    ssl_context = ssl.create_default_context() if verify_ssl else ssl._create_unverified_context()
    settings = ConnectionSettings(
        url=SPEECHMATICS_API_URL,
        auth_token=api_key,
        ssl_context=ssl_context,
    )

    config = {
        "type": "transcription",
        "transcription_config": {
            "language": language,
            "operating_point": "enhanced",
        },
    }

    with BatchClient(settings) as client:
        job_id = client.submit_job(audio=audio_path, transcription_config=config)
        result = client.wait_for_completion(job_id, transcription_format="json-v2")

    if not isinstance(result, dict):
        raise RuntimeError("Speechmatics returned an unexpected transcript format.")
    return result


def transcribe_audio_speechmatics(audio_path: str, language: str | None = None) -> List[Dict]:
    api_key = os.getenv("SPEECHMATICS_API_KEY") or SPEECHMATICS_API_KEY
    if not api_key:
        raise RuntimeError("SPEECHMATICS_API_KEY is not set.")

    chosen_language = _normalize_language(language)

    try:
        payload = _submit_batch_job(
            audio_path=audio_path,
            api_key=api_key,
            language=chosen_language,
            verify_ssl=True,
        )
    except Exception as exc:
        if not _is_ssl_verify_error(exc):
            raise RuntimeError(f"Speechmatics transcription failed: {exc}") from exc

        payload = _submit_batch_job(
            audio_path=audio_path,
            api_key=api_key,
            language=chosen_language,
            verify_ssl=False,
        )

    return _extract_segments(payload)
