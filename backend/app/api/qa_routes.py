import json
import os

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.api.helpers import chunks_path, load_lecture_metadata, mark_lecture_opened, parse_top_k, sse_event

_MAX_HISTORY_TURNS = 4

router = APIRouter()


def _parse_conversation_history(raw: str | None) -> list[dict]:
    if not raw:
        return []
    try:
        history = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(history, list):
        return []
    clean = []
    for turn in history[-_MAX_HISTORY_TURNS:]:
        if isinstance(turn, dict) and turn.get("q"):
            clean.append({"q": str(turn["q"])[:2000], "a": str(turn.get("a", ""))[:2000]})
    return clean


@router.get("/qa")
async def qa_info(lecture_id: str = ""):
    lecture_id = lecture_id.strip()
    has_chunks = bool(lecture_id) and os.path.exists(chunks_path(lecture_id))
    lecture_meta = mark_lecture_opened(lecture_id) if lecture_id else {}
    if lecture_id and not lecture_meta:
        lecture_meta = load_lecture_metadata(lecture_id)

    return {
        "lecture_id": lecture_id,
        "has_chunks": has_chunks,
        "lecture_meta": lecture_meta,
    }


@router.post("/qa")
async def qa_ask(
    lecture_id: str = Form(""),
    question: str = Form(""),
    top_k: str = Form("3"),
    conversation_history: str = Form(""),
):
    from app.core.qa_engine import LectureQA

    lecture_id = lecture_id.strip()
    question = question.strip()
    top_k_val = parse_top_k(top_k)

    if not lecture_id:
        return JSONResponse({"error": "Lecture ID is required."}, status_code=400)
    if not question:
        return JSONResponse({"error": "Please enter a question."}, status_code=400)

    history = _parse_conversation_history(conversation_history)

    try:
        engine = LectureQA(lecture_id)
        result = engine.answer_question(
            question, top_k=top_k_val, conversation_history=history
        )
        return {
            "answer": result["answer"],
            "segments": result["segments"],
            "timestamp": int(result["timestamp"]),
            "mode": result.get("mode", "rag"),
        }
    except Exception as exc:
        return {"error": f"Error during question answering: {exc}"}


@router.post("/qa/stream")
async def qa_stream(
    lecture_id: str = Form(""),
    question: str = Form(""),
    top_k: str = Form("3"),
    conversation_history: str = Form(""),
):
    lecture_id = lecture_id.strip()
    question = question.strip()
    top_k_val = parse_top_k(top_k)
    history = _parse_conversation_history(conversation_history)

    if not lecture_id:
        return JSONResponse({"error": "Lecture ID is required."}, status_code=400)
    if not question:
        return JSONResponse({"error": "Please enter a question."}, status_code=400)

    def generate():
        try:
            from app.core.qa_engine import LectureQA

            engine = LectureQA(lecture_id)
            for event in engine.answer_question_stream(
                question, top_k=top_k_val, conversation_history=history
            ):
                event_name = event.get("event", "message")
                payload = event.get("data", {})
                yield sse_event(event_name, payload)
        except Exception as exc:
            yield sse_event("error", {"message": f"Error during question answering: {exc}"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/qa/tts")
async def qa_tts(text: str = Form(""), voice: str = Form("")):
    from app.services.speechmatics_tts import clean_for_tts, synthesize

    cleaned = clean_for_tts(text)
    if not cleaned:
        return JSONResponse({"error": "Text is required."}, status_code=400)

    try:
        audio = synthesize(cleaned, voice=voice or None)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception as exc:
        return JSONResponse({"error": f"TTS failed: {exc}"}, status_code=502)

    return Response(
        content=audio,
        media_type="audio/wav",
        headers={"Cache-Control": "no-store"},
    )
