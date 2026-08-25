import json
import os

from app.config.settings import INDEX_DIR, TRANSCRIPT_DIR


def chunks_path(lecture_id: str) -> str:
    return os.path.join(TRANSCRIPT_DIR, f"{lecture_id}_chunks.json")


def load_chunks(lecture_id: str):
    path = chunks_path(lecture_id)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Lecture '{lecture_id}' has not been processed yet.")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def index_paths(lecture_id: str) -> tuple[str, str]:
    return (
        os.path.join(INDEX_DIR, f"{lecture_id}_embeddings.npy"),
        os.path.join(INDEX_DIR, f"{lecture_id}_segments.json"),
    )


def reuse_processed_lecture(lecture_id: str) -> bool:
    chunk_file = chunks_path(lecture_id)
    if not os.path.exists(chunk_file):
        return False

    emb_path, seg_path = index_paths(lecture_id)
    if not (os.path.exists(emb_path) and os.path.exists(seg_path)):
        from app.core.indexing import build_index
        build_index(lecture_id)

    return True


def load_lecture_metadata(lecture_id: str) -> dict:
    if not lecture_id:
        return {}
    from app.utils.media_utils import load_lecture_metadata as load_metadata
    return load_metadata(lecture_id)


def mark_lecture_opened(lecture_id: str) -> dict:
    if not lecture_id:
        return {}
    from app.utils.study_storage import touch_lecture
    return touch_lecture(lecture_id)


def parse_top_k(raw_value) -> int:
    try:
        top_k = int(raw_value or "3")
    except (TypeError, ValueError):
        return 3
    return max(1, min(5, top_k))


def sse_event(event_name: str, payload: dict) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def is_rate_limit_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    markers = (
        "resource_exhausted",
        "rate limit",
        "too many requests",
        "quota",
        "429",
    )
    return any(marker in message for marker in markers)


def format_generation_error(label: str, exc: Exception) -> str:
    if is_rate_limit_error(exc):
        return f"{label} failed: API rate limit reached. Please wait 30-60 seconds and try again."
    return f"{label} failed: {exc}"
