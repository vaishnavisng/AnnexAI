from fastapi import APIRouter, Form
from fastapi.responses import FileResponse

from app.api.helpers import format_generation_error, load_chunks, load_lecture_metadata, mark_lecture_opened

router = APIRouter()


@router.get("/summary")
async def summary_view(lecture_id: str = ""):
    lecture_id = lecture_id.strip()
    if not lecture_id:
        return {"error": "Lecture ID is required."}

    try:
        from app.core.summary_engine import generate_summary

        chunks = load_chunks(lecture_id)
        payload = generate_summary(lecture_id, chunks)
    except Exception as exc:
        return {"error": format_generation_error("Summary generation", exc)}

    return {
        "lecture_id": lecture_id,
        "title": "Lecture Summary",
        "content": payload.get("summary", ""),
        "mode": "summary",
        "lecture_meta": mark_lecture_opened(lecture_id) or load_lecture_metadata(lecture_id),
    }


@router.get("/notes")
async def notes_view(lecture_id: str = ""):
    lecture_id = lecture_id.strip()
    if not lecture_id:
        return {"error": "Lecture ID is required."}

    try:
        from app.core.summary_engine import generate_detailed_notes

        chunks = load_chunks(lecture_id)
        payload = generate_detailed_notes(lecture_id, chunks)
    except Exception as exc:
        return {"error": format_generation_error("Notes generation", exc)}

    return {
        "lecture_id": lecture_id,
        "title": "Detailed Notes",
        "content": payload.get("notes", ""),
        "mode": "notes",
        "lecture_meta": mark_lecture_opened(lecture_id) or load_lecture_metadata(lecture_id),
    }


@router.get("/download/{doc_type}")
async def download_doc(doc_type: str, lecture_id: str = ""):
    lecture_id = lecture_id.strip()
    if not lecture_id:
        return {"error": "Lecture ID is required."}
    if doc_type not in {"summary", "notes"}:
        return {"error": "Invalid document type."}

    try:
        from app.core.summary_engine import generate_detailed_notes, generate_summary
        from app.utils.pdf_generator import generate_pdf

        chunks = load_chunks(lecture_id)
        if doc_type == "summary":
            payload = generate_summary(lecture_id, chunks)
            text = payload.get("summary", "")
            title = "Lecture Summary"
        else:
            payload = generate_detailed_notes(lecture_id, chunks)
            text = payload.get("notes", "")
            title = "Detailed Notes"

        pdf_path = generate_pdf(lecture_id, title, text, doc_type)
        return FileResponse(
            pdf_path,
            media_type="application/pdf",
            filename=f"{lecture_id}_{doc_type}.pdf",
        )
    except Exception as exc:
        return {"error": f"PDF generation failed: {exc}"}
