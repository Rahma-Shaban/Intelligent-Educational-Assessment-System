"""
Question Bank Persistence and Embedding Service.

Stage 4B implementation of the Intelligent Educational Assessment System.

Provides:
  - Idempotent import of question-bank records into SQLite (QuestionBankItem).
  - Deterministic stable ID generation with collision detection.
  - Exact, normalized, and semantic duplicate detection (detection only; never silent deletion).
  - Chroma embedding synchronization into an isolated 'question_bank' collection.
  - Embedding sync status tracking (pending / synced / failed) with retry / reconciliation.
  - Per-record outcome reporting; batch partial-failure is explicit and returned to the caller.
  - Teacher review decisions (approved/rejected) are preserved on re-import.

Design notes:
  - SQLite and Chroma are treated as SEPARATE persistence systems.
  - A Chroma upsert does not constitute a true atomic transaction with the SQL write.
  - No paid API calls required: uses the project's existing HuggingFace sentence-transformer embeddings.
  - The 'curriculum' Chroma collection is never modified or deleted.
  - Embedding text strategy: "<question_text> [OPTIONS: A: ... B: ... ...] [ANSWER: ...]"
    This ensures that questions with the same answer but different stems remain distinct,
    while still capturing answer content for semantic retrieval.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Union

from sqlalchemy.orm import Session

from app.models import QuestionBankItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

QUESTION_BANK_CHROMA_COLLECTION = "question_bank"
"""Dedicated Chroma collection name for question bank embeddings.
The curriculum collection is never touched by this service."""

DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD: float = 0.92
"""Configurable cosine similarity threshold above which two questions are
flagged as semantic duplicate candidates. This is a REVIEW SIGNAL only;
no question is deleted or merged automatically."""

_DETERMINISTIC_ID_PREFIX = "QBK-"
"""Prefix for synthetic IDs generated for records that have no original ID."""


# ---------------------------------------------------------------------------
# Per-record outcome dataclass
# ---------------------------------------------------------------------------


@dataclass
class QuestionBankItemOutcome:
    """Outcome for a single question bank import operation."""

    input_index: int
    question_id: str
    status: str  # "inserted" | "updated" | "skipped" | "invalid" | "error"
    sql_id: Optional[int] = None
    embedding_status: Optional[str] = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duplicate_flags: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_index": self.input_index,
            "question_id": self.question_id,
            "status": self.status,
            "sql_id": self.sql_id,
            "embedding_status": self.embedding_status,
            "errors": self.errors,
            "warnings": self.warnings,
            "duplicate_flags": self.duplicate_flags,
        }


@dataclass
class BatchImportResult:
    """Summary of a batch import operation."""

    total_input: int
    inserted: int
    updated: int
    skipped: int
    invalid: int
    errored: int
    outcomes: list[QuestionBankItemOutcome]
    collision_report: list[dict[str, Any]]  # ID collision details

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_input": self.total_input,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped": self.skipped,
            "invalid": self.invalid,
            "errored": self.errored,
            "outcomes": [o.to_dict() for o in self.outcomes],
            "collision_report": self.collision_report,
        }


# ---------------------------------------------------------------------------
# Stable ID generation
# ---------------------------------------------------------------------------


def generate_stable_question_id(record: dict[str, Any], index: int) -> tuple[str, bool]:
    """
    Generates a stable, deterministic question ID for a question record.

    Strategy:
      1. Use the record's own 'question_id' if present and non-empty.
      2. Use 'original_question_id' as a fallback.
      3. If neither is available, generate a deterministic SHA-256 hash of
         (question_type, question_text) so that identical questions always
         get the same synthetic ID, regardless of row position.

    Returns:
      (question_id: str, is_synthetic: bool)

    Note: Row position (index) is NOT used as the sole basis for synthetic IDs.
    """
    qid = record.get("question_id") or record.get("original_question_id")
    if qid and str(qid).strip():
        return str(qid).strip(), False

    # Deterministic hash of (type, text) — position-independent
    q_type = str(record.get("question_type") or "").strip()
    q_text = str(record.get("question_text") or "").strip()
    raw = f"{q_type}::{q_text}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    synthetic_id = f"{_DETERMINISTIC_ID_PREFIX}{digest.upper()}"
    return synthetic_id, True


def detect_id_collisions(
    records: list[dict[str, Any]],
) -> tuple[dict[str, list[int]], list[dict[str, Any]]]:
    """
    Inspects a batch for duplicate question_ids before persistence.

    Returns:
      id_to_indices: mapping of question_id -> list of record indices that share it.
      collision_report: list of collision details for records with non-unique IDs.
    """
    id_to_indices: dict[str, list[int]] = {}
    for i, rec in enumerate(records):
        qid, _ = generate_stable_question_id(rec, i)
        id_to_indices.setdefault(qid, []).append(i)

    collision_report = []
    for qid, indices in id_to_indices.items():
        if len(indices) > 1:
            collision_report.append({
                "question_id": qid,
                "collision_indices": indices,
                "collision_count": len(indices),
            })
    return id_to_indices, collision_report


# ---------------------------------------------------------------------------
# Embedding text strategy
# ---------------------------------------------------------------------------


def build_embedding_text(record: dict[str, Any]) -> str:
    """
    Constructs the text string to embed for a question record.

    Strategy:
      "<question_text> [OPTIONS: A: <opt_a> B: <opt_b> C: <opt_c> D: <opt_d>] [ANSWER: <correct_answer>]"

    For essay/short-answer questions the OPTIONS section is omitted.

    Rationale:
    - Including the question stem prevents answer-text collisions from dominating
      similarity (two distinct questions with the same correct answer will still
      have different embeddings if their stems differ).
    - Including answer text allows semantic retrieval to surface conceptually
      related questions even when wording differs.
    - OPTIONS are labeled A/B/C/D so option order is semantically meaningful.
    """
    q_text = str(record.get("question_text") or "").strip()
    q_type = str(record.get("question_type") or "").strip()
    correct_answer = str(record.get("correct_answer") or "").strip()

    parts = [q_text]

    options = record.get("options")
    if q_type == "mcq" and options and isinstance(options, list):
        letters = ("A", "B", "C", "D")
        opts_str = " ".join(
            f"{letters[i]}: {opt}" for i, opt in enumerate(options[:4]) if opt
        )
        if opts_str:
            parts.append(f"[OPTIONS: {opts_str}]")

    if correct_answer:
        parts.append(f"[ANSWER: {correct_answer}]")

    return " ".join(parts).strip()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {"question_type", "question_text"}
VALID_QUESTION_TYPES = {"mcq", "short_answer", "essay"}
VALID_MCQ_KEYS = {"A", "B", "C", "D"}


def validate_record_for_persistence(record: dict[str, Any]) -> list[str]:
    """
    Validates a question record before persistence.

    Returns a list of error strings; empty list means the record is valid.
    Does NOT silently discard unknown fields.
    """
    errors: list[str] = []

    q_type = str(record.get("question_type") or "").strip()
    q_text = str(record.get("question_text") or "").strip()

    if not q_text:
        errors.append("question_text is required and cannot be empty.")
    if not q_type:
        errors.append("question_type is required and cannot be empty.")
    elif q_type not in VALID_QUESTION_TYPES:
        errors.append(
            f"question_type '{q_type}' is invalid; must be one of {sorted(VALID_QUESTION_TYPES)}."
        )
        return errors  # further checks depend on type

    if q_type == "mcq":
        options = record.get("options")
        if not isinstance(options, list) or len(options) != 4:
            errors.append("MCQ requires exactly 4 options in 'options' list.")
        correct_opt = record.get("correct_option")
        raw_ans = str(record.get("correct_answer") or "").strip()
        if correct_opt is None or str(correct_opt).strip() == "":
            if raw_ans.upper() in VALID_MCQ_KEYS:
                correct_opt = raw_ans.upper()
                record["correct_option"] = correct_opt
                if isinstance(options, list) and len(options) == 4:
                    idx = ["A", "B", "C", "D"].index(correct_opt)
                    record["correct_answer"] = options[idx]
            elif isinstance(options, list) and len(options) == 4:
                found_idx = None
                for idx, opt in enumerate(options):
                    if str(opt).strip().casefold() == raw_ans.casefold() and raw_ans:
                        found_idx = idx
                        break
                if found_idx is not None:
                    correct_opt = ["A", "B", "C", "D"][found_idx]
                    record["correct_option"] = correct_opt
                    record["correct_answer"] = options[found_idx]
                else:
                    errors.append(
                        "MCQ requires an explicit correct_option ('A', 'B', 'C', or 'D')."
                    )
            else:
                errors.append(
                    "MCQ requires an explicit correct_option ('A', 'B', 'C', or 'D')."
                )
        else:
            norm_opt = str(correct_opt).strip().upper()
            if norm_opt not in VALID_MCQ_KEYS:
                errors.append(
                    f"MCQ correct_option must be one of {sorted(VALID_MCQ_KEYS)}; got '{correct_opt}'."
                )
            else:
                record["correct_option"] = norm_opt
                if isinstance(options, list) and len(options) == 4:
                    idx = ["A", "B", "C", "D"].index(norm_opt)
                    chosen_opt_text = str(options[idx]).strip()
                    if not raw_ans:
                        record["correct_answer"] = chosen_opt_text
        if not str(record.get("correct_answer") or "").strip():
            errors.append("MCQ correct_answer (answer text) is missing or empty.")
    else:
        if not str(record.get("correct_answer") or "").strip():
            errors.append(f"{q_type} question is missing a correct_answer / model answer.")

    return errors


# ---------------------------------------------------------------------------
# SQLAlchemy ORM helpers
# ---------------------------------------------------------------------------


def _record_to_orm_kwargs(
    question_id: str,
    record: dict[str, Any],
    imported_from: Optional[str] = None,
) -> dict[str, Any]:
    """
    Converts a canonical question record to keyword arguments for QuestionBankItem.
    Preserves ALL fields, including unknown source_metadata keys.
    """
    options = record.get("options")
    options_json = json.dumps(options, ensure_ascii=False) if options else None

    source_metadata = record.get("source_metadata")
    source_metadata_json = (
        json.dumps(source_metadata, ensure_ascii=False, default=str)
        if source_metadata
        else None
    )

    validation_warnings = record.get("validation_warnings")
    validation_warnings_json = (
        json.dumps(validation_warnings, ensure_ascii=False)
        if validation_warnings
        else None
    )

    review_reasons = record.get("review_reasons")
    review_reasons_json = (
        json.dumps(review_reasons, ensure_ascii=False) if review_reasons else None
    )

    curriculum_mapping = record.get("curriculum_mapping")
    curriculum_mapping_json = (
        json.dumps(curriculum_mapping, ensure_ascii=False, default=str)
        if curriculum_mapping
        else None
    )

    original_source_metadata = record.get("original_source_metadata")
    original_source_metadata_json = (
        json.dumps(original_source_metadata, ensure_ascii=False, default=str)
        if original_source_metadata
        else None
    )

    page_number = record.get("page_number")
    page_number_str = str(page_number) if page_number is not None else None

    analysis_confidence = record.get("analysis_confidence") or record.get("confidence")
    if analysis_confidence is not None:
        try:
            analysis_confidence = float(analysis_confidence)
        except (TypeError, ValueError):
            analysis_confidence = None

    # Source chunk IDs
    source_chunk_ids = record.get("source_chunk_ids")
    if not source_chunk_ids and curriculum_mapping:
        supporting = curriculum_mapping.get("supporting_chunks") or []
        source_chunk_ids = [
            c.get("chunk_id") for c in supporting if isinstance(c, dict) and c.get("chunk_id")
        ]
    source_chunk_ids_json = (
        json.dumps(source_chunk_ids, ensure_ascii=False) if source_chunk_ids else None
    )

    source_evidence = record.get("source_evidence")
    if not source_evidence and curriculum_mapping:
        source_evidence = curriculum_mapping.get("evidence_excerpt")

    # Classification status
    raw_status = record.get("classification_status") or record.get("review_status")
    if raw_status in ("approved", "rejected", "needs_review", "pending_review"):
        classification_status = raw_status
    elif bool(record.get("needs_teacher_review", True)):
        classification_status = "needs_review"
    else:
        classification_status = "pending_review"

    review_status = record.get("review_status") or classification_status

    return {
        "question_id": question_id,
        "original_question_id": record.get("original_question_id"),
        "question_type": str(record.get("question_type") or "").strip(),
        "question_text": str(record.get("question_text") or "").strip(),
        "options_json": options_json,
        "correct_option": record.get("correct_option"),
        "correct_answer": str(record.get("correct_answer") or ""),
        "explanation": record.get("explanation"),
        "subject": record.get("subject"),
        "curriculum_id": str(record.get("curriculum_id")) if record.get("curriculum_id") is not None else None,
        "unit": record.get("unit"),
        "chapter": record.get("chapter"),
        "lesson": record.get("lesson"),
        "page_number": page_number_str,
        "source_file": record.get("source_file"),
        "answer_source": record.get("answer_source"),
        "verification_status": record.get("verification_status"),
        "source_metadata_json": source_metadata_json,
        "validation_warnings_json": validation_warnings_json,
        "bloom_level": record.get("bloom_level"),
        "difficulty": record.get("difficulty"),
        "learning_objective": record.get("learning_objective"),
        "learning_objective_grounded": bool(record.get("learning_objective_grounded", False)),
        "classification_reasoning": record.get("classification_reasoning"),
        "classification_confidence": record.get("classification_confidence") or analysis_confidence,
        "analysis_confidence": analysis_confidence,
        "classification_method": record.get("classification_method") or "rag_llm",
        "model_version": record.get("model_version"),
        "source_chunk_ids_json": source_chunk_ids_json,
        "source_evidence": source_evidence,
        "classification_status": classification_status,
        "review_status": review_status,
        "needs_teacher_review": bool(record.get("needs_teacher_review", True)),
        "review_reasons_json": review_reasons_json,
        "curriculum_mapping_json": curriculum_mapping_json,
        "original_source_metadata_json": original_source_metadata_json,
        "created_by": record.get("created_by"),
        "embedding_id": None,  # set separately after Chroma sync
        "embedding_status": "pending",
        "embedding_error": None,
        "embedded_at": None,
        "imported_from": imported_from,
    }


def _update_orm_record(
    item: QuestionBankItem,
    record: dict[str, Any],
    imported_from: Optional[str] = None,
) -> None:
    """
    Updates mutable fields on an existing QuestionBankItem while PRESERVING
    teacher review decisions (approved/rejected) and the existing embedding_id.

    Critical invariants:
    - review_status 'approved' or 'rejected' is NEVER overwritten.
    - embedding_id is NOT overwritten here; sync manages it separately.
    - embedding_status is only reset to 'pending' if content fields changed,
      so that unchanged re-imports do not trigger unnecessary re-embedding.
    """
    old_text = item.question_text
    old_answer = item.correct_answer
    old_options = item.options_json

    kwargs = _record_to_orm_kwargs(
        question_id=item.question_id,
        record=record,
        imported_from=imported_from,
    )

    # Detect whether question content has actually changed
    new_text = kwargs["question_text"]
    new_answer = kwargs["correct_answer"]
    new_options = kwargs["options_json"]
    content_changed = (
        old_text != new_text
        or old_answer != new_answer
        or old_options != new_options
    )

    # Update all non-protected fields
    protected_fields = {
        "review_status", "classification_status", "review_notes", "reviewed_by", "reviewed_at",
        "embedding_id", "embedding_status", "embedding_error", "embedded_at",
        "question_id", "id", "created_at"
    }
    # If the item was not yet approved/rejected, allow classification_status to be updated
    if item.classification_status not in ("approved", "rejected"):
        protected_fields.discard("classification_status")
        protected_fields.discard("review_status")

    for attr, val in kwargs.items():
        if attr not in protected_fields:
            setattr(item, attr, val)

    # Reset embedding to pending only if content changed
    if content_changed and item.embedding_status == "synced":
        item.embedding_status = "pending"
        item.embedding_error = None
        logger.info(
            "Question %s content changed on re-import; embedding reset to pending.",
            item.question_id,
        )


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


def normalize_text_for_comparison(text: str) -> str:
    """
    Normalizes text for duplicate detection:
    - Lowercases, collapses whitespace, strips trailing punctuation.
    """
    import re
    if not text:
        return ""
    norm = text.lower()
    norm = re.sub(r"\s+", " ", norm)
    norm = norm.strip().rstrip("?.! ")
    return norm


def detect_exact_and_normalized_duplicates(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Detects exact and normalized text duplicates across a list of records.
    Does NOT delete or merge records.
    Returns a list of duplicate flags (each is a dict describing the match).
    """
    flags: list[dict[str, Any]] = []
    seen_exact: dict[tuple[str, str], str] = {}   # (type, raw_text) -> first qid
    seen_norm: dict[tuple[str, str], str] = {}    # (type, norm_text) -> first qid

    for rec in records:
        qid, _ = generate_stable_question_id(rec, 0)
        q_type = str(rec.get("question_type") or "").strip()
        raw_text = str(rec.get("question_text") or "").strip()
        norm_text = normalize_text_for_comparison(raw_text)

        if not raw_text:
            continue

        exact_key = (q_type, raw_text)
        norm_key = (q_type, norm_text)

        if exact_key in seen_exact:
            flags.append({
                "duplicate_type": "exact",
                "question_id": qid,
                "matches_question_id": seen_exact[exact_key],
                "question_text": raw_text,
                "question_type": q_type,
            })
        elif norm_key in seen_norm:
            flags.append({
                "duplicate_type": "normalized",
                "question_id": qid,
                "matches_question_id": seen_norm[norm_key],
                "question_text": raw_text,
                "question_type": q_type,
            })
        else:
            seen_exact[exact_key] = qid
            seen_norm[norm_key] = qid

    return flags


