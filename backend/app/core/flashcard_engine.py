import hashlib
import json
import logging
import re
from typing import Any, Dict, List

from app.config.settings import FLASHCARD_NUM_CARDS
from app.core.review_engine import sync_review_progress
from app.core.study_utils import clip_text, derive_concept_label, find_matching_segments, normalize_whitespace
from app.utils.study_storage import (
    iso_utc_now,
    load_flashcard_deck,
    load_lecture_metadata,
    notes_cache_path,
    save_flashcard_deck,
    summary_cache_path,
    update_lecture_metadata,
)

FLASHCARD_CACHE_VERSION = 1
logger = logging.getLogger(__name__)


def _read_cached_markdown(path: str, key: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return ""
    value = payload.get(key, "") if isinstance(payload, dict) else ""
    return normalize_whitespace(str(value or ""))


def _extract_json_payload(raw_text: str) -> Dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        raise ValueError("Model returned an empty flashcard response.")

    decoder = json.JSONDecoder()
    candidates = [text]
    fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
    candidates.extend(block.strip() for block in fenced_blocks if block.strip())

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list):
            return {"cards": payload}
        if isinstance(payload, dict):
            if isinstance(payload.get("cards"), list):
                return payload
            for value in payload.values():
                if isinstance(value, list):
                    return {"cards": value}

    for index, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, list):
            return {"cards": payload}
        if isinstance(payload, dict):
            return payload

    raise ValueError("Flashcard generator did not return valid JSON.")


def _build_source_text(lecture_id: str, chunks: List[Dict[str, Any]]) -> str:
    summary_text = _read_cached_markdown(summary_cache_path(lecture_id), "summary")
    notes_text = _read_cached_markdown(notes_cache_path(lecture_id), "notes")
    chunk_lines = []
    for index, chunk in enumerate(chunks[:50], start=1):
        text = normalize_whitespace(chunk.get("text", ""))
        if text:
            chunk_lines.append(f"[{index}] {text}")

    parts = []
    if summary_text:
        parts.append("Summary:\n" + summary_text[:2200])
    if notes_text:
        parts.append("Notes:\n" + notes_text[:2600])
    parts.append("Transcript chunks:\n" + "\n".join(chunk_lines))
    return "\n\n".join(part for part in parts if part)


def _stable_card_id(lecture_id: str, concept: str, front: str, source_segments: List[Dict[str, Any]]) -> str:
    source_hint = ""
    if source_segments:
        first = source_segments[0]
        source_hint = f"{float(first.get('start', 0.0)):.1f}:{float(first.get('end', 0.0)):.1f}"
    seed = "|".join(
        [
            lecture_id,
            normalize_whitespace(concept).lower(),
            normalize_whitespace(front).lower(),
            source_hint,
        ]
    )
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def _sanitize_source_segments(segments: Any, chunks: List[Dict[str, Any]], query_text: str) -> List[Dict[str, Any]]:
    normalized = []
    if isinstance(segments, list):
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            text = normalize_whitespace(segment.get("text", ""))
            normalized.append(
                {
                    "start": float(segment.get("start", 0.0)),
                    "end": float(segment.get("end", segment.get("start", 0.0))),
                    "text": clip_text(text, 180),
                }
            )
    if not normalized:
        normalized = find_matching_segments(chunks, query_text, limit=2)
    return normalized[:2]


