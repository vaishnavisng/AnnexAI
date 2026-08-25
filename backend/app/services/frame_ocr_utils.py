from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List

import pytesseract  # type: ignore[reportMissingImports]
from PIL import Image, ImageOps

from app.config.settings import (
    FRAME_DIR,
    OCR_FRAME_SAMPLE_SECONDS,
    OCR_MIN_CONFIDENCE,
    OCR_MAX_FRAMES,
    OCR_MAX_WORDS_PER_FRAME,
    OCR_MIN_TEXT_CHARS,
    OCR_WORKERS,
)


def _extract_frames(
    video_path: str,
    frame_pattern: str,
    sample_seconds: int,
    max_frames: int,
) -> None:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        video_path,
        "-vf",
        f"fps=1/{sample_seconds},scale='min(1280,iw)':-2",
        "-frames:v",
        str(max_frames),
        frame_pattern,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("FFmpeg is not installed. Install it first, then retry.") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or "Unknown FFmpeg error"
        raise RuntimeError(f"FFmpeg frame extraction failed: {message}") from exc


def _clean_ocr_text(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    text = re.sub(r"\s*([,.;:!?])\s*", r"\1 ", text)
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split()
    if len(words) > OCR_MAX_WORDS_PER_FRAME:
        words = words[:OCR_MAX_WORDS_PER_FRAME]
    return " ".join(words)


def _is_good_ocr_text(text: str) -> bool:
    if len(text) < OCR_MIN_TEXT_CHARS:
        return False
    alpha_chars = sum(1 for ch in text if ch.isalpha())
    if alpha_chars < max(12, len(text) // 4):
        return False
    return True


def _is_near_duplicate(current_text: str, previous_text: str) -> bool:
    if not previous_text:
        return False
    ratio = SequenceMatcher(None, current_text.lower(), previous_text.lower()).ratio()
    return ratio >= 0.9


def _ocr_image(image_path: Path) -> tuple[str, float]:
    with Image.open(image_path) as image:
        gray = ImageOps.grayscale(image)
        boosted = ImageOps.autocontrast(gray)
        data = pytesseract.image_to_data(
            boosted,
            output_type=pytesseract.Output.DICT,
            config="--oem 3 --psm 6",
        )

    words = []
    conf_values = []
    for raw_word, raw_conf in zip(data.get("text", []), data.get("conf", [])):
        word = str(raw_word or "").strip()
        if not word:
            continue
        words.append(word)
        try:
            conf = float(raw_conf)
        except (TypeError, ValueError):
            continue
        if conf >= 0:
            conf_values.append(conf)

    avg_conf = float(sum(conf_values) / len(conf_values)) if conf_values else 0.0
    text = _clean_ocr_text(" ".join(words))
    return text, avg_conf


def _build_ocr_candidate(image_path: Path, frame_index: int, sample_seconds: int) -> Dict | None:
    try:
        text, confidence = _ocr_image(image_path)
    except pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError("Tesseract OCR is not installed.") from exc

    if confidence < OCR_MIN_CONFIDENCE:
        return None
    if not _is_good_ocr_text(text):
        return None

    start = float(frame_index * sample_seconds)
    end = float(start + sample_seconds)
    return {
        "text": text,
        "start": start,
        "end": end,
    }


def extract_frame_ocr_segments(
    video_path: str,
    lecture_id: str,
    sample_seconds: int = OCR_FRAME_SAMPLE_SECONDS,
    max_frames: int = OCR_MAX_FRAMES,
) -> List[Dict]:
    frame_dir = Path(FRAME_DIR) / lecture_id
    frame_dir.mkdir(parents=True, exist_ok=True)

    for old_frame in frame_dir.glob("frame_*.jpg"):
        old_frame.unlink()

    frame_pattern = str(frame_dir / "frame_%05d.jpg")
    _extract_frames(video_path, frame_pattern, sample_seconds=sample_seconds, max_frames=max_frames)

    image_paths = sorted(frame_dir.glob("frame_*.jpg"))
    segments: List[Dict] = []
    previous_text = ""

    ordered_candidates: List[Dict | None] = [None] * len(image_paths)
    if image_paths:
        max_workers = max(1, min(OCR_WORKERS, len(image_paths)))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {
                executor.submit(_build_ocr_candidate, image_path, idx, sample_seconds): idx
                for idx, image_path in enumerate(image_paths)
            }
            for future in as_completed(future_map):
                idx = future_map[future]
                ordered_candidates[idx] = future.result()

    for candidate in ordered_candidates:
        if not candidate:
            continue

        text = candidate["text"]
        if _is_near_duplicate(text, previous_text):
            continue

        tagged = f"[Visual] {text}"
        segments.append({"text": tagged, "start": candidate["start"], "end": candidate["end"]})
        previous_text = text

    return segments
