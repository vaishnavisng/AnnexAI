from typing import Dict, List, Tuple

import requests
import urllib3
from youtube_transcript_api import YouTubeTranscriptApi


def _is_ssl_verify_error(exc: Exception) -> bool:
    message = str(exc).lower()
    reason = getattr(exc, "reason", None)
    return "certificate verify failed" in message or "certificate verify failed" in str(reason).lower()


def _build_api(verify_ssl: bool) -> YouTubeTranscriptApi:
    if verify_ssl:
        return YouTubeTranscriptApi()

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session = requests.Session()
    session.verify = False
    return YouTubeTranscriptApi(http_client=session)


def _normalize_segments(raw_items: List[Dict]) -> List[Dict]:
    parsed: List[Dict] = []
    for item in raw_items:
        text = str(item.get("text") or "").replace("\n", " ").strip()
        if not text:
            continue
        start = float(item.get("start", 0.0))
        duration = float(item.get("duration", 0.0))
        parsed.append(
            {
                "text": text,
                "start": start,
                "duration": duration,
                "end": start + duration,
            }
        )
    return parsed


def _normalize_language_codes(language: str | None) -> List[str]:
    if not language:
        return []
    cleaned = language.strip().replace("_", "-")
    if not cleaned:
        return []

    out: List[str] = []
    seen: set[str] = set()

    def _append(code: str):
        if not code:
            return
        key = code.lower()
        if key in seen:
            return
        seen.add(key)
        out.append(code)

    _append(cleaned)
    _append(cleaned.lower())

    if "-" in cleaned:
        lang, region = cleaned.split("-", 1)
        _append(f"{lang.lower()}-{region.upper()}")

    base = cleaned.split("-", 1)[0]
    _append(base)
    _append(base.lower())
    return out


def _list_transcripts(api: YouTubeTranscriptApi, video_id: str):
    try:
        return api.list(video_id)
    except Exception as exc:
        if not _is_ssl_verify_error(exc):
            raise RuntimeError(f"Failed to list YouTube transcripts: {exc}") from exc

        fallback_api = _build_api(verify_ssl=False)
        try:
            return fallback_api.list(video_id)
        except Exception as retry_exc:
            raise RuntimeError(f"Failed to list YouTube transcripts: {retry_exc}") from retry_exc


def _pick_best_transcript(transcript_list, preferred_language: str | None):
    language_codes = _normalize_language_codes(preferred_language)
    if language_codes:
        try:
            return transcript_list.find_manually_created_transcript(language_codes)
        except Exception:
            pass
        try:
            return transcript_list.find_generated_transcript(language_codes)
        except Exception:
            pass

    fallback_choice = None
    for transcript in transcript_list:
        if not transcript.is_generated:
            return transcript
        if fallback_choice is None:
            fallback_choice = transcript
    return fallback_choice


def fetch_youtube_transcript(
    video_id: str,
    preferred_language: str | None = None,
) -> Tuple[List[Dict], str]:
    api = _build_api(verify_ssl=True)
    transcript_list = _list_transcripts(api, video_id)
    chosen = _pick_best_transcript(transcript_list, preferred_language)
    if chosen is None:
        raise RuntimeError("No YouTube transcripts available for this video.")

    try:
        fetched = chosen.fetch()
    except Exception as exc:
        if _is_ssl_verify_error(exc):
            fallback_api = _build_api(verify_ssl=False)
            fallback_list = _list_transcripts(fallback_api, video_id)
            fallback_choice = _pick_best_transcript(fallback_list, preferred_language)
            if fallback_choice is None:
                raise RuntimeError("No YouTube transcripts available for this video.") from exc
            chosen = fallback_choice
            try:
                fetched = chosen.fetch()
            except Exception as retry_exc:
                raise RuntimeError(f"Failed to fetch YouTube transcript: {retry_exc}") from retry_exc
        else:
            raise RuntimeError(f"Failed to fetch YouTube transcript: {exc}") from exc

    raw_data = fetched.to_raw_data()
    segments = _normalize_segments(raw_data)
    if not segments:
        raise RuntimeError("YouTube transcript was empty.")

    language_code = str(getattr(chosen, "language_code", "") or "").strip()
    return segments, language_code
