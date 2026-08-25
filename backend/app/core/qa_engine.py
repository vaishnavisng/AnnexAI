import re
import threading
from collections import OrderedDict
from typing import Dict, Iterator, List, Tuple

import numpy as np

from app.config.settings import (
    HYBRID_ALPHA,
    RETRIEVAL_CANDIDATES,
    RETRIEVAL_TOPK,
    NEIGHBOR_WINDOW,
)
from app.core.indexing import get_embedder, load_index_and_segments
from app.services.llm_client import call_llm, call_llm_stream

# Optional lexical scorer
try:
    from rank_bm25 import BM25Okapi

    _HAS_BM25 = True
except Exception:
    BM25Okapi = None
    _HAS_BM25 = False


_TOKEN_RE = re.compile(r"\w+")
_RECOMMENDED_TAIL_RE = re.compile(
    r"(?is)\n*recommended segments to rewatch\s*:.*$"
)


def _normalize(arr: np.ndarray) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float32)
    if arr.size == 0:
        return arr
    mn, mx = float(arr.min()), float(arr.max())
    if mx <= mn:
        return np.zeros_like(arr, dtype=np.float32)
    return (arr - mn) / (mx - mn)


def _tok(text: str):
    return _TOKEN_RE.findall((text or "").lower())


def _clean_answer_text(answer_text: str) -> str:
    return _RECOMMENDED_TAIL_RE.sub("", str(answer_text or "")).strip()


