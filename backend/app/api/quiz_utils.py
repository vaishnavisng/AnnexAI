import json
import re

MULTI_SELECT_TYPES = {
    "multi_select",
    "multiple_correct",
    "multiple_answers",
    "multi_choice",
    "msq",
}
CHOICE_SPLIT_PATTERN = re.compile(r"\s*(?:,|/|;|\||\band\b|&)\s*", flags=re.IGNORECASE)


def normalize_quiz_type(raw_type: str) -> str:
    qtype = str(raw_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    if qtype in MULTI_SELECT_TYPES:
        return "multi_select"
    if qtype in {"mcq", "multiple_choice", "single_choice"}:
        return "mcq"
    if qtype in {"true_false", "true/false", "boolean"}:
        return "true_false"
    if qtype in {"short_answer", "short", "open_ended", "openended"}:
        return "short_answer"
    return qtype


def normalize_text(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def clean_choice_options(raw_options) -> list:
    if not isinstance(raw_options, list):
        return []
    options = []
    for option in raw_options:
        text = str(option or "").strip()
        if text:
            options.append(text)
    return options


def token_to_option(token: str, options: list) -> str:
    probe = str(token or "").strip()
    if not probe:
        return ""

    probe_key = normalize_text(probe)
    for option in options:
        if normalize_text(option) == probe_key:
            return option

    letter_match = re.fullmatch(r"\(?\s*([A-Za-z])\s*[\).]?\s*", probe)
    if letter_match:
        idx = ord(letter_match.group(1).upper()) - ord("A")
        if 0 <= idx < len(options):
            return options[idx]

    number_match = re.fullmatch(r"\(?\s*(\d+)\s*[\).]?\s*", probe)
    if number_match:
        idx = int(number_match.group(1)) - 1
        if 0 <= idx < len(options):
            return options[idx]

    prefixed_match = re.match(r"^\s*([A-Za-z]|\d+)\s*[\).:\-]\s*(.+?)\s*$", probe)
    if prefixed_match:
        by_label = token_to_option(prefixed_match.group(1), options)
        if by_label:
            return by_label
        trailing = prefixed_match.group(2)
        trailing_key = normalize_text(trailing)
        for option in options:
            if normalize_text(option) == trailing_key:
                return option

    return ""


def extract_answer_tokens(raw_answer, options: list) -> list:
    if isinstance(raw_answer, list):
        return [str(item).strip() for item in raw_answer if str(item).strip()]

    text = str(raw_answer or "").strip()
    if not text:
        return []

    if options and token_to_option(text, options):
        return [text]

    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            pass

    tokens = [part.strip() for part in CHOICE_SPLIT_PATTERN.split(text) if part.strip()]
    if len(tokens) > 1:
        return tokens
    return [text]


def resolve_choice_answers(raw_answer, options: list) -> list:
    tokens = extract_answer_tokens(raw_answer, options)
    resolved = []
    seen = set()

    for token in tokens:
        option = token_to_option(token, options)
        candidate = option or str(token).strip()
        key = normalize_text(candidate)
        if key and key not in seen:
            seen.add(key)
            resolved.append(candidate)

    return resolved


def format_answer_list(answers: list) -> str:
    cleaned = [str(answer).strip() for answer in answers if str(answer).strip()]
    return ", ".join(cleaned) if cleaned else "No answer"


def prepare_quiz_questions(raw_questions: list) -> list:
    prepared = []
    for raw_question in raw_questions:
        question = dict(raw_question or {})
        qtype = normalize_quiz_type(question.get("type", ""))
        options = clean_choice_options(question.get("options", []))
        question["options"] = options

        resolved_correct = []
        if qtype in {"mcq", "multi_select"}:
            resolved_correct = resolve_choice_answers(question.get("correct", ""), options)
            if qtype == "mcq" and len(resolved_correct) > 1:
                qtype = "multi_select"

        question["type"] = qtype
        question["resolved_correct_options"] = resolved_correct
        prepared.append(question)
    return prepared


def evaluate_multi_select(selected_answers: list, correct_answers: list) -> tuple:
    selected_norm = {normalize_text(answer) for answer in selected_answers if normalize_text(answer)}
    correct_norm = {normalize_text(answer) for answer in correct_answers if normalize_text(answer)}

    if not correct_norm:
        return 0.0, "No correct answers were configured for this question."
    if not selected_norm:
        return 0.0, ""
    if selected_norm == correct_norm:
        return 1.0, ""

    if selected_norm.issubset(correct_norm):
        missing = [answer for answer in correct_answers if normalize_text(answer) not in selected_norm]
        feedback = f"Missing: {', '.join(missing)}." if missing else ""
        score = len(selected_norm) / len(correct_norm)
        return round(score, 2), feedback

    wrong = [answer for answer in selected_answers if normalize_text(answer) not in correct_norm]
    missing = [answer for answer in correct_answers if normalize_text(answer) not in selected_norm]
    parts = []
    if wrong:
        parts.append(f"Not correct: {', '.join(wrong)}")
    if missing:
        parts.append(f"Missing: {', '.join(missing)}")
    feedback = ". ".join(parts)
    if feedback:
        feedback += "."
    return 0.0, feedback