def detect_semantic_duplicates_against_db(
    new_records: list[dict[str, Any]],
    db: Session,
    chroma_collection: Any = None,
    threshold: float = DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD,
    embeddings: Any = None,
) -> list[dict[str, Any]]:
    """
    Detects semantic duplicates by comparing new records against existing embeddings.

    This is a REVIEW SIGNAL only — no question is deleted or merged.
    Returns candidate pairs with similarity scores above threshold.

    Args:
      new_records: Records about to be inserted.
      db: Active SQLAlchemy session.
      chroma_collection: An already-loaded chromadb Collection object (not Chroma langchain wrapper).
      threshold: Configurable cosine similarity threshold.
      embeddings: HuggingFace embeddings object (reuses project config).

    Returns:
      list of dicts: {question_id, candidate_id, score, match_type: "semantic"}
    """
    if chroma_collection is None:
        return []
    if embeddings is None:
        return []

    flags: list[dict[str, Any]] = []
    try:
        for rec in new_records:
            qid, _ = generate_stable_question_id(rec, 0)
            embed_text = build_embedding_text(rec)
            if not embed_text.strip():
                continue

            # Embed the new record's text
            try:
                vec = embeddings.embed_query(embed_text)
            except Exception as e:
                logger.debug("Could not embed text for semantic dup check on %s: %s", qid, e)
                continue

            # Query existing embeddings — exclude the record's own ID
            try:
                results = chroma_collection.query(
                    query_embeddings=[vec],
                    n_results=5,
                    include=["distances", "metadatas"],
                )
            except Exception as e:
                logger.debug("Chroma query error during semantic dup check: %s", e)
                continue

            ids = results.get("ids", [[]])[0]
            distances = results.get("distances", [[]])[0]

            for cid, dist in zip(ids, distances):
                if cid == qid:
                    continue
                # Chroma returns L2 distances for HF embeddings by default;
                # convert cosine distance: similarity = 1 - (dist / 2) for cosine,
                # or use 1 / (1 + dist) for L2. We normalize conservatively.
                try:
                    sim = float(1.0 - (float(dist) / 2.0))
                    sim = max(0.0, min(1.0, sim))
                except Exception:
                    sim = 0.0

                if sim >= threshold:
                    flags.append({
                        "question_id": qid,
                        "candidate_id": cid,
                        "score": round(sim, 4),
                        "match_type": "semantic",
                        "threshold": threshold,
                    })
    except Exception as exc:
        logger.warning("Semantic duplicate detection failed: %s", exc)

    return flags


