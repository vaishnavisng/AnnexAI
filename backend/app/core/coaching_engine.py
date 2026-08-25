from collections import defaultdict
from typing import Any, Dict, List
from uuid import uuid4

from app.core.review_engine import build_lecture_review_summary
from app.core.study_utils import derive_concept_label, find_matching_segments
from app.utils.study_storage import (
    iso_utc_now,
    load_coaching_payload,
    load_quiz_attempts,
    save_coaching_payload,
    save_quiz_attempts,
    update_lecture_metadata,
)


def _sanitize_result_entry(result: Dict[str, Any]) -> Dict[str, Any]:
    score = max(0.0, min(1.0, float(result.get("score") or 0.0)))
    return {
        "question": str(result.get("question") or "").strip(),
        "type": str(result.get("type") or "").strip(),
        "user_answer": str(result.get("user_answer") or "").strip(),
        "correct": str(result.get("correct") or "").strip(),
        "assessment": str(result.get("assessment") or "").strip(),
        "feedback": str(result.get("feedback") or "").strip(),
        "explanation": str(result.get("explanation") or "").strip(),
        "score": round(score, 2),
    }


def _weak_concepts_from_attempts(attempts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    buckets = defaultdict(lambda: {"mistakes": 0, "score_total": 0.0, "questions": []})
    for attempt in attempts[-3:]:
        for result in attempt.get("results", []):
            score = float(result.get("score") or 0.0)
            if score >= 0.99:
                continue

            label = derive_concept_label(
                result.get("explanation", ""),
                result.get("correct", ""),
                result.get("question", ""),
            )
            bucket = buckets[label]
            bucket["mistakes"] = int(bucket.get("mistakes", 0)) + 1
            bucket["score_total"] = float(bucket.get("score_total", 0.0)) + score
            questions = bucket.get("questions", [])
            if not isinstance(questions, list):
                questions = []
            questions.append(result)
            bucket["questions"] = questions

    weak_concepts = []
    for label, bucket in buckets.items():
        mistakes = int(bucket["mistakes"])
        avg_score = 0.0 if mistakes == 0 else round(bucket["score_total"] / mistakes, 2)
        weak_concepts.append(
            {
                "label": label,
                "mistakes": mistakes,
                "avg_score": avg_score,
                "questions": bucket["questions"],
            }
        )

    weak_concepts.sort(key=lambda item: (-item["mistakes"], item["avg_score"], item["label"].lower()))
    return weak_concepts[:5]


def _load_chunks_safe(lecture_id: str) -> List[Dict[str, Any]]:
    try:
        from app.api.helpers import load_chunks

        return load_chunks(lecture_id)
    except Exception:
        return []


def build_coaching_payload(lecture_id: str) -> Dict[str, Any]:
    attempts_payload = load_quiz_attempts(lecture_id)
    attempts = attempts_payload.get("attempts", []) if isinstance(attempts_payload, dict) else []
    if not attempts:
        return load_coaching_payload(lecture_id) or {}

    chunks = _load_chunks_safe(lecture_id)
    review_summary = build_lecture_review_summary(lecture_id)
    weak_concepts = _weak_concepts_from_attempts(attempts)
    latest_attempt = attempts[-1]

    recommendations = []
    for concept in weak_concepts[:3]:
        concept_label = concept["label"]
        segments = find_matching_segments(chunks, concept_label, limit=2)
        actions = [
            f"Review your notes for {concept_label}.",
            f"Answer a fresh quiz question on {concept_label}.",
        ]
        if review_summary.get("due_today_count") or review_summary.get("overdue_count"):
            actions.append(f"Revisit flashcards tied to {concept_label}.")
        if segments:
            actions.insert(0, f"Rewatch the highlighted lecture segment for {concept_label}.")

        recommendations.append(
            {
                "concept": concept_label,
                "mistakes": concept["mistakes"],
                "avg_score": concept["avg_score"],
                "segments": segments,
                "actions": actions[:3],
                "sample_questions": [entry.get("question", "") for entry in concept.get("questions", [])[:2]],
            }
        )

    payload = {
        "lecture_id": lecture_id,
        "updated_at": iso_utc_now(),
        "last_quiz_score": latest_attempt.get("total_score"),
        "weak_concepts": [
            {
                "label": item["label"],
                "mistakes": item["mistakes"],
                "avg_score": item["avg_score"],
            }
            for item in weak_concepts
        ],
        "recommendations": recommendations,
        "review_summary": review_summary,
        "attempt_count": len(attempts),
    }
    save_coaching_payload(lecture_id, payload)
    update_lecture_metadata(
        lecture_id,
        last_quiz_score=payload.get("last_quiz_score"),
        weak_concepts=payload.get("weak_concepts", []),
    )
    return payload


def record_quiz_attempt(lecture_id: str, results: List[Dict[str, Any]], total_score: float) -> Dict[str, Any]:
    payload = load_quiz_attempts(lecture_id)
    attempts = payload.get("attempts") if isinstance(payload, dict) else []
    if not isinstance(attempts, list):
        attempts = []

    sanitized_results = [_sanitize_result_entry(result) for result in results]
    attempt = {
        "attempt_id": uuid4().hex[:12],
        "created_at": iso_utc_now(),
        "total_score": round(float(total_score or 0.0), 2),
        "question_count": len(sanitized_results),
        "results": sanitized_results,
    }
    attempts.append(attempt)
    attempts = attempts[-12:]
    next_payload = {"lecture_id": lecture_id, "attempts": attempts}
    save_quiz_attempts(lecture_id, next_payload)
    coaching = build_coaching_payload(lecture_id)
    attempt["coaching"] = coaching
    return attempt
