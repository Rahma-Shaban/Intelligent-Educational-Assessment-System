"""
Reusable Dataset Loader for Question Bank Cleaned Datasets.

Discovers, validates, caches, and provides structured access to the verified
Question Bank dataset (e.g. Question_Bank_Cleaned.xlsx).

Invariants:
  - Read-only access: never modifies the original dataset file.
  - Zero database writes: loading or training never touches production DB tables.
  - Provable integrity: calculates and tracks SHA-256 hash and file provenance.
  - No label fabrication: reports true label presence without inventing labels.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

import pandas as pd

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent

# Canonical locations where cleaned datasets reside
CANONICAL_DATASET_PATHS = [
    ROOT_DIR / "data" / "processed" / "Question_Bank_Cleaned.xlsx",
    ROOT_DIR / "data" / "raw" / "Question_Bank_Cleaned.xlsx",
]

# Required schema columns expected from the question cleaning process
REQUIRED_COLUMNS: tuple[str, ...] = (
    "question_id",
    "question_type",
    "question_text",
    "option_A",
    "option_B",
    "option_C",
    "option_D",
    "correct_option",
    "correct_answer",
    "chapter",
    "lesson",
    "page_number",
    "source_file",
    "answer_source",
    "verification_status",
    "Source",
    "original_question_id",
)


@dataclass
class DatasetProvenance:
    """Provenance and cryptographic integrity metadata for a loaded dataset."""

    file_path: str
    file_size_bytes: int
    sha256_hash: str
    loaded_at: str
    sheet_name: str
    total_raw_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    has_difficulty_labels: bool
    has_bloom_labels: bool
    difficulty_column: Optional[str] = None
    bloom_column: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "file_size_bytes": self.file_size_bytes,
            "sha256_hash": self.sha256_hash,
            "loaded_at": self.loaded_at,
            "sheet_name": self.sheet_name,
            "total_raw_rows": self.total_raw_rows,
            "valid_rows": self.valid_rows,
            "invalid_rows": self.invalid_rows,
            "duplicate_rows": self.duplicate_rows,
            "has_difficulty_labels": self.has_difficulty_labels,
            "has_bloom_labels": self.has_bloom_labels,
            "difficulty_column": self.difficulty_column,
            "bloom_column": self.bloom_column,
        }


@dataclass
class LoadedDataset:
    """Container holding cleaned questions and full inspection/provenance details."""

    records: list[dict[str, Any]]
    provenance: DatasetProvenance
    invalid_records: list[dict[str, Any]] = field(default_factory=list)
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    filters_available: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_records": len(self.records),
            "provenance": self.provenance.to_dict(),
            "invalid_count": len(self.invalid_records),
            "duplicate_count": len(self.duplicates),
            "filters_available": self.filters_available,
        }


# Global in-memory cache to prevent re-parsing large Excel files on every API call
_DATASET_CACHE: dict[str, Any] = {
    "mtime": None,
    "file_path": None,
    "dataset": None,
}


def resolve_cleaned_dataset_path(explicit_path: Optional[Union[str, Path]] = None) -> Path:
    """
    Resolves the canonical cleaned dataset path from an explicit argument or default locations.
    Raises FileNotFoundError if no dataset file exists.
    """
    if explicit_path:
        p = Path(explicit_path)
        if p.exists() and p.is_file():
            return p
        raise FileNotFoundError(f"Cleaned dataset not found at explicit path: {explicit_path}")

    for candidate in CANONICAL_DATASET_PATHS:
        if candidate.exists() and candidate.is_file():
            return candidate

    raise FileNotFoundError(
        f"No cleaned question bank dataset found in canonical locations: "
        f"{[str(p) for p in CANONICAL_DATASET_PATHS]}"
    )


def load_cleaned_dataset(
    file_path: Optional[Union[str, Path]] = None,
    sheet_name: str = "All_Questions",
    use_cache: bool = True,
) -> LoadedDataset:
    """
    Loads, validates, and normalizes the real cleaned question bank dataset.

    Deterministic duplicate policy:
      - Tracks duplicate question_ids and normalized question_text.
      - First occurrence is preserved; subsequent duplicates are recorded with
        'matches_question_id' for transparent auditing, without mutating original data.
    """
    global _DATASET_CACHE

    resolved_path = resolve_cleaned_dataset_path(file_path)
    stat = resolved_path.stat()
    current_mtime = stat.st_mtime

    # Return cached dataset if file has not been modified
    if (
        use_cache
        and _DATASET_CACHE["dataset"] is not None
        and _DATASET_CACHE["file_path"] == str(resolved_path)
        and _DATASET_CACHE["mtime"] == current_mtime
    ):
        return _DATASET_CACHE["dataset"]

    raw_bytes = resolved_path.read_bytes()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    # Read target sheet (default to 'All_Questions', fallback to 0)
    with pd.ExcelFile(resolved_path) as xl:
        target_sheet = sheet_name if sheet_name in xl.sheet_names else xl.sheet_names[0]
        df = pd.read_excel(xl, sheet_name=target_sheet)

    # Normalize column names: strip whitespace
    df.columns = [str(c).strip() for c in df.columns]

    # Check for missing required columns
    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        logger.warning(
            "Dataset at %s is missing expected schema columns: %s",
            resolved_path,
            missing_cols,
        )

    # Check for legitimate difficulty or Bloom columns
    diff_col = next((c for c in df.columns if c.lower() in ("difficulty", "difficulty_level")), None)
    bloom_col = next((c for c in df.columns if c.lower() in ("bloom_level", "bloom_taxonomy", "bloom")), None)

    has_diff = diff_col is not None and not df[diff_col].dropna().empty
    has_bloom = bloom_col is not None and not df[bloom_col].dropna().empty

    records: list[dict[str, Any]] = []
    invalid_records: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []

    seen_ids: dict[str, int] = {}
    seen_texts: dict[str, str] = {}

    for idx, row in df.iterrows():
        raw_dict = row.to_dict()
        qid = str(raw_dict.get("question_id") or "").strip()
        qtext = str(raw_dict.get("question_text") or "").strip()
        qtype = str(raw_dict.get("question_type") or "").strip().lower()

        # Validation: question_text and question_id must not be empty
        errors = []
        if not qid:
            errors.append("missing question_id")
        if not qtext:
            errors.append("missing question_text")
        if qtype not in ("mcq", "essay", "short_answer"):
            errors.append(f"invalid question_type '{qtype}'")

        if errors:
            invalid_records.append({
                "row_index": int(idx),
                "raw_record": raw_dict,
                "errors": errors,
            })
            continue

        # Duplicate checking: deterministic policy
        norm_text = "".join(ch for ch in qtext.lower() if ch.isalnum() or ch.isspace()).strip()
        is_dup = False
        if qid in seen_ids:
            is_dup = True
            duplicates.append({
                "duplicate_type": "duplicate_id",
                "question_id": qid,
                "first_seen_row": seen_ids[qid],
                "duplicate_row": int(idx),
            })
        elif norm_text in seen_texts:
            is_dup = True
            duplicates.append({
                "duplicate_type": "duplicate_text",
                "question_id": qid,
                "matches_question_id": seen_texts[norm_text],
                "duplicate_row": int(idx),
            })

        seen_ids[qid] = int(idx)
        seen_texts[norm_text] = qid

        # Normalize options for MCQs
        options = []
        if qtype == "mcq":
            for opt_key in ("option_A", "option_B", "option_C", "option_D"):
                val = raw_dict.get(opt_key)
                if pd.notna(val) and str(val).strip():
                    options.append(str(val).strip())

        correct_opt = raw_dict.get("correct_option")
        correct_opt_str = str(correct_opt).strip().upper() if pd.notna(correct_opt) else None

        clean_item = {
            "question_id": qid,
            "original_question_id": str(raw_dict.get("original_question_id") or qid).strip(),
            "question_type": qtype,
            "question_text": qtext,
            "options": options,
            "option_A": str(raw_dict.get("option_A") or "").strip() if pd.notna(raw_dict.get("option_A")) else None,
            "option_B": str(raw_dict.get("option_B") or "").strip() if pd.notna(raw_dict.get("option_B")) else None,
            "option_C": str(raw_dict.get("option_C") or "").strip() if pd.notna(raw_dict.get("option_C")) else None,
            "option_D": str(raw_dict.get("option_D") or "").strip() if pd.notna(raw_dict.get("option_D")) else None,
            "correct_option": correct_opt_str,
            "correct_answer": str(raw_dict.get("correct_answer") or "").strip(),
            "chapter": str(raw_dict.get("chapter") or "").strip(),
            "lesson": str(raw_dict.get("lesson") or "").strip(),
            "page_number": str(raw_dict.get("page_number") or "").strip(),
            "source_file": str(raw_dict.get("source_file") or "").strip(),
            "answer_source": str(raw_dict.get("answer_source") or "").strip(),
            "verification_status": str(raw_dict.get("verification_status") or "").strip(),
            "Source": str(raw_dict.get("Source") or "").strip(),
            "difficulty": str(raw_dict[diff_col]).strip() if has_diff and pd.notna(raw_dict.get(diff_col)) else None,
            "bloom_level": str(raw_dict[bloom_col]).strip() if has_bloom and pd.notna(raw_dict.get(bloom_col)) else None,
            "is_duplicate": is_dup,
        }
        records.append(clean_item)

    # Extract distinct filter options
    chapters = sorted(list({r["chapter"] for r in records if r.get("chapter")}))
    lessons = sorted(list({r["lesson"] for r in records if r.get("lesson")}))
    types = sorted(list({r["question_type"] for r in records if r.get("question_type")}))
    verifications = sorted(list({r["verification_status"] for r in records if r.get("verification_status")}))
    answer_sources = sorted(list({r["answer_source"] for r in records if r.get("answer_source")}))

    filters_available = {
        "question_types": types,
        "chapters": chapters,
        "lessons": lessons,
        "verification_statuses": verifications,
        "answer_sources": answer_sources,
    }

    provenance = DatasetProvenance(
        file_path=str(resolved_path),
        file_size_bytes=stat.st_size,
        sha256_hash=sha256,
        loaded_at=datetime.now(timezone.utc).isoformat(),
        sheet_name=target_sheet,
        total_raw_rows=len(df),
        valid_rows=len(records),
        invalid_rows=len(invalid_records),
        duplicate_rows=len(duplicates),
        has_difficulty_labels=has_diff,
        has_bloom_labels=has_bloom,
        difficulty_column=diff_col,
        bloom_column=bloom_col,
    )

    dataset_obj = LoadedDataset(
        records=records,
        provenance=provenance,
        invalid_records=invalid_records,
        duplicates=duplicates,
        filters_available=filters_available,
    )

    if use_cache:
        _DATASET_CACHE["mtime"] = current_mtime
        _DATASET_CACHE["file_path"] = str(resolved_path)
        _DATASET_CACHE["dataset"] = dataset_obj

    return dataset_obj

