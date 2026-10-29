"""Safe exam generation for the Intelligent Educational Assessment System.

This module retrieves curriculum-grounded context from the existing Chroma vector
store, generates exam questions through the Google Gemini or Ollama API, validates
structured output, and saves generated assessments under outputs/ without
overwriting earlier files.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_root_dir = Path(__file__).resolve().parent.parent
if str(_root_dir) not in sys.path:
    sys.path.insert(0, str(_root_dir))

from typing import Any, Iterable
from scripts.config import (
    BASE_DIR,
    GEMINI_API_KEY,
    GEMINI_MODEL_NAME,
    GROQ_API_KEY,
    GROQ_BASE_URL,
    GROQ_MODEL_NAME,
    HF_EMBEDDING_MODEL_NAME,
    LLM_FALLBACK_PROVIDERS,
    LLM_MIN_INTERVAL_SECONDS,
    LLM_MODEL_NAME,
    LLM_PROVIDER,
    MAX_PER_QUESTION_RETRIES as CONFIG_MAX_RETRIES,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL_NAME,
    OLLAMA_NUM_CTX,
    OUTPUTS_DIR,
    VECTOR_DB_PATH,
    VERIFY_MCQ_ANSWERS,
)
from scripts.ingestion import get_embeddings, load_vectorstore, retrieve

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

VALID_QUESTION_TYPES = {"mcq", "short_answer", "essay"}
VALID_DIFFICULTY = {"easy", "medium", "hard"}
VALID_BLOOM_LEVELS = {"remember", "understand", "apply", "analyze", "evaluate", "create"}
DEFAULT_QUESTION_TYPES = ["mcq", "short_answer", "essay"]
GENERATION_TEMPERATURE = 0.4
MAX_CHUNK_CHARS = 2500
MAX_CONTEXT_CHUNKS = 8
MAX_COMPLETION_ATTEMPTS = 2
MAX_COMPLETION_TOKENS = 4096
RETRY_COMPLETION_TOKENS = 8192
MAX_QUESTION_GENERATION_ATTEMPTS = 2
MAX_PER_QUESTION_RETRIES = int(CONFIG_MAX_RETRIES or 3)
MAX_429_RETRIES = 3
MAX_BACKOFF_WAIT_SECONDS = 60.0

logger = logging.getLogger(__name__)

_LAST_LLM_CALL_TIMESTAMP: float = 0.0
_LLM_CALL_COUNTER: int = 0
_LAST_USED_METADATA: dict[str, str] = {"provider": "", "model": ""}


def get_llm_call_count() -> int:
    """Return total number of LLM API requests made during this session."""
    return _LLM_CALL_COUNTER


def reset_llm_call_count() -> int:
    """Reset LLM API request counter and return previous count."""
    global _LLM_CALL_COUNTER
    old = _LLM_CALL_COUNTER
    _LLM_CALL_COUNTER = 0
    return old


def get_last_llm_metadata() -> dict[str, str]:
    """Return metadata (provider, model) of the most recently executed completion."""
    return dict(_LAST_USED_METADATA)


def _increment_llm_call_count() -> None:
    global _LLM_CALL_COUNTER
    _LLM_CALL_COUNTER += 1


def _gemini_model() -> str:
    """Return a Gemini model ID even when another provider is primary.

    LLM_MODEL_NAME holds the primary provider's model (e.g. a Groq ID), so it is only
    reused for Gemini when it is actually a Gemini model.
    """
    if LLM_MODEL_NAME and str(LLM_MODEL_NAME).lower().startswith("gemini"):
        return LLM_MODEL_NAME
    return GEMINI_MODEL_NAME or "gemini-2.5-flash"


def _throttle_client() -> None:
    """Pause execution if necessary to respect LLM_MIN_INTERVAL_SECONDS."""
    global _LAST_LLM_CALL_TIMESTAMP
    min_interval = float(LLM_MIN_INTERVAL_SECONDS or 0.0)
    if min_interval > 0.0:
        elapsed = time.monotonic() - _LAST_LLM_CALL_TIMESTAMP
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
    _LAST_LLM_CALL_TIMESTAMP = time.monotonic()


def _parse_retry_after(headers: Any) -> float:
    """Extract wait time in seconds from Retry-After or x-ratelimit headers."""
    if not hasattr(headers, "get"):
        return 2.0
    val = headers.get("retry-after")
    if val:
        try:
            return max(0.5, float(val))
        except (ValueError, TypeError):
            pass
    for h in ("x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
        raw = headers.get(h)
        if not raw:
            continue
        raw_str = str(raw).strip().lower()
        try:
            if raw_str.endswith("ms"):
                return max(0.2, float(raw_str[:-2]) / 1000.0)
            if raw_str.endswith("s") and "m" not in raw_str:
                return max(0.5, float(raw_str[:-1]))
            if "m" in raw_str and raw_str.endswith("s"):
                parts = raw_str.split("m")
                mins = float(parts[0])
                secs = float(parts[1][:-1]) if parts[1].endswith("s") else 0.0
                return max(1.0, mins * 60 + secs)
            return max(1.0, float(raw_str))
        except (ValueError, TypeError):
            continue
    return 2.0



class LLMProviderError(ValueError):
    """Raised for provider failures that should not be retried as question errors."""


class InvalidSourceRefError(ValueError):
    """Raised when a model cites a missing or invalid curriculum source."""


class InvalidEvidenceQuoteError(InvalidSourceRefError):
    """Raised when a model citation quote does not occur in its cited chunk."""


def _as_path(value: str | Path | None) -> Path:
    if value is None:
        return VECTOR_DB_PATH
    path = Path(value)
    return (path if path.is_absolute() else BASE_DIR / path).resolve()


def resolve_vectorstore_dir(persist_dir: str | Path | None = None) -> Path:
    if persist_dir is not None:
        return _as_path(persist_dir)
    return VECTOR_DB_PATH


def validate_configuration() -> tuple[bool, list[str], str | None]:
    """Validate environment and loaded config without exposing secrets."""
    missing: list[str] = []
    if LLM_PROVIDER not in {"gemini", "ollama", "groq"}:
        missing.append("LLM_PROVIDER must be 'gemini', 'ollama', or 'groq'")
    if LLM_PROVIDER == "gemini":
        if not GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")
        model = _gemini_model()
    elif LLM_PROVIDER == "ollama":
        model = OLLAMA_MODEL_NAME or (LLM_MODEL_NAME if LLM_MODEL_NAME and not LLM_MODEL_NAME.startswith("gemini") else None) or "llama3.2"
        if not model:
            missing.append("OLLAMA_MODEL_NAME or LLM_MODEL_NAME")
    elif LLM_PROVIDER == "groq":
        if not GROQ_API_KEY:
            missing.append("GROQ_API_KEY")
        model = GROQ_MODEL_NAME or LLM_MODEL_NAME or "openai/gpt-oss-20b"
        if not model:
            missing.append("GROQ_MODEL_NAME or LLM_MODEL_NAME")
    else:
        model = LLM_MODEL_NAME
    return (not missing, missing, model)


def _build_source_refs(documents: Iterable[Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for doc in documents:
        metadata = getattr(doc, "metadata", {}) or {}
        ref = {
            "source": metadata.get("source", "unknown"),
            "chapter_id": metadata.get("chapter_id"),
            "chapter_title": metadata.get("chapter_title"),
            "lesson_id": metadata.get("lesson_id"),
            "lesson_title": metadata.get("lesson_title"),
            "chunk_id": metadata.get("chunk_id"),
            "content_type": metadata.get("content_type"),
            "pdf_page_start": metadata.get("pdf_page_start"),
            "pdf_page_end": metadata.get("pdf_page_end"),
            "printed_page_start": metadata.get("printed_page_start"),
            "printed_page_end": metadata.get("printed_page_end"),
        }
        refs.append(ref)
    return refs


def _extract_json_object(raw_output: str) -> dict[str, Any]:
    text = raw_output.strip()
    if not text:
        raise ValueError("Empty response from model")

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text, flags=re.IGNORECASE)

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("Model response must contain a JSON object")
    return value


def _validate_question(question: dict[str, Any]) -> None:
    if not isinstance(question, dict):
        raise ValueError("Model response was not a JSON object")

    required = [
        "question",
        "question_type",
        "difficulty",
        "bloom_level",
        "bloom_rationale",
        "options",
        "correct_answer",
        "reference_answer",
        "explanation",
        "max_score",
        "rubric",
        "source_refs",
    ]
    missing = [key for key in required if key not in question]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")
    for key in ("question", "bloom_rationale", "reference_answer", "explanation"):
        if not isinstance(question[key], str) or not question[key].strip():
            raise ValueError(f"{key} must be a non-empty string")

    q_type = str(question.get("question_type", "")).strip().lower()
    if q_type not in VALID_QUESTION_TYPES:
        raise ValueError(f"Unsupported question type: {q_type}")

    difficulty = str(question.get("difficulty", "")).strip().lower()
    if difficulty not in VALID_DIFFICULTY:
        raise ValueError(f"Unsupported difficulty: {difficulty}")

    bloom_level = str(question.get("bloom_level", "")).strip().lower()
    if bloom_level not in VALID_BLOOM_LEVELS:
        raise ValueError(f"Unsupported Bloom level: {bloom_level}")

    if not isinstance(question.get("source_refs"), list) or not question["source_refs"]:
        raise ValueError("Question must include at least one source reference")
    if any(
        not isinstance(ref, dict)
        or not ref.get("source")
        or not ref.get("chunk_id")
        or not isinstance(ref.get("evidence_quote"), str)
        or not ref["evidence_quote"].strip()
        for ref in question["source_refs"]
    ):
        raise InvalidSourceRefError(
            "Each source reference must identify a source, chunk, and evidence quote"
        )

    if q_type == "mcq":
        options = question.get("options")
        if (
            not isinstance(options, list)
            or len(options) != 4
            or any(not isinstance(option, str) or not option.strip() for option in options)
        ):
            raise ValueError("MCQs require exactly four options")

        cleaned_options = [
            re.sub(r"^\s*[A-D1-4][\s.):\-]+", "", str(opt)).strip()
            for opt in options
        ]
        if (
            len(cleaned_options) == 4
            and all(cleaned_options)
            and len({opt.casefold() for opt in cleaned_options}) == 4
        ):
            options = cleaned_options
            question["options"] = cleaned_options

        if len({option.strip().casefold() for option in options}) != 4:
            raise ValueError("MCQ options must be distinct")

        for option in options:
            norm_opt = option.strip().casefold()
            if norm_opt in {
                "all of the above", "none of the above",
                "both a and b", "both b and c", "both a and c",
                "neither a nor b", "all the above", "none the above",
                "all of these", "none of these",
            }:
                raise ValueError(f"MCQ contains prohibited low-quality distractor: '{option}'")

        if "correct_answer" not in question:
            raise ValueError("MCQ missing correct_answer")
        correct = str(question["correct_answer"]).strip().upper()
        if correct in {"1", "2", "3", "4"}:
            correct = "ABCD"[int(correct) - 1]
        if correct not in {"A", "B", "C", "D"}:
            raise ValueError("Correct answer must be one of A/B/C/D or 1/2/3/4")
        question["correct_answer"] = correct
        reference_match = re.match(
            r"^\s*([A-D1-4])(?:(?:\s*[:.)\-]\s*(.*))|$)",
            question["reference_answer"],
            flags=re.IGNORECASE,
        )
        if reference_match:
            reference_label = reference_match.group(1).upper()
            if reference_label in {"1", "2", "3", "4"}:
                reference_label = "ABCD"[int(reference_label) - 1]
            if reference_label != question["correct_answer"]:
                raise ValueError("MCQ reference_answer does not match correct_answer")
            answer_text = reference_match.group(2)
            if answer_text:
                clean_ref_text = re.sub(
                    r"^\s*[A-D1-4][\s.):\-]+",
                    "",
                    answer_text,
                    flags=re.IGNORECASE,
                ).strip()
                selected_option = options["ABCD".index(question["correct_answer"])]
                if " ".join(clean_ref_text.split()).casefold() != " ".join(selected_option.split()).casefold():
                    raise ValueError("MCQ reference_answer text does not match the selected option")
                question["reference_answer"] = f"{question['correct_answer']}: {selected_option}"
        rubric = question.get("rubric")
        if (
            not isinstance(rubric, list)
            or len(rubric) != 1
            or not isinstance(rubric[0], dict)
            or rubric[0].get("points") != 1
        ):
            raise ValueError("MCQ rubric must award exactly 1 point for its single selected answer")
    elif question.get("options") not in (None, []) or question.get("correct_answer") not in (None, ""):
        raise ValueError("Non-MCQ questions must not include options or a correct answer")

    rubric = question.get("rubric")
    if not isinstance(rubric, list) or not rubric or any(not isinstance(item, dict) for item in rubric):
        raise ValueError("Rubric must be a non-empty list")
    for item in rubric:
        if (
            not isinstance(item.get("criterion"), str)
            or not item["criterion"].strip()
            or not isinstance(item.get("description"), str)
            or not item["description"].strip()
            or isinstance(item.get("points"), bool)
            or not isinstance(item.get("points"), (int, float))
            or item["points"] <= 0
        ):
            raise ValueError("Each rubric item requires a criterion, description, and positive point value")
    max_score = question["max_score"]
    rubric_score = sum(item["points"] for item in rubric)
    if (
        isinstance(max_score, bool)
        or not isinstance(max_score, (int, float))
        or max_score <= 0
        or max_score != rubric_score
    ):
        raise ValueError("max_score must equal the sum of rubric points")

    question["question_type"] = q_type
    question["difficulty"] = difficulty
    question["bloom_level"] = bloom_level


MCQ_GROUNDING_RULE = (
    "The scenario may be new, but every fact needed to choose the correct answer must be stated in the "
    "curriculum context. Exactly one option must be supported by the context; each distractor must be clearly "
    "contradicted by or unsupported by the context. Do not use outside knowledge."
)


def _build_prompt(
    question_type: str,
    topic: str,
    difficulty: str,
    bloom_level: str,
    context_docs: list[Any],
    custom_prompt: str | None = None,
    previous_questions: list[str | dict[str, str]] | None = None,
    focus_chunk_id: str | None = None,
    language: str = "en",
) -> str:
    context_sections = []
    ordered_docs = list(context_docs[:MAX_CONTEXT_CHUNKS])
    if focus_chunk_id:
        focus_docs = [
            d for d in ordered_docs
            if str((getattr(d, "metadata", {}) or {}).get("chunk_id")) == str(focus_chunk_id)
        ]
        other_docs = [
            d for d in ordered_docs
            if str((getattr(d, "metadata", {}) or {}).get("chunk_id")) != str(focus_chunk_id)
        ]
        ordered_docs = focus_docs + other_docs[:3]

    for d_idx, doc in enumerate(ordered_docs):
        full_content = doc.page_content if hasattr(doc, "page_content") else str(doc)
        chunk_budget = MAX_CHUNK_CHARS if d_idx == 0 else min(MAX_CHUNK_CHARS, 1500)
        content = full_content[:chunk_budget]
        if len(full_content) > chunk_budget:
            chunk_id = (getattr(doc, "metadata", {}) or {}).get("chunk_id", "unknown")
            logger.warning(
                "Truncated curriculum chunk %s from %d to %d characters",
                chunk_id,
                len(full_content),
                chunk_budget,
            )
        references = _build_source_refs([doc])
        context_sections.append(
            f"Source references: {json.dumps(references, ensure_ascii=False)}\nContent:\n{content}"
        )
    context_text = "\n\n---\n\n".join(context_sections)
    covered_questions = []
    for previous in previous_questions or []:
        if isinstance(previous, dict):
            question_text = str(previous.get("question", "")).strip()
            reference_answer = str(previous.get("reference_answer", "")).strip()
            covered_questions.append(
                f"Question: {question_text}; reference answer: {reference_answer[:150]}"
            )
        else:
            covered_questions.append(f"Question: {previous}")

    if custom_prompt:
        task = custom_prompt
    elif question_type == "mcq":
        task = (
            "Generate one multiple-choice question with exactly four distinct options, exactly one correct answer, "
            "a brief reference answer, a one-paragraph explanation, and a single-criterion rubric worth exactly 1 point "
            "(correct selected option = 1, otherwise = 0). Do not split one selected-answer question across overlapping criteria. "
            "Options must be clean text without option prefixes (do NOT include 'A)' or '1.' in the option strings). "
            "Distractors must be plausible, realistic curriculum concepts from the focus lesson that are clearly incorrect. "
            "Do NOT use 'All of the above', 'None of the above', or trivial non-options. "
            f"{MCQ_GROUNDING_RULE}"
        )
    elif question_type == "short_answer":
        task = (
            "Generate one short-answer question with a concise model answer, a brief explanation, and a rubric with 3 criteria."
        )
    else:
        task = (
            "Generate one essay question with a strong model answer, a brief explanation, and a rubric with 4 criteria."
        )

    if question_type == "mcq":
        rubric_example = [
            {
                "criterion": "Correct selected answer",
                "points": 1,
                "description": "Correct option = 1 point; incorrect or unanswered = 0 points.",
            }
        ]
    else:
        criterion_count = 3 if question_type == "short_answer" else 4
        rubric_example = [
            {
                "criterion": f"Distinct criterion {index}",
                "points": 1,
                "description": "Award this point only for the stated element.",
            }
            for index in range(1, criterion_count + 1)
        ]
    max_score_example = sum(item["points"] for item in rubric_example)

    lang_instruction = ""
    if language and str(language).lower() in {"ar", "arabic"}:
        lang_instruction = (
            "\nLanguage Requirement:\n"
            "Generate the question text, options, explanation, bloom_rationale, and rubric descriptions in Arabic.\n"
            "CRITICAL EXCEPTION: Every evidence_quote in source_refs MUST be copied verbatim in its original English "
            "text directly from the curriculum chunk without translation or modification.\n"
        )

    return f"""
