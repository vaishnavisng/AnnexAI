from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.api.helpers import load_chunks, load_lecture_metadata, reuse_processed_lecture

router = APIRouter()


def _build_lecture_title(
    stype: str,
    label: str,
    url: str,
    fetch_youtube_title: Callable[[str], str],
) -> str:
    label = (label or "").strip()
    if stype == "upload" and label:
        stem = Path(label).stem.replace("_", " ").replace("-", " ").strip()
        return stem.title() if stem else ""
    if url:
        fetched = fetch_youtube_title(url)
        if fetched:
            return fetched
    return ""


@router.post("/lectures/process")
async def process_lecture(
    source_type: str = Form("youtube"),
    youtube_url: Optional[str] = Form(None),
    video_file: Optional[UploadFile] = File(None),
):
    from app.core.indexing import build_index
    from app.services.frame_ocr_utils import extract_frame_ocr_segments
    from app.services.speechmatics_transcribe import transcribe_audio_speechmatics
    from app.services.youtube_transcript_utils import fetch_youtube_transcript
    from app.utils.media_utils import (
        allowed_file,
        create_upload_lecture_id,
        download_youtube_audio,
        download_youtube_video_for_frames,
        extract_audio_ffmpeg,
        get_youtube_video_title,
        save_lecture_metadata,
        save_uploaded_video,
    )
    from app.utils.transcript_utils import get_video_id, merge_segments, save_chunks

    source_type = (source_type or "youtube").strip()

    try:
        transcript_source = ""
        detected_language = ""
        ocr_error = ""
        ocr_segments = []
        video_path = ""

        if source_type == "upload":
            if not video_file or not video_file.filename:
                return JSONResponse({"error": "Please choose a local video file."}, status_code=400)
            if not allowed_file(video_file.filename):
                return JSONResponse({"error": "Unsupported file format. Allowed: MP4, MKV, AVI, MOV."}, status_code=400)

            lecture_id = create_upload_lecture_id()
            video_path = save_uploaded_video(video_file, lecture_id)
            audio_path = extract_audio_ffmpeg(video_path, lecture_id)
            source_url = ""
            source_label = video_file.filename
            raw_segments = transcribe_audio_speechmatics(audio_path)
            transcript_source = "speechmatics-local"
        else:
            youtube_url = (youtube_url or "").strip()
            if not youtube_url:
                return JSONResponse({"error": "Please paste a YouTube lecture URL."}, status_code=400)
            video_id = get_video_id(youtube_url)
            lecture_id = f"yt_{video_id}"
            source_url = youtube_url
            source_label = youtube_url

            if reuse_processed_lecture(lecture_id):
                existing_meta = load_lecture_metadata(lecture_id)
                needs_save = not existing_meta
                existing_title = str((existing_meta or {}).get("title") or "").strip()
                generic_title = (
                    not existing_title
                    or existing_title == lecture_id
                    or existing_title.startswith(("YouTube Lecture ", "Lecture from "))
                )

                refreshed_title = ""
                if generic_title:
                    refreshed_title = get_youtube_video_title(youtube_url)
                    if refreshed_title:
                        needs_save = True

                if needs_save:
                    chunks = load_chunks(lecture_id)
                    payload = {
                        "lecture_id": lecture_id,
                        "source_type": source_type,
                        "source_label": source_label,
                        "source_url": source_url,
                        "transcript_source": existing_meta.get("transcript_source") or "cached",
                        "detected_language": existing_meta.get("detected_language") or "",
                        "ocr_segment_count": existing_meta.get("ocr_segment_count") or 0,
                        "ocr_error": existing_meta.get("ocr_error") or "",
                        "chunk_count": existing_meta.get("chunk_count") or len(chunks),
                    }
                    if refreshed_title:
                        payload["title"] = refreshed_title
                    save_lecture_metadata(lecture_id, payload)
                meta = load_lecture_metadata(lecture_id)
                return {
                    "lecture_id": lecture_id,
                    "reused": True,
                    "message": f"Lecture already processed. Reusing saved materials for {lecture_id}.",
                    "source_url": meta.get("source_url", ""),
                }

            with ThreadPoolExecutor(max_workers=2) as executor:
                frame_future = executor.submit(download_youtube_video_for_frames, youtube_url, lecture_id)
                transcript_future = executor.submit(fetch_youtube_transcript, video_id)

                try:
                    raw_segments, transcript_language = transcript_future.result()
                    detected_language = transcript_language or ""
                    transcript_source = "youtube-transcript"
                except Exception:
                    audio_path = download_youtube_audio(youtube_url, lecture_id)
                    raw_segments = transcribe_audio_speechmatics(audio_path, language="auto")
                    transcript_source = "speechmatics-youtube-fallback"
                    detected_language = "auto"

                try:
                    video_path = frame_future.result()
                except Exception as exc:
                    video_path = ""
                    ocr_error = f"Frame analysis skipped: {exc}"

        if video_path:
            try:
                ocr_segments = extract_frame_ocr_segments(video_path, lecture_id)
            except Exception as exc:
                ocr_segments = []
                ocr_error = f"Frame analysis skipped: {exc}"

        if ocr_segments:
            raw_segments.extend(ocr_segments)
            raw_segments.sort(
                key=lambda seg: (
                    float(seg.get("start", 0.0)),
                    float(seg.get("end", seg.get("start", 0.0))),
                )
            )
            transcript_source = f"{transcript_source}+ocr"

        chunks = merge_segments(raw_segments)
        save_chunks(lecture_id, chunks)
        build_index(lecture_id)

        lecture_title = _build_lecture_title(
            source_type, source_label, source_url, get_youtube_video_title
        )

        metadata_payload = {
            "lecture_id": lecture_id,
            "source_type": source_type,
            "source_label": source_label,
            "source_url": source_url,
            "transcript_source": transcript_source,
            "detected_language": detected_language,
            "ocr_segment_count": len(ocr_segments),
            "ocr_error": ocr_error,
            "chunk_count": len(chunks),
        }
        if lecture_title:
            metadata_payload["title"] = lecture_title

        save_lecture_metadata(lecture_id, metadata_payload)
    except Exception as exc:
        return JSONResponse({"error": f"Processing failed: {exc}"}, status_code=500)

    meta = load_lecture_metadata(lecture_id)
    return {
        "lecture_id": lecture_id,
        "reused": False,
        "chunk_count": len(chunks),
        "message": f"Lecture processed successfully: {lecture_id}, chunks={len(chunks)}",
        "source_url": meta.get("source_url", ""),
    }
