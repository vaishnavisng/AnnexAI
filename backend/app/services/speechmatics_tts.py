import re
from typing import Optional

import requests

from app.config.settings import (
    SPEECHMATICS_TTS_ALLOWED_VOICES,
    SPEECHMATICS_TTS_API_KEY,
    SPEECHMATICS_TTS_DEFAULT_VOICE,
    SPEECHMATICS_TTS_MAX_CHARS,
    SPEECHMATICS_TTS_URL,
)


_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_LIST_BULLET_RE = re.compile(r"^\s*[-*+]\s+", re.MULTILINE)
_ORDERED_LIST_RE = re.compile(r"^\s*\d+\.\s+", re.MULTILINE)
_BOLD_ITALIC_RE = re.compile(r"(\*\*|__|\*|_)(.+?)\1")
_BLOCKQUOTE_RE = re.compile(r"^\s*>\s?", re.MULTILINE)
_HORIZONTAL_RULE_RE = re.compile(r"^\s*([-*_])\1{2,}\s*$", re.MULTILINE)
_MULTI_NEWLINES_RE = re.compile(r"\n{3,}")
_MULTI_SPACES_RE = re.compile(r"[ \t]{2,}")


def clean_for_tts(text: str) -> str:
    """Strip common Markdown noise so synthesized speech sounds natural."""
    if not text:
        return ""

    out = str(text)
    out = _IMAGE_RE.sub(r"\1", out)
    out = _LINK_RE.sub(r"\1", out)
    out = _FENCED_CODE_RE.sub(" ", out)
    out = _INLINE_CODE_RE.sub(r"\1", out)
    out = _HEADING_RE.sub("", out)
    out = _LIST_BULLET_RE.sub("", out)
    out = _ORDERED_LIST_RE.sub("", out)
    out = _BLOCKQUOTE_RE.sub("", out)
    out = _HORIZONTAL_RULE_RE.sub("", out)
    out = _BOLD_ITALIC_RE.sub(r"\2", out)
    out = _MULTI_NEWLINES_RE.sub("\n\n", out)
    out = _MULTI_SPACES_RE.sub(" ", out)
    return out.strip()


def _resolve_voice(voice: Optional[str]) -> str:
    candidate = (voice or "").strip().lower()
    if candidate in SPEECHMATICS_TTS_ALLOWED_VOICES:
        return candidate
    return SPEECHMATICS_TTS_DEFAULT_VOICE


def synthesize(text: str, voice: Optional[str] = None) -> bytes:
    """Call Speechmatics TTS and return raw WAV audio bytes."""
    if not SPEECHMATICS_TTS_API_KEY:
        raise RuntimeError("Speechmatics TTS API key is not configured.")

    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("Text is empty.")
    if len(cleaned) > SPEECHMATICS_TTS_MAX_CHARS:
        cleaned = cleaned[:SPEECHMATICS_TTS_MAX_CHARS]

    resolved_voice = _resolve_voice(voice)
    url = f"{SPEECHMATICS_TTS_URL.rstrip('/')}/{resolved_voice}"
    headers = {
        "Authorization": f"Bearer {SPEECHMATICS_TTS_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "audio/wav",
    }

    try:
        resp = requests.post(url, headers=headers, json={"text": cleaned}, timeout=60)
    except requests.RequestException as exc:
        raise RuntimeError(f"Speechmatics TTS request failed: {exc}") from exc

    if resp.status_code >= 400:
        detail = ""
        try:
            payload = resp.json()
            detail = payload.get("error") or payload.get("detail") or str(payload)
        except ValueError:
            detail = (resp.text or "").strip()[:300]
        raise RuntimeError(
            f"Speechmatics TTS returned {resp.status_code}: {detail or 'unknown error'}"
        )

    audio = resp.content or b""
    if not audio:
        raise RuntimeError("Speechmatics TTS returned an empty audio body.")
    return audio