You are generating a curriculum-aligned exam question.
Use only the provided curriculum context. Do not invent facts or add outside knowledge.
Question type: {question_type}
Topic: {topic}
Difficulty: {difficulty}
Bloom level: {bloom_level}

Task:
{task}

Return valid JSON only with this exact structure:
{{
  "question": "...",
  "question_type": "{question_type}",
  "difficulty": "{difficulty}",
  "bloom_level": "{bloom_level}",
  "bloom_rationale": "Briefly state the thinking task that makes this the requested Bloom level.",
  "options": ["option A", "option B", "option C", "option D"],
  "correct_answer": "A",
  "reference_answer": "{'A: the exact text of option A' if question_type == 'mcq' else '...'}",
  "explanation": "...",
  "max_score": {max_score_example},
  "rubric": {json.dumps(rubric_example, ensure_ascii=False)},
  "source_refs": [
    {{
      "source": "...",
      "chapter_id": 1,
      "lesson_id": "1-1",
      "chunk_id": "1-1-001",
      "content_type": "text",
      "evidence_quote": "An exact, brief quotation from this chunk that supports the question or answer."
    }}
  ]
}}

For MCQs, reference_answer must be "correct letter: exact option text". For short-answer or essay questions, set "options" to [] and "correct_answer" to ""; max_score must equal the sum of rubric points. Written-question rubric criteria must be distinct, non-overlapping, and directly score separate required elements of the prompt. Keep source_refs non-empty. Select only the chunk references that directly support the question, correct answer, or explanation; do not cite every provided chunk. Each evidence_quote must be copied verbatim from that chunk. Do not invent chunk IDs, source names, or quotations. Set bloom_level to the requested cognitive process; do not label simple recall as application.
For apply-level MCQs: {MCQ_GROUNDING_RULE} For other apply-level questions, use a new scenario rather than asking the student to repeat a table entry. For remember/understand, test recall or explanation; for analyze/evaluate/create, require comparison, judgment, or production appropriate to the selected level. Explain the cognitive task in bloom_rationale so the teacher can review the classification.
Do NOT test any fact already covered by the previously generated questions. Pick a different fact, rule, or example from the focus chunk.
{f"The question MUST test the facts in the chunk with this chunk_id: {focus_chunk_id}. The first listed context chunk is that chunk." if focus_chunk_id else ""}
{lang_instruction}
Previously generated questions to avoid repeating:
{json.dumps(covered_questions, ensure_ascii=False)}

