from fastapi import APIRouter, Form

from app.api.helpers import format_generation_error, load_lecture_metadata, mark_lecture_opened
from app.core.library_engine import build_due_groups, build_library_dashboard

router = APIRouter()


@router.get("/flashcards")
async def flashcards_view(lecture_id: str = ""):
    lecture_id = lecture_id.strip()

    if not lecture_id:
        dashboard = build_library_dashboard()
        return {
            "dashboard": dashboard,
            "due_groups": build_due_groups(dashboard),
            "lecture_id": "",
            "lecture_meta": {},
            "lecture_summary": {},
            "current_card": None,
            "queue_cards": [],
            "coaching": {},
        }

    lecture_meta = load_lecture_metadata(lecture_id)
    if not lecture_meta:
        return {"error": "Lecture not found. Process a lecture first."}

    try:
        from app.core.coaching_engine import build_coaching_payload
        from app.core.flashcard_engine import ensure_flashcard_deck
        from app.core.review_engine import build_lecture_review_summary, get_due_cards_for_lecture

        mark_lecture_opened(lecture_id)
        deck = ensure_flashcard_deck(lecture_id)
        lecture_summary = build_lecture_review_summary(lecture_id)
        queue_cards = get_due_cards_for_lecture(lecture_id)
        current_card = queue_cards[0] if queue_cards else None
        coaching = build_coaching_payload(lecture_id)
    except Exception as exc:
        return {"error": format_generation_error("Flashcard view", exc)}

    dashboard = build_library_dashboard()
    return {
        "dashboard": dashboard,
        "due_groups": build_due_groups(dashboard),
        "lecture_id": lecture_id,
        "lecture_meta": lecture_meta,
        "lecture_summary": {**lecture_summary, "card_count": deck.get("card_count", 0)},
        "current_card": current_card,
        "queue_cards": queue_cards[1:6] if current_card else [],
        "coaching": coaching,
    }


@router.post("/flashcards/review")
async def review_flashcard(
    lecture_id: str = Form(""),
    card_id: str = Form(""),
    rating: str = Form(""),
):
    lecture_id = lecture_id.strip()
    card_id = card_id.strip()
    rating = rating.strip().lower()

    if not lecture_id:
        return {"error": "Lecture ID is required."}
    if not card_id:
        return {"error": "Card ID is required."}

    try:
        from app.core.review_engine import apply_review_rating, get_due_cards_for_lecture

        apply_review_rating(lecture_id, card_id, rating)
        remaining = get_due_cards_for_lecture(lecture_id)
    except Exception as exc:
        return {"error": f"Flashcard review failed: {exc}"}

    return {
        "success": True,
        "remaining_count": len(remaining),
        "lecture_id": lecture_id,
        "completed": len(remaining) == 0,
    }


@router.post("/flashcards/regenerate")
async def regenerate_flashcards(lecture_id: str = Form("")):
    lecture_id = lecture_id.strip()
    if not lecture_id:
        return {"error": "Lecture ID is required."}

    try:
        from app.core.flashcard_engine import ensure_flashcard_deck

        deck = ensure_flashcard_deck(lecture_id, force=True)
    except Exception as exc:
        return {"error": format_generation_error("Flashcard generation", exc)}

    return {
        "success": True,
        "message": "Flashcards regenerated successfully.",
        "lecture_id": lecture_id,
        "card_count": deck.get("card_count", 0),
    }
