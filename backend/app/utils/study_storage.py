import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

from app.config.settings import (
    COACHING_DIR,
    FLASHCARD_DIR,
    LECTURE_META_DIR,
    QUIZ_ATTEMPT_DIR,
    QUIZ_DIR,
    REVIEW_DIR,
    SUMMARY_DIR,
)


def iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso_datetime(raw_value: str | None) -> datetime | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _read_json(path: str, default: Any):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def write_json_atomic(path: str, payload: Any) -> str:
    target_dir = os.path.dirname(path) or "."
    os.makedirs(target_dir, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".tmp_", dir=target_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    except Exception:
        # Only the failure path needs to clean up — successful os.replace
        # consumes the temp file, so a defensive unlink there would race
        # with another writer creating the same path.
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
    return path


def lecture_meta_path(lecture_id: str) -> str:
    return os.path.join(LECTURE_META_DIR, f"{lecture_id}.json")


def flashcard_deck_path(lecture_id: str) -> str:
    return os.path.join(FLASHCARD_DIR, f"{lecture_id}_deck.json")


def review_progress_path(lecture_id: str) -> str:
    return os.path.join(REVIEW_DIR, f"{lecture_id}_progress.json")


def quiz_attempts_path(lecture_id: str) -> str:
    return os.path.join(QUIZ_ATTEMPT_DIR, f"{lecture_id}.json")


def coaching_path(lecture_id: str) -> str:
    return os.path.join(COACHING_DIR, f"{lecture_id}.json")


def summary_cache_path(lecture_id: str) -> str:
    return os.path.join(SUMMARY_DIR, f"{lecture_id}_summary.json")


def notes_cache_path(lecture_id: str) -> str:
    return os.path.join(SUMMARY_DIR, f"{lecture_id}_notes.json")


def quiz_cache_path(lecture_id: str) -> str:
    return os.path.join(QUIZ_DIR, f"{lecture_id}_quiz.json")


_GENERIC_TITLE_PREFIXES = ("YouTube Lecture ", "Lecture from ")


def _looks_generic_title(value: str, lecture_id: str) -> bool:
    cleaned = (value or "").strip()
    if not cleaned:
        return True
    if cleaned == lecture_id:
        return True
    if cleaned.startswith(_GENERIC_TITLE_PREFIXES):
        return True
    return False


def _shorten_title(value: str, limit: int = 80) -> str:
    cleaned = " ".join((value or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _extract_youtube_video_id(source_label: str) -> str:
    parsed = urlparse(source_label)
    if not parsed.netloc or "youtu" not in parsed.netloc:
        return ""
    video_id = parse_qs(parsed.query).get("v", [""])[0].strip()
    if video_id:
        return video_id
    if parsed.path and parsed.path != "/":
        candidate = parsed.path.rsplit("/", 1)[-1].strip()
        if candidate and candidate.lower() != "watch":
            return candidate
    return ""


def _derive_lecture_title(payload: Dict[str, Any]) -> str:
    lecture_id = str(payload.get("lecture_id") or "Lecture").strip()
    existing_title = str(payload.get("title") or "").strip()
    if existing_title and not _looks_generic_title(existing_title, lecture_id):
        return _shorten_title(existing_title)

    source_type = str(payload.get("source_type") or "").strip().lower()
    source_label = str(payload.get("source_label") or "").strip()

    if source_type == "upload" and source_label:
        stem = Path(source_label).stem.replace("_", " ").replace("-", " ").strip()
        if stem:
            return _shorten_title(stem.title())
        return lecture_id

    if source_label:
        video_id = _extract_youtube_video_id(source_label)
        if video_id:
            return f"YouTube Lecture {video_id}"
        parsed = urlparse(source_label)
        if parsed.netloc:
            host = parsed.netloc.replace("www.", "")
            return f"Lecture from {host}"
        return _shorten_title(source_label)

    if existing_title:
        return _shorten_title(existing_title)

    return lecture_id


def _normalize_weak_concepts(raw_value: Any) -> List[Dict[str, Any]]:
    normalized = []
    for item in raw_value if isinstance(raw_value, list) else []:
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("concept") or "").strip()
            if not label:
                continue
            normalized.append(
                {
                    "label": label,
                    "mistakes": int(item.get("mistakes") or item.get("count") or 0),
                    "avg_score": round(float(item.get("avg_score") or 0.0), 2),
                }
            )
        else:
            label = str(item or "").strip()
            if label:
                normalized.append({"label": label, "mistakes": 0, "avg_score": 0.0})
    return normalized[:5]


def normalize_lecture_metadata(lecture_id: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    existing = _read_json(lecture_meta_path(lecture_id), {}) if payload is None else {}
    merged = dict(existing)
    if payload:
        merged.update(payload)

    created_at = str(merged.get("created_at") or existing.get("created_at") or iso_utc_now())
    last_opened_at = str(merged.get("last_opened_at") or existing.get("last_opened_at") or created_at)

    normalized = {
        "lecture_id": lecture_id,
        "title": _derive_lecture_title({**merged, "lecture_id": lecture_id}),
        "source_type": str(merged.get("source_type") or "").strip(),
        "source_label": str(merged.get("source_label") or "").strip(),
        "source_url": str(merged.get("source_url") or "").strip(),
        "transcript_source": str(merged.get("transcript_source") or "").strip(),
        "detected_language": str(merged.get("detected_language") or "").strip(),
        "ocr_segment_count": int(merged.get("ocr_segment_count") or 0),
        "ocr_error": str(merged.get("ocr_error") or "").strip(),
        "chunk_count": int(merged.get("chunk_count") or 0),
        "created_at": created_at,
        "last_opened_at": last_opened_at,
        "updated_at": str(merged.get("updated_at") or iso_utc_now()),
        "has_summary": bool(merged.get("has_summary", False)),
        "has_notes": bool(merged.get("has_notes", False)),
        "has_quiz": bool(merged.get("has_quiz", False)),
        "has_flashcards": bool(merged.get("has_flashcards", False)),
        "due_today_count": int(merged.get("due_today_count") or 0),
        "overdue_count": int(merged.get("overdue_count") or 0),
        "last_quiz_score": merged.get("last_quiz_score"),
        "weak_concepts": _normalize_weak_concepts(merged.get("weak_concepts", [])),
    }

    for key, value in merged.items():
        if key not in normalized:
            normalized[key] = value

    return normalized


def load_lecture_metadata(lecture_id: str) -> Dict[str, Any]:
    if not lecture_id:
        return {}
    raw = _read_json(lecture_meta_path(lecture_id), {})
    if not raw:
        return {}
    return normalize_lecture_metadata(lecture_id, raw)


def save_lecture_metadata(lecture_id: str, payload: Dict[str, Any]) -> str:
    existing = _read_json(lecture_meta_path(lecture_id), {})
    merged = dict(existing)
    merged.update(payload or {})
    merged["lecture_id"] = lecture_id
    merged["updated_at"] = iso_utc_now()
    if not merged.get("created_at"):
        merged["created_at"] = iso_utc_now()
    if not merged.get("last_opened_at"):
        merged["last_opened_at"] = merged["created_at"]

    normalized = normalize_lecture_metadata(lecture_id, merged)
    return write_json_atomic(lecture_meta_path(lecture_id), normalized)


def update_lecture_metadata(lecture_id: str, **updates: Any) -> Dict[str, Any]:
    existing = load_lecture_metadata(lecture_id)
    merged = dict(existing)
    merged.update(updates)
    save_lecture_metadata(lecture_id, merged)
    return load_lecture_metadata(lecture_id)


def touch_lecture(lecture_id: str) -> Dict[str, Any]:
    if not lecture_id:
        return {}
    return update_lecture_metadata(lecture_id, last_opened_at=iso_utc_now())


def list_lecture_metadata() -> List[Dict[str, Any]]:
    items = []
    for path in Path(LECTURE_META_DIR).glob("*.json"):
        payload = _read_json(str(path), {})
        lecture_id = str(payload.get("lecture_id") or path.stem).strip()
        if not lecture_id:
            continue
        items.append(normalize_lecture_metadata(lecture_id, payload))
    return items


def load_flashcard_deck(lecture_id: str) -> Dict[str, Any]:
    return _read_json(flashcard_deck_path(lecture_id), {})


def save_flashcard_deck(lecture_id: str, payload: Dict[str, Any]) -> str:
    return write_json_atomic(flashcard_deck_path(lecture_id), payload)


def load_review_progress(lecture_id: str) -> Dict[str, Any]:
    return _read_json(review_progress_path(lecture_id), {})


def save_review_progress(lecture_id: str, payload: Dict[str, Any]) -> str:
    return write_json_atomic(review_progress_path(lecture_id), payload)


def load_quiz_attempts(lecture_id: str) -> Dict[str, Any]:
    return _read_json(quiz_attempts_path(lecture_id), {"lecture_id": lecture_id, "attempts": []})


def save_quiz_attempts(lecture_id: str, payload: Dict[str, Any]) -> str:
    return write_json_atomic(quiz_attempts_path(lecture_id), payload)


def load_coaching_payload(lecture_id: str) -> Dict[str, Any]:
    return _read_json(coaching_path(lecture_id), {})


def save_coaching_payload(lecture_id: str, payload: Dict[str, Any]) -> str:
    return write_json_atomic(coaching_path(lecture_id), payload)