Curriculum context:
{context_text}
""".strip()


def _find_verbatim_subquote(
    quote: str,
    content: str,
    min_words: int = 8,
    min_chars: int = 40,
) -> str | None:
    """Find the longest contiguous word sequence from quote that appears verbatim in content."""
    words = quote.split()
    for window_len in range(len(words), min_words - 1, -1):
        for start in range(len(words) - window_len + 1):
            sub = " ".join(words[start:start + window_len])
            if len(sub) < min_chars:
                continue
            pattern = r"\s+".join(re.escape(word) for word in words[start:start + window_len])
            match = re.search(pattern, content, flags=re.IGNORECASE | re.UNICODE)
            if match and len(match.group(0)) >= min_chars:
                return match.group(0)
    return None


def _canonicalize_source_refs(source_refs: Any, context_docs: list[Any]) -> list[dict[str, Any]]:
    if not isinstance(source_refs, list) or not source_refs:
        raise InvalidSourceRefError("Question must cite at least one supporting curriculum chunk")

    documents_by_chunk = {
        str((getattr(doc, "metadata", {}) or {}).get("chunk_id")): doc
        for doc in context_docs
        if (getattr(doc, "metadata", {}) or {}).get("chunk_id")
    }
    normalized_refs: list[dict[str, Any]] = []
    seen_chunks: set[str] = set()
    for ref in source_refs:
        if not isinstance(ref, dict):
            raise InvalidSourceRefError("Each source reference must be a JSON object")
        chunk_id = str(ref.get("chunk_id", "")).strip()
        doc = documents_by_chunk.get(chunk_id)
        if doc is None:
            raise InvalidSourceRefError(
                f"Source reference chunk_id '{chunk_id}' was not provided as curriculum context"
            )
        page_content = getattr(doc, "page_content", "")
        normalized_content = " ".join(page_content.split()).casefold()
        evidence_quote = ref.get("evidence_quote")
        if not isinstance(evidence_quote, str) or len(evidence_quote.strip()) < 12:
            raise InvalidSourceRefError(
                f"Source reference '{chunk_id}' must include a useful evidence_quote"
            )
        normalized_quote = " ".join(evidence_quote.split()).casefold()
        if normalized_quote not in normalized_content:
            subquote = _find_verbatim_subquote(evidence_quote, page_content)
            if subquote:
                evidence_quote = subquote
            else:
                raise InvalidEvidenceQuoteError(
                    f"Source reference '{chunk_id}' evidence_quote is not present in its curriculum chunk"
                )
        if chunk_id not in seen_chunks:
            canonical_ref = _build_source_refs([doc])[0]
            canonical_ref["evidence_quote"] = evidence_quote.strip()
            normalized_refs.append(canonical_ref)
            seen_chunks.add(chunk_id)

    if not normalized_refs:
        raise InvalidSourceRefError("Question must cite at least one supporting curriculum chunk")
    return normalized_refs


def _send_gemini_completion(
    prompt: str,
    *,
    max_tokens: int = MAX_COMPLETION_TOKENS,
    max_attempts: int = MAX_COMPLETION_ATTEMPTS,
    temperature: float = GENERATION_TEMPERATURE,
) -> str:
    if not GEMINI_API_KEY:
        raise LLMProviderError("GEMINI_API_KEY is missing from the current project configuration")
    gemini_model = _gemini_model()

    from google import genai
    from google.genai import errors, types

    empty_response_details: list[str] = []
    client = genai.Client(api_key=GEMINI_API_KEY)
    try:
        for attempt in range(max_attempts):
            output_budget = max_tokens if attempt == 0 else RETRY_COMPLETION_TOKENS
            _throttle_client()
            _increment_llm_call_count()
            config_kwargs: dict[str, Any] = {
                "temperature": temperature,
                "max_output_tokens": output_budget,
                "response_mime_type": "application/json",
            }
            if output_budget <= 64:
                config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
            try:
                response = client.models.generate_content(
                    model=gemini_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(**config_kwargs),
                )
            except errors.APIError as exc:
                status = exc.code
                if "API_KEY_INVALID" in str(exc) or "API key not valid" in str(exc) or status in {401, 403}:
                    raise LLMProviderError(
                        "Gemini API authentication or permission failed. Verify GEMINI_API_KEY "
                        "and that the Gemini API is enabled for its Google AI Studio project."
                    ) from exc
                if status in {400, 404}:
                    raise LLMProviderError(
                        f"Gemini model '{gemini_model}' is unavailable or the request is "
                        f"unsupported (HTTP {status}). Check the model name and API access."
                    ) from exc
                if status == 429:
                    raise LLMProviderError(
                        "Gemini API quota or rate limit exceeded. Check the project's model quota "
                        "and billing in Google AI Studio, then retry."
                    ) from exc
                if status is not None and status >= 500:
                    raise LLMProviderError(f"Gemini API server error (HTTP {status}); retry later.") from exc
                detail = str(exc).replace(GEMINI_API_KEY, "[REDACTED]")
                raise ValueError(f"Gemini API request failed: {detail}") from exc

            candidates = getattr(response, "candidates", None) or []
            finish_reason = getattr(candidates[0], "finish_reason", None) if candidates else None
            finish_reason_name = getattr(finish_reason, "name", str(finish_reason or "unknown"))
            usage_metadata = getattr(response, "usage_metadata", None)
            thought_tokens = getattr(usage_metadata, "thoughts_token_count", None)
            logger.debug(
                "Gemini finish_reason=%s thought_tokens=%s",
                finish_reason_name,
                thought_tokens if thought_tokens is not None else "unavailable",
            )
            if "MAX_TOKENS" in str(finish_reason_name).upper():
                if attempt + 1 == max_attempts:
                    raise ValueError(
                        f"Gemini response stopped with MAX_TOKENS after {max_attempts} attempt(s); "
                        "increase the output token budget or shorten the prompt."
                    )
                empty_response_details.append("response stopped with MAX_TOKENS")
                continue
            content = response.text
            if isinstance(content, str) and content.strip():
                return content
            empty_response_details.append("model returned empty content")
    finally:
        client.close()

    details = ", ".join(empty_response_details)
    retry_guidance = (
        f" The retry used an {RETRY_COMPLETION_TOKENS}-token output budget."
        if max_attempts > 1
        else " No retry was attempted."
    )
    raise ValueError(
        f"Gemini returned empty assistant content after {max_attempts} attempts "
        f"({details}).{retry_guidance} Verify the model supports content generation "
        "and that the prompt was not blocked."
    )


def _send_ollama_completion(
    prompt: str,
    *,
    max_tokens: int = MAX_COMPLETION_TOKENS,
    max_attempts: int = MAX_COMPLETION_ATTEMPTS,
    temperature: float = GENERATION_TEMPERATURE,
) -> str:
    model_name = OLLAMA_MODEL_NAME or (LLM_MODEL_NAME if LLM_MODEL_NAME and not LLM_MODEL_NAME.startswith("gemini") else None) or "llama3.2"
    base_url = OLLAMA_BASE_URL or "http://localhost:11434"
    num_ctx = OLLAMA_NUM_CTX or 8192
    estimated_tokens = len(prompt) / 4
    if estimated_tokens > num_ctx * 0.75:
        logger.warning(
            "Estimated Ollama prompt size %.0f tokens exceeds 75%% of num_ctx=%d",
            estimated_tokens,
            num_ctx,
        )

    try:
        from langchain_ollama import ChatOllama
    except ImportError as exc:
        raise ImportError(
            "langchain-ollama is required for the Ollama provider. "
            "Install it with: pip install langchain-ollama"
        ) from exc

    empty_response_details: list[str] = []
    for attempt in range(max_attempts):
        try:
            llm = ChatOllama(
                model=model_name,
                base_url=base_url,
                temperature=temperature,
                format="json",
                num_ctx=num_ctx,
                num_predict=max_tokens,
            )
            _throttle_client()
            _increment_llm_call_count()
            response = llm.invoke(prompt)
            content = getattr(response, "content", "")
            if isinstance(content, list):
                content = "".join(
                    item if isinstance(item, str) else str(item.get("text", item))
                    for item in content
                )
            if isinstance(content, str) and content.strip():
                return content
            empty_response_details.append("model returned empty content")
        except Exception as exc:
            err_msg = str(exc)
            if "ConnectError" in type(exc).__name__ or "connection" in err_msg.lower() or "11434" in err_msg:
                raise ConnectionError(
                    f"Could not connect to Ollama server at '{base_url}'. "
                    "Ensure the Ollama service is running (e.g., 'ollama serve')."
                ) from exc
            if "not found" in err_msg.lower() or "404" in err_msg:
                raise LLMProviderError(
                    f"Ollama model '{model_name}' was not found on the server at '{base_url}'. "
                    f"Download it using: ollama pull {model_name}"
                ) from exc
            status = getattr(exc, "status_code", None)
            if status in {401, 403} or "unauthorized" in err_msg.lower() or "forbidden" in err_msg.lower():
                raise LLMProviderError(f"Ollama authentication or permission failed: {err_msg}") from exc
            if status == 429 or "rate limit" in err_msg.lower() or "quota" in err_msg.lower():
                raise LLMProviderError(f"Ollama quota or rate limit exceeded: {err_msg}") from exc
            if (isinstance(status, int) and status >= 500) or "server error" in err_msg.lower():
                raise LLMProviderError(f"Ollama server error: {err_msg}") from exc
            if attempt + 1 == max_attempts:
                raise ValueError(f"Ollama generation failed: {err_msg}") from exc

    details = ", ".join(empty_response_details)
    retry_guidance = (
        f" (after {max_attempts} attempts)"
        if max_attempts > 1
        else " No retry was attempted."
    )
    raise ValueError(
        f"Ollama returned empty assistant content after {max_attempts} attempts "
        f"({details}).{retry_guidance} Verify the model supports JSON content generation."
    )


def _build_ssl_context() -> Any:
    """
    Builds an SSLContext that validates against both certifi CA certificates
    and the host operating system's root certificate store (e.g. Windows ROOT,
    antivirus HTTPS inspection like Avast/Kaspersky, or enterprise proxies)
    without compromising TLS certificate verification.
    """
    import ssl
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
            ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)
            return ctx
        except Exception:
            return True


def _send_groq_completion(
    prompt: str,
    *,
    max_tokens: int = MAX_COMPLETION_TOKENS,
    max_attempts: int = MAX_COMPLETION_ATTEMPTS,
    temperature: float = GENERATION_TEMPERATURE,
) -> str:
    if not GROQ_API_KEY:
        raise LLMProviderError("GROQ_API_KEY is missing from the current project configuration")
    model = GROQ_MODEL_NAME or LLM_MODEL_NAME or "openai/gpt-oss-20b"
    base_url = (GROQ_BASE_URL or "https://api.groq.com/openai/v1").rstrip("/")

    import httpx

    empty_response_details: list[str] = []
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }

    ssl_context = _build_ssl_context()
    with httpx.Client(timeout=60.0, verify=ssl_context) as client:
        rate_limit_attempt = 0
        for attempt in range(max_attempts):
            response = None
            output_budget = max_tokens if attempt == 0 else RETRY_COMPLETION_TOKENS
            payload = {
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a helpful educational assessment assistant that outputs valid JSON only.",
                    },
                    {"role": "user", "content": prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": temperature,
                "max_completion_tokens": output_budget,
            }
            while True:
                _throttle_client()
                _increment_llm_call_count()
                try:
                    response = client.post(
                        f"{base_url}/chat/completions",
                        headers=headers,
                        json=payload,
                    )
                except Exception as exc:
                    sanitized_exc = str(exc).replace(GROQ_API_KEY, "[REDACTED]")
                    if attempt + 1 == max_attempts:
                        raise LLMProviderError(f"Groq network or connection error: {sanitized_exc}") from exc
                    empty_response_details.append(f"connection error ({sanitized_exc})")
                    break

                status = response.status_code
                if status == 429:
                    err_msg = response.text.replace(GROQ_API_KEY, "[REDACTED]")
                    wait_sec = min(_parse_retry_after(response.headers), MAX_BACKOFF_WAIT_SECONDS)
                    if rate_limit_attempt < MAX_429_RETRIES and wait_sec <= MAX_BACKOFF_WAIT_SECONDS:
                        logger.warning(
                            "Groq rate limit hit (HTTP 429). Backing off for %.2f seconds (attempt %d/%d)...",
                            wait_sec,
                            rate_limit_attempt + 1,
                            MAX_429_RETRIES,
                        )
                        time.sleep(wait_sec)
                        rate_limit_attempt += 1
                        continue
                    raise LLMProviderError(
                        f"Groq quota or rate limit exceeded, retry in {wait_sec:.1f} seconds. Details: {err_msg}"
                    )
                break

            if response is None:
                continue

            if status in {401, 403}:
                raise LLMProviderError(
                    "Groq API authentication or permission failed. Verify GROQ_API_KEY "
                    "in your environment."
                )
            if status in {400, 404}:
                err_msg = response.text.replace(GROQ_API_KEY, "[REDACTED]")
                raise LLMProviderError(
                    f"Groq model '{model}' is unavailable or the request is unsupported (HTTP {status}): {err_msg}"
                )
            if status >= 500:
                raise LLMProviderError(f"Groq API server error (HTTP {status}); retry later.")
            if status != 200:
                err_msg = response.text.replace(GROQ_API_KEY, "[REDACTED]")
                raise ValueError(f"Groq API request failed (HTTP {status}): {err_msg}")

            try:
                data = response.json()
            except Exception as exc:
                if attempt + 1 == max_attempts:
                    raise ValueError("Groq returned non-JSON response payload") from exc
                empty_response_details.append("invalid JSON response payload")
                continue

            choices = data.get("choices") or []
            if not choices:
                empty_response_details.append("no choices returned")
                continue

            choice = choices[0]
            finish_reason = str(choice.get("finish_reason", "")).lower()
            if finish_reason in {"length", "max_tokens"}:
                if attempt + 1 == max_attempts:
                    raise ValueError(
                        f"Groq response stopped with MAX_TOKENS after {max_attempts} attempt(s); "
                        "increase the output token budget or shorten the prompt."
                    )
                empty_response_details.append("response stopped with MAX_TOKENS")
                continue

            content = choice.get("message", {}).get("content", "")
            if isinstance(content, str) and content.strip():
                return content
            empty_response_details.append("model returned empty content")

    details = ", ".join(empty_response_details)
    retry_guidance = (
        f" The retry used an {RETRY_COMPLETION_TOKENS}-token output budget."
        if max_attempts > 1
        else " No retry was attempted."
    )
    raise ValueError(
        f"Groq returned empty assistant content after {max_attempts} attempts "
        f"({details}).{retry_guidance} Verify the model supports JSON content generation."
    )


def _invoke_provider_completion(
    provider: str,
    prompt: str,
    *,
    max_tokens: int,
    max_attempts: int,
    temperature: float,
) -> tuple[str, str, str]:
    if provider == "ollama":
        model = OLLAMA_MODEL_NAME or (LLM_MODEL_NAME if LLM_MODEL_NAME and not LLM_MODEL_NAME.startswith("gemini") else None) or "llama3.2"
        content = _send_ollama_completion(prompt, max_tokens=max_tokens, max_attempts=max_attempts, temperature=temperature)
    elif provider == "groq":
        model = GROQ_MODEL_NAME or LLM_MODEL_NAME or "openai/gpt-oss-20b"
        content = _send_groq_completion(prompt, max_tokens=max_tokens, max_attempts=max_attempts, temperature=temperature)
    elif provider == "gemini":
        model = _gemini_model()
        content = _send_gemini_completion(prompt, max_tokens=max_tokens, max_attempts=max_attempts, temperature=temperature)
    else:
        raise ValueError(f"Unsupported provider: {provider}")
    return content, provider, model


def _send_completion(
    prompt: str,
    *,
    max_tokens: int = MAX_COMPLETION_TOKENS,
    max_attempts: int = MAX_COMPLETION_ATTEMPTS,
    temperature: float = GENERATION_TEMPERATURE,
) -> str:
    global _LAST_USED_METADATA
    if LLM_PROVIDER not in {"gemini", "ollama", "groq"}:
        raise ValueError("LLM_PROVIDER must be 'gemini', 'ollama', or 'groq'")
    if max_tokens < 1 or max_attempts < 1:
        raise ValueError("max_tokens and max_attempts must be positive")

    providers = [LLM_PROVIDER]
    for fb in LLM_FALLBACK_PROVIDERS:
        if fb in {"gemini", "ollama", "groq"} and fb not in providers:
            providers.append(fb)

    last_exc: Exception | None = None
    for idx, prov in enumerate(providers):
        try:
            content, used_prov, used_model = _invoke_provider_completion(
                prov,
                prompt,
                max_tokens=max_tokens,
                max_attempts=max_attempts,
                temperature=temperature,
            )
            _LAST_USED_METADATA = {"provider": used_prov, "model": used_model}
            return content
        except Exception as exc:
            err_text = str(exc).lower()
            is_auth_error = any(w in err_text for w in ("authentication", "permission", "api_key", "401", "403"))
            if is_auth_error or idx + 1 == len(providers):
                raise
            logger.warning("Provider '%s' encountered error: %s. Falling back to '%s'...", prov, exc, providers[idx + 1])
            last_exc = exc
    if last_exc:
        raise last_exc
    raise ValueError("No LLM provider available")


def test_ollama_connection(
    model: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Make exactly one minimal request to check Ollama model access."""
    target_model = model or OLLAMA_MODEL_NAME or (LLM_MODEL_NAME if LLM_MODEL_NAME and not LLM_MODEL_NAME.startswith("gemini") else None) or "llama3.2"
    target_base_url = base_url or OLLAMA_BASE_URL or "http://localhost:11434"

    try:
        from langchain_ollama import ChatOllama
        llm = ChatOllama(
            model=target_model,
            base_url=target_base_url,
            temperature=0,
            format="json",
            num_ctx=2048,
        )
        response = llm.invoke('Return this JSON only: {"status":"READY"}.')
        content = getattr(response, "content", "")
        return {
            "ok": True,
            "provider": "ollama",
            "model": target_model,
            "base_url": target_base_url,
            "content": content,
        }
    except Exception as exc:
        err_msg = str(exc)
        if "ConnectError" in type(exc).__name__ or "connection" in err_msg.lower():
            raise ConnectionError(
                f"Could not connect to Ollama server at '{target_base_url}'. "
                "Ensure Ollama is running ('ollama serve')."
            ) from exc
        raise ValueError(f"Ollama connection check failed: {exc}") from exc