# ---------------------------------------------------------------------------
# Chroma embedding helpers
# ---------------------------------------------------------------------------


def _get_or_create_question_bank_collection(
    chroma_persist_dir: Union[str, Path],
) -> Any:
    """
    Returns the 'question_bank' chromadb Collection, creating it if absent.
    Never modifies or deletes the 'curriculum' collection.
    Uses cosine distance to align with the embedding model.
    """
    import chromadb

    path = Path(chroma_persist_dir)
    path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(path))

    existing = {c.name for c in client.list_collections()}
    if QUESTION_BANK_CHROMA_COLLECTION not in existing:
        collection = client.create_collection(
            name=QUESTION_BANK_CHROMA_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info("Created new Chroma collection: '%s'", QUESTION_BANK_CHROMA_COLLECTION)
    else:
        collection = client.get_collection(QUESTION_BANK_CHROMA_COLLECTION)

    # Verify curriculum collection is untouched
    return collection


def close_chroma_client(client_or_collection: Any) -> None:
    """
    Safely releases Chroma background workers, SQLite connections, and segment handles.
    Vital for resource cleanup and preventing WinError 32 PermissionError on Windows.
    """
    if client_or_collection is None:
        return
    client = getattr(client_or_collection, "_client", client_or_collection)
    system = getattr(client, "_system", None)
    if system is not None and hasattr(system, "stop"):
        try:
            system.stop()
        except Exception as exc:
            logger.debug("Chroma system stop exception: %s", exc)
    try:
        from chromadb.api.client import SharedSystemClient
        SharedSystemClient.clear_system_cache()
    except Exception:
        pass


def _upsert_embedding_to_chroma(
    collection: Any,
    question_id: str,
    embed_text: str,
    metadata: dict[str, Any],
    embeddings: Any,
) -> str:
    """
    Upserts a single question's embedding into the Chroma collection.
    Uses question_id as the Chroma document ID for traceability.
    Returns the Chroma document ID used.
    Raises on failure (caller handles embedding_status = 'failed').
    """
    vec = embeddings.embed_query(embed_text)
    # Sanitize metadata: Chroma only accepts str/int/float/bool values
    safe_meta: dict[str, Any] = {}
    for k, v in metadata.items():
        if isinstance(v, (str, int, float, bool)):
            safe_meta[k] = v
        elif v is not None:
            safe_meta[k] = str(v)

    collection.upsert(
        ids=[question_id],
        embeddings=[vec],
        metadatas=[safe_meta],
        documents=[embed_text],
    )
    return question_id


# ---------------------------------------------------------------------------
# Core import function
# ---------------------------------------------------------------------------


def import_questions_to_db(
    records: list[dict[str, Any]],
    db: Session,
    chroma_persist_dir: Optional[Union[str, Path]] = None,
    embeddings: Any = None,
    imported_from: Optional[str] = None,
    semantic_dup_threshold: float = DEFAULT_SEMANTIC_SIMILARITY_THRESHOLD,
    skip_embedding: bool = False,
) -> BatchImportResult:
    """
    Idempotently imports a list of canonical question records into SQLite and Chroma.

    Idempotency rules:
    - If the question_id already exists in SQL, the record is UPDATED (non-protected fields only).
    - Teacher review decisions (approved/rejected) are NEVER overwritten on re-import.
    - If content is unchanged, embedding_status is not reset.
    - Re-importing the same record never creates duplicate SQL rows or Chroma entries.

    Partial-failure:
    - Each record is processed independently.
    - Failures on individual records are captured and returned; the batch continues.
    - Invalid records are reported but not persisted.

    Returns:
      BatchImportResult with per-record outcomes and collision report.
    """
    if chroma_persist_dir is None:
        try:
            from scripts.config import VECTOR_DB_PATH
            chroma_persist_dir = VECTOR_DB_PATH
        except ImportError:
            skip_embedding = True

    # --- Pre-flight: ID collision detection ---
    _, collision_report = detect_id_collisions(records)
    if collision_report:
        logger.warning(
            "ID collisions detected in input batch: %d collision groups.",
            len(collision_report),
        )
        for cr in collision_report:
            logger.warning("  Collision: ID=%s, indices=%s", cr["question_id"], cr["collision_indices"])

    # --- Pre-flight: exact/normalized duplicate detection ---
    dup_flags = detect_exact_and_normalized_duplicates(records)
    dup_map: dict[str, list[dict[str, Any]]] = {}
    for f in dup_flags:
        dup_map.setdefault(f["question_id"], []).append(f)

    # --- Chroma collection ---
    chroma_collection = None
    if not skip_embedding and embeddings is not None and chroma_persist_dir is not None:
        try:
            chroma_collection = _get_or_create_question_bank_collection(chroma_persist_dir)
        except Exception as exc:
            logger.warning("Could not initialize Chroma collection; embeddings will be skipped: %s", exc)

    # --- Per-record processing ---
    outcomes: list[QuestionBankItemOutcome] = []
    inserted = updated = skipped = invalid_count = errored = 0

    try:
        for idx, record in enumerate(records):
            question_id, is_synthetic = generate_stable_question_id(record, idx)
            outcome = QuestionBankItemOutcome(
                input_index=idx,
                question_id=question_id,
                status="pending",
            )

            # Attach duplicate flags to outcome
            if question_id in dup_map:
                outcome.duplicate_flags = dup_map[question_id]
                outcome.warnings.append(
                    f"Duplicate detected: {dup_map[question_id][0]['duplicate_type']} of "
                    f"'{dup_map[question_id][0]['matches_question_id']}'."
                )

            # --- Validation ---
            validation_errors = validate_record_for_persistence(record)
            if validation_errors:
                outcome.status = "invalid"
                outcome.errors = validation_errors
                invalid_count += 1
                outcomes.append(outcome)
                logger.warning("Invalid record at index %d (%s): %s", idx, question_id, validation_errors)
                continue

            # --- SQL persistence ---
            try:
                existing = db.query(QuestionBankItem).filter(
                    QuestionBankItem.question_id == question_id
                ).first()

                if existing is not None:
                    # Preserve approved/rejected decisions — skip content update for approved records
                    if existing.review_status in ("approved", "rejected"):
                        outcome.status = "skipped"
                        outcome.sql_id = existing.id
                        outcome.embedding_status = existing.embedding_status
                        outcome.warnings.append(
                            f"Record has review_status='{existing.review_status}'; "
                            "content update skipped to preserve teacher decision."
                        )
                        skipped += 1
                    else:
                        _update_orm_record(existing, record, imported_from=imported_from)
                        db.flush()
                        outcome.status = "updated"
                        outcome.sql_id = existing.id
                        outcome.embedding_status = existing.embedding_status
                        updated += 1
                else:
                    kwargs = _record_to_orm_kwargs(question_id, record, imported_from=imported_from)
                    new_item = QuestionBankItem(**kwargs)
                    db.add(new_item)
                    db.flush()  # get auto-assigned id
                    outcome.status = "inserted"
                    outcome.sql_id = new_item.id
                    outcome.embedding_status = "pending"
                    inserted += 1

            except Exception as exc:
                db.rollback()
                outcome.status = "error"
                outcome.errors.append(f"SQL persistence failed: {exc}")
                errored += 1
                outcomes.append(outcome)
                logger.error("SQL persistence failed for record %d (%s): %s", idx, question_id, exc)
                continue

            # --- Chroma embedding sync ---
            if not skip_embedding and chroma_collection is not None and embeddings is not None:
                # Only sync if embedding is pending or failed
                db_item = db.query(QuestionBankItem).filter(
                    QuestionBankItem.question_id == question_id
                ).first()
                if db_item and db_item.embedding_status in ("pending", "failed"):
                    embed_text = build_embedding_text(record)
                    meta = {
                        "question_id": question_id,
                        "question_type": str(record.get("question_type") or ""),
                        "bloom_level": str(record.get("bloom_level") or ""),
                        "difficulty": str(record.get("difficulty") or ""),
                        "review_status": db_item.review_status,
                        "sql_id": db_item.id,
                    }
                    try:
                        chroma_id = _upsert_embedding_to_chroma(
                            chroma_collection,
                            question_id,
                            embed_text,
                            meta,
                            embeddings,
                        )
                        db_item.embedding_id = chroma_id
                        db_item.embedding_status = "synced"
                        db_item.embedding_error = None
                        db_item.embedded_at = datetime.now(timezone.utc)
                        outcome.embedding_status = "synced"
                        db.flush()
                        logger.debug("Embedded question %s into Chroma.", question_id)
                    except Exception as exc:
                        db_item.embedding_status = "failed"
                        db_item.embedding_error = str(exc)[:500]
                        outcome.embedding_status = "failed"
                        outcome.warnings.append(f"Chroma embedding failed (SQL committed): {exc}")
                        db.flush()
                        logger.warning(
                            "Chroma embedding failed for %s (SQL is committed): %s",
                            question_id, exc,
                        )

            outcomes.append(outcome)

        # --- Final SQL commit ---
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error("Final batch commit failed: %s", exc)
            # Mark all outcomes as errored
            for o in outcomes:
                if o.status in ("inserted", "updated"):
                    o.status = "error"
                    o.errors.append(f"Batch commit failed: {exc}")
                    errored += 1
                    if o.status == "inserted":
                        inserted -= 1
                    elif o.status == "updated":
                        updated -= 1
    finally:
        if chroma_collection is not None:
            close_chroma_client(chroma_collection)

    return BatchImportResult(
        total_input=len(records),
        inserted=inserted,
        updated=updated,
        skipped=skipped,
        invalid=invalid_count,
        errored=errored,
        outcomes=outcomes,
        collision_report=collision_report,
    )


# ---------------------------------------------------------------------------
# Reconciliation / retry for pending and failed embeddings
# ---------------------------------------------------------------------------


def reconcile_pending_embeddings(
    db: Session,
    chroma_persist_dir: Union[str, Path],
    embeddings: Any,
    statuses: tuple[str, ...] = ("pending", "failed"),
    batch_size: int = 50,
) -> dict[str, Any]:
    """
    Retries Chroma embedding for all records whose embedding_status is in `statuses`.

    Safe retry behavior:
    - Chroma upsert is idempotent (same ID -> overwrite).
    - Only records with matching embedding_status are processed.
    - SQL embedding_status is updated atomically per record.
    - Returns a summary of synced, failed, and skipped counts.
    """
    collection = None
    try:
        collection = _get_or_create_question_bank_collection(chroma_persist_dir)
    except Exception as exc:
        return {"error": str(exc), "synced": 0, "failed": 0, "skipped": 0}

    synced = failed = skipped = 0

    try:
        items = (
            db.query(QuestionBankItem)
            .filter(QuestionBankItem.embedding_status.in_(list(statuses)))
            .limit(batch_size)
            .all()
        )

        for item in items:
            record = {
                "question_id": item.question_id,
                "question_type": item.question_type,
                "question_text": item.question_text,
                "correct_answer": item.correct_answer,
                "correct_option": item.correct_option,
                "options": json.loads(item.options_json) if item.options_json else [],
            }
            embed_text = build_embedding_text(record)
            meta = {
                "question_id": item.question_id,
                "question_type": item.question_type,
                "bloom_level": str(item.bloom_level or ""),
                "difficulty": str(item.difficulty or ""),
                "review_status": item.review_status,
                "sql_id": item.id,
            }
            try:
                chroma_id = _upsert_embedding_to_chroma(
                    collection, item.question_id, embed_text, meta, embeddings
                )
                item.embedding_id = chroma_id
                item.embedding_status = "synced"
                item.embedding_error = None
                item.embedded_at = datetime.now(timezone.utc)
                db.flush()
                synced += 1
            except Exception as exc:
                item.embedding_status = "failed"
                item.embedding_error = str(exc)[:500]
                db.flush()
                failed += 1
                logger.warning("Reconciliation embedding failed for %s: %s", item.question_id, exc)

        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error("Reconciliation commit failed: %s", exc)
            return {"error": str(exc), "synced": 0, "failed": failed, "skipped": skipped}
    finally:
        if collection is not None:
            close_chroma_client(collection)

    return {
        "total_processed": len(items),
        "synced": synced,
        "failed": failed,
        "skipped": skipped,
    }


# ---------------------------------------------------------------------------
# Question Bank Query & Exam Integration Functions
# ---------------------------------------------------------------------------


def query_question_bank(
    db: Session,
    lesson: Optional[str] = None,
    chapter: Optional[str] = None,
    bloom_level: Optional[str] = None,
    difficulty: Optional[str] = None,
    question_type: Optional[str] = None,
    review_status: str = "approved",
    limit: int = 10,
) -> list[QuestionBankItem]:
    """
    Queries verified or approved questions from the Question Bank SQL store.
    Allows filtering by curriculum attributes and difficulty/Bloom taxonomy.
    """
    query = db.query(QuestionBankItem)
    if review_status:
        query = query.filter(QuestionBankItem.review_status == review_status)
    if lesson:
        query = query.filter(QuestionBankItem.lesson.ilike(f"%{lesson}%"))
    if chapter:
        query = query.filter(QuestionBankItem.chapter.ilike(f"%{chapter}%"))
    if bloom_level:
        query = query.filter(QuestionBankItem.bloom_level == bloom_level.lower())
    if difficulty:
        query = query.filter(QuestionBankItem.difficulty == difficulty.lower())
    if question_type:
        query = query.filter(QuestionBankItem.question_type == question_type.lower())

    return query.limit(limit).all()


def persist_exam_to_question_bank(
    exam: dict[str, Any],
    db: Session,
    chroma_persist_dir: Optional[Union[str, Path]] = None,
    embeddings: Any = None,
    imported_from: Optional[str] = None,
    skip_embedding: bool = False,
) -> BatchImportResult:
    """
    Persists AI-generated exam questions into the question bank.
    Translates exam question schema to the QuestionBankItem schema,
    preserving rubrics, citations/curriculum mappings, model answers,
    Bloom taxonomy rationale, and marks them for teacher review.
    """
    questions = exam.get("questions") or []
    if not questions:
        return BatchImportResult(
            total_input=0,
            inserted=0,
            updated=0,
            skipped=0,
            invalid=0,
            errored=0,
            outcomes=[],
            collision_report=[],
        )

    topic = exam.get("topic") or exam.get("exam_title") or "Generated Exam"
    lesson_id = exam.get("lesson_id")
    source_label = imported_from or f"Exam Generation: {topic}"

    canonical_records: list[dict[str, Any]] = []
    for idx, q in enumerate(questions, start=1):
        q_type = str(q.get("question_type") or "mcq").strip().lower()
        q_text = str(q.get("question") or q.get("question_text") or "").strip()
        correct_ans = str(q.get("reference_answer") or q.get("correct_answer") or "").strip()

        # Handle MCQ options and correct option
        options = q.get("options") or []
        correct_opt = None
        if q_type == "mcq":
            raw_opt = q.get("correct_answer")
            if raw_opt and str(raw_opt).strip().upper() in ("A", "B", "C", "D"):
                correct_opt = str(raw_opt).strip().upper()

        # Curriculum evidence from source_refs
        source_refs = q.get("source_refs") or []
        primary_ref = source_refs[0] if source_refs else {}
        evidence_excerpt = primary_ref.get("evidence_quote") or ""
        matched_chunk_id = primary_ref.get("chunk_id")
        matched_source = primary_ref.get("source")

        curriculum_mapping = {
            "mapping_status": "mapped" if matched_chunk_id else "unresolved",
            "confidence_score": 0.95 if q.get("verified") else 0.85,
            "matched_chunk_id": matched_chunk_id,
            "matched_source_document": matched_source,
            "matched_lesson_id": lesson_id,
            "evidence_excerpt": evidence_excerpt,
            "supporting_chunks": source_refs,
            "needs_review": not bool(q.get("verified")),
            "review_reasons": [] if q.get("verified") else ["Newly generated exam question awaiting human review."],
        }

        source_meta = {
            "exam_topic": topic,
            "max_score": q.get("max_score", 1),
            "rubric": q.get("rubric"),
            "explanation": q.get("explanation"),
            "bloom_rationale": q.get("bloom_rationale"),
            "generation_model": exam.get("model"),
        }

        qid = q.get("question_id") or f"GEN-{hashlib.sha256(f'{topic}:{idx}:{q_text}'.encode()).hexdigest()[:12].upper()}"

        record = {
            "question_id": qid,
            "original_question_id": q.get("question_id"),
            "question_type": q_type,
            "question_text": q_text,
            "options": options,
            "correct_option": correct_opt,
            "correct_answer": correct_ans,
            "chapter": exam.get("topic"),
            "lesson": lesson_id or exam.get("lesson_title"),
            "source_file": matched_source,
            "answer_source": "Model Generated",
            "verification_status": "Verified by AI" if q.get("verified") else "Generated by AI",
            "source_metadata": source_meta,
            "validation_warnings": [],
            "bloom_level": q.get("bloom_level"),
            "difficulty": q.get("difficulty"),
            "classification_reasoning": q.get("bloom_rationale"),
            "analysis_confidence": 0.95 if q.get("verified") else 0.85,
            "needs_teacher_review": True,
            "review_reasons": ["Generated exam question requires teacher approval."],
            "curriculum_mapping": curriculum_mapping,
            "original_source_metadata": {"generated_from_topic": topic, "lesson_id": lesson_id},
        }
        canonical_records.append(record)

    return import_questions_to_db(
        canonical_records,
        db=db,
        chroma_persist_dir=chroma_persist_dir,
        embeddings=embeddings,
        imported_from=source_label,
        skip_embedding=skip_embedding,
    )


def process_and_import_question_bank(
    source: Any,
    db: Session,
    vector_store: Any = None,
    embeddings: Any = None,
    chroma_persist_dir: Optional[Union[str, Path]] = None,
    skip_analysis: bool = False,
    skip_mapping: bool = False,
    skip_embedding: bool = False,
    allow_partial: bool = True,
    confidence_threshold: float = 0.75,
    min_mapping_confidence: float = 0.65,
    file_format: Optional[str] = None,
) -> dict[str, Any]:
    """
    End-to-end integration orchestrating:
      1. Processing & Ingestion (scripts.question_processing)
      2. Question Analysis (scripts.question_analysis)
      3. Curriculum Mapping (scripts.curriculum_mapping)
      4. Question Bank Persistence & Embedding (scripts.question_bank_service)

    Preserves question IDs, metadata, partial errors, and outputs a complete pipeline report.
    """
    from scripts.question_processing import process_question_source
    from scripts.question_analysis import analyze_questions_batch
    from scripts.curriculum_mapping import map_questions_batch

    pipeline_report: dict[str, Any] = {
        "stage_1_processing": {},
        "stage_2_analysis": {},
        "stage_3_mapping": {},
        "stage_4_persistence": {},
        "status": "success",
    }

    # Stage 1: Parsing, cleaning, and validation
    proc_result = process_question_source(source, file_format=file_format)
    pipeline_report["stage_1_processing"] = proc_result.to_dict()

    valid_questions = proc_result.valid_records
    if not valid_questions:
        pipeline_report["status"] = "empty_or_invalid"
        return pipeline_report

    # Stage 2: Question analysis (Bloom taxonomy, difficulty, learning objectives)
    if not skip_analysis:
        analysis_result = analyze_questions_batch(
            valid_questions,
            allow_partial=allow_partial,
            confidence_threshold=confidence_threshold,
        )
        pipeline_report["stage_2_analysis"] = analysis_result.to_dict()
        analyzed_questions = analysis_result.questions
    else:
        analyzed_questions = valid_questions

    # Stage 3: Curriculum mapping (RAG grounding to actual chunks)
    if not skip_mapping:
        mapping_result = map_questions_batch(
            analyzed_questions,
            store=vector_store,
            min_confidence=min_mapping_confidence,
            allow_partial=allow_partial,
        )
        pipeline_report["stage_3_mapping"] = mapping_result.to_dict()
        mapped_questions = mapping_result.questions
    else:
        mapped_questions = analyzed_questions

    # Stage 4: Persistence into SQLite & Chroma question_bank collection
    import_result = import_questions_to_db(
        mapped_questions,
        db=db,
        chroma_persist_dir=chroma_persist_dir,
        embeddings=embeddings,
        imported_from=str(source) if isinstance(source, (str, Path)) else "Pipeline Ingestion",
        skip_embedding=skip_embedding,
    )
    pipeline_report["stage_4_persistence"] = import_result.to_dict()

    return pipeline_report


# ==============================================================================
# Stage 5: In-Context Learning & Exemplar Retrieval
# ==============================================================================


def retrieve_approved_exemplars(
    db: Session,
    question_text: str,
    limit: int = 2,
    exclude_question_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Retrieves previously teacher-approved questions to serve as in-context reference
    examples for LLM classification, enabling the system to learn from approved feedback.

    Critical safeguard:
    - Excludes `exclude_question_id` to strictly prevent data leakage.
    - Only retrieves records with classification_status == 'approved'.
    """
    if not question_text or not question_text.strip():
        return []

    query = db.query(QuestionBankItem).filter(
        QuestionBankItem.classification_status == "approved"
    )
    if exclude_question_id:
        query = query.filter(QuestionBankItem.question_id != exclude_question_id)

    # Keywords matching
    words = [w.lower() for w in re.findall(r"\w{4,}", question_text)[:5]]
    exemplars: list[QuestionBankItem] = []

    if words:
        filters = [QuestionBankItem.question_text.ilike(f"%{w}%") for w in words]
        from sqlalchemy import or_
        exemplars = query.filter(or_(*filters)).limit(limit).all()

    if len(exemplars) < limit:
        remaining = limit - len(exemplars)
        existing_ids = {e.id for e in exemplars}
        fallback = (
            query.filter(~QuestionBankItem.id.in_(existing_ids) if existing_ids else True)
            .order_by(QuestionBankItem.id.desc())
            .limit(remaining)
            .all()
        )
        exemplars.extend(fallback)

    results: list[dict[str, Any]] = []
    for item in exemplars:
        results.append({
            "question_id": item.question_id,
            "question_text": item.question_text,
            "question_type": item.question_type,
            "bloom_level": item.bloom_level,
            "difficulty": item.difficulty,
            "lesson": item.lesson,
            "unit": item.unit,
            "classification_reasoning": item.classification_reasoning,
        })
    return results


# ==============================================================================
# Stage 6: Curriculum-Grounded Classification Pipeline
# ==============================================================================


def classify_and_ground_question(
    question_dict: dict[str, Any],
    db: Session,
    curriculum_id: Optional[Union[str, int]] = None,
    collection_name: Optional[str] = None,
    chroma_persist_dir: Optional[Union[str, Path]] = None,
    top_k: int = 5,
    confidence_threshold: float = 0.70,
    llm_provider: Optional[str] = None,
    model_name: Optional[str] = None,
    embeddings: Any = None,
    allow_fallback: bool = False,
) -> dict[str, Any]:
    """
    Performs curriculum-grounded classification for a newly submitted question:
      1. Retrieves evidence chunks from the targeted Chroma collection.
      2. In-context reference retrieval from teacher-approved examples.
      3. Prompts LLM for structured curriculum mapping, Bloom taxonomy, cognitive difficulty,
         and explicit supporting chunk citation.
      4. Strictly validates returned chunk IDs against actual retrieval results (no hallucination).
      5. Computes a calibrated heuristic confidence score and flags low-confidence or
         unsupported cases for teacher review ('needs_review').
    """
    from scripts.config import VECTOR_DB_PATH
    from scripts.curriculum_mapping import (
        _safely_get_vectorstore,
        _normalize_relevance_score,
        extract_evidence_excerpt,
    )
    from scripts.question_analysis import _send_analysis_completion, _extract_json_object

    target_dir = chroma_persist_dir or VECTOR_DB_PATH
    raw_qid = str(question_dict.get("question_id") or "").strip()
    if raw_qid:
        qid = raw_qid
    else:
        qid, _ = generate_stable_question_id(question_dict, 0)
    q_text = str(question_dict.get("question_text") or "").strip()
    q_type = str(question_dict.get("question_type") or "mcq").strip().lower()
    options = question_dict.get("options") or []
    correct_ans = str(question_dict.get("correct_answer") or "").strip()
    explanation = question_dict.get("explanation")

    # Step 1: Resolve Chroma collection
    target_col = collection_name or "curriculum"
    if curriculum_id and not collection_name:
        from app.models import Curriculum
        try:
            curr_row = db.query(Curriculum).filter_by(id=int(curriculum_id)).first()
            if curr_row and curr_row.collection_name:
                target_col = curr_row.collection_name
        except Exception:
            pass

    # Step 2: Retrieve evidence from Chroma
    vstore = _safely_get_vectorstore(persist_dir=target_dir, collection_name=target_col)
    topic_meta = " ".join(filter(None, [str(question_dict.get(k) or "").strip() for k in ("subject", "lesson", "unit", "chapter")]))
    query_str = f"{q_text} {correct_ans} {topic_meta}".strip()
    query_keywords = re.findall(r"\w+", query_str)

    retrieved_items: list[tuple[Any, float]] = []
    is_distance = False
    if vstore is not None:
        try:
            if hasattr(vstore, "similarity_search_with_relevance_scores"):
                retrieved_items = vstore.similarity_search_with_relevance_scores(query=query_str, k=top_k)
                is_distance = False
            elif hasattr(vstore, "similarity_search_with_score"):
                retrieved_items = vstore.similarity_search_with_score(query=query_str, k=top_k)
                is_distance = True
            elif hasattr(vstore, "similarity_search"):
                docs = vstore.similarity_search(query=query_str, k=top_k)
                retrieved_items = [(doc, 0.8) for doc in docs]
                is_distance = False
        except Exception as exc:
            logger.warning("Evidence retrieval failed for %s: %s", qid, exc)

    supporting_chunks: list[dict[str, Any]] = []
    verified_chunk_ids: set[str] = set()

    for doc, raw_score in retrieved_items:
        meta = getattr(doc, "metadata", {}) or {}
        cid = str(meta.get("chunk_id", "")).strip() or "unknown"
        if cid != "unknown":
            verified_chunk_ids.add(cid)
        try:
            sim = _normalize_relevance_score(raw_score, is_distance=is_distance)
        except Exception:
            sim = 0.80
        excerpt = extract_evidence_excerpt(getattr(doc, "page_content", ""), query_keywords)
        supporting_chunks.append({
            "chunk_id": cid,
            "source_document": str(meta.get("source", "")),
            "chapter_id": meta.get("chapter_id"),
            "chapter_title": meta.get("chapter_title"),
            "lesson_id": meta.get("lesson_id"),
            "lesson_title": meta.get("lesson_title"),
            "pdf_page_start": meta.get("pdf_page_start"),
            "pdf_page_end": meta.get("pdf_page_end"),
            "similarity_score": sim,
            "evidence_excerpt": excerpt,
        })

    top_similarity = supporting_chunks[0]["similarity_score"] if supporting_chunks else 0.0

    # Step 3: Fetch approved exemplars for in-context demonstration (few-shot)
    exemplars = retrieve_approved_exemplars(
        db=db,
        question_text=q_text,
        limit=2,
        exclude_question_id=qid,
    )

    # Step 4: Prompt LLM with evidence and exemplars
    evidence_text = "\n".join([
        f"- Chunk [{c['chunk_id']}] (Lesson: {c.get('lesson_title') or c.get('lesson_id')}, Page: {c.get('pdf_page_start')}): {c['evidence_excerpt']}"
        for c in supporting_chunks
    ]) if supporting_chunks else "None retrieved."

    exemplars_text = "\n".join([
        f"- Example: \"{ex['question_text']}\" -> Bloom: {ex.get('bloom_level')}, Difficulty: {ex.get('difficulty')}, Lesson: {ex.get('lesson')}"
        for ex in exemplars
    ]) if exemplars else "None available."

    prompt = f"""You are an expert psychometrician and curriculum analyst.
You must classify the following teacher-submitted educational question. Do NOT generate a new question.

### Question Under Analysis:
- Text: {q_text}
- Question Type: {q_type}
- Options: {options if q_type == 'mcq' else 'N/A'}
- Correct Answer / Model Answer: {correct_ans}

### Retrieved Curriculum Evidence Chunks (from course vector store):
{evidence_text}

### Teacher-Approved Reference Exemplars:
{exemplars_text}

### Cognitive Taxonomy Standards:
1. Bloom's Revised Taxonomy (evaluate cognitive task required by student, NOT superficial keywords):
   - "Remember": Recall, retrieve, or recognize terminology, definitions, dates, or isolated facts.
   - "Understand": Comprehend meaning, explain in own words, summarize, interpret, or contrast concepts.
   - "Apply": Execute, calculate, or implement a rule, formula, procedure, or technique to a specific problem.
   - "Analyze": Break down components, identify structure, diagnose relationships, or examine trade-offs.
   - "Evaluate": Justify decisions, critique methods, or make informed judgments against defined criteria.
   - "Create": Synthesize elements to propose novel solutions, design workflows, or formulate original models.
   * REQUIRED: bloom_level MUST be exactly one of: ["Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"].

2. Cognitive Difficulty (evaluate cognitive steps, reasoning complexity, and depth independently of Bloom):
   - "Easy": Single-step cognitive operation; straightforward recall or simple classification; unambiguous cues.
   - "Medium": Multi-step reasoning; transferring concepts to scenarios; discerning subtle distractor boundaries.
   - "Hard": Complex multi-step synthesis, edge cases, trade-offs, or multiple interacting constraints.
   * REQUIRED: difficulty MUST be exactly one of: ["Easy", "Medium", "Hard"].

3. Curriculum Grounding Rules:
   - Grounding MUST be strictly based on the provided Retrieved Curriculum Evidence Chunks.
   - If the retrieved evidence directly covers the topic of this question:
     * evidence_sufficient: true
     * supporting_chunk_ids: list containing only chunk IDs from the retrieved evidence chunks above ({list(verified_chunk_ids)}) that actually support the answer.
     * source_evidence: verbatim quote or excerpt from the supporting chunk(s).
     * subject, unit, lesson: specific topic names derived directly from the supporting chunk metadata.
     * page_number: page number from supporting chunk or null.
   - If the retrieved evidence does NOT cover or support the question (unrelated topic, general knowledge, or outside curriculum):
     * evidence_sufficient: false
     * supporting_chunk_ids: []
     * source_evidence: null
     * subject: "Unknown"
     * unit: "Unknown"
     * lesson: "Unknown"
     * page_number: null
     * IMPORTANT: Even when evidence is missing or insufficient, you MUST STILL classify
       bloom_level and difficulty from the cognitive demand of the question text itself.
       NEVER return "Unknown" for bloom_level or difficulty — these fields are ALWAYS
       determinable from the question alone, regardless of curriculum grounding.

4. Confidence Calibration:
   - reported_confidence: numeric float between 0.0 and 1.0 reflecting your certainty in the
     cognitive classification (bloom_level + difficulty). This score is INDEPENDENT of whether
     curriculum evidence was found. A question with no matching curriculum can still earn high
     confidence if the cognitive level is unambiguous from the question text.

Respond with ONLY a valid JSON object matching this schema:
{{
  "bloom_level": "Remember",
  "difficulty": "Easy",
  "evidence_sufficient": true,
  "subject": "string or Unknown",
  "unit": "string or Unknown",
  "lesson": "string or Unknown",
  "page_number": "string or null",
  "supporting_chunk_ids": ["chunk_id"],
  "source_evidence": "quote or null",
  "classification_reasoning": "clear explanation justifying the cognitive level and difficulty",
  "reported_confidence": 0.85
}}"""

    llm_data: dict[str, Any] = {}
    review_reasons: list[str] = []
    llm_call_succeeded = True

    try:
        raw_output = _send_analysis_completion(prompt)
        llm_data = _extract_json_object(raw_output)
    except Exception as exc:
        logger.warning("LLM classification call failed for %s: %s.", qid, exc)
        llm_call_succeeded = False
        if not allow_fallback:
            # On-demand manual classification requests must report genuine failure
            raise RuntimeError(f"AI classification provider error: {exc}") from exc
        review_reasons.append(f"Model classification failed: {exc}")
        llm_data = {
            "subject": "Unknown",
            "unit": "Unknown",
            "lesson": "Unknown",
            "page_number": None,
            "supporting_chunk_ids": [],
            "source_evidence": None,
            "evidence_sufficient": False,
            "bloom_level": "Unknown",
            "difficulty": "Unknown",
            "classification_reasoning": f"AI classification failed ({exc}). Requires manual teacher classification.",
            "reported_confidence": None,
        }

    # Step 5: Validate returned chunk IDs against actual retrieval results
    raw_chunk_ids = llm_data.get("supporting_chunk_ids") or []
    valid_cited_chunk_ids = [cid for cid in raw_chunk_ids if str(cid).strip() in verified_chunk_ids]

    # Normalize Bloom and Difficulty
    raw_bloom = str(llm_data.get("bloom_level") or "").strip().capitalize()
    allowed_blooms = {"Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"}
    # When LLM call succeeded, bloom MUST be a valid level. Never return Unknown on LLM success.
    # "Unknown" is only acceptable when the LLM call itself failed (and fallback dict was used).
    if raw_bloom in allowed_blooms:
        bloom_level = raw_bloom
    elif llm_call_succeeded:
        # LLM returned unexpected value — default to Remember (lowest cognitive level)
        bloom_level = "Remember"
        review_reasons.append(
            f"Bloom level \"{raw_bloom}\" returned by LLM is not a valid Bloom level; "
            "defaulted to Remember. Manual review recommended."
        )
    else:
        bloom_level = "Unknown"  # LLM call failed — genuinely unknown

    raw_diff = str(llm_data.get("difficulty") or "").strip().capitalize()
    allowed_diffs = {"Easy", "Medium", "Hard"}
    # Same logic: never return Unknown for difficulty when LLM call succeeded.
    if raw_diff in allowed_diffs:
        difficulty = raw_diff
    elif llm_call_succeeded:
        difficulty = "Medium"  # neutral fallback when LLM call succeeded but returned bad value
        review_reasons.append(
            f"Difficulty \"{raw_diff}\" returned by LLM is not a valid difficulty; "
            "defaulted to Medium. Manual review recommended."
        )
    else:
        difficulty = "Unknown"  # LLM call failed — genuinely unknown

    # Step 6: Safe Calibrated Confidence Calculation
    llm_conf_raw = llm_data.get("reported_confidence")
    if llm_conf_raw is not None and llm_call_succeeded:
        try:
            llm_conf = float(llm_conf_raw)
            llm_conf = max(0.0, min(1.0, llm_conf))
        except (ValueError, TypeError):
            llm_conf = 0.80
    else:
        llm_conf = None

    evidence_sufficient = (
        bool(llm_data.get("evidence_sufficient", False))
        and len(valid_cited_chunk_ids) > 0
        and top_similarity >= 0.40
    )

    if not llm_call_succeeded or llm_conf is None:
        # LLM call failed: cannot compute any meaningful confidence score
        classification_confidence = None
        grounding_confidence = None
    elif evidence_sufficient:
        # Fully grounded: classification confidence = LLM cognitive certainty.
        # Grounding confidence = weighted evidence quality + citation validity.
        classification_confidence = round(llm_conf, 2)
        grounding_confidence = round(
            0.60 * float(top_similarity) + 0.40 * 1.0,  # similarity + citation coverage
            2
        )
    else:
        # No curriculum grounding: classification confidence = LLM cognitive certainty directly.
        # Do NOT penalize Bloom/Difficulty confidence for missing evidence.
        classification_confidence = round(llm_conf, 2)
        grounding_confidence = 0.0  # explicitly no curriculum support

    # composite_confidence is what gets exposed as classification_confidence in the API
    composite_confidence = classification_confidence

    # Step 7: Curriculum Grounding Integrity & Status Assignment
    if evidence_sufficient:
        subject = llm_data.get("subject") or "Unknown"
        unit = llm_data.get("unit") or "Unknown"
        lesson = llm_data.get("lesson") or "Unknown"
        page_number = str(llm_data.get("page_number")) if llm_data.get("page_number") is not None else None
        source_evidence = llm_data.get("source_evidence")
    else:
        if not supporting_chunks:
            review_reasons.append(
                "No curriculum evidence retrieved for this question. "
                "Bloom level and difficulty were classified from the question text alone; "
                "subject and lesson cannot be verified without curriculum grounding."
            )
        else:
            review_reasons.append(
                "Retrieved curriculum evidence does not cover this question's topic. "
                "Bloom level and difficulty were classified from cognitive demand only; "
                "subject and lesson remain unverified."
            )
        subject = "Unknown"
        unit = "Unknown"
        lesson = "Unknown"
        page_number = None
        source_evidence = None
        valid_cited_chunk_ids = []

    if composite_confidence is not None and composite_confidence < confidence_threshold:
        review_reasons.append(
            f"Low classification confidence ({composite_confidence:.2f} < {confidence_threshold:.2f})"
        )

    classification_status = "needs_review" if review_reasons else "pending_review"

    # Step 8: Accurate MCQ answer & option preservation
    correct_opt = question_dict.get("correct_option")
    if not correct_opt and q_type == "mcq":
        raw_ans = str(correct_ans).strip()
        if raw_ans.upper() in ("A", "B", "C", "D"):
            correct_opt = raw_ans.upper()
        elif isinstance(options, list):
            for idx, opt in enumerate(options):
                if str(opt).strip().casefold() == raw_ans.casefold() and raw_ans:
                    correct_opt = ["A", "B", "C", "D"][idx]
                    break
    if correct_opt in ("A", "B", "C", "D") and isinstance(options, list) and len(options) == 4:
        idx = ["A", "B", "C", "D"].index(correct_opt)
        if not correct_ans:
            correct_ans = str(options[idx]).strip()

    return {
        "question_id": qid,
        "question_text": q_text,
        "question_type": q_type,
        "options": options,
        "correct_option": correct_opt,
        "correct_answer": correct_ans,
        "explanation": explanation,
        "subject": subject,
        "unit": unit,
        "lesson": lesson,
        "page_number": page_number,
        "bloom_level": bloom_level,
        "difficulty": difficulty,
        "classification_reasoning": llm_data.get("classification_reasoning") or "Evaluated against cognitive criteria.",
        "classification_confidence": composite_confidence,
        "grounding_confidence": grounding_confidence if llm_call_succeeded else None,
        "classification_status": classification_status,
        "classification_method": "rag_llm",
        "model_version": model_name or "active_provider",
        "source_chunk_ids": valid_cited_chunk_ids,
        "source_evidence": source_evidence,
        "supporting_chunks": supporting_chunks,
        "needs_teacher_review": len(review_reasons) > 0,
        "review_reasons": review_reasons,
        "curriculum_id": str(curriculum_id) if curriculum_id is not None else None,
    }


# ==============================================================================
# Stage 7: Teacher Review & Approval Actions
# ==============================================================================


def approve_question_item(
    db: Session,
    question_id: str,
    reviewer_name: str,
    reviewer_id: Optional[int] = None,
    corrections: Optional[dict[str, Any]] = None,
    notes: Optional[str] = None,
) -> QuestionBankItem:
    """
    Approves a question item, recording reviewer identity, timestamps, notes,
    and capturing teacher corrections diff for incremental learning.
    """
    item = db.query(QuestionBankItem).filter_by(question_id=question_id).first()
    if not item:
        raise KeyError(f"Question with ID '{question_id}' not found in question bank.")

    # Record teacher corrections diff
    orig_values = {
        "bloom_level": item.bloom_level,
        "difficulty": item.difficulty,
        "lesson": item.lesson,
        "unit": item.unit,
        "subject": item.subject,
    }

    if corrections:
        for k, v in corrections.items():
            if hasattr(item, k) and v is not None:
                setattr(item, k, v)

    corrections_record = {
        "original_proposed": orig_values,
        "approved_values": {
            "bloom_level": item.bloom_level,
            "difficulty": item.difficulty,
            "lesson": item.lesson,
            "unit": item.unit,
            "subject": item.subject,
        },
        "corrections_made": bool(corrections),
        "reviewed_by": reviewer_name,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes,
    }

    item.teacher_corrections_json = json.dumps(corrections_record, ensure_ascii=False)
    item.classification_status = "approved"
    item.review_status = "approved"
    item.needs_teacher_review = False
    item.reviewed_by = reviewer_name
    item.reviewed_at = datetime.now(timezone.utc)
    item.review_notes = notes

    db.commit()
    db.refresh(item)
    return item


def reject_question_item(
    db: Session,
    question_id: str,
    reviewer_name: str,
    reviewer_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> QuestionBankItem:
    """
    Rejects a question item, keeping full audit logs and reviewer notes.
    """
    item = db.query(QuestionBankItem).filter_by(question_id=question_id).first()
    if not item:
        raise KeyError(f"Question with ID '{question_id}' not found in question bank.")

    item.classification_status = "rejected"
    item.review_status = "rejected"
    item.needs_teacher_review = False
    item.reviewed_by = reviewer_name
    item.reviewed_at = datetime.now(timezone.utc)
    item.review_notes = notes

    db.commit()
    db.refresh(item)
    return item


def update_question_item(
    db: Session,
    question_id: str,
    patch_data: dict[str, Any],
    current_user_id: Optional[int] = None,
    chroma_persist_dir: Optional[Union[str, Path]] = None,
    embeddings: Any = None,
) -> QuestionBankItem:
    """
    Updates editable fields of a question. If question text or options change,
    automatically marks embedding status as pending and triggers re-embedding.
    """
    item = db.query(QuestionBankItem).filter_by(question_id=question_id).first()
    if not item:
        raise KeyError(f"Question with ID '{question_id}' not found in question bank.")

    old_text = item.question_text
    old_opts = item.options_json

    # Editable fields
    if "question_text" in patch_data and patch_data["question_text"]:
        item.question_text = str(patch_data["question_text"]).strip()
    if "options" in patch_data:
        opts = patch_data["options"]
        item.options_json = json.dumps(opts, ensure_ascii=False) if opts else None
    if "correct_option" in patch_data:
        item.correct_option = patch_data["correct_option"]
    if "correct_answer" in patch_data and patch_data["correct_answer"]:
        item.correct_answer = str(patch_data["correct_answer"]).strip()
    if "explanation" in patch_data:
        item.explanation = patch_data["explanation"]
    if "bloom_level" in patch_data:
        item.bloom_level = patch_data["bloom_level"]
    if "difficulty" in patch_data:
        item.difficulty = patch_data["difficulty"]
    if "lesson" in patch_data:
        item.lesson = patch_data["lesson"]
    if "unit" in patch_data:
        item.unit = patch_data["unit"]
    if "subject" in patch_data:
        item.subject = patch_data["subject"]
    if "classification_status" in patch_data:
        st = patch_data["classification_status"]
        if st in ("approved", "rejected", "needs_review", "pending_review"):
            item.classification_status = st
            item.review_status = st

    item.updated_at = datetime.now(timezone.utc)

    # Check if embedding invalidation is required
    text_changed = (item.question_text != old_text) or (item.options_json != old_opts)
    if text_changed:
        item.embedding_status = "pending"
        item.embedding_error = None
        # Attempt immediate re-embedding if directory provided
        if chroma_persist_dir and embeddings:
            try:
                col = _get_or_create_question_bank_collection(chroma_persist_dir)
                rec = {
                    "question_id": item.question_id,
                    "question_type": item.question_type,
                    "question_text": item.question_text,
                    "correct_answer": item.correct_answer,
                    "correct_option": item.correct_option,
                    "options": json.loads(item.options_json) if item.options_json else [],
                }
                embed_text = build_embedding_text(rec)
                meta = {
                    "question_id": item.question_id,
                    "question_type": item.question_type,
                    "bloom_level": str(item.bloom_level or ""),
                    "difficulty": str(item.difficulty or ""),
                    "review_status": item.review_status,
                    "sql_id": item.id,
                }
                c_id = _upsert_embedding_to_chroma(col, item.question_id, embed_text, meta, embeddings)
                item.embedding_id = c_id
                item.embedding_status = "synced"
                item.embedded_at = datetime.now(timezone.utc)
                close_chroma_client(col)
            except Exception as exc:
                logger.warning("Re-embedding question %s failed: %s", item.question_id, exc)
                item.embedding_status = "failed"
                item.embedding_error = str(exc)

    db.commit()
    db.refresh(item)
    return item


# ==============================================================================
# Stage 8: Querying, Pagination, and Statistical Summaries
# ==============================================================================


def question_item_to_dict(item: QuestionBankItem) -> dict[str, Any]:
    """Serializes QuestionBankItem to a standard dictionary representation."""
    options = []
    if item.options_json:
        try:
            options = json.loads(item.options_json)
        except Exception:
            options = []

    source_chunks = []
    if item.source_chunk_ids_json:
        try:
            source_chunks = json.loads(item.source_chunk_ids_json)
        except Exception:
            source_chunks = []

    review_reasons = []
    if item.review_reasons_json:
        try:
            review_reasons = json.loads(item.review_reasons_json)
        except Exception:
            review_reasons = []

    teacher_corrections = None
    if item.teacher_corrections_json:
        try:
            teacher_corrections = json.loads(item.teacher_corrections_json)
        except Exception:
            teacher_corrections = None

    return {
        "id": item.id,
        "question_id": item.question_id,
        "original_question_id": item.original_question_id,
        "question_type": item.question_type,
        "question_text": item.question_text,
        "options": options,
        "correct_option": item.correct_option,
        "correct_answer": item.correct_answer,
        "explanation": item.explanation,
        "subject": item.subject,
        "curriculum_id": item.curriculum_id,
        "unit": item.unit,
        "chapter": item.chapter,
        "lesson": item.lesson,
        "page_number": item.page_number,
        "bloom_level": item.bloom_level,
        "difficulty": item.difficulty,
        "learning_objective": item.learning_objective,
        "classification_reasoning": item.classification_reasoning,
        "classification_confidence": item.classification_confidence,
        "classification_status": item.classification_status,
        "review_status": item.review_status,
        "needs_teacher_review": item.needs_teacher_review,
        "review_reasons": review_reasons,
        "review_notes": item.review_notes,
        "reviewed_by": item.reviewed_by,
        "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
        "created_by": item.created_by,
        "teacher_corrections": teacher_corrections,
        "source_chunk_ids": source_chunks,
        "source_evidence": item.source_evidence,
        "embedding_status": item.embedding_status,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def query_question_bank_paginated(
    db: Session,
    search: Optional[str] = None,
    status: Optional[str] = None,
    difficulty: Optional[str] = None,
    bloom_level: Optional[str] = None,
    curriculum_id: Optional[str] = None,
    lesson: Optional[str] = None,
    question_type: Optional[str] = None,
    current_user_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """
    Advanced paginated query with multi-attribute filtering and text search.
    """
    from sqlalchemy import or_

    query = db.query(QuestionBankItem)

    if status and status.strip():
        query = query.filter(
            or_(
                QuestionBankItem.classification_status == status.strip().lower(),
                QuestionBankItem.review_status == status.strip().lower(),
            )
        )
    if difficulty and difficulty.strip():
        query = query.filter(QuestionBankItem.difficulty.ilike(difficulty.strip()))
    if bloom_level and bloom_level.strip():
        query = query.filter(QuestionBankItem.bloom_level.ilike(bloom_level.strip()))
    if curriculum_id and curriculum_id.strip():
        query = query.filter(QuestionBankItem.curriculum_id == str(curriculum_id).strip())
    if lesson and lesson.strip():
        query = query.filter(QuestionBankItem.lesson.ilike(f"%{lesson.strip()}%"))
    if question_type and question_type.strip():
        query = query.filter(QuestionBankItem.question_type == question_type.strip().lower())
    if search and search.strip():
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                QuestionBankItem.question_text.ilike(s),
                QuestionBankItem.correct_answer.ilike(s),
                QuestionBankItem.question_id.ilike(s),
            )
        )

    total_count = query.count()
    offset = max(0, (page - 1) * page_size)
    items = query.order_by(QuestionBankItem.id.desc()).offset(offset).limit(page_size).all()

    return {
        "total": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size if page_size > 0 else 1,
        "items": [question_item_to_dict(it) for it in items],
    }


def get_question_bank_statistics(db: Session, current_user_id: Optional[int] = None) -> dict[str, Any]:
    """
    Computes summary metrics, review status breakdown, and taxonomy distributions.
    """
    from sqlalchemy import func

    total = db.query(func.count(QuestionBankItem.id)).scalar() or 0
    approved = db.query(func.count(QuestionBankItem.id)).filter(
        QuestionBankItem.classification_status == "approved"
    ).scalar() or 0
    rejected = db.query(func.count(QuestionBankItem.id)).filter(
        QuestionBankItem.classification_status == "rejected"
    ).scalar() or 0
    needs_review = db.query(func.count(QuestionBankItem.id)).filter(
        QuestionBankItem.classification_status == "needs_review"
    ).scalar() or 0
    pending_review = db.query(func.count(QuestionBankItem.id)).filter(
        QuestionBankItem.classification_status == "pending_review"
    ).scalar() or 0

    # Difficulty distribution
    diff_rows = db.query(
        QuestionBankItem.difficulty, func.count(QuestionBankItem.id)
    ).group_by(QuestionBankItem.difficulty).all()
    difficulty_counts = {str(d or "Unknown").capitalize(): c for d, c in diff_rows}

    # Bloom distribution
    bloom_rows = db.query(
        QuestionBankItem.bloom_level, func.count(QuestionBankItem.id)
    ).group_by(QuestionBankItem.bloom_level).all()
    bloom_counts = {str(b or "Unknown").capitalize(): c for b, c in bloom_rows}

    # Type distribution
    type_rows = db.query(
        QuestionBankItem.question_type, func.count(QuestionBankItem.id)
    ).group_by(QuestionBankItem.question_type).all()
    type_counts = {str(t): c for t, c in type_rows}

    return {
        "total_questions": total,
        "approved_count": approved,
        "rejected_count": rejected,
        "needs_review_count": needs_review,
        "pending_review_count": pending_review,
        "difficulty_distribution": difficulty_counts,
        "bloom_distribution": bloom_counts,
        "type_distribution": type_counts,
    }


def get_supervised_learning_evaluation(db: Session) -> dict[str, Any]:
    """
    Evaluates whether the approved question bank has collected sufficient verified
    training examples to justify training a dedicated supervised classifier.
    """
    from sqlalchemy import func

    approved_count = db.query(func.count(QuestionBankItem.id)).filter(
        QuestionBankItem.classification_status == "approved"
    ).scalar() or 0

    # Minimum recommended labeled samples per class
    MIN_TOTAL_SAMPLES = 200
    MIN_PER_CLASS_SAMPLES = 40

    diff_counts = dict(
        db.query(QuestionBankItem.difficulty, func.count(QuestionBankItem.id))
        .filter(QuestionBankItem.classification_status == "approved")
        .group_by(QuestionBankItem.difficulty)
        .all()
    )

    bloom_counts = dict(
        db.query(QuestionBankItem.bloom_level, func.count(QuestionBankItem.id))
        .filter(QuestionBankItem.classification_status == "approved")
        .group_by(QuestionBankItem.bloom_level)
        .all()
    )

    is_ready = (
        approved_count >= MIN_TOTAL_SAMPLES
        and all(diff_counts.get(d, 0) >= MIN_PER_CLASS_SAMPLES for d in ("Easy", "Medium", "Hard"))
    )

    guidance = (
        "Dataset is sufficient for supervised baseline training."
        if is_ready
        else (
            f"Insufficient approved data for supervised training ({approved_count}/{MIN_TOTAL_SAMPLES} approved samples). "
            f"Continue using curriculum RAG and LLM classification as the active method. "
            f"Teachers should review and approve at least {MIN_PER_CLASS_SAMPLES} samples per class."
        )
    )

    return {
        "approved_sample_count": approved_count,
        "required_total_samples": MIN_TOTAL_SAMPLES,
        "required_per_class_samples": MIN_PER_CLASS_SAMPLES,
        "difficulty_sample_distribution": {str(k): v for k, v in diff_counts.items()},
        "bloom_sample_distribution": {str(k): v for k, v in bloom_counts.items()},
        "is_ready_for_supervised_training": is_ready,
        "active_method": "rag_llm",
        "guidance": guidance,
    }
