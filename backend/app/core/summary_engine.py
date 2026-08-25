from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
import os
import time
from typing import Callable, Dict, List

from app.config.settings import (
    LLM_MAX_PARALLEL_REQUESTS,
    LLM_POST_PARTIALS_DELAY,
    SUMMARY_CHUNK_BATCH_SIZE,
    SUMMARY_DIR,
    SUMMARY_MAX_WORDS,
)
from app.services.llm_client import call_llm

SUMMARY_CACHE_VERSION = 2
_logger = logging.getLogger(__name__)


def _chunks_to_text(chunks: List[Dict], include_timestamps: bool = False) -> str:
    lines = []
    for idx, chunk in enumerate(chunks, start=1):
        text = str(chunk.get("text", "")).strip()
        if not text:
            continue
        if include_timestamps:
            lines.append(
                f"[{idx}] {float(chunk.get('start', 0.0)):.1f}-{float(chunk.get('end', 0.0)):.1f}s: {text}"
            )
        else:
            lines.append(text)
    return "\n".join(lines)


def _slice_chunks(chunks: List[Dict], batch_size: int = SUMMARY_CHUNK_BATCH_SIZE) -> List[List[Dict]]:
    size = max(1, int(batch_size))
    return [chunks[i : i + size] for i in range(0, len(chunks), size)]


def _save_json(path: str, payload: Dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def _load_json(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _generate_partials(
    batches: List[List[Dict]],
    system_prompt: str,
    build_prompt: Callable[[List[Dict]], str],
    *,
    max_output_tokens: int,
    temperature: float,
    task_type: str,
) -> List[str]:
    if not batches:
        return []

    prompts = [build_prompt(batch) for batch in batches]
    partials = [""] * len(prompts)
    max_workers = max(1, min(LLM_MAX_PARALLEL_REQUESTS, len(prompts)))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                call_llm,
                system_prompt=system_prompt,
                user_prompt=prompt,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
                task_type=task_type,
            ): idx
            for idx, prompt in enumerate(prompts)
        }

        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                partials[idx] = future.result().strip()
            except Exception as exc:
                _logger.warning("Partial generation failed for batch %d: %s", idx, exc)
                partials[idx] = ""

    return partials


def generate_summary(lecture_id: str, chunks: List[Dict], force: bool = False) -> Dict:
    summary_path = os.path.join(SUMMARY_DIR, f"{lecture_id}_summary.json")
    if os.path.exists(summary_path) and not force:
        cached = _load_json(summary_path)
        if int(cached.get("version", 0)) == SUMMARY_CACHE_VERSION:
            return cached

    batches = _slice_chunks(chunks)

    system_prompt = (
        "You are an elite academic editor for university lecture material. "
        "Write with textbook precision, strong conceptual flow, and high information density. "
        "The output must feel like excellent revision material, not generic AI prose."
    )

    partials = _generate_partials(
        batches,
        system_prompt,
        lambda batch: (
            "Create a polished academic digest of these lecture segments.\n"
            "Requirements:\n"
            "- Preserve the conceptual flow of the lecture.\n"
            "- Surface definitions, mechanisms, assumptions, and exam-relevant logic.\n"
            "- Use clean markdown with short headings or bullets when useful.\n"
            "- Bold the most important technical terms on first mention.\n"
            "- Include one short `> Key Insight:` callout if the batch contains a crucial idea.\n"
            "- Avoid filler, repetition, and vague phrasing.\n\n"
            f"Segments:\n{_chunks_to_text(batch)}"
        ),
        max_output_tokens=1536,
        temperature=0.2,
        task_type="summary",
    )

    if partials and float(LLM_POST_PARTIALS_DELAY) > 0:
        time.sleep(float(LLM_POST_PARTIALS_DELAY))

    user_prompt_final = (
        f"Merge these academic digests into one final summary under {SUMMARY_MAX_WORDS} words.\n"
        "Return only markdown with this exact structure:\n"
        "# Lecture Summary\n"
        "## Central Thesis\n"
        "## Core Ideas\n"
        "## Analytical Flow\n"
        "## High-Yield Insights\n"
        "## Revision Triggers\n"
        "Formatting rules:\n"
        "- Open each section with a crisp topic sentence or compact bullet set.\n"
        "- Bold essential terms, principles, formulas, and named processes.\n"
        "- Include exactly one short blockquote callout for the single most testable idea.\n"
        "- Keep every line academically precise, readable, and revision-friendly.\n"
        "- Remove repetition and avoid generic motivational language.\n\n"
        "Partial summaries:\n"
        + "\n\n".join(partials)
    )
    final_summary = call_llm(
        system_prompt,
        user_prompt_final,
        max_output_tokens=2048,
        temperature=0.2,
        task_type="summary",
    )

    payload = {
        "lecture_id": lecture_id,
        "version": SUMMARY_CACHE_VERSION,
        "summary": final_summary.strip(),
        "partials": partials,
    }
    _save_json(summary_path, payload)
    return payload