def test_gemini_connection() -> dict[str, Any]:
    """Make exactly one minimal request to check Gemini model access."""
    content = _send_gemini_completion(
        'Return this JSON only: {"status":"READY"}.',
        max_tokens=16,
        max_attempts=1,
        temperature=0,
    )
    return {"ok": True, "provider": "gemini", "model": _gemini_model(), "content": content}


def test_groq_connection(model: str | None = None) -> dict[str, Any]:
    """Make exactly one minimal request to check Groq model access."""
    target_model = model or GROQ_MODEL_NAME or LLM_MODEL_NAME or "openai/gpt-oss-120b"
    content = _send_groq_completion(
        'Return this JSON object only: {"status":"READY"}.',
        max_tokens=64,
        max_attempts=1,
        temperature=0,
    )
    return {"ok": True, "provider": "groq", "model": target_model, "content": content}


def test_llm_connection() -> dict[str, Any]:
    """Check connectivity to whichever LLM provider is active."""
    if LLM_PROVIDER == "ollama":
        return test_ollama_connection()
    elif LLM_PROVIDER == "groq":
        return test_groq_connection()
    return test_gemini_connection()

def generate_single_question(
    topic: str,
    question_type: str,
    context_docs: list[Any],
    difficulty: str = "medium",
    bloom_level: str = "apply",
    custom_prompt: str | None = None,
    previous_questions: list[str | dict[str, str]] | None = None,
    focus_chunk_id: str | None = None,
    temperature: float = GENERATION_TEMPERATURE,
    correction_message: str | None = None,
    language: str = "en",
) -> dict[str, Any]:
    if question_type not in VALID_QUESTION_TYPES:
        raise ValueError(f"Unsupported question type: {question_type}")
    if difficulty not in VALID_DIFFICULTY:
        raise ValueError(f"Unsupported difficulty: {difficulty}")
    if bloom_level not in VALID_BLOOM_LEVELS:
        raise ValueError(f"Unsupported Bloom level: {bloom_level}")

    if not context_docs:
        raise ValueError("No curriculum context available for generation")

    prompt = _build_prompt(
        question_type,
        topic,
        difficulty,
        bloom_level,
        context_docs,
        custom_prompt,
        previous_questions,
        focus_chunk_id,
        language=language,
    )
    retry_correction = correction_message
    for attempt in range(MAX_QUESTION_GENERATION_ATTEMPTS):
        response_prompt = prompt
        if retry_correction:
            response_prompt += f"\n\nCorrection required: {retry_correction}"
        raw_response = _send_completion(response_prompt, temperature=temperature)
        try:
            parsed = _extract_json_object(raw_response)
        except json.JSONDecodeError as exc:
            if attempt + 1 == MAX_QUESTION_GENERATION_ATTEMPTS:
                raise ValueError(
                    "The model returned invalid JSON twice "
                    f"(last error at line {exc.lineno}, column {exc.colno}). "
                    "Try again or choose a different LLM_MODEL_NAME."
                ) from exc
            retry_correction = (
                "Your previous response was not valid JSON "
                f"(parser error at line {exc.lineno}, column {exc.colno}). "
                "Return exactly one complete JSON object matching the required schema. "
                "Do not include markdown fences, comments, trailing commas, or text before or after the JSON."
            )
            continue
        actual_qtype = str(parsed.get("question_type", "")).strip().lower()
        if actual_qtype != question_type:
            if attempt + 1 == MAX_QUESTION_GENERATION_ATTEMPTS:
                raise ValueError("Model returned a question type different from the requested type")
            retry_correction = f"Your previous response had question_type='{actual_qtype}'. You MUST generate a '{question_type}' question."
            continue

        actual_diff = str(parsed.get("difficulty", "")).strip().lower()
        if actual_diff != difficulty:
            if attempt + 1 == MAX_QUESTION_GENERATION_ATTEMPTS:
                parsed["difficulty"] = difficulty
            else:
                retry_correction = f"Your previous response had difficulty='{actual_diff}'. You MUST generate a '{difficulty}' difficulty question."
                continue

        actual_bloom = str(parsed.get("bloom_level", "")).strip().lower()
        if actual_bloom != bloom_level:
            if attempt + 1 == MAX_QUESTION_GENERATION_ATTEMPTS:
                parsed["bloom_level"] = bloom_level
            else:
                retry_correction = f"Your previous response had bloom_level='{actual_bloom}'. You MUST generate a '{bloom_level}'-level question."
                continue

        if not isinstance(parsed.get("bloom_rationale"), str) or not parsed["bloom_rationale"].strip():
            if attempt + 1 == MAX_QUESTION_GENERATION_ATTEMPTS:
                raise ValueError("Model response must explain the requested Bloom level")
            retry_correction = "You must provide a non-empty 'bloom_rationale' explaining the cognitive task."
            continue

        try:
            parsed["source_refs"] = _canonicalize_source_refs(parsed.get("source_refs"), context_docs)
            if focus_chunk_id and focus_chunk_id not in {
                str(ref.get("chunk_id", "")) for ref in parsed["source_refs"]
            }:
                raise InvalidSourceRefError(
                    f"Question must cite its focus chunk '{focus_chunk_id}'"
                )
        except InvalidSourceRefError as exc:
            if attempt + 1 == MAX_QUESTION_GENERATION_ATTEMPTS:
                raise
            if isinstance(exc, InvalidEvidenceQuoteError):
                retry_correction = (
                    "Your previous response cited an evidence_quote that was not copied exactly from its "
                    "curriculum chunk. Generate the question again and include only a short, verbatim quote "
                    "copied exactly from the matching chunk shown below. Do not paraphrase or change punctuation."
                )
            else:
                retry_correction = (
                    f"Your previous response had an invalid source reference ({exc}). Cite a provided chunk "
                    "with a useful verbatim evidence_quote."
                )
            continue
        if question_type == "mcq":
            parsed["rubric"] = [
                {
                    "criterion": "Correct selected answer",
                    "points": 1,
                    "description": "Correct option = 1 point; incorrect or unanswered = 0 points.",
                }
            ]
            parsed["max_score"] = 1
            options = parsed.get("options") or []
            correct_key = str(parsed.get("correct_answer", "")).strip().upper()
            if correct_key in {"1", "2", "3", "4"} and len(options) == 4:
                correct_key = "ABCD"[int(correct_key) - 1]
                parsed["correct_answer"] = correct_key
            if correct_key in {"A", "B", "C", "D"} and len(options) == 4:
                cleaned_options = [
                    re.sub(r"^\s*[A-D1-4][\s.):\-]+", "", str(opt)).strip()
                    for opt in options
                ]
                if (
                    len(cleaned_options) == 4
                    and all(cleaned_options)
                    and len({opt.casefold() for opt in cleaned_options}) == 4
                ):
                    options = cleaned_options
                    parsed["options"] = cleaned_options

                selected_text = options["ABCD".index(correct_key)].strip()
                parsed["reference_answer"] = f"{correct_key}: {selected_text}"
        else:
            rubric = parsed.get("rubric")
            if isinstance(rubric, list) and rubric:
                rubric_sum = sum(item.get("points", 0) for item in rubric if isinstance(item, dict))
                if rubric_sum > 0:
                    parsed["max_score"] = rubric_sum

        meta = get_last_llm_metadata()
        if meta.get("provider"):
            parsed["provider"] = meta["provider"]
        if meta.get("model"):
            parsed["model"] = meta["model"]
        _validate_question(parsed)
        return parsed
    raise RuntimeError("Question generation ended without a result")