def _normalize_cards(raw_cards: List[Dict[str, Any]], lecture_id: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cards = []
    seen = set()
    for raw_card in raw_cards:
        if not isinstance(raw_card, dict):
            continue
        front = normalize_whitespace(raw_card.get("front", ""))
        back = normalize_whitespace(raw_card.get("back", ""))
        hint = clip_text(raw_card.get("hint", ""), 120)
        concept = derive_concept_label(raw_card.get("concept", ""), front, back)
        if not front or not back:
            continue

        source_segments = _sanitize_source_segments(
            raw_card.get("source_segments", []),
            chunks,
            " ".join([concept, front, back]),
        )
        card_id = _stable_card_id(lecture_id, concept, front, source_segments)
        dedupe_key = (front.casefold(), concept.casefold())
        if card_id in seen or dedupe_key in seen:
            continue

        seen.add(card_id)
        seen.add(dedupe_key)
        cards.append(
            {
                "card_id": card_id,
                "lecture_id": lecture_id,
                "front": front,
                "back": back,
                "hint": hint,
                "concept": concept,
                "source_segments": source_segments,
            }
        )
        if len(cards) >= max(1, int(FLASHCARD_NUM_CARDS)):
            break
    return cards


def _heuristic_cards(chunks: List[Dict[str, Any]], lecture_id: str) -> List[Dict[str, Any]]:
    raw_cards = []
    for chunk in chunks:
        text = normalize_whitespace(chunk.get("text", ""))
        if len(text) < 30:
            continue
        source_segments = [
            {
                "start": float(chunk.get("start", 0.0)),
                "end": float(chunk.get("end", chunk.get("start", 0.0))),
                "text": clip_text(text, 180),
            }
        ]
        lower_text = text.lower()
        front = ""
        back = ""
        concept = derive_concept_label(text)
        if " is " in lower_text:
            left, right = text.split(" is ", 1)
            concept = derive_concept_label(left)
            front = f"What is {concept}?"
            back = right.strip().rstrip(".") + "."
        elif " are " in lower_text:
            left, right = text.split(" are ", 1)
            concept = derive_concept_label(left)
            front = f"What are {concept}?"
            back = right.strip().rstrip(".") + "."
        elif ":" in text:
            left, right = text.split(":", 1)
            concept = derive_concept_label(left)
            front = f"What should you remember about {concept}?"
            back = right.strip().rstrip(".") + "."
        else:
            front = f"What is the key idea behind {concept}?"
            back = clip_text(text, 180)

        raw_cards.append(
            {
                "front": front,
                "back": back,
                "hint": f"Think about the lecture explanation of {concept.lower()}.",
                "concept": concept,
                "source_segments": source_segments,
            }
        )
        if len(raw_cards) >= max(1, int(FLASHCARD_NUM_CARDS)) * 2:
            break

    return _normalize_cards(raw_cards, lecture_id, chunks)


def _generate_cards_with_llm(lecture_id: str, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from app.services.llm_client import call_llm

    lecture_meta = load_lecture_metadata(lecture_id)
    lecture_title = lecture_meta.get("title") or lecture_id
    system_prompt = (
        "You create concise, exam-ready flashcards for university lectures. "
        "Each card should test one clear idea and help with active recall."
    )
    user_prompt = (
        f"Create exactly {int(FLASHCARD_NUM_CARDS)} flashcards for this lecture.\n"
        "Return strict JSON only with this shape:\n"
        '{"cards":[{"front":"...","back":"...","hint":"...","concept":"..."}]}\n'
        "Rules:\n"
        "- Keep `front` short and question-style.\n"
        "- Keep `back` precise and under 60 words.\n"
        "- Keep `hint` under 18 words.\n"
        "- Use `concept` as a compact topic label.\n"
        "- Avoid duplicates, fluff, and generic cards.\n"
        "- Prefer definitions, mechanisms, distinctions, formulas, and cause-effect logic.\n\n"
        f"Lecture title: {lecture_title}\n\n"
        f"Source material:\n{_build_source_text(lecture_id, chunks)}"
    )
    raw_text = call_llm(
        system_prompt,
        user_prompt,
        max_output_tokens=4096,
        temperature=0.2,
        task_type="notes",
    )
    payload = _extract_json_payload(raw_text)
    cards = payload.get("cards", []) if isinstance(payload, dict) else []
    if not isinstance(cards, list) or not cards:
        raise ValueError("Flashcard generator returned no cards.")
    return _normalize_cards(cards, lecture_id, chunks)


def ensure_flashcard_deck(lecture_id: str, force: bool = False) -> Dict[str, Any]:
    cached = load_flashcard_deck(lecture_id)
    if cached and int(cached.get("version", 0)) == FLASHCARD_CACHE_VERSION and not force:
        cards = cached.get("cards", []) if isinstance(cached.get("cards"), list) else []
        sync_review_progress(lecture_id, cards)
        return cached

    from app.api.helpers import load_chunks

    chunks = load_chunks(lecture_id)
    try:
        cards = _generate_cards_with_llm(lecture_id, chunks)
    except Exception as exc:
        logger.warning("Falling back to heuristic flashcards for %s: %s", lecture_id, exc)
        cards = _heuristic_cards(chunks, lecture_id)

    if not cards:
        raise RuntimeError("Could not generate any flashcards for this lecture.")

    deck = {
        "lecture_id": lecture_id,
        "version": FLASHCARD_CACHE_VERSION,
        "generated_at": iso_utc_now(),
        "card_count": len(cards),
        "cards": cards,
    }
    save_flashcard_deck(lecture_id, deck)
    sync_review_progress(lecture_id, cards)
    update_lecture_metadata(lecture_id, has_flashcards=True)
    return deck
