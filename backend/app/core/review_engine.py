from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from app.utils.study_storage import (
    iso_utc_now,
    load_flashcard_deck,
    load_review_progress,
    parse_iso_datetime,
    save_review_progress,
    update_lecture_metadata,
)


_DEFAULT_EASE = 2.5
_MIN_EASE = 1.3


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_from_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalize_review_entry(card_id: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload = dict(payload or {})
    due_at = str(payload.get("due_at") or iso_utc_now())
    repetitions = max(0, int(payload.get("repetitions") or 0))
    lapses = max(0, int(payload.get("lapses") or 0))
    interval_days = max(0.0, float(payload.get("interval_days") or 0.0))
    ease_factor = max(_MIN_EASE, float(payload.get("ease_factor") or _DEFAULT_EASE))
    return {
        "card_id": card_id,
        "due_at": due_at,
        "interval_days": round(interval_days, 2),
        "ease_factor": round(ease_factor, 2),
        "repetitions": repetitions,
        "lapses": lapses,
        "last_rating": str(payload.get("last_rating") or "").strip(),
        "last_reviewed_at": str(payload.get("last_reviewed_at") or "").strip(),
    }


def _classify_due_state(due_at: str, reference_time: datetime | None = None) -> str:
    now = reference_time or _utc_now()
    due_dt = parse_iso_datetime(due_at) or now
    if due_dt.date() < now.date():
        return "overdue"
    if due_dt <= now:
        return "due_today"
    return "upcoming"


def sync_review_progress(lecture_id: str, cards: List[Dict[str, Any]]) -> Dict[str, Any]:
    existing = load_review_progress(lecture_id)
    existing_cards = existing.get("cards") if isinstance(existing, dict) else {}
    if not isinstance(existing_cards, dict):
        existing_cards = {}

    next_cards = {}
    for card in cards:
        card_id = str(card.get("card_id") or "").strip()
        if not card_id:
            continue
        next_cards[card_id] = _normalize_review_entry(card_id, existing_cards.get(card_id, {}))

    payload = {
        "lecture_id": lecture_id,
        "updated_at": iso_utc_now(),
        "cards": next_cards,
    }
    save_review_progress(lecture_id, payload)
    refresh_lecture_review_metrics(lecture_id)
    return payload


def get_cards_for_lecture(lecture_id: str) -> List[Dict[str, Any]]:
    deck = load_flashcard_deck(lecture_id)
    cards = deck.get("cards") if isinstance(deck, dict) else []
    if not isinstance(cards, list):
        return []

    progress = load_review_progress(lecture_id)
    progress_cards = progress.get("cards") if isinstance(progress, dict) else {}
    if not isinstance(progress_cards, dict):
        progress_cards = {}

    now = _utc_now()
    merged = []
    for card in cards:
        card_id = str(card.get("card_id") or "").strip()
        if not card_id:
            continue
        review_state = _normalize_review_entry(card_id, progress_cards.get(card_id, {}))
        due_state = _classify_due_state(review_state.get("due_at", ""), now)
        merged.append({**card, "review": review_state, "due_state": due_state})

    merged.sort(
        key=lambda item: (
            0 if item["due_state"] == "overdue" else 1 if item["due_state"] == "due_today" else 2,
            parse_iso_datetime(item["review"].get("due_at")) or now,
            str(item.get("concept") or ""),
        )
    )
    return merged


def get_due_cards_for_lecture(lecture_id: str) -> List[Dict[str, Any]]:
    return [card for card in get_cards_for_lecture(lecture_id) if card.get("due_state") in {"overdue", "due_today"}]


def build_lecture_review_summary(lecture_id: str) -> Dict[str, Any]:
    cards = get_cards_for_lecture(lecture_id)
    due_cards = [card for card in cards if card.get("due_state") == "due_today"]
    overdue_cards = [card for card in cards if card.get("due_state") == "overdue"]
    upcoming_cards = [card for card in cards if card.get("due_state") == "upcoming"]
    return {
        "lecture_id": lecture_id,
        "total_cards": len(cards),
        "due_today_count": len(due_cards),
        "overdue_count": len(overdue_cards),
        "upcoming_count": len(upcoming_cards),
        "completed_for_now": len(cards) > 0 and not due_cards and not overdue_cards,
    }


def refresh_lecture_review_metrics(lecture_id: str) -> Dict[str, Any]:
    summary = build_lecture_review_summary(lecture_id)
    return update_lecture_metadata(
        lecture_id,
        due_today_count=summary["due_today_count"],
        overdue_count=summary["overdue_count"],
        has_flashcards=summary["total_cards"] > 0,
    )


def apply_review_rating(lecture_id: str, card_id: str, rating: str) -> Dict[str, Any]:
    normalized_rating = str(rating or "").strip().lower()
    if normalized_rating not in {"again", "hard", "good", "easy"}:
        raise ValueError("Invalid flashcard rating.")

    progress = load_review_progress(lecture_id)
    cards = progress.get("cards") if isinstance(progress, dict) else {}
    if not isinstance(cards, dict) or card_id not in cards:
        raise KeyError("Flashcard progress is missing for this card.")

    current = _normalize_review_entry(card_id, cards.get(card_id, {}))
    now = _utc_now()
    repetitions = int(current.get("repetitions") or 0)
    lapses = int(current.get("lapses") or 0)
    ease_factor = float(current.get("ease_factor") or _DEFAULT_EASE)
    interval_days = float(current.get("interval_days") or 0.0)

    if normalized_rating == "again":
        repetitions = 0
        lapses += 1
        interval_days = 1.0
        ease_factor = max(_MIN_EASE, ease_factor - 0.2)
        due_at = now + timedelta(hours=12)
    else:
        repetitions += 1
        if normalized_rating == "hard":
            ease_factor = max(_MIN_EASE, ease_factor - 0.15)
            interval_days = 2.0 if interval_days < 1.0 else max(2.0, interval_days * 1.2)
        elif normalized_rating == "good":
            interval_days = 3.0 if interval_days < 1.0 else max(3.0, interval_days * ease_factor)
        else:
            ease_factor = max(_MIN_EASE, ease_factor + 0.15)
            interval_days = 5.0 if interval_days < 1.0 else max(5.0, interval_days * (ease_factor + 0.25))
        due_at = now + timedelta(days=max(1.0, interval_days))

    next_state = _normalize_review_entry(
        card_id,
        {
            **current,
            "due_at": _iso_from_datetime(due_at),
            "interval_days": interval_days,
            "ease_factor": ease_factor,
            "repetitions": repetitions,
            "lapses": lapses,
            "last_rating": normalized_rating,
            "last_reviewed_at": _iso_from_datetime(now),
        },
    )
    cards[card_id] = next_state
    payload = {
        "lecture_id": lecture_id,
        "updated_at": _iso_from_datetime(now),
        "cards": cards,
    }
    save_review_progress(lecture_id, payload)
    refresh_lecture_review_metrics(lecture_id)
    return next_state
