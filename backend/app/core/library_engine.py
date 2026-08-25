from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from app.core.review_engine import build_lecture_review_summary
from app.utils.study_storage import (
    flashcard_deck_path,
    list_lecture_metadata,
    notes_cache_path,
    parse_iso_datetime,
    quiz_cache_path,
    summary_cache_path,
    update_lecture_metadata,
)


_GENERIC_TITLE_PREFIXES = ("YouTube Lecture ", "Lecture from ")


def _sort_timestamp(raw_value: str | None) -> float:
    parsed = parse_iso_datetime(raw_value)
    if parsed is None:
        return 0.0
    return parsed.timestamp()


import os


_DERIVED_METADATA_KEYS = (
    "has_summary",
    "has_notes",
    "has_quiz",
    "has_flashcards",
    "due_today_count",
    "overdue_count",
)


def _lecture_asset_flags(lecture_id: str) -> Dict[str, bool]:
    return {
        "has_summary": os.path.exists(summary_cache_path(lecture_id)),
        "has_notes": os.path.exists(notes_cache_path(lecture_id)),
        "has_quiz": os.path.exists(quiz_cache_path(lecture_id)),
        "has_flashcards": os.path.exists(flashcard_deck_path(lecture_id)),
    }


def _is_generic_title(title: str, lecture_id: str) -> bool:
    cleaned = (title or "").strip()
    if not cleaned:
        return True
    if cleaned == lecture_id:
        return True
    if cleaned.startswith(_GENERIC_TITLE_PREFIXES):
        return True
    return False


def _refresh_generic_youtube_titles(metas: List[Dict[str, Any]]) -> Dict[str, str]:
    """Fetch real YouTube titles for any lectures whose stored title is still generic.

    Runs concurrently and persists the new title to disk via update_lecture_metadata,
    so the work happens at most once per lecture.
    """
    pending: List[Dict[str, Any]] = []
    for meta in metas:
        lecture_id = str(meta.get("lecture_id") or "").strip()
        if not lecture_id:
            continue
        source_url = str(meta.get("source_url") or "").strip()
        source_type = str(meta.get("source_type") or "").lower()
        if not source_url or "youtu" not in source_url.lower():
            continue
        if source_type and source_type == "upload":
            continue
        if not _is_generic_title(str(meta.get("title") or ""), lecture_id):
            continue
        pending.append({"lecture_id": lecture_id, "url": source_url})

    if not pending:
        return {}

    try:
        from app.utils.media_utils import get_youtube_video_title
    except Exception:
        return {}

    refreshed: Dict[str, str] = {}
    max_workers = min(4, len(pending))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(get_youtube_video_title, item["url"]): item["lecture_id"]
            for item in pending
        }
        for future in as_completed(future_map):
            lecture_id = future_map[future]
            try:
                title = future.result()
            except Exception:
                title = ""
            cleaned = (title or "").strip()
            if cleaned and not _is_generic_title(cleaned, lecture_id):
                refreshed[lecture_id] = cleaned

    for lecture_id, title in refreshed.items():
        try:
            update_lecture_metadata(lecture_id, title=title)
        except Exception:
            pass

    return refreshed


def build_library_dashboard() -> Dict[str, Any]:
    lectures = []
    total_due_today = 0
    total_overdue = 0
    lectures_in_rotation = 0

    raw_metas = list_lecture_metadata()
    refreshed_titles = _refresh_generic_youtube_titles(raw_metas)

    for lecture_meta in raw_metas:
        if refreshed_titles:
            lid = str(lecture_meta.get("lecture_id") or "")
            if lid in refreshed_titles:
                lecture_meta = {**lecture_meta, "title": refreshed_titles[lid]}
        lecture_id = str(lecture_meta.get("lecture_id") or "").strip()
        if not lecture_id:
            continue

        assets = _lecture_asset_flags(lecture_id)
        review = build_lecture_review_summary(lecture_id)
        lecture = {
            **lecture_meta,
            **assets,
            **review,
            "weak_concepts": lecture_meta.get("weak_concepts", []),
        }
        lecture["review_total"] = lecture["due_today_count"] + lecture["overdue_count"]
        if lecture["review_total"] > 0:
            lectures_in_rotation += 1

        total_due_today += lecture["due_today_count"]
        total_overdue += lecture["overdue_count"]

        # Only persist when a derived field actually changed; otherwise we
        # would trigger a needless atomic JSON write on every dashboard load.
        derived_updates = {key: lecture[key] for key in _DERIVED_METADATA_KEYS}
        if any(lecture_meta.get(key) != value for key, value in derived_updates.items()):
            update_lecture_metadata(lecture_id, **derived_updates)
        lectures.append(lecture)

    lectures.sort(
        key=lambda item: (
            -int(item.get("overdue_count") or 0),
            -int(item.get("due_today_count") or 0),
            -_sort_timestamp(item.get("last_opened_at")),
            str(item.get("title") or item.get("lecture_id") or "").lower(),
        )
    )

    weak_lectures = [lecture for lecture in lectures if lecture.get("weak_concepts")]
    study_next = weak_lectures[:3] if weak_lectures else lectures[:3]

    return {
        "stats": {
            "due_today": total_due_today,
            "overdue": total_overdue,
            "lectures_in_rotation": lectures_in_rotation,
            "lecture_count": len(lectures),
        },
        "lectures": lectures,
        "study_next": study_next,
        "has_due_cards": any((lecture.get("review_total") or 0) > 0 for lecture in lectures),
    }


def build_due_groups(dashboard: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    if dashboard is None:
        dashboard = build_library_dashboard()
    due_groups = [lecture for lecture in dashboard["lectures"] if (lecture.get("review_total") or 0) > 0]
    due_groups.sort(
        key=lambda item: (
            -int(item.get("overdue_count") or 0),
            -int(item.get("due_today_count") or 0),
            -_sort_timestamp(item.get("last_opened_at")),
        )
    )
    return due_groups
