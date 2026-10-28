"""
Question Ingestion, Cleaning, Extraction, and Validation Pipeline.

Stage 1 implementation of the Intelligent Educational Assessment System.
Handles multi-source question ingestion (dictionaries, lists, DataFrames, CSV, XLSX, JSON),
data cleaning, schema mapping and field extraction, rigorous validation, and non-destructive
duplicate detection.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
import io
import json
import logging
from pathlib import Path
import re
from typing import Any, BinaryIO, Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)

# Core allowed question types
VALID_QUESTION_TYPES: set[str] = {"mcq", "short_answer", "essay"}

# Normalized aliases mapping to canonical question types
QUESTION_TYPE_ALIASES: dict[str, str] = {
    "mcq": "mcq",
    "multiple_choice": "mcq",
    "multiple choice": "mcq",
    "multiple-choice": "mcq",
    "essay": "essay",
    "text": "essay",
    "text_based": "essay",
    "text-based": "essay",
    "text based": "essay",
    "short_answer": "short_answer",
    "short answer": "short_answer",
    "short-answer": "short_answer",
}

# Low-quality distractors that compromise MCQ assessment integrity
PROHIBITED_DISTRACTORS: set[str] = {
    "all of the above",
    "none of the above",
    "both a and b",
    "both b and c",
    "both a and c",
    "neither a nor b",
    "all the above",
    "none the above",
    "all of these",
    "none of these",
}

# Option letters supported for multiple-choice questions
VALID_MCQ_KEYS: tuple[str, ...] = ("A", "B", "C", "D")


@dataclass
class DuplicateMatch:
    """Represents a detected duplicate question relationship."""

    duplicate_type: str  # "exact" or "normalized"
    question_id: str
    matches_question_id: str
    question_text: str
    matched_text: str
    question_type: str


@dataclass
class ValidationErrorRecord:
    """Represents a rejected or malformed question record with its error log."""

    index: int
    raw_record: dict[str, Any]
    errors: list[str]
    warnings: list[str] = field(default_factory=list)


@dataclass
class ProcessingResult:
    """Structured report returned by the question ingestion and processing pipeline."""

    total_records: int
    valid_count: int
    invalid_count: int
    duplicate_count: int
    valid_records: list[dict[str, Any]]
    invalid_records: list[dict[str, Any]]
    duplicates: list[dict[str, Any]]
    warnings: list[str]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert result object to standard serializable dictionary."""
        return {
            "total_records": self.total_records,
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "duplicate_count": self.duplicate_count,
            "valid_records": self.valid_records,
            "invalid_records": self.invalid_records,
            "duplicates": self.duplicates,
            "warnings": self.warnings,
            "summary": self.summary,
        }


# ==============================================================================
# 1. Parsing Stage
# ==============================================================================