QUESTION_BOILERPLATE_WORDS = {
    "which", "of", "the", "following", "is", "are", "a", "an", "what", "how", "why",
    "when", "where", "who", "whom", "this", "that", "these", "those", "best", "describes",
    "according", "to", "curriculum", "lesson", "statements", "statement", "true", "false",
    "correct", "incorrect", "explain", "describe", "identify", "analyze", "in", "on", "at",
    "by", "for", "with", "about", "from", "and", "or", "not", "does", "do", "did",
    # Arabic question boilerplate
    "ما", "ماذا", "من", "كيف", "لماذا", "أي", "التي", "الذي", "في", "على", "من", "عن",
    "إلى", "مع", "هذا", "هذه", "الصحيحة", "الخاطئة", "وفقا", "للدرس"
}


def _question_tokens(text: str, remove_stopwords: bool = True) -> set[str]:
    tokens = set(re.findall(r"\w+", text.casefold(), flags=re.UNICODE))
    if remove_stopwords:
        content_tokens = tokens - QUESTION_BOILERPLATE_WORDS
        if len(content_tokens) >= 2:
            return content_tokens
    return tokens


def _jaccard_similarity(left: str, right: str) -> float:
    left_tokens = _question_tokens(left)
    right_tokens = _question_tokens(right)
    union = left_tokens | right_tokens
    return len(left_tokens & right_tokens) / len(union) if union else 0.0


