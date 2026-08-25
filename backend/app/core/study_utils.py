import re
from typing import Dict, Iterable, List


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "does",
    "explain",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "its",
    "mean",
    "means",
    "of",
    "on",
    "or",
    "the",
    "their",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "why",
}


def normalize_whitespace(text: str) -> str:
    return " ".join(str(text or "").split())


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def clip_text(text: str, limit: int = 220) -> str:
    cleaned = normalize_whitespace(text)
    if len(cleaned) <= limit:
        return cleaned
    if limit <= 3:
        return cleaned[:limit]
    return cleaned[: limit - 3].rstrip() + "..."


def derive_concept_label(*parts: str) -> str:
    raw = normalize_whitespace(" ".join(str(part or "") for part in parts))
    if not raw:
        return "Key Idea"

    cleaned = re.sub(r"[`*_#>\[\]{}()]+", " ", raw)
    cleaned = re.sub(r"\b(q|question)\s*\d+\b", " ", cleaned, flags=re.IGNORECASE)
    lower_cleaned = cleaned.lower()
    for marker in (
        " is ",
        " are ",
        " means ",
        " refers to ",
        " prevents ",
        " keeps ",
        " controls ",
        " protects ",
        " manages ",
        " describes ",
        " enables ",
        " ensures ",
    ):
        if marker not in lower_cleaned:
            continue
        split_index = lower_cleaned.index(marker)
        left_side = normalize_whitespace(cleaned[:split_index])
        left_tokens = tokenize(left_side)
        if 1 <= len(left_tokens) <= 6:
            return " ".join(left_tokens[:4]).title()

    pieces = re.split(r"[?.:;!-]", cleaned)
    candidate = normalize_whitespace(pieces[0] if pieces else cleaned)
    words = [word for word in tokenize(candidate) if word not in _STOPWORDS]
    if not words:
        words = tokenize(candidate)
    if not words:
        return "Key Idea"

    return " ".join(words[:4]).title()


def _token_overlap(query_tokens: Iterable[str], text_tokens: Iterable[str]) -> int:
    q = set(query_tokens)
    t = set(text_tokens)
    return len(q & t)


def find_matching_segments(chunks: List[Dict], query_text: str, limit: int = 3) -> List[Dict]:
    query_tokens = [token for token in tokenize(query_text) if token not in _STOPWORDS]
    scored = []
    for index, chunk in enumerate(chunks):
        text = normalize_whitespace(chunk.get("text", ""))
        if not text:
            continue

        text_tokens = tokenize(text)
        overlap = _token_overlap(query_tokens, text_tokens)
        bonus = 1 if overlap and normalize_whitespace(query_text).lower() in text.lower() else 0
        score = overlap * 10 + bonus
        if score <= 0 and query_tokens:
            continue

        scored.append(
            (
                score,
                index,
                {
                    "start": float(chunk.get("start", 0.0)),
                    "end": float(chunk.get("end", chunk.get("start", 0.0))),
                    "text": clip_text(text, 180),
                },
            )
        )

    if not scored:
        return []

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:limit]]