def parse_question_source(
    source: Union[str, Path, bytes, BinaryIO, io.StringIO, io.BytesIO, list[dict[str, Any]], dict[str, Any], pd.DataFrame],
    file_format: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Parses questions from diverse input formats into a list of raw dictionaries.

    Supports:
      - Python dict (single question)
      - Python list of dicts (batch questions)
      - pandas DataFrame
      - File paths (.csv, .xlsx, .xls, .json)
      - In-memory bytes or stream buffers (e.g. uploaded files)

    Returns:
      A list of raw dictionary records with original column names and values preserved.
    """
    # 1. Python dictionary (single record)
    if isinstance(source, dict):
        return [dict(source)]

    # 2. Python list of records
    if isinstance(source, list):
        parsed = []
        for i, item in enumerate(source):
            if isinstance(item, dict):
                parsed.append(dict(item))
            else:
                parsed.append({"_raw_non_dict_value": item, "_source_index": i})
        return parsed

    # 3. pandas DataFrame
    if isinstance(source, pd.DataFrame):
        return source.to_dict(orient="records")

    # 4. In-memory bytes or binary stream
    if isinstance(source, bytes):
        fmt = (file_format or "").strip().lower()
        if not fmt:
            # Guess format from header magic or text content
            stripped = source.strip()
            if stripped.startswith(b"{") or stripped.startswith(b"["):
                fmt = "json"
            elif stripped.startswith(b"PK"):
                fmt = "xlsx"
            else:
                fmt = "csv"
        return _parse_from_stream(io.BytesIO(source), fmt)

    if hasattr(source, "read"):
        fmt = (file_format or "").strip().lower()
        if not fmt and hasattr(source, "name"):
            fmt = Path(source.name).suffix.lstrip(".").lower()
        if not fmt:
            fmt = "csv"
        return _parse_from_stream(source, fmt)

    # 5. File path (str or Path)
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Question source file not found: {path}")

    fmt = (file_format or path.suffix.lstrip(".")).lower()
    if fmt in ("xlsx", "xls"):
        # Excel reader: prefer sheet 'All_Questions' if present (dataset convention)
        with pd.ExcelFile(path) as excel_file:
            sheet_name = "All_Questions" if "All_Questions" in excel_file.sheet_names else 0
            df = pd.read_excel(excel_file, sheet_name=sheet_name)
            return df.to_dict(orient="records")

    if fmt == "csv":
        try:
            df = pd.read_csv(path, encoding="utf-8")
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="utf-8-sig")
        return df.to_dict(orient="records")

    if fmt == "json":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _normalize_json_data(data)

    raise ValueError(f"Unsupported question source file format: '{fmt}' (from {path})")


def _parse_from_stream(stream: Any, fmt: str) -> list[dict[str, Any]]:
    """Helper to parse records from a stream based on file format."""
    fmt = fmt.lower()
    if fmt in ("xlsx", "xls"):
        with pd.ExcelFile(stream) as excel_file:
            sheet_name = "All_Questions" if "All_Questions" in excel_file.sheet_names else 0
            df = pd.read_excel(excel_file, sheet_name=sheet_name)
            return df.to_dict(orient="records")

    if fmt == "csv":
        try:
            df = pd.read_csv(stream, encoding="utf-8")
        except UnicodeDecodeError:
            if hasattr(stream, "seek"):
                stream.seek(0)
            df = pd.read_csv(stream, encoding="utf-8-sig")
        return df.to_dict(orient="records")

    if fmt == "json":
        if hasattr(stream, "read"):
            content = stream.read()
            if isinstance(content, bytes):
                content = content.decode("utf-8")
            data = json.loads(content)
        else:
            data = json.load(stream)
        return _normalize_json_data(data)

    raise ValueError(f"Unsupported stream format: '{fmt}'")


def _normalize_json_data(data: Any) -> list[dict[str, Any]]:
    """Extract list of question dictionaries from various JSON payload structures."""
    if isinstance(data, list):
        return [item if isinstance(item, dict) else {"_raw_non_dict_value": item} for item in data]
    if isinstance(data, dict):
        for key in ("questions", "All_Questions", "data", "items", "records"):
            if key in data and isinstance(data[key], list):
                return [item if isinstance(item, dict) else {"_raw_non_dict_value": item} for item in data[key]]
        return [data]
    raise ValueError(f"JSON input must be a list of records or a dictionary containing a question list.")


# ==============================================================================
# 2. Cleaning Stage
# ==============================================================================


def clean_cell_value(val: Any) -> Any:
    """
    Cleans individual cell values:
      - Strips whitespace from strings.
      - Converts pandas NaN / None / float('nan') / empty string representations to None.
      - Preserves valid integers, floats, booleans, and content strings.
    """
    if val is None:
        return None
    if isinstance(val, float) and pd.isna(val):
        return None
    if isinstance(val, str):
        cleaned = val.strip()
        if not cleaned:
            return None
        # Handle stringified NaN representations commonly emitted by spreadsheets
        if cleaned.lower() in ("nan", "none", "null", "n/a"):
            return None
        return cleaned
    return val


def normalize_question_type(raw_type: Any) -> str:
    """
    Normalizes a question type string into one of 'mcq', 'short_answer', or 'essay'.
    Returns empty string if missing or unparseable.
    """
    cleaned = clean_cell_value(raw_type)
    if not cleaned:
        return ""
    norm = str(cleaned).strip().lower().replace("-", "_")
    return QUESTION_TYPE_ALIASES.get(norm, norm)


def strip_option_prefix(option_text: Any) -> str:
    """
    Strips leading distractor labels (e.g. 'A) ', 'B. ', '1: ', 'D - ') from option text.
    Preserves actual option content without alteration.
    """
    val = clean_cell_value(option_text)
    if not val:
        return ""
    text = str(val).strip()
    return re.sub(r"^\s*[A-D1-4][\s.):\-]+\s*", "", text, flags=re.IGNORECASE).strip()


def normalize_correct_option(raw_option: Any) -> Optional[str]:
    """
    Normalizes correct option keys into uppercase 'A', 'B', 'C', or 'D'.
    Handles numeric index conversion ('1' -> 'A', '2' -> 'B', etc.).
    """
    val = clean_cell_value(raw_option)
    if not val:
        return None
    text = str(val).strip().upper()
    # Check numeric 1-4
    if text in ("1", "2", "3", "4"):
        return VALID_MCQ_KEYS[int(text) - 1]
    # Check single character A-D
    if text in VALID_MCQ_KEYS:
        return text
    # Check if string starts with A-D, e.g. "A: Supervised Learning" or "B)"
    match = re.match(r"^([A-D1-4])[\s.):\-]", text)
    if match:
        key = match.group(1)
        if key in ("1", "2", "3", "4"):
            return VALID_MCQ_KEYS[int(key) - 1]
        return key
    return text


def clean_question_record(record: dict[str, Any]) -> dict[str, Any]:
    """
    Applies standard cleaning rules to a single raw question record.
      - Strips accidental spaces from keys.
      - Cleans all cell values (handles NaN/whitespace).
      - Reuses dataset cleaning conventions from notebook.
    """
    cleaned: dict[str, Any] = {}
    for k, v in record.items():
        clean_key = str(k).strip() if isinstance(k, str) else str(k)
        cleaned[clean_key] = clean_cell_value(v)
    return cleaned


def clean_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cleans a sequence of raw question records."""
    return [clean_question_record(r) for r in records]


# ==============================================================================
# 3. Extraction & Schema Mapping Stage
# ==============================================================================


def extract_question(
    record: dict[str, Any],
    default_id_index: int = 1,
) -> dict[str, Any]:
    """
    Maps cleaned raw fields into the canonical question schema.

    Canonical Schema Attributes:
      - question_id: str (stable unique identifier, e.g. 'Q-0001')
      - original_question_id: Optional[str] (source id, e.g. 'MCQ-001', 'TEXT-001')
      - question_type: str ('mcq', 'short_answer', 'essay')
      - question_text: str (main stem of question)
      - options: list[str] (4 clean distinct options for MCQ, empty list for non-MCQ)
      - correct_option: Optional[str] ('A', 'B', 'C', 'D' for MCQ, None for non-MCQ)
      - correct_answer: str (text answer: correct option text for MCQ, model answer for essay)
      - chapter: Optional[str] (chapter or unit title/id)
      - lesson: Optional[str] (lesson or topic title/id)
      - page_number: Optional[Union[int, str]] (page number or page range)
      - source_file: Optional[str] (source PDF / book document name)
      - answer_source: Optional[str] (e.g. 'Book Content')
      - verification_status: Optional[str] (e.g. 'Verified from Source', 'Solved by AI')
      - source_metadata: dict[str, Any] (traceable source metadata and extra columns)
      - validation_warnings: list[str]
    """
    warnings: list[str] = []

    # 1. Resolve IDs
    orig_id = record.get("original_question_id") or record.get("question_id") or record.get("id")
    raw_qid = record.get("question_id")
    if raw_qid:
        qid = str(raw_qid).strip()
    else:
        qid = f"Q-{default_id_index:04d}"

    # 2. Resolve Question Type
    raw_type = record.get("question_type") or record.get("type")
    q_type = normalize_question_type(raw_type)

    # 3. Resolve Question Text
    text_candidates = ["question_text", "question", "prompt", "stem", "text"]
    q_text = None
    for cand in text_candidates:
        if cand in record and record[cand] is not None:
            q_text = str(record[cand]).strip()
            break
    if q_text is None:
        q_text = ""

    # 4. Resolve Options (for MCQ)
    options: list[str] = []
    # Check if an explicit list exists first
    if "options" in record and isinstance(record["options"], list):
        options = [strip_option_prefix(opt) for opt in record["options"] if opt is not None]
    else:
        # Check individual option columns (option_A, option_B, option_C, option_D)
        for letter in VALID_MCQ_KEYS:
            cand_keys = [
                f"option_{letter}",
                f"option_{letter.lower()}",
                f"opt_{letter}",
                f"opt_{letter.lower()}",
                f"Option_{letter}",
            ]
            opt_val = None
            for k in cand_keys:
                if k in record and record[k] is not None:
                    opt_val = record[k]
                    break
            if opt_val is not None:
                options.append(strip_option_prefix(opt_val))

    # If question_type is not set, infer from presence of options
    if not q_type:
        if len(options) >= 2:
            q_type = "mcq"
        else:
            q_type = "essay"

    # 5. Resolve Correct Option (MCQ key)
    raw_opt_keys = ["correct_option", "correct_letter", "answer_option", "key"]
    correct_opt = None
    for k in raw_opt_keys:
        if k in record and record[k] is not None:
            correct_opt = normalize_correct_option(record[k])
            break

    # 6. Resolve Correct Answer / Model Answer
    answer_candidates = [
        "correct_answer",
        "model_answer",
        "reference_answer",
        "answer",
        "expected_answer",
    ]
    correct_ans = None
    for k in answer_candidates:
        if k in record and record[k] is not None:
            correct_ans = str(record[k]).strip()
            break
    if correct_ans is None:
        correct_ans = ""

    # Cross-fill MCQ correct_answer and correct_option if one is missing
    if q_type == "mcq":
        # If correct_option is available and correct_answer is empty, retrieve text from options
        if correct_opt in VALID_MCQ_KEYS and not correct_ans:
            idx = VALID_MCQ_KEYS.index(correct_opt)
            if idx < len(options):
                correct_ans = options[idx]

        # If correct_ans is available but correct_opt is missing, try to find option index
        if not correct_opt and correct_ans:
            clean_ans = strip_option_prefix(correct_ans).lower()
            for idx, opt in enumerate(options):
                if opt.lower() == clean_ans:
                    correct_opt = VALID_MCQ_KEYS[idx]
                    break
    else:
        # For essay or short answer, clear options and correct_option
        if options:
            warnings.append(f"Non-MCQ question type '{q_type}' had {len(options)} options, which were discarded.")
            options = []
        if correct_opt:
            correct_opt = None

    # 7. Metadata extraction
    chapter = record.get("chapter") or record.get("unit") or record.get("chapter_title")
    lesson = record.get("lesson") or record.get("topic") or record.get("lesson_title")
    page_number = record.get("page_number") or record.get("page") or record.get("pages")
    source_file = record.get("source_file") or record.get("source_doc") or record.get("document")
    answer_source = record.get("answer_source")
    verification_status = record.get("verification_status") or record.get("status")

    # Extra columns kept in source_metadata for full traceability
    standard_keys = {
        "question_id", "original_question_id", "question_type", "type", "question_text",
        "question", "prompt", "text", "option_A", "option_B", "option_C", "option_D",
        "option_a", "option_b", "option_c", "option_d", "options", "correct_option",
        "correct_letter", "answer_option", "key", "correct_answer", "model_answer",
        "reference_answer", "answer", "chapter", "unit", "chapter_title", "lesson",
        "topic", "lesson_title", "page_number", "page", "pages", "source_file",
        "source_doc", "document", "answer_source", "verification_status", "status",
        "_source_index", "_raw_non_dict_value",
    }
    source_metadata: dict[str, Any] = {}
    for k, v in record.items():
        if k not in standard_keys and v is not None:
            source_metadata[k] = v

    return {
        "question_id": qid,
        "original_question_id": str(orig_id) if orig_id is not None else None,
        "question_type": q_type,
        "question_text": q_text,
        "options": options,
        "correct_option": correct_opt,
        "correct_answer": correct_ans,
        "chapter": str(chapter).strip() if chapter is not None else None,
        "lesson": str(lesson).strip() if lesson is not None else None,
        "page_number": page_number,
        "source_file": str(source_file).strip() if source_file is not None else None,
        "answer_source": str(answer_source).strip() if answer_source is not None else None,
        "verification_status": str(verification_status).strip() if verification_status is not None else None,
        "source_metadata": source_metadata if source_metadata else None,
        "validation_warnings": warnings,
    }


def extract_questions(cleaned_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extracts questions into standard canonical format for a list of records."""
    return [extract_question(r, default_id_index=i + 1) for i, r in enumerate(cleaned_records)]


# ==============================================================================
# 4. Validation Stage
# ==============================================================================


def validate_question_record(record: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    """
    Validates a canonical question record against system standards.

    Checks:
      - Required fields: question_text and question_type must be non-empty.
      - Supported question type: must be 'mcq', 'short_answer', or 'essay'.
      - MCQ integrity:
          * Must have exactly 4 non-empty options.
          * Options must be distinct.
          * Prohibited distractors ('all of the above', etc.) are rejected.
          * Must specify a valid correct_option ('A', 'B', 'C', or 'D').
          * Answer presence: correct_answer must not be blank.
      - Essay / Short Answer integrity:
          * Must have model answer (correct_answer) present.
          * Options must be empty.

    Returns:
      (is_valid: bool, errors: list[str], warnings: list[str])
    """
    errors: list[str] = []
    warnings: list[str] = list(record.get("validation_warnings", []))

    # 1. Question Text validation
    q_text = record.get("question_text")
    if not isinstance(q_text, str) or not q_text.strip():
        errors.append("Question text is required and cannot be empty.")

    # 2. Question Type validation
    q_type = record.get("question_type")
    if not q_type or q_type not in VALID_QUESTION_TYPES:
        errors.append(
            f"Invalid or missing question_type: '{q_type}'. Allowed types: {sorted(VALID_QUESTION_TYPES)}."
        )
        return False, errors, warnings

    # 3. Type-specific validations
    if q_type == "mcq":
        options = record.get("options")
        if not isinstance(options, list):
            errors.append("MCQ options must be a list of 4 options.")
        else:
            if len(options) != 4:
                errors.append(f"MCQ requires exactly 4 options; found {len(options)}.")
            for i, opt in enumerate(options):
                if not isinstance(opt, str) or not opt.strip():
                    errors.append(f"MCQ option {VALID_MCQ_KEYS[i] if i < 4 else i + 1} cannot be blank.")

            # Distinct options check
            clean_opts = [str(opt).strip().casefold() for opt in options if opt is not None]
            if len(clean_opts) == 4 and len(set(clean_opts)) != 4:
                errors.append("MCQ options must be distinct; duplicate options detected.")

            # Prohibited distractors check
            for opt in options:
                if str(opt).strip().casefold() in PROHIBITED_DISTRACTORS:
                    errors.append(f"MCQ contains prohibited low-quality distractor: '{opt}'.")

        # Correct option key check
        correct_opt = record.get("correct_option")
        if not correct_opt or correct_opt not in VALID_MCQ_KEYS:
            errors.append(
                f"MCQ correct_option must be one of {list(VALID_MCQ_KEYS)}; got '{correct_opt}'."
            )

        # Correct answer text presence
        correct_ans = record.get("correct_answer")
        if not correct_ans or not str(correct_ans).strip():
            errors.append("MCQ correct_answer (answer text) is missing or empty.")

        # Consistency check: if both correct_option and correct_answer exist, verify match
        if (
            correct_opt in VALID_MCQ_KEYS
            and isinstance(options, list)
            and len(options) == 4
            and correct_ans
        ):
            expected_text = options[VALID_MCQ_KEYS.index(correct_opt)]
            if expected_text.strip().casefold() != str(correct_ans).strip().casefold():
                warnings.append(
                    f"MCQ correct_answer text '{correct_ans}' does not exactly match "
                    f"option {correct_opt} ('{expected_text}')."
                )

    elif q_type in ("essay", "short_answer"):
        # Answer presence check
        correct_ans = record.get("correct_answer")
        if not correct_ans or not str(correct_ans).strip():
            errors.append(f"{q_type.replace('_', ' ').title()} question is missing a model/correct answer.")

        # Options should be empty
        options = record.get("options")
        if options:
            warnings.append(f"Options are not applicable to {q_type} questions and should be empty.")

    is_valid = len(errors) == 0
    return is_valid, errors, warnings


# ==============================================================================
# 5. Duplicate Detection Stage
# ==============================================================================


def normalize_text_for_comparison(text: str) -> str:
    """
    Normalizes question text for duplicate detection:
      - Converts to lowercase.
      - Collapses multiple whitespace characters to single spaces.
      - Strips leading and trailing punctuation and whitespace.
    """
    if not text:
        return ""
    norm = text.lower()
    norm = re.sub(r"\s+", " ", norm)
    norm = norm.strip().rstrip("?.! ")
    return norm


def detect_duplicates(
    questions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Detects exact and normalized duplicate questions within a batch.
    Does NOT delete records; returns structured report for teacher review.
    """
    duplicates: list[dict[str, Any]] = []
    seen_exact: dict[tuple[str, str], str] = {}  # (type, exact_text) -> first question_id
    seen_norm: dict[tuple[str, str], str] = {}   # (type, norm_text) -> first question_id

    for q in questions:
        qid = q.get("question_id", "unknown")
        qtype = q.get("question_type", "unknown")
        raw_text = (q.get("question_text") or "").strip()
        norm_text = normalize_text_for_comparison(raw_text)

        if not raw_text:
            continue

        exact_key = (qtype, raw_text)
        norm_key = (qtype, norm_text)

        if exact_key in seen_exact:
            first_id = seen_exact[exact_key]
            duplicates.append({
                "duplicate_type": "exact",
                "question_id": qid,
                "matches_question_id": first_id,
                "question_text": raw_text,
                "matched_text": raw_text,
                "question_type": qtype,
            })
        elif norm_key in seen_norm:
            first_id = seen_norm[norm_key]
            duplicates.append({
                "duplicate_type": "normalized",
                "question_id": qid,
                "matches_question_id": first_id,
                "question_text": raw_text,
                "matched_text": seen_norm[norm_key],
                "question_type": qtype,
            })
        else:
            seen_exact[exact_key] = qid
            seen_norm[norm_key] = qid

    return duplicates


# ==============================================================================
# 6. Full Ingestion & Processing Pipeline
# ==============================================================================


def process_question_source(
    source: Union[str, Path, bytes, BinaryIO, io.StringIO, io.BytesIO, list[dict[str, Any]], dict[str, Any], pd.DataFrame],
    file_format: Optional[str] = None,
) -> ProcessingResult:
    """
    Executes the complete Question Processing Pipeline:
      Parsing → Cleaning → Extraction → Validation → Duplicate Detection

    Args:
      source: Ingestion source (file path, bytes buffer, dict, list of dicts, DataFrame)
      file_format: Optional format override ('csv', 'xlsx', 'json')

    Returns:
      ProcessingResult containing valid records, invalid records with error logs,
      duplicate reports, warnings, and summary statistics.
    """
    # 1. Parsing
    raw_records = parse_question_source(source, file_format=file_format)
    total_records = len(raw_records)

    if total_records == 0:
        return ProcessingResult(
            total_records=0,
            valid_count=0,
            invalid_count=0,
            duplicate_count=0,
            valid_records=[],
            invalid_records=[],
            duplicates=[],
            warnings=["Input source contained 0 records."],
            summary={"status": "empty", "valid_ratio": 0.0},
        )

    # 2. Cleaning
    cleaned_records = clean_records(raw_records)

    # 3. Extraction & Schema Mapping
    extracted_questions = extract_questions(cleaned_records)

    # 4. Validation
    valid_records: list[dict[str, Any]] = []
    invalid_records: list[dict[str, Any]] = []
    pipeline_warnings: list[str] = []

    for idx, question in enumerate(extracted_questions, start=1):
        is_valid, errors, record_warnings = validate_question_record(question)
        if record_warnings:
            pipeline_warnings.extend([f"Question {question['question_id']}: {w}" for w in record_warnings])

        if is_valid:
            valid_records.append(question)
        else:
            invalid_records.append({
                "index": idx,
                "question_id": question.get("question_id"),
                "raw_record": raw_records[idx - 1],
                "extracted_record": question,
                "errors": errors,
                "warnings": record_warnings,
            })

    # 5. Duplicate Detection (on valid questions)
    duplicates = detect_duplicates(valid_records)
    if duplicates:
        # Attach duplicate warning to each matching valid question for teacher review
        dup_map = {d["question_id"]: d for d in duplicates}
        for v in valid_records:
            qid = v["question_id"]
            if qid in dup_map:
                match_id = dup_map[qid]["matches_question_id"]
                dtype = dup_map[qid]["duplicate_type"]
                warn_msg = f"Potential {dtype} duplicate of question '{match_id}'."
                v["validation_warnings"].append(warn_msg)
                pipeline_warnings.append(f"Question '{qid}': {warn_msg}")

    # 6. Compile Summary
    type_counts: dict[str, int] = {}
    for r in valid_records:
        t = r["question_type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    summary = {
        "total_input_records": total_records,
        "valid_count": len(valid_records),
        "invalid_count": len(invalid_records),
        "duplicate_count": len(duplicates),
        "type_counts": type_counts,
        "valid_ratio": round(len(valid_records) / total_records, 4) if total_records > 0 else 0.0,
    }

    return ProcessingResult(
        total_records=total_records,
        valid_count=len(valid_records),
        invalid_count=len(invalid_records),
        duplicate_count=len(duplicates),
        valid_records=valid_records,
        invalid_records=invalid_records,
        duplicates=duplicates,
        warnings=pipeline_warnings,
        summary=summary,
    )