def _find_similar_previous_question(
    new_question: dict[str, Any],
    previous: list[dict[str, Any]],
    threshold: float = 0.55,
) -> dict[str, Any] | None:
    new_text = str(new_question.get("question", ""))
    new_with_answer = f"{new_text} {new_question.get('reference_answer', '')}"
    for earlier in previous:
        earlier_text = str(earlier.get("question", ""))
        earlier_with_answer = f"{earlier_text} {earlier.get('reference_answer', '')}"
        if (
            _jaccard_similarity(new_text, earlier_text) >= threshold
            or _jaccard_similarity(new_with_answer, earlier_with_answer) >= threshold
        ):
            return earlier
    return None


def _is_duplicate_question(
    new_question: dict[str, Any],
    previous: list[dict[str, Any]],
    threshold: float = 0.55,
) -> bool:
    return _find_similar_previous_question(new_question, previous, threshold) is not None


def _verify_mcq_answer(question: dict[str, Any], context_docs: list[Any]) -> bool:
    context_sections = []
    for doc in context_docs[:MAX_CONTEXT_CHUNKS]:
        content = doc.page_content if hasattr(doc, "page_content") else str(doc)
        if len(content) > MAX_CHUNK_CHARS:
            chunk_id = (getattr(doc, "metadata", {}) or {}).get("chunk_id", "unknown")
            logger.warning(
                "Truncated curriculum chunk %s for MCQ verification from %d to %d characters",
                chunk_id,
                len(content),
                MAX_CHUNK_CHARS,
            )
        context_sections.append(content[:MAX_CHUNK_CHARS])
    context_text = "\n\n---\n\n".join(context_sections)
    prompt = f"""
Independently answer the curriculum-grounded multiple-choice question using only the context.
Return valid JSON only with exactly these fields: {{"answer":"A|B|C|D","supported":true|false}}.
Set supported to true only if the context supports the selected answer and does not support another option.

Context:
{context_text}

Question:
{question["question"]}

Options:
{json.dumps(question["options"], ensure_ascii=False)}
""".strip()
    response = _send_completion(prompt, temperature=0)
    try:
        result = _extract_json_object(response)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("MCQ answer verification response was invalid: %s", exc)
        return False
    answer = str(result.get("answer", "")).strip().upper()
    return answer == question.get("correct_answer") and result.get("supported") is True


