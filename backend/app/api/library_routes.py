import os
import shutil
from glob import glob

from fastapi import APIRouter

from app.config.settings import (
    AUDIO_DIR,
    COACHING_DIR,
    FLASHCARD_DIR,
    FRAME_DIR,
    INDEX_DIR,
    LECTURE_META_DIR,
    QUIZ_ATTEMPT_DIR,
    QUIZ_DIR,
    REVIEW_DIR,
    SUMMARY_DIR,
    TRANSCRIPT_DIR,
    UPLOAD_DIR,
)
from app.core.library_engine import build_library_dashboard

router = APIRouter()


@router.get("/lectures")
async def dashboard():
    payload = build_library_dashboard()
    return payload


def _delete_lecture_files(lecture_id: str) -> int:
    """Remove every persisted artifact tied to a single lecture id.

    Covers JSON caches plus the larger media files (audio/video/frames)
    that were previously orphaned on deletion, so the on-disk footprint
    matches what the UI shows.
    """
    file_paths = [
        os.path.join(TRANSCRIPT_DIR, f"{lecture_id}_chunks.json"),
        os.path.join(INDEX_DIR, f"{lecture_id}_embeddings.npy"),
        os.path.join(INDEX_DIR, f"{lecture_id}_segments.json"),
        os.path.join(SUMMARY_DIR, f"{lecture_id}_summary.json"),
        os.path.join(SUMMARY_DIR, f"{lecture_id}_notes.json"),
        os.path.join(QUIZ_DIR, f"{lecture_id}_quiz.json"),
        os.path.join(FLASHCARD_DIR, f"{lecture_id}_deck.json"),
        os.path.join(REVIEW_DIR, f"{lecture_id}_progress.json"),
        os.path.join(QUIZ_ATTEMPT_DIR, f"{lecture_id}.json"),
        os.path.join(COACHING_DIR, f"{lecture_id}.json"),
        os.path.join(LECTURE_META_DIR, f"{lecture_id}.json"),
    ]

    glob_patterns = [
        os.path.join(AUDIO_DIR, f"{lecture_id}.*"),
        os.path.join(UPLOAD_DIR, f"{lecture_id}.*"),
        os.path.join(UPLOAD_DIR, f"{lecture_id}_frames.*"),
    ]
    for pattern in glob_patterns:
        file_paths.extend(glob(pattern))

    removed = 0
    for path in file_paths:
        if not path or not os.path.exists(path):
            continue
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass

    frame_dir = os.path.join(FRAME_DIR, lecture_id)
    if os.path.isdir(frame_dir):
        try:
            shutil.rmtree(frame_dir, ignore_errors=True)
            removed += 1
        except OSError:
            pass

    return removed


@router.delete("/lectures/{lecture_id}")
async def delete_lecture(lecture_id: str):
    lecture_id = lecture_id.strip()
    if not lecture_id:
        return {"error": "Lecture ID is required."}

    removed = _delete_lecture_files(lecture_id)

    return {
        "success": True,
        "message": f"Lecture '{lecture_id}' deleted ({removed} files removed).",
        "removed_count": removed,
    }