class LectureQA:
    """
    Industry-style RAG engine for a single lecture:

    - loads embeddings and transcript segments
    - hybrid retrieval: cosine (semantic) + BM25 (lexical)
    - builds a rich prompt and calls the configured LLM through llm_client.call_llm()
    """

    def __init__(self, lecture_id: str):
        self.lecture_id = lecture_id
        self.emb, self.segments, self.bm25 = _load_lecture_resources(lecture_id)
        self.embedder = get_embedder()

    # -------- Retrieval --------

    def _hybrid_search(self, question: str, pool_k: int) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Hybrid score = HYBRID_ALPHA * cosine + (1 - HYBRID_ALPHA) * normalized BM25.
        Returns (indices, hybrid_scores, cos_scores, bm25_scores).
        """
        # Semantic
        qv = self.embedder.encode([question], convert_to_numpy=True)[0].astype("float32")
        qv = qv / (np.linalg.norm(qv) + 1e-10)
        cos_scores = self.emb @ qv
        cos_n = _normalize(cos_scores)

        # Lexical
        if self.bm25 is not None:
            bm_scores = np.asarray(self.bm25.get_scores(_tok(question)), dtype=np.float32)
            bm_n = _normalize(bm_scores)
        else:
            bm_scores = np.zeros_like(cos_scores)
            bm_n = np.zeros_like(cos_scores)

        hybrid = HYBRID_ALPHA * cos_n + (1.0 - HYBRID_ALPHA) * bm_n

        k = min(pool_k, hybrid.shape[0])
        idx = np.argpartition(-hybrid, k - 1)[:k]
        idx = idx[np.argsort(-hybrid[idx])]

        return idx, hybrid[idx], cos_scores[idx], bm_scores[idx]

    def retrieve_segments(self, question: str, top_k: int = RETRIEVAL_TOPK, pool_k: int = RETRIEVAL_CANDIDATES) -> List[Dict]:
        """
        Retrieve top_k segments using hybrid search.
        """
        idx, hybrid, cos_vals, bm_vals = self._hybrid_search(question, pool_k=pool_k)
        out: List[Dict] = []
        for rank, (i, h, c, b) in enumerate(zip(idx, hybrid, cos_vals, bm_vals), start=1):
            seg = self.segments[int(i)]
            out.append(
                {
                    "rank": rank,
                    "i": int(i),
                    "start": float(seg["start"]),
                    "end": float(seg["end"]),
                    "text": seg["text"],
                    "hybrid": float(h),
                    "cosine": float(c),
                    "bm25": float(b),
                }
            )
        return out[:top_k]

    def _expand_neighbors(self, core_segments: List[Dict]) -> List[Dict]:
        """
        Include neighboring chunks around each selected core segment so
        the LLM sees better context. NEIGHBOR_WINDOW controls how many.
        """
        picked = {}
        for c in core_segments:
            center = c["i"]
            for j in range(center - NEIGHBOR_WINDOW, center + NEIGHBOR_WINDOW + 1):
                if 0 <= j < len(self.segments):
                    seg = self.segments[j]
                    if j not in picked:
                        picked[j] = {
                            "i": j,
                            "start": float(seg["start"]),
                            "end": float(seg["end"]),
                            "text": seg["text"],
                        }
        ordered = [picked[k] for k in sorted(picked.keys(), key=lambda ix: picked[ix]["start"])]
        return ordered

    # -------- Prompt building --------

    _MAX_HISTORY_TURNS = 4

    @staticmethod
    def _build_history_block(conversation_history: List[Dict] | None) -> str:
        if not conversation_history:
            return ""
        turns = conversation_history[-LectureQA._MAX_HISTORY_TURNS:]
        lines = ["Previous conversation:\n"]
        for turn in turns:
            q = (turn.get("q") or "").strip()
            a = (turn.get("a") or "").strip()
            if not q:
                continue
            lines.append(f"Student: {q}")
            if a:
                summary = a[:500] + ("..." if len(a) > 500 else "")
                lines.append(f"Tutor: {summary}")
        lines.append("\n---\n\n")
        return "\n".join(lines)

    def _build_context_block(self, segs: List[Dict]) -> str:
        lines = []
        for idx, s in enumerate(segs, start=1):
            lines.append(f"[{idx}] {s['start']:.1f}–{s['end']:.1f}s :: {s['text']}")
        return "\n".join(lines)

    def _build_prompts(
        self,
        question: str,
        support_segs: List[Dict],
        conversation_history: List[Dict] | None = None,
    ) -> tuple[str, str]:
        context = self._build_context_block(support_segs)

        system_prompt = (
            "You are an elite academic tutor for B.Tech students. "
            "Explain ideas with textbook precision, strong structure, and concise intellectual clarity. "
            "You are given lecture segments with timestamps. "
            "Some segments may start with [Visual], which means OCR text extracted from slides or video frames. "
            "Treat the lecture material as the primary source of truth. "
            "You may add brief standard clarifications or examples when they sharpen understanding, "
            "but never contradict the lecture evidence."
        )

        history_block = self._build_history_block(conversation_history)

        user_prompt = (
            f"{history_block}"
            f"Student question:\n{question}\n\n"
            f"Relevant lecture segments (speech + visual OCR):\n"
            f"{context}\n\n"
            "Instructions:\n"
            "- Respond in the same language as the student's question unless asked otherwise.\n"
            "- Use the conversation history (if any) to understand context, resolve references like "
            "'it', 'this', 'that', 'the previous one', etc., and avoid repeating information already covered.\n"
            "- Start with `## Direct Answer` and answer the question in 1-2 crisp sentences.\n"
            "- Then use `## Explanation` and add `### Step-by-Step Logic`, `### Example`, or `### Key Distinction` only when they genuinely help.\n"
            "- Base the explanation primarily on the lecture segments above (speech + visual OCR).\n"
            "- Use textbook-standard wording, bold key terms/formulas, and prefer bullets or numbered steps for clarity.\n"
            "- Do not mention retrieval, OCR, or that you were given segments.\n"
            "- End with `## Key Takeaways` containing 3-5 compact bullets.\n"
            "- Do not add a 'Recommended segments to rewatch' line."
        )

        return system_prompt, user_prompt

    def _prepare_answer_context(
        self,
        question: str,
        top_k: int,
        conversation_history: List[Dict] | None = None,
    ) -> tuple[List[Dict], float, str, str, str] | None:
        retrieved_core = self.retrieve_segments(
            question,
            top_k=top_k,
            pool_k=RETRIEVAL_CANDIDATES,
        )
        if not retrieved_core:
            return None

        windowed = self._expand_neighbors(retrieved_core)
        earliest_start = min(s["start"] for s in windowed)
        system_prompt, user_prompt = self._build_prompts(
            question, windowed, conversation_history
        )
        fallback_text = windowed[0]["text"]
        return retrieved_core, float(earliest_start), system_prompt, user_prompt, fallback_text

    # -------- Public API --------

    def answer_question(
        self,
        question: str,
        top_k: int = RETRIEVAL_TOPK,
        conversation_history: List[Dict] | None = None,
    ) -> Dict:
        prepared = self._prepare_answer_context(question, top_k, conversation_history)
        if prepared is None:
            return {
                "answer": "I couldn't find any relevant part in this lecture.",
                "score": 0.0,
                "timestamp": 0.0,
                "segments": [],
                "mode": "none",
            }

        retrieved_core, earliest_start, system_prompt, user_prompt, fallback_text = prepared

        try:
            answer_text = call_llm(
                system_prompt,
                user_prompt,
                max_output_tokens=2048,
                temperature=0.2,
                task_type="qa",
            ).strip()
            answer_text = _clean_answer_text(answer_text)
            mode = "gemini-rag"
        except Exception as e:
            # fallback: show best transcript chunk only
            answer_text = (
                f"(LLM error: {e})\n\n"
                f"Best matching transcript snippet:\n\n{fallback_text}"
            )
            mode = "retrieval-only"

        # For UI segments, use the core retrieved ones (with scores)
        return {
            "answer": answer_text,
            "score": float(retrieved_core[0]["hybrid"]),
            "timestamp": float(earliest_start),
            "segments": retrieved_core,
            "mode": mode,
        }

    def answer_question_stream(
        self,
        question: str,
        top_k: int = RETRIEVAL_TOPK,
        conversation_history: List[Dict] | None = None,
    ) -> Iterator[Dict]:
        prepared = self._prepare_answer_context(question, top_k, conversation_history)
        if prepared is None:
            empty_answer = "I couldn't find any relevant part in this lecture."
            yield {
                "event": "meta",
                "data": {"segments": [], "timestamp": 0.0, "score": 0.0},
            }
            yield {
                "event": "done",
                "data": {
                    "answer": empty_answer,
                    "score": 0.0,
                    "timestamp": 0.0,
                    "segments": [],
                    "mode": "none",
                },
            }
            return

        retrieved_core, earliest_start, system_prompt, user_prompt, fallback_text = prepared
        score = float(retrieved_core[0]["hybrid"])

        yield {
            "event": "meta",
            "data": {
                "segments": retrieved_core,
                "timestamp": float(earliest_start),
                "score": score,
            },
        }

        collected_chunks: List[str] = []

        try:
            for chunk in call_llm_stream(
                system_prompt,
                user_prompt,
                max_output_tokens=2048,
                temperature=0.2,
                task_type="qa",
            ):
                if not chunk:
                    continue
                collected_chunks.append(chunk)
                yield {"event": "chunk", "data": {"text": chunk}}

            final_answer = _clean_answer_text("".join(collected_chunks))
            if not final_answer:
                raise RuntimeError("Gemini returned no text response.")
            mode = "gemini-rag"
        except Exception as exc:
            final_answer = _clean_answer_text("".join(collected_chunks))
            if final_answer:
                mode = "gemini-rag-partial"
            else:
                final_answer = (
                    f"(LLM error: {exc})\n\n"
                    f"Best matching transcript snippet:\n\n{fallback_text}"
                )
                mode = "retrieval-only"
                yield {"event": "chunk", "data": {"text": final_answer}}

        yield {
            "event": "done",
            "data": {
                "answer": final_answer,
                "score": score,
                "timestamp": float(earliest_start),
                "segments": retrieved_core,
                "mode": mode,
            },
        }


_LECTURE_CACHE_LIMIT = 8
_lecture_cache: "OrderedDict[str, tuple]" = OrderedDict()
_lecture_cache_lock = threading.Lock()


def _load_lecture_resources(lecture_id: str):
    """Return shared, read-only resources for a lecture.

    The embedding matrix is L2-normalized once and treated as immutable;
    callers never mutate it (writes are scalar reads only). Segments are
    likewise read-only after build, so we share the same Python list across
    requests instead of deep-copying it on every QA call.
    """
    with _lecture_cache_lock:
        cached = _lecture_cache.get(lecture_id)
        if cached is not None:
            _lecture_cache.move_to_end(lecture_id)
            return cached

    emb, segments = load_index_and_segments(lecture_id)

    emb = np.ascontiguousarray(emb, dtype=np.float32)
    norms = np.linalg.norm(emb, axis=1, keepdims=True) + 1e-10
    emb = emb / norms
    emb.setflags(write=False)

    if _HAS_BM25 and BM25Okapi is not None:
        corpus_tokens = [_tok(segment["text"]) for segment in segments]
        bm25 = BM25Okapi(corpus_tokens)
    else:
        bm25 = None

    resources = (emb, segments, bm25)

    with _lecture_cache_lock:
        _lecture_cache[lecture_id] = resources
        _lecture_cache.move_to_end(lecture_id)
        while len(_lecture_cache) > _LECTURE_CACHE_LIMIT:
            _lecture_cache.popitem(last=False)

    return resources
