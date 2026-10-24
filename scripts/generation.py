"""Safe exam generation for the Intelligent Educational Assessment System.

This module retrieves curriculum-grounded context from the existing Chroma vector
store, generates exam questions through the Google Gemini API, validates
structured output, and saves generated assessments under outputs/ without
overwriting earlier files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

_root_dir = Path(__file__).resolve().parent.parent
if str(_root_dir) not in sys.path:
    sys.path.insert(0, str(_root_dir))

from typing import Any, Iterable
from scripts.config import (
    BASE_DIR,
    GEMINI_API_KEY,
    HF_EMBEDDING_MODEL_NAME,
    LLM_MODEL_NAME,
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL_NAME,
    OLLAMA_NUM_CTX,
    OUTPUTS_DIR,
    VECTOR_DB_PATH,
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
MAX_COMPLETION_ATTEMPTS = 2
MAX_COMPLETION_TOKENS = 4096
RETRY_COMPLETION_TOKENS = 8192
MAX_QUESTION_GENERATION_ATTEMPTS = 2


class InvalidEvidenceQuoteError(ValueError):
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
    if LLM_PROVIDER not in {"gemini", "ollama"}:
        missing.append("LLM_PROVIDER must be 'gemini' or 'ollama'")
    if LLM_PROVIDER == "gemini":
        if not GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")
        if not LLM_MODEL_NAME:
            missing.append("LLM_MODEL_NAME")
        model = LLM_MODEL_NAME
    elif LLM_PROVIDER == "ollama":
        model = LLM_MODEL_NAME or OLLAMA_MODEL_NAME
        if not model:
            missing.append("LLM_MODEL_NAME or OLLAMA_MODEL_NAME")
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
        or len(ref["evidence_quote"].strip()) < 12
        for ref in question["source_refs"]
    ):
        raise ValueError("Each source reference must identify a source, chunk, and evidence quote")

    if q_type == "mcq":
        options = question.get("options")
        if (
            not isinstance(options, list)
            or len(options) != 4
            or any(not isinstance(option, str) or not option.strip() for option in options)
        ):
            raise ValueError("MCQs require exactly four options")
        if len({option.strip().casefold() for option in options}) != 4:
            raise ValueError("MCQ options must be distinct")
        if "correct_answer" not in question:
            raise ValueError("MCQ missing correct_answer")
        correct = str(question["correct_answer"]).strip().upper()
        if correct not in {"A", "B", "C", "D", "1", "2", "3", "4"}:
            raise ValueError("Correct answer must be one of A/B/C/D or 1/2/3/4")
        correct_index = "ABCD".index(correct) if correct in "ABCD" else int(correct) - 1
        question["correct_answer"] = "ABCD"[correct_index]
        reference_match = re.match(
            r"^\s*([A-D1-4])(?:(?:\s*[:.)\-]\s*(.*))|$)",
            question["reference_answer"],
            flags=re.IGNORECASE,
        )
        if reference_match:
            reference_label = reference_match.group(1).upper()
            if reference_label in "ABCD":
                reference_label = reference_label
            else:
                reference_label = "ABCD"[int(reference_label) - 1]
            if reference_label != question["correct_answer"]:
                raise ValueError("MCQ reference_answer does not match correct_answer")
            answer_text = reference_match.group(2)
            if answer_text:
                selected_option = re.sub(
                    r"^\s*[A-D1-4][\s.):\-]+",
                    "",
                    options["ABCD".index(question["correct_answer"])],
                    flags=re.IGNORECASE,
                )
                if " ".join(answer_text.split()).casefold() != " ".join(selected_option.split()).casefold():
                    raise ValueError("MCQ reference_answer text does not match the selected option")
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


def _build_prompt(
    question_type: str,
    topic: str,
    difficulty: str,
    bloom_level: str,
    context_docs: list[Any],
    custom_prompt: str | None = None,
    previous_questions: list[str] | None = None,
) -> str:
    context_sections = []
    for doc in context_docs[:8]:
        content = (doc.page_content if hasattr(doc, "page_content") else str(doc))[:2500]
        references = _build_source_refs([doc])
        context_sections.append(
            f"Source references: {json.dumps(references, ensure_ascii=False)}\nContent:\n{content}"
        )
    context_text = "\n\n---\n\n".join(context_sections)

    if custom_prompt:
        task = custom_prompt
    elif question_type == "mcq":
        task = (
            "Generate one multiple-choice question with exactly four distinct options, exactly one correct answer, "
            "a brief reference answer, a one-paragraph explanation, and a single-criterion rubric worth exactly 1 point "
            "(correct selected option = 1, otherwise = 0). Do not split one selected-answer question across overlapping criteria. "
            "When Bloom level is apply, describe a new, less-obvious scenario and ask the student to transfer a lesson idea; "
            "make distractors plausible but ensure only one is supported as correct by the curriculum."
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
When Bloom level is apply, use a new scenario rather than asking the student to repeat a table entry. For remember/understand, test recall or explanation; for analyze/evaluate/create, require comparison, judgment, or production appropriate to the selected level. Explain the cognitive task in bloom_rationale so the teacher can review the classification.

Previously generated questions to avoid repeating:
{json.dumps(previous_questions or [], ensure_ascii=False)}

Curriculum context:
{context_text}
""".strip()


