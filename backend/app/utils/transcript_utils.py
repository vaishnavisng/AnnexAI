import json
import os
import re
from typing import Dict, List

from app.config.settings import MAX_CHUNK_WORDS, TRANSCRIPT_DIR
from app.utils.study_storage import write_json_atomic


def get_video_id(url: str) -> str:
    """
    Extract a valid 11-character YouTube video ID from common URL formats.
    Raises ValueError if a valid ID cannot be found.
    """
    url = (url or "").strip()

    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url):
        return url

    patterns = [
        r"youtu\.be/([A-Za-z0-9_-]{11})",
        r"[?&]v=([A-Za-z0-9_-]{11})",
        r"/shorts/([A-Za-z0-9_-]{11})",
        r"/embed/([A-Za-z0-9_-]{11})",
        r"/live/([A-Za-z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    raise ValueError(
        "Could not extract a valid YouTube video ID. "
        "Please paste a real YouTube lecture link or a raw 11-character ID."
    )


def merge_segments(raw_transcript: List[Dict], max_words: int = MAX_CHUNK_WORDS) -> List[Dict]:
    """
    Merge small transcript entries into chunks of roughly max_words words.
    Input entries can contain either:
    - {text, start, end}
    - {text, start, duration}
    """
    chunks: List[Dict] = []
    current_words: List[str] = []
    current_start = None
    current_end = None

    for entry in raw_transcript:
        text = (entry.get("text") or "").replace("\n", " ").strip()
        if not text:
            continue

        words = text.split()
        if current_start is None:
            current_start = float(entry.get("start", 0.0))

        if "duration" in entry:
            current_end = float(entry["start"]) + float(entry.get("duration", 0.0))
        else:
            current_end = float(entry.get("end", entry.get("start", 0.0)))

        current_words.extend(words)

        if len(current_words) >= max_words:
            chunks.append(
                {
                    "start": float(current_start),
                    "end": float(current_end),
                    "text": " ".join(current_words),
                }
            )
            current_words, current_start, current_end = [], None, None

    if current_words:
        safe_start = 0.0 if current_start is None else float(current_start)
        safe_end = safe_start if current_end is None else float(current_end)
        chunks.append(
            {
                "start": safe_start,
                "end": safe_end,
                "text": " ".join(current_words),
            }
        )

    return chunks


def save_chunks(lecture_id: str, chunks: List[Dict]) -> str:
    path = os.path.join(TRANSCRIPT_DIR, f"{lecture_id}_chunks.json")
    write_json_atomic(path, chunks)
    return path
