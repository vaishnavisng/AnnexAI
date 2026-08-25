import json
import logging
import os
import re
from typing import Callable, Dict, List

from app.config.settings import QUIZ_DIR, QUIZ_NUM_QUESTIONS
from app.services.llm_client import call_llm

QUIZ_CACHE_VERSION = 2
logger = logging.getLogger(__name__)

_QUESTION_KEY_CANDIDATES = (
    "questions",
    "quiz",
    "quiz_questions",
    "question_list",
    "question_set",
    "items",
    "quiz_items",
    "data",
)


def _chunks_to_text(chunks: List[Dict], limit: int = 70) -> str:
    clipped = chunks[:limit]
    lines = []
    for chunk in clipped:
        text = str(chunk.get("text", "")).strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def _describe_response_structure(raw_text: str) -> str:
    text = (raw_text or "").strip()
    if not text:
        return "empty response"

    try:
        payload = json.loads(text)
    except Exception:
        preview = text[:220].replace("\n", "\\n")
        suffix = "..." if len(text) > 220 else ""
        return f"non-json text len={len(text)} preview={preview!r}{suffix}"

    if isinstance(payload, dict):
        key_types = []
        for idx, (key, value) in enumerate(payload.items()):
            if idx >= 10:
                break
            key_types.append(f"{key}:{type(value).__name__}")
        return f"dict keys={len(payload)} sample={', '.join(key_types)}"

    if isinstance(payload, list):
        first_type = type(payload[0]).__name__ if payload else "empty"
        return f"list len={len(payload)} first_item={first_type}"

    return f"{type(payload).__name__}"