def _find_first_sentence(content: str, min_chars: int = 20) -> str | None:
    """Extract the first meaningful complete sentence from curriculum content."""
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    for line in lines:
        if line.startswith(("#", "•", "?", "❓", "Lesson")):
            continue
        for s in re.split(r'(?<=[.!?])\s+', line):
            cleaned = " ".join(s.split()).strip()
            if len(cleaned) >= min_chars:
                return cleaned
    flat = " ".join(content.split())
    if len(flat) >= min_chars:
        return flat[:80]
    return None


def _find_verbatim_subquote(quote: str, content: str, min_chars: int = 20) -> str | None:
    """Find the longest contiguous word sequence from quote that appears verbatim in content."""
    norm_content = " ".join(content.split()).casefold()
    words = quote.split()
    for window_len in range(len(words), 3, -1):
        for start in range(len(words) - window_len + 1):
            sub = " ".join(words[start:start + window_len])
            norm_sub = " ".join(sub.split()).casefold()
            if len(norm_sub) >= min_chars and norm_sub in norm_content:
                idx = norm_content.find(norm_sub)
                orig_flat = " ".join(content.split())
                return orig_flat[idx:idx + len(norm_sub)]
    return None


def _canonicalize_source_refs(source_refs: Any, context_docs: list[Any]) -> list[dict[str, Any]]:
    if not isinstance(source_refs, list) or not source_refs:
        raise ValueError("Question must cite at least one supporting curriculum chunk")

    documents_by_chunk = {
        str((getattr(doc, "metadata", {}) or {}).get("chunk_id")): doc
        for doc in context_docs
        if (getattr(doc, "metadata", {}) or {}).get("chunk_id")
    }
    normalized_refs: list[dict[str, Any]] = []
    seen_chunks: set[str] = set()
    errors: list[str] = []
    for ref in source_refs:
        if not isinstance(ref, dict):
            raise ValueError("Each source reference must be a JSON object")
        chunk_id = str(ref.get("chunk_id", "")).strip()
        doc = documents_by_chunk.get(chunk_id)
        if doc is None:
            errors.append(f"Source reference chunk_id '{chunk_id}' was not provided as curriculum context")
            continue
        page_content = getattr(doc, "page_content", "")
        normalized_content = " ".join(page_content.split()).casefold()
        evidence_quote = ref.get("evidence_quote")
        if not isinstance(evidence_quote, str) or len(evidence_quote.strip()) < 12:
            candidate = _find_first_sentence(page_content, min_chars=20)
            if candidate:
                evidence_quote = candidate
            else:
                errors.append(f"Source reference '{chunk_id}' must include a useful evidence_quote")
                continue
        else:
            normalized_quote = " ".join(evidence_quote.split()).casefold()
            if normalized_quote not in normalized_content:
                subquote = _find_verbatim_subquote(evidence_quote, page_content, min_chars=20)
                if subquote:
                    evidence_quote = subquote
                else:
                    errors.append(f"Source reference '{chunk_id}' evidence_quote is not present in its curriculum chunk")
                    continue
        if chunk_id not in seen_chunks:
            canonical_ref = _build_source_refs([doc])[0]
            canonical_ref["evidence_quote"] = evidence_quote.strip()
            normalized_refs.append(canonical_ref)
            seen_chunks.add(chunk_id)

    if not normalized_refs:
        first_error = errors[0] if errors else "Question must cite at least one supporting curriculum chunk"
        if "not present in its curriculum chunk" in first_error:
            raise InvalidEvidenceQuoteError(first_error)
        raise ValueError(first_error)
    return normalized_refs