def load_curriculum_store(
    persist_dir: str | Path | None = None,
    collection_name: str = "curriculum",
    embedding_model: str | None = None,
) -> Any:
    store_dir = resolve_vectorstore_dir(persist_dir)
    if not store_dir.exists():
        raise FileNotFoundError(f"Vector store directory not found: {store_dir}")

    model_name = (
        embedding_model
        or os.getenv("HF_EMBEDDING_MODEL_NAME")
        or HF_EMBEDDING_MODEL_NAME
        or os.getenv("EMBEDDING_MODEL_NAME")
    )
    embeddings = get_embeddings(model_name=model_name)
    return load_vectorstore(embeddings, persist_dir=store_dir, collection_name=collection_name)


def retrieve_curriculum_context(
    topic: str,
    persist_dir: str | Path | None = None,
    collection_name: str = "curriculum",
    k: int = MAX_CONTEXT_CHUNKS,
    embedding_model: str | None = None,
    lesson_id: str | None = None,
) -> list[Any]:
    store = load_curriculum_store(persist_dir=persist_dir, collection_name=collection_name, embedding_model=embedding_model)
    requested_k = k
    collection = getattr(store, "_collection", None)
    if lesson_id is not None and collection is not None:
        records = collection.get(
            where={"lesson_id": str(lesson_id)},
            include=["metadatas"],
        )
        metadata_records = records.get("metadatas") or []
        chunk_ids = {
            str(metadata["chunk_id"])
            for metadata in metadata_records
            if metadata and metadata.get("chunk_id")
        }
        if chunk_ids:
            requested_k = min(k, len(chunk_ids))
    docs = retrieve(store, query=topic, k=requested_k, lesson_id=lesson_id)
    if not docs:
        if lesson_id:
            raise ValueError(f"No curriculum chunks found for lesson '{lesson_id}' and topic '{topic}'")
        raise ValueError(f"No curriculum chunks found for topic '{topic}'")
    return docs


def list_curriculum_lessons(store: Any) -> list[dict[str, Any]]:
    """List unique lesson choices and chunk counts from an already-loaded store."""
    records = store._collection.get(include=["metadatas"])
    lessons: dict[str, dict[str, Any]] = {}
    for metadata in records.get("metadatas") or []:
        if not metadata or not metadata.get("lesson_id"):
            continue
        lesson_id = str(metadata["lesson_id"])
        lesson = lessons.setdefault(
            lesson_id,
            {
                "lesson_id": lesson_id,
                "lesson_title": metadata.get("lesson_title") or lesson_id,
                "chapter_id": metadata.get("chapter_id"),
                "chapter_title": metadata.get("chapter_title"),
                "chunk_count": 0,
            },
        )
        lesson["chunk_count"] += 1
    if not lessons:
        raise ValueError("The curriculum collection does not contain lesson metadata")
    return sorted(lessons.values(), key=lambda lesson: lesson["lesson_id"])


def _build_question_type_sequence(
    question_types: list[str] | None,
    number_of_questions: int,
) -> list[str]:
    selected_types = question_types or DEFAULT_QUESTION_TYPES
    normalized_types: list[str] = []
    for question_type in selected_types:
        normalized = str(question_type).strip().lower()
        if normalized not in VALID_QUESTION_TYPES:
            raise ValueError(f"Unsupported question type '{question_type}'")
        if normalized not in normalized_types:
            normalized_types.append(normalized)
    if not normalized_types:
        raise ValueError("Select at least one question type")
    return [
        normalized_types[index % len(normalized_types)]
        for index in range(number_of_questions)
    ]


def validate_exam(exam: dict[str, Any]) -> None:
    """Validate an exam before it is displayed or persisted."""
    if not isinstance(exam, dict) or not isinstance(exam.get("questions"), list):
        raise ValueError("Exam must be an object containing a questions list")
    if not exam["questions"]:
        raise ValueError("Exam must contain at least one question")
    if "warnings" in exam and (
        not isinstance(exam["warnings"], list)
        or any(not isinstance(warning, str) for warning in exam["warnings"])
    ):
        raise ValueError("Exam warnings must be a list of strings")
    question_count = exam.get("question_count")
    if (
        isinstance(question_count, bool)
        or not isinstance(question_count, int)
        or question_count != len(exam["questions"])
    ):
        raise ValueError("Exam question_count does not match its questions")
    question_ids = [
        question.get("question_id")
        for question in exam["questions"]
        if isinstance(question, dict)
    ]
    if (
        len(question_ids) != len(exam["questions"])
        or any(not isinstance(question_id, str) or not question_id.strip() for question_id in question_ids)
        or len(set(question_ids)) != len(question_ids)
    ):
        raise ValueError("Exam question IDs must be present and unique")
    lesson_id = exam.get("lesson_id")
    if not isinstance(lesson_id, str) or not lesson_id.strip():
        raise ValueError("Exam must identify the selected lesson")
    for index, question in enumerate(exam["questions"], start=1):
        try:
            _validate_question(question)
            if question.get("lesson_id") != lesson_id:
                raise ValueError("Question lesson_id does not match the exam lesson")
            if question.get("difficulty") != exam.get("difficulty"):
                raise ValueError("Question difficulty does not match the exam difficulty")
            if question.get("bloom_level") != exam.get("bloom_level"):
                raise ValueError("Question Bloom level does not match the exam Bloom level")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Question {index} is invalid: {exc}") from exc
    expected_total = sum(question["max_score"] for question in exam["questions"])
    total_points = exam.get("total_points")
    if (
        isinstance(total_points, bool)
        or not isinstance(total_points, (int, float))
        or total_points != expected_total
    ):
        raise ValueError("Exam total_points does not match the sum of its question rubrics")