def _extract_json_block(text: str) -> Dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Model returned an empty response.")

    decoder = json.JSONDecoder()
    candidates = [text]
    fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)\s*```", text, flags=re.IGNORECASE)
    candidates.extend(block.strip() for block in fenced_blocks if block.strip())

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        return _normalize_json_payload(payload)

    for idx, char in enumerate(text):
        if char not in "[{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[idx:])
        except json.JSONDecodeError:
            continue
        return _normalize_json_payload(payload)

    raise ValueError("No valid JSON object found in model response.")


def _normalize_json_payload(payload) -> Dict:
    if isinstance(payload, list):
        return {"questions": payload}

    if isinstance(payload, dict):
        normalized = dict(payload)

        lowered_key_map = {str(key).strip().lower(): key for key in payload.keys()}
        for candidate_key in _QUESTION_KEY_CANDIDATES:
            matched_key = lowered_key_map.get(candidate_key)
            if matched_key is None:
                continue
            candidate_value = payload.get(matched_key)
            if isinstance(candidate_value, list):
                normalized["questions"] = candidate_value
                return normalized
            if isinstance(candidate_value, dict):
                nested = _normalize_json_payload(candidate_value)
                nested_questions = nested.get("questions")
                if isinstance(nested_questions, list):
                    normalized["questions"] = nested_questions
                    return normalized

        for key, value in payload.items():
            lowered_key = str(key).strip().lower()
            if "question" in lowered_key and isinstance(value, list):
                normalized["questions"] = value
                return normalized

        if len(payload) == 1:
            only_value = next(iter(payload.values()))
            if isinstance(only_value, list):
                normalized["questions"] = only_value
                return normalized

        for value in payload.values():
            if not isinstance(value, dict):
                continue
            nested = _normalize_json_payload(value)
            nested_questions = nested.get("questions")
            if isinstance(nested_questions, list):
                normalized["questions"] = nested_questions
                return normalized

        return normalized

    raise ValueError("Parsed JSON did not contain an object or array.")


def _call_json_payload(
    system_prompt: str,
    user_prompt: str,
    *,
    max_output_tokens: int,
    temperature: float,
    task_type: str,
    attempts: int = 3,
    validator: Callable[[Dict], None] | None = None,
) -> Dict:
    errors = []
    last_error = ""

    for attempt in range(1, attempts + 1):
        retry_note = ""
        if attempt > 1:
            detail = f" Previous attempt failed validation: {last_error}." if last_error else ""
            retry_note = (
                "\n\nPrevious output was invalid or incomplete."
                f"{detail} "
                "Return exactly one valid JSON payload only. "
                "Do not use markdown fences, commentary, trailing notes, or ellipses. "
                "Ensure the payload contains a non-empty questions array of JSON objects."
            )

        raw = call_llm(
            system_prompt,
            user_prompt + retry_note,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            task_type=task_type,
        )

        try:
            parsed = _extract_json_block(raw)
            if validator is not None:
                validator(parsed)
            return parsed
        except Exception as exc:
            logger.warning(
                "JSON payload rejected (task=%s, attempt=%s): %s | %s",
                task_type,
                attempt,
                exc,
                _describe_response_structure(raw),
            )
            last_error = str(exc)
            errors.append(f"attempt {attempt}: {exc}")

    joined = "; ".join(errors)
    raise RuntimeError(f"Model did not return valid JSON after {attempts} attempts: {joined}")


def _validate_quiz_payload(payload: Dict, num_questions: int) -> None:
    questions = payload.get("questions") if isinstance(payload, dict) else None
    if not isinstance(questions, list) or not questions:
        raise ValueError("Quiz JSON does not contain a non-empty questions list.")

    question_like_count = 0
    for item in questions:
        if not isinstance(item, dict):
            raise ValueError("Quiz questions must be JSON objects.")

        lowered_keys = {str(key).strip().lower() for key in item.keys()}
        if any("question" in key for key in lowered_keys) or "prompt" in lowered_keys or "stem" in lowered_keys:
            question_like_count += 1

    if question_like_count == 0:
        raise ValueError("Quiz questions list does not contain recognizable question fields.")

    expected = max(1, int(num_questions))
    min_allowed = max(1, expected - 2)
    max_allowed = expected + 2
    if len(questions) < min_allowed or len(questions) > max_allowed:
        raise ValueError(
            f"Expected around {expected} questions ({min_allowed}-{max_allowed}) "
            f"but received {len(questions)}."
        )


def _has_multi_select_questions(payload: Dict) -> bool:
    questions = payload.get("questions", []) if isinstance(payload, dict) else []
    for question in questions:
        if not isinstance(question, dict):
            continue

        qtype = str(question.get("type", "")).strip().lower().replace("-", "_").replace(" ", "_")
        if qtype in {"multi_select", "multiple_correct", "multiple_answers", "multi_choice", "msq"}:
            return True

        correct = question.get("correct")
        if isinstance(correct, list) and len(correct) > 1:
            return True
    return False


def generate_quiz(lecture_id: str, chunks: List[Dict], num_questions: int = QUIZ_NUM_QUESTIONS, force: bool = False) -> Dict:
    quiz_path = os.path.join(QUIZ_DIR, f"{lecture_id}_quiz.json")
    if os.path.exists(quiz_path) and not force:
        with open(quiz_path, "r", encoding="utf-8") as handle:
            cached = json.load(handle)
        if int(cached.get("version", 0)) == QUIZ_CACHE_VERSION and _has_multi_select_questions(cached):
            return cached

    system_prompt = "You are an exam question setter for engineering students."
    user_prompt = (
        f"Generate exactly {num_questions} questions from the lecture transcript. "
        "Mix types: 40% mcq (single correct), 20% multi_select (multiple correct), 20% true_false, 20% short_answer. "
        "Include at least 2 multi_select questions. "
        "Return only strict JSON in this shape (no markdown fences):\n"
        "{\"questions\":[{\"id\":1,\"type\":\"mcq\",\"question\":\"...\","
        "\"options\":[\"A. ...\",\"B. ...\",\"C. ...\",\"D. ...\"],\"correct\":\"A\",\"explanation\":\"...\"}]}\n"
        "Use the same fields for every question object.\n"
        "For mcq, correct must be exactly one answer (label like A/B/C/D or exact option text).\n"
        "For multi_select, correct must be an array with at least 2 correct answers (labels or exact option text).\n"
        "For true_false, correct must be 'True' or 'False'.\n"
        "For short_answer, keep correct concise (1-3 lines).\n\n"
        f"Transcript:\n{_chunks_to_text(chunks)}"
    )
    parsed = _call_json_payload(
        system_prompt,
        user_prompt,
        max_output_tokens=8192,
        temperature=0.2,
        task_type="quiz",
        validator=lambda payload: _validate_quiz_payload(payload, num_questions),
    )

    if not _has_multi_select_questions(parsed):
        retry_prompt = (
            "The following quiz JSON does not satisfy constraints.\n"
            "Rewrite it so it includes at least 2 multi_select questions with multiple correct answers.\n"
            f"Keep exactly {num_questions} questions and return strict JSON only.\n\n"
            f"Current JSON:\n{json.dumps(parsed, ensure_ascii=False)}"
        )
        parsed = _call_json_payload(
            system_prompt,
            retry_prompt,
            max_output_tokens=8192,
            temperature=0.2,
            task_type="quiz",
            validator=lambda payload: _validate_quiz_payload(payload, num_questions),
        )

    parsed["lecture_id"] = lecture_id
    parsed["version"] = QUIZ_CACHE_VERSION

    with open(quiz_path, "w", encoding="utf-8") as handle:
        json.dump(parsed, handle, ensure_ascii=False, indent=2)
    return parsed


def evaluate_short_answer(question: str, expected_answer: str, user_answer: str) -> Dict:
    system_prompt = "You are a strict but fair exam evaluator."
    user_prompt = (
        "Evaluate the student's short answer and return JSON only with keys: score, feedback.\n"
        "score should be from 0 to 1.\n\n"
        f"Question: {question}\n"
        f"Expected: {expected_answer}\n"
        f"Student: {user_answer}"
    )
    parsed = _call_json_payload(
        system_prompt,
        user_prompt,
        max_output_tokens=256,
        temperature=0.0,
        task_type="quiz_eval",
        attempts=2,
    )
    score = float(parsed.get("score", 0.0))
    parsed["score"] = max(0.0, min(1.0, score))
    parsed["feedback"] = str(parsed.get("feedback", ""))
    return parsed
