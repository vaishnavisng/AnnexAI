import json
import logging
import os
from typing import List, Optional, Tuple

import numpy as np
from sentence_transformers import SentenceTransformer

from app.config.settings import TRANSCRIPT_DIR, INDEX_DIR, EMBEDDING_MODEL_NAME

_logger = logging.getLogger(__name__)
_embedder: Optional[SentenceTransformer] = None


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedder


def build_index(lecture_id: str) -> Tuple[str, str]:
    """
    Build embeddings for all chunks of a lecture and save them.

    Returns (embeddings_path, segments_path).
    """
    chunks_path = os.path.join(TRANSCRIPT_DIR, f"{lecture_id}_chunks.json")
    if not os.path.exists(chunks_path):
        raise FileNotFoundError(
            f"No chunk file found for lecture '{lecture_id}'. "
            "Run the transcript step first."
        )

    with open(chunks_path, "r", encoding="utf-8") as f:
        segments = json.load(f)

    texts: List[str] = [s["text"] for s in segments]

    model = get_embedder()

    _logger.info("Encoding %d chunks for lecture %s...", len(texts), lecture_id)
    emb = model.encode(
        texts,
        convert_to_numpy=True,
        show_progress_bar=True,
        batch_size=32,
    ).astype("float32")

    # L2-normalize for cosine similarity
    norms = np.linalg.norm(emb, axis=1, keepdims=True) + 1e-10
    emb = emb / norms

    emb_path = os.path.join(INDEX_DIR, f"{lecture_id}_embeddings.npy")
    seg_path = os.path.join(INDEX_DIR, f"{lecture_id}_segments.json")

    np.save(emb_path, emb)
    with open(seg_path, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)

    _logger.info("Index built for lecture %s with %d chunks.", lecture_id, len(segments))
    return emb_path, seg_path


def load_index_and_segments(lecture_id: str):
    """Load embedding matrix and segments list for a lecture."""
    emb_path = os.path.join(INDEX_DIR, f"{lecture_id}_embeddings.npy")
    seg_path = os.path.join(INDEX_DIR, f"{lecture_id}_segments.json")

    if not (os.path.exists(emb_path) and os.path.exists(seg_path)):
        raise FileNotFoundError(
            f"Index data missing for lecture '{lecture_id}'. "
            "You need to process this lecture first."
        )

    emb = np.load(emb_path).astype("float32")

    with open(seg_path, "r", encoding="utf-8") as f:
        segments = json.load(f)

    return emb, segments
