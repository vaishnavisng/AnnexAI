import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, cast

import yt_dlp

from app.config.settings import ALLOWED_UPLOAD_EXTENSIONS, AUDIO_DIR, UPLOAD_DIR
from app.utils.study_storage import load_lecture_metadata as load_saved_lecture_metadata
from app.utils.study_storage import save_lecture_metadata as save_saved_lecture_metadata


def _ytdlp_proxy_setting() -> str:
    """
    Returns the proxy yt-dlp should use.

    By default we pass an empty string, which tells yt-dlp to bypass any
    system-level proxy autodetection (macOS PAC files, env vars, etc.) that
    may otherwise return 403 / Tunnel connection failed errors. Users who
    actually need a proxy can opt in via the YT_DLP_PROXY env var.
    """
    return os.environ.get("YT_DLP_PROXY", "")


def allowed_file(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_UPLOAD_EXTENSIONS


def _safe_filename(name: str) -> str:
    base = Path(name).name
    return "".join(ch for ch in base if ch.isalnum() or ch in {"-", "_", "."})


def create_upload_lecture_id() -> str:
    return f"local_{int(time.time())}_{uuid.uuid4().hex[:8]}"


def save_uploaded_video(file_storage, lecture_id: str) -> str:
    filename = _safe_filename(getattr(file_storage, "filename", None) or "lecture.mp4")
    ext = filename.rsplit(".", 1)[1].lower() if "." in filename else "mp4"
    out_path = os.path.join(UPLOAD_DIR, f"{lecture_id}.{ext}")

    if hasattr(file_storage, "save"):
        file_storage.save(out_path)
    else:
        import shutil
        with open(out_path, "wb") as dst:
            shutil.copyfileobj(file_storage.file, dst)

    return out_path


def extract_audio_ffmpeg(input_video_path: str, lecture_id: str) -> str:
    audio_path = os.path.join(AUDIO_DIR, f"{lecture_id}.wav")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_video_path,
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        audio_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("FFmpeg is not installed. Install it first, then retry.") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip() or exc.stdout.strip() or "Unknown FFmpeg error"
        raise RuntimeError(f"FFmpeg audio extraction failed: {message}") from exc
    return audio_path


def download_youtube_audio(youtube_url: str, lecture_id: str) -> str:
    out_base = os.path.join(AUDIO_DIR, lecture_id)
    out_template = f"{out_base}.%(ext)s"
    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "proxy": _ytdlp_proxy_setting(),
        "format": "bestaudio/best",
        "outtmpl": out_template,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }
        ],
    }
    try:
        with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:  # type: ignore[arg-type]
            ydl.download([youtube_url])
    except Exception as exc:
        message = str(exc)
        if "Requested format is not available" in message:
            raise RuntimeError(
                "Failed to download YouTube audio. Install a JavaScript runtime "
                "(Node.js or Deno) and retry."
            ) from exc
        raise RuntimeError(f"Failed to download YouTube audio: {exc}") from exc

    final_path = f"{out_base}.wav"
    if not os.path.exists(final_path):
        raise RuntimeError("YouTube audio download completed but WAV file was not generated.")
    return final_path


def download_youtube_video_for_frames(youtube_url: str, lecture_id: str) -> str:
    out_base = os.path.join(UPLOAD_DIR, f"{lecture_id}_frames")
    out_template = f"{out_base}.%(ext)s"
    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "proxy": _ytdlp_proxy_setting(),
        "format": "worst[ext=mp4]/worst",
        "outtmpl": out_template,
    }
    try:
        with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:  # type: ignore[arg-type]
            ydl.download([youtube_url])
    except Exception as exc:
        message = str(exc)
        if "Requested format is not available" in message:
            raise RuntimeError(
                "Failed to download YouTube video for frame analysis. "
                "Install a JavaScript runtime (Node.js or Deno) and retry."
            ) from exc
        raise RuntimeError(f"Failed to download YouTube video for frames: {exc}") from exc

    candidates = []
    for path in Path(UPLOAD_DIR).glob(f"{lecture_id}_frames.*"):
        if path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi"}:
            candidates.append(path)

    if not candidates:
        raise RuntimeError("YouTube video download completed but no video file was generated.")

    best_path = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)[0]
    return str(best_path)


def get_youtube_video_language(youtube_url: str) -> str:
    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "proxy": _ytdlp_proxy_setting(),
    }
    try:
        with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:  # type: ignore[arg-type]
            info = ydl.extract_info(youtube_url, download=False)
    except Exception as exc:
        raise RuntimeError(f"Failed to detect YouTube video language: {exc}") from exc

    language = str((info or {}).get("language") or "").strip().lower()
    return language


def get_youtube_video_title(youtube_url: str) -> str:
    """Best-effort fetch of a YouTube video's display title.

    Returns an empty string if the title cannot be retrieved (e.g. network
    error, age-gated video, etc.) so callers can fall back to a derived name.
    """
    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "skip_download": True,
        "proxy": _ytdlp_proxy_setting(),
    }
    try:
        with yt_dlp.YoutubeDL(cast(Any, ydl_opts)) as ydl:  # type: ignore[arg-type]
            info = ydl.extract_info(youtube_url, download=False)
    except Exception:
        return ""

    title = str((info or {}).get("title") or "").strip()
    return title


def save_lecture_metadata(lecture_id: str, payload: Dict) -> str:
    return save_saved_lecture_metadata(lecture_id, payload)


def load_lecture_metadata(lecture_id: str) -> Dict:
    return load_saved_lecture_metadata(lecture_id)