def generate_detailed_notes(lecture_id: str, chunks: List[Dict], force: bool = False) -> Dict:
    notes_path = os.path.join(SUMMARY_DIR, f"{lecture_id}_notes.json")
    if os.path.exists(notes_path) and not force:
        cached = _load_json(notes_path)
        if int(cached.get("version", 0)) == SUMMARY_CACHE_VERSION:
            return cached

    batches = _slice_chunks(chunks)

    system_prompt = (
        "You are an elite lecture-note writer for serious university study. "
        "Produce rigorous, structured, exam-ready notes with clear conceptual scaffolding. "
        "The writing should sound like polished academic course notes."
    )

    partials = _generate_partials(
        batches,
        system_prompt,
        lambda batch: (
            "Transform these lecture segments into rigorous academic notes.\n"
            "Requirements:\n"
            "- Preserve the lecture's conceptual sequence.\n"
            "- Define technical terms precisely and explain why they matter.\n"
            "- Use numbered steps for mechanisms, procedures, or derivations.\n"
            "- Use concise examples only when they sharpen understanding.\n"
            "- Bold high-value terms, formulas, and contrast points.\n"
            "- Use blockquotes sparingly for `> Exam Lens:` or `> Key Distinction:` callouts.\n"
            "- Eliminate filler and keep the material dense but readable.\n\n"
            f"Segments:\n{_chunks_to_text(batch)}"
        ),
        max_output_tokens=1536,
        temperature=0.2,
        task_type="notes",
    )

    if partials and float(LLM_POST_PARTIALS_DELAY) > 0:
        time.sleep(float(LLM_POST_PARTIALS_DELAY))

    user_prompt_final = (
        "Merge these partial notes into one cohesive final set of lecture notes.\n"
        "Return only markdown with this exact structure:\n"
        "# Lecture Notes\n"
        "## Conceptual Map\n"
        "## Foundational Definitions\n"
        "## Core Explanations\n"
        "## Processes, Mechanisms, and Derivations\n"
        "## Examples and Applications\n"
        "## Subtle Distinctions and Pitfalls\n"
        "## Exam-Focused Recall Grid\n"
        "Formatting rules:\n"
        "- Use clear markdown hierarchy with `###` subsections where useful.\n"
        "- Bold essential terms, formulas, and contrast words.\n"
        "- Prefer compact bullets for recall and numbered steps for ordered reasoning.\n"
        "- Use short callouts such as `> Exam Lens:` only when they add value.\n"
        "- Keep the writing factual, polished, and dense with insight.\n"
        "- Remove repetition and keep the notes genuinely revision-ready.\n\n"
        "Partial notes:\n"
        + "\n\n".join(partials)
    )
    notes = call_llm(
        system_prompt,
        user_prompt_final,
        max_output_tokens=4096,
        temperature=0.2,
        task_type="notes",
    )

    payload = {
        "lecture_id": lecture_id,
        "version": SUMMARY_CACHE_VERSION,
        "notes": notes.strip(),
    }
    _save_json(notes_path, payload)
    return payload