def save_exam(exam: dict[str, Any], output_dir: str | Path | None = None) -> Path:
    """Validate and save an exam without replacing any existing output."""
    validate_exam(exam)
    destination = Path(output_dir) if output_dir is not None else OUTPUTS_DIR
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    for _ in range(10):
        output_path = destination / f"exam_{timestamp}_{os.urandom(4).hex()}.json"
        try:
            with output_path.open("x", encoding="utf-8") as fh:
                json.dump(exam, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            return output_path
        except FileExistsError:
            continue
    raise FileExistsError(f"Could not allocate a unique exam filename in {destination}")


def generate_exam(
    topic: str,
    question_types: list[str] | None = None,
    number_of_questions: int = 10,
    difficulty: str = "medium",
    bloom_level: str = "apply",
    persist_dir: str | Path | None = None,
    collection_name: str = "curriculum",
    output_dir: str | Path | None = None,
    context_docs: list[Any] | None = None,
    lesson_id: str | None = None,
    allow_partial: bool = False,
    verify_answers: bool | None = None,
    language: str = "en",
) -> tuple[dict[str, Any], Path]:
    """Generate and save a complete exam, optionally verifying each MCQ with one extra LLM call."""
    if verify_answers is None:
        verify_answers = VERIFY_MCQ_ANSWERS
    start_calls = get_llm_call_count()

    ok, missing, model_name = validate_configuration()
    if not ok:
        raise ValueError(f"Missing required config values: {', '.join(missing)}")

    if (
        isinstance(number_of_questions, bool)
        or not isinstance(number_of_questions, int)
        or number_of_questions < 1
    ):
        raise ValueError("number_of_questions must be a positive integer")
    if not topic.strip():
        raise ValueError("topic must not be empty")
    if not lesson_id or not str(lesson_id).strip():
        raise ValueError("lesson_id is required; select a curriculum lesson before generating an exam")
    if difficulty not in VALID_DIFFICULTY:
        raise ValueError(f"Unsupported difficulty: {difficulty}")
    if bloom_level not in VALID_BLOOM_LEVELS:
        raise ValueError(f"Unsupported Bloom level: {bloom_level}")

    requested = _build_question_type_sequence(question_types, number_of_questions)

    if context_docs is None:
        context_docs = retrieve_curriculum_context(
            topic=topic,
            persist_dir=persist_dir,
            collection_name=collection_name,
            k=max(MAX_CONTEXT_CHUNKS, number_of_questions),
            lesson_id=lesson_id,
        )
    elif not context_docs:
        raise ValueError("No curriculum context available for generation")
    if lesson_id:
        mismatched_docs = [
            doc for doc in context_docs
            if str((getattr(doc, "metadata", {}) or {}).get("lesson_id")) != str(lesson_id)
        ]
        if mismatched_docs:
            raise ValueError(
                f"Retrieved context contains chunks outside the selected lesson '{lesson_id}'"
            )

    unique_context_docs: list[Any] = []
    seen_chunk_ids: set[str] = set()
    for doc in context_docs:
        chunk_id = str((getattr(doc, "metadata", {}) or {}).get("chunk_id", "")).strip()
        if not chunk_id:
            continue
        if chunk_id not in seen_chunk_ids:
            unique_context_docs.append(doc)
            seen_chunk_ids.add(chunk_id)
    if not unique_context_docs:
        raise ValueError("No curriculum chunks with unique chunk_ids are available for generation")

    lesson_chunk_count = len(unique_context_docs)
    retrieved_chunk_ids = sorted(seen_chunk_ids)
    logger.info(
        "Exam generation lesson_id=%s lesson_chunk_count=%d docs_retrieved=%d unique_chunk_ids=%d",
        lesson_id,
        lesson_chunk_count,
        len(context_docs),
        len(retrieved_chunk_ids),
    )
    warnings: list[str] = []
    if lesson_chunk_count < number_of_questions:
        warnings.append(
            f"Only {lesson_chunk_count} unique curriculum chunks were available for "
            f"{number_of_questions} requested questions."
        )
    questions: list[dict[str, Any]] = []
    previous_questions: list[dict[str, Any]] = []
    for idx, q_type in enumerate(requested, start=1):
        focus_doc = unique_context_docs[(idx - 1) % lesson_chunk_count]
        focus_chunk_id = str(focus_doc.metadata["chunk_id"])
        question_context = [focus_doc] + [
            doc for doc in unique_context_docs if doc is not focus_doc
        ][:3]
        retry_correction: str | None = None
        temperature = GENERATION_TEMPERATURE
        for attempt in range(1, MAX_PER_QUESTION_RETRIES + 1):
            similar_question: dict[str, Any] | None = None
            try:
                question = generate_single_question(
                    topic=topic,
                    question_type=q_type,
                    context_docs=question_context,
                    difficulty=difficulty,
                    bloom_level=bloom_level,
                    previous_questions=previous_questions,
                    focus_chunk_id=focus_chunk_id,
                    temperature=temperature,
                    correction_message=retry_correction,
                    language=language,
                )
                _validate_question(question)
                similar_question = _find_similar_previous_question(question, previous_questions)
                if similar_question:
                    raise ValueError(
                        f"Question duplicates earlier question: {similar_question['question']}"
                    )
                if q_type == "mcq" and verify_answers:
                    if not _verify_mcq_answer(question, question_context):
                        raise ValueError("MCQ answer failed independent verification")
                    question["verified"] = True
                question["question_id"] = f"Q{len(questions) + 1:02d}"
                question["lesson_id"] = lesson_id
                _validate_question(question)
                questions.append(question)
                previous_questions.append(
                    {
                        "question": question["question"],
                        "reference_answer": question["reference_answer"][:150],
                    }
                )
                cited_chunk_ids = [
                    ref["chunk_id"] for ref in question.get("source_refs", [])
                ]
                logger.info(
                    "Generated question index=%d type=%s chunk_ids=%s question=%s",
                    len(questions),
                    q_type,
                    cited_chunk_ids,
                    question["question"][:80],
                )
                break
            except LLMProviderError:
                raise
            except ConnectionError:
                raise
            except ValueError as exc:
                if similar_question:
                    retry_correction = (
                        f"The candidate was too similar to this earlier question: "
                        f"{similar_question['question']!r}. Demand a different fact, rule, or example "
                        "from the focus chunk."
                    )
                    temperature = min(0.9, temperature + 0.2)
                else:
                    retry_correction = (
                        f"The previous attempt failed validation: {exc}. Generate a valid, "
                        "curriculum-supported question with valid source references."
                    )
                if attempt == MAX_PER_QUESTION_RETRIES:
                    if allow_partial:
                        warnings.append(
                            f"Question Q{idx:02d} was skipped after {MAX_PER_QUESTION_RETRIES} "
                            f"attempts: {exc}"
                        )
                        logger.warning("Skipping failed question Q%02d: %s", idx, exc)
                        break
                    raise ValueError(
                        f"Q{idx:02d} failed after {MAX_PER_QUESTION_RETRIES} attempts: {exc}"
                    ) from exc
        else:
            raise RuntimeError(f"Question generation retry loop ended unexpectedly for Q{idx:02d}")

    if not questions:
        raise ValueError("All questions failed generation; no exam was saved.")

    exam = {
        "exam_title": f"{topic.title()} Assessment",
        "topic": topic,
        "lesson_id": lesson_id,
        "language": language,
        "lesson_title": next(
            (
                (getattr(doc, "metadata", {}) or {}).get("lesson_title")
                for doc in context_docs
                if (getattr(doc, "metadata", {}) or {}).get("lesson_title")
            ),
            None,
        ),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "provider": LLM_PROVIDER,
        "model": model_name,
        "llm_calls_made": get_llm_call_count() - start_calls,
        "question_count": len(questions),
        "total_points": sum(question["max_score"] for question in questions),
        "difficulty": difficulty,
        "bloom_level": bloom_level,
        "questions": questions,
        "warnings": warnings,
    }

    validate_exam(exam)
    output_path = save_exam(exam, output_dir)
    calls_used = exam["llm_calls_made"]
    logger.info(
        "Exam generation complete: %d questions created with %d LLM calls (provider=%s, model=%s)",
        len(questions),
        calls_used,
        LLM_PROVIDER,
        model_name,
    )
    return exam, output_path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a curriculum-grounded assessment from the project RAG store.")
    parser.add_argument("--topic", required=True, help="Curriculum topic within the selected lesson")
    parser.add_argument("--lesson-id", required=True, help="Selected curriculum lesson, e.g. 1-3")
    parser.add_argument("--question-type", action="append", choices=sorted(VALID_QUESTION_TYPES), default=None, help="Question type to generate. Repeat for multiple questions.")
    parser.add_argument("--number-of-questions", type=int, default=10, help="Number of questions to generate")
    parser.add_argument("--difficulty", choices=sorted(VALID_DIFFICULTY), default="medium")
    parser.add_argument("--bloom-level", choices=sorted(VALID_BLOOM_LEVELS), default="apply")
    parser.add_argument("--persist-dir", default=None, help="Path to the Chroma persist directory")
    parser.add_argument("--collection-name", default="curriculum", help="Collection name used in the Chroma store")
    return parser


if __name__ == "__main__":
    parser = _build_parser()
    args = parser.parse_args()
    try:
        exam, output_path = generate_exam(
            topic=args.topic,
            question_types=args.question_type,
            number_of_questions=args.number_of_questions,
            difficulty=args.difficulty,
            bloom_level=args.bloom_level,
            persist_dir=args.persist_dir,
            collection_name=args.collection_name,
            lesson_id=args.lesson_id,
        )
        print(f"Generated exam: {output_path.name}")
        print(f"Question count: {exam['question_count']}")
    except (ValueError, OSError, RuntimeError) as exc:  # pragma: no cover - CLI safety
        print(f"Exam generation failed: {exc}")
        sys.exit(1)
