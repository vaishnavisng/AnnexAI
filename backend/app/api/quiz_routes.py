from fastapi import APIRouter, Form
from typing import Optional

from app.api.helpers import format_generation_error, load_chunks, load_lecture_metadata, mark_lecture_opened
from app.api.quiz_utils import evaluate_multi_select, format_answer_list, normalize_text, prepare_quiz_questions

router = APIRouter()


@router.get("/quiz")
async def quiz_get(lecture_id: str = ""):
    lecture_id = lecture_id.strip()
    if not lecture_id:
        return {"error": "Lecture ID is required."}

    try:
        from app.core.quiz_engine import generate_quiz

        chunks = load_chunks(lecture_id)
        quiz = generate_quiz(lecture_id, chunks)
        questions = prepare_quiz_questions(quiz.get("questions", []))
    except Exception as exc:
        return {"error": format_generation_error("Quiz generation", exc)}

    coaching = {}
    try:
        from app.core.coaching_engine import build_coaching_payload
        coaching = build_coaching_payload(lecture_id)
    except Exception:
        pass

    return {
        "lecture_id": lecture_id,
        "questions": questions,
        "lecture_meta": mark_lecture_opened(lecture_id) or load_lecture_metadata(lecture_id),
        "coaching": coaching,
    }


@router.post("/quiz/regenerate")
async def quiz_regenerate(lecture_id: str = Form("")):
    lecture_id = lecture_id.strip()
    if not lecture_id:
        return {"error": "Lecture ID is required."}

    try:
        from app.core.quiz_engine import generate_quiz

        chunks = load_chunks(lecture_id)
        quiz = generate_quiz(lecture_id, chunks, force=True)
        questions = prepare_quiz_questions(quiz.get("questions", []))
    except Exception as exc:
        return {"error": format_generation_error("Quiz generation", exc)}

    coaching = {}
    try:
        from app.core.coaching_engine import build_coaching_payload
        coaching = build_coaching_payload(lecture_id)
    except Exception:
        pass

    return {
        "lecture_id": lecture_id,
        "questions": questions,
        "lecture_meta": mark_lecture_opened(lecture_id) or load_lecture_metadata(lecture_id),
        "coaching": coaching,
    }


@router.post("/quiz/submit")
async def quiz_submit(
    lecture_id: str = Form(""),
    answers: str = Form("{}"),
):
    """Submit quiz answers. `answers` is a JSON string: {"q_1": "A", "q_2": ["B","C"], ...}"""
    import json

    lecture_id = lecture_id.strip()
    if not lecture_id:
        return {"error": "Lecture ID is required."}

    try:
        answers_dict = json.loads(answers)
    except (json.JSONDecodeError, TypeError):
        answers_dict = {}

    try:
        from app.core.quiz_engine import evaluate_short_answer, generate_quiz

        chunks = load_chunks(lecture_id)
        quiz = generate_quiz(lecture_id, chunks)
        questions = prepare_quiz_questions(quiz.get("questions", []))
    except Exception as exc:
        return {"error": format_generation_error("Quiz generation", exc)}

    results = []
    total = 0.0
    possible = 0.0

    for idx, question in enumerate(questions, start=1):
        qtype = question.get("type", "")
        answer_key = f"q_{idx}"
        raw_answer = answers_dict.get(answer_key, "")

        selected_answers = []
        if qtype == "multi_select":
            if isinstance(raw_answer, list):
                selected_answers = [a.strip() for a in raw_answer if a and a.strip()]
            elif isinstance(raw_answer, str) and raw_answer.strip():
                selected_answers = [raw_answer.strip()]
        else:
            if isinstance(raw_answer, str) and raw_answer.strip():
                selected_answers = [raw_answer.strip()]
            elif isinstance(raw_answer, list) and raw_answer:
                selected_answers = [str(raw_answer[0]).strip()]

        correct = str(question.get("correct", "")).strip()
        correct_options = question.get("resolved_correct_options", [])
        if qtype in {"mcq", "multi_select"}:
            correct_display = format_answer_list(correct_options or [correct])
        else:
            correct_display = correct or "No answer"

        entry = {
            "question": question.get("question", ""),
            "type": qtype,
            "user_answer": format_answer_list(selected_answers),
            "correct": correct_display,
            "explanation": question.get("explanation", ""),
            "score": 0.0,
            "feedback": "",
            "assessment": "No answer",
        }

        if qtype == "mcq":
            expected = correct_options[0] if correct_options else correct
            if selected_answers and normalize_text(selected_answers[0]) == normalize_text(expected):
                entry["score"] = 1.0
            elif selected_answers and expected:
                entry["feedback"] = "Selected option is incorrect."
            elif not expected:
                entry["feedback"] = "No expected answer was configured for this question."
            possible += 1.0
            total += entry["score"]
        elif qtype == "multi_select":
            entry["score"], entry["feedback"] = evaluate_multi_select(selected_answers, correct_options)
            possible += 1.0
            total += entry["score"]
        elif qtype == "true_false":
            expected = correct
            if selected_answers and normalize_text(selected_answers[0]) == normalize_text(expected):
                entry["score"] = 1.0
            elif selected_answers:
                entry["feedback"] = "Selected option is incorrect."
            possible += 1.0
            total += entry["score"]
        elif qtype == "short_answer":
            user_answer = selected_answers[0] if selected_answers else ""
            entry["user_answer"] = user_answer or "No answer"
            possible += 1.0
            if not user_answer:
                entry["score"] = 0.0
                entry["feedback"] = "No response submitted."
            else:
                try:
                    eval_result = evaluate_short_answer(entry["question"], correct, user_answer)
                    entry["score"] = float(eval_result.get("score", 0.0))
                    entry["feedback"] = str(eval_result.get("feedback", ""))
                except Exception:
                    entry["score"] = 0.0
                    entry["feedback"] = "Could not auto-evaluate this answer."
            total += entry["score"]

        if entry["user_answer"] == "No answer":
            entry["assessment"] = "No answer"
        elif entry["score"] >= 0.99:
            entry["assessment"] = "Correct"
        elif entry["score"] <= 0.01:
            entry["assessment"] = "Incorrect"
        else:
            entry["assessment"] = "Partially correct"

        results.append(entry)

    total_score = 0.0 if possible == 0 else round((total / possible) * 100.0, 2)

    coaching = {}
    try:
        from app.core.coaching_engine import record_quiz_attempt
        attempt = record_quiz_attempt(lecture_id, results, total_score)
        coaching = attempt.get("coaching", {})
    except Exception:
        pass

    return {
        "lecture_id": lecture_id,
        "results": results,
        "total_score": total_score,
        "coaching": coaching,
        "lecture_meta": mark_lecture_opened(lecture_id) or load_lecture_metadata(lecture_id),
    }