def _send_gemini_completion(
    prompt: str,
    *,
    max_tokens: int = MAX_COMPLETION_TOKENS,
    max_attempts: int = MAX_COMPLETION_ATTEMPTS,
) -> str:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is missing from the current project configuration")
    if not LLM_MODEL_NAME:
        raise ValueError("LLM_MODEL_NAME is missing from the current project configuration")

    from google import genai
    from google.genai import errors, types

    empty_response_details: list[str] = []
    client = genai.Client(api_key=GEMINI_API_KEY)
    try:
        for attempt in range(max_attempts):
            output_budget = max_tokens if attempt == 0 else RETRY_COMPLETION_TOKENS
            try:
                response = client.models.generate_content(
                    model=LLM_MODEL_NAME,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0,
                        max_output_tokens=output_budget,
                        response_mime_type="application/json",
                    ),
                )
            except errors.APIError as exc:
                status = exc.code
                if "API_KEY_INVALID" in str(exc) or "API key not valid" in str(exc) or status in {401, 403}:
                    raise ValueError(
                        "Gemini API authentication or permission failed. Verify GEMINI_API_KEY "
                        "and that the Gemini API is enabled for its Google AI Studio project."
                    ) from exc
                if status in {400, 404}:
                    raise ValueError(
                        f"Gemini model '{LLM_MODEL_NAME}' is unavailable or the request is "
                        f"unsupported (HTTP {status}). Check the model name and API access."
                    ) from exc
                if status == 429:
                    raise ValueError(
                        "Gemini API quota or rate limit exceeded. Check the project's model quota "
                        "and billing in Google AI Studio, then retry."
                    ) from exc
                if status is not None and status >= 500:
                    raise ValueError(f"Gemini API server error (HTTP {status}); retry later.") from exc
                detail = str(exc).replace(GEMINI_API_KEY, "[REDACTED]")
                raise ValueError(f"Gemini API request failed: {detail}") from exc

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
) -> str:
    model_name = LLM_MODEL_NAME or OLLAMA_MODEL_NAME or "llama3.2"
    base_url = OLLAMA_BASE_URL or "http://localhost:11434"
    num_ctx = OLLAMA_NUM_CTX or 8192

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
                temperature=0,
                format="json",
                num_ctx=num_ctx,
            )
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
                raise ValueError(
                    f"Ollama model '{model_name}' was not found on the server at '{base_url}'. "
                    f"Download it using: ollama pull {model_name}"
                ) from exc
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


def _send_completion(
    prompt: str,
    *,
    max_tokens: int = MAX_COMPLETION_TOKENS,
    max_attempts: int = MAX_COMPLETION_ATTEMPTS,
) -> str:
    if LLM_PROVIDER not in {"gemini", "ollama"}:
        raise ValueError("LLM_PROVIDER must be 'gemini' or 'ollama'")
    if max_tokens < 1 or max_attempts < 1:
        raise ValueError("max_tokens and max_attempts must be positive")

    if LLM_PROVIDER == "ollama":
        return _send_ollama_completion(prompt, max_tokens=max_tokens, max_attempts=max_attempts)
    return _send_gemini_completion(prompt, max_tokens=max_tokens, max_attempts=max_attempts)


def test_ollama_connection(
    model: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Make exactly one minimal request to check Ollama model access."""
    target_model = model or LLM_MODEL_NAME or OLLAMA_MODEL_NAME or "llama3.2"
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
    )
    return {"ok": True, "provider": "gemini", "model": LLM_MODEL_NAME, "content": content}


def test_llm_connection() -> dict[str, Any]:
    """Check connectivity to whichever LLM provider is active."""
    if LLM_PROVIDER == "ollama":
        return test_ollama_connection()
    return test_gemini_connection()

def generate_single_question(
    topic: str,
    question_type: str,
    context_docs: list[Any],
    difficulty: str = "medium",
    bloom_level: str = "apply",
    custom_prompt: str | None = None,
    previous_questions: list[str] | None = None,
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
    )
    retry_correction: str | None = None
    for attempt in range(MAX_QUESTION_GENERATION_ATTEMPTS):
        response_prompt = prompt
        if retry_correction:
            response_prompt += f"\n\nCorrection required: {retry_correction}"
        raw_response = _send_completion(response_prompt)
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
        if str(parsed.get("question_type", "")).strip().lower() != question_type:
            raise ValueError("Model returned a question type different from the requested type")
        if str(parsed.get("difficulty", "")).strip().lower() != difficulty:
            raise ValueError("Model returned a difficulty different from the requested difficulty")
        if str(parsed.get("bloom_level", "")).strip().lower() != bloom_level:
            raise ValueError("Model returned a Bloom level different from the requested level")
        if not isinstance(parsed.get("bloom_rationale"), str) or not parsed["bloom_rationale"].strip():
            raise ValueError("Model response must explain the requested Bloom level")
        try:
            parsed["source_refs"] = _canonicalize_source_refs(parsed.get("source_refs"), context_docs)
        except InvalidEvidenceQuoteError:
            if attempt + 1 == MAX_QUESTION_GENERATION_ATTEMPTS:
                raise
            retry_correction = (
                "Your previous response cited an evidence_quote that was not copied exactly from its "
                "curriculum chunk. Generate the question again and include only a short, verbatim quote "
                "copied exactly from the matching chunk shown below. Do not paraphrase or change punctuation."
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
            options = parsed.get("options") or []
            correct_key = str(parsed.get("correct_answer", "")).strip().upper()
            if correct_key in "1234" and len(options) == 4:
                correct_key = "ABCD"[int(correct_key) - 1]
                parsed["correct_answer"] = correct_key
            if correct_key in "ABCD" and len(options) == 4:
                selected_text = re.sub(
                    r"^\s*[A-D1-4][\s.):\-]+", "", options["ABCD".index(correct_key)], flags=re.IGNORECASE
                ).strip()
                parsed["reference_answer"] = f"{correct_key}: {selected_text}"
        _validate_question(parsed)
        return parsed
    raise RuntimeError("Question generation ended without a result")


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
    k: int = 8,
    embedding_model: str | None = None,
    lesson_id: str | None = None,
) -> list[Any]:
    store = load_curriculum_store(persist_dir=persist_dir, collection_name=collection_name, embedding_model=embedding_model)
    docs = retrieve(store, query=topic, k=k, lesson_id=lesson_id)
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
) -> tuple[dict[str, Any], Path]:
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
            k=8,
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
        if not context_docs:
            raise ValueError(f"No curriculum context available for selected lesson '{lesson_id}'")

    questions: list[dict[str, Any]] = []
    previous_questions: list[str] = []
    for idx, q_type in enumerate(requested, start=1):
        question = generate_single_question(
            topic=topic,
            question_type=q_type,
            context_docs=context_docs,
            difficulty=difficulty,
            bloom_level=bloom_level,
            previous_questions=previous_questions,
        )
        question["question_id"] = f"Q{idx:02d}"
        question["lesson_id"] = lesson_id
        _validate_question(question)
        questions.append(question)
        previous_questions.append(question["question"])

    exam = {
        "exam_title": f"{topic.title()} Assessment",
        "topic": topic,
        "lesson_id": lesson_id,
        "lesson_title": next(
            (
                (getattr(doc, "metadata", {}) or {}).get("lesson_title")
                for doc in context_docs
                if (getattr(doc, "metadata", {}) or {}).get("lesson_title")
            ),
            None,
        ),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": model_name,
        "question_count": len(questions),
        "total_points": sum(question["max_score"] for question in questions),
        "difficulty": difficulty,
        "bloom_level": bloom_level,
        "questions": questions,
    }

    validate_exam(exam)
    output_path = save_exam(exam, output_dir)
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
