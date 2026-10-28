"""
Curriculum Mapping Module for Intelligent Educational Assessment System.

Stage 3 implementation:
  - Grounds each question to curriculum chunks in the Chroma vector store.
  - Extracts and returns actual chunk IDs, document source, chapter, lesson, and page numbers.
  - Generates supporting evidence excerpts from the retrieved curriculum chunks.
  - Calibrates mapping confidence and flags uncertain or low-similarity matches for teacher review.
  - Strictly distinguishes the question bank's original source metadata from the grounded curriculum evidence.
  - Safely handles missing, empty, or uninitialized vector stores by marking mappings as unresolved (never fabricating chunks).
  - Preserves all question fields and upstream metadata without destructive alteration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
from pathlib import Path
import re
from typing import Any, Optional

from scripts.config import VECTOR_DB_PATH

logger = logging.getLogger(__name__)

DEFAULT_MIN_MAPPING_CONFIDENCE: float = 0.65
MAX_EVIDENCE_EXCERPT_CHARS: int = 300


# ==============================================================================
# 1. Data Models & Containers
# ==============================================================================


@dataclass
class CurriculumEvidenceChunk:
    """Represents a specific curriculum chunk retrieved to support a question."""

    chunk_id: str
    source_document: str
    chapter_id: Optional[int]
    chapter_title: Optional[str]
    lesson_id: Optional[str]
    lesson_title: Optional[str]
    pdf_page_start: Optional[int]
    pdf_page_end: Optional[int]
    printed_page_start: Optional[int]
    printed_page_end: Optional[int]
    similarity_score: float
    evidence_excerpt: str


@dataclass
class CurriculumMappingDetails:
    """Detailed curriculum grounding record attached to a question."""

    mapping_status: str  # "mapped", "low_confidence", "unresolved"
    confidence_score: float
    matched_chunk_id: Optional[str]
    matched_source_document: Optional[str]
    matched_chapter_id: Optional[int]
    matched_chapter_title: Optional[str]
    matched_lesson_id: Optional[str]
    matched_lesson_title: Optional[str]
    matched_page_start: Optional[int]
    matched_page_end: Optional[int]
    evidence_excerpt: Optional[str]
    supporting_chunks: list[dict[str, Any]]
    needs_review: bool
    review_reasons: list[str] = field(default_factory=list)


@dataclass
class MappedQuestionRecord:
    """Full question record containing original metadata plus verified curriculum mapping."""

    question_id: str
    original_question_id: Optional[str]
    question_type: str
    question_text: str
    options: list[str]
    correct_option: Optional[str]
    correct_answer: str

    # Upstream analysis metadata
    bloom_level: Optional[str]
    difficulty: Optional[str]
    learning_objective: Optional[str]
    learning_objective_grounded: bool
    classification_reasoning: Optional[str]
    analysis_confidence: Optional[float]
    needs_teacher_review: bool
    review_reasons: list[str]

    # Grounded curriculum mapping
    curriculum_mapping: dict[str, Any]

    # Separated original question bank source metadata
    original_source_metadata: dict[str, Any]

    # General metadata
    validation_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert mapped question to standard serializable dictionary."""
        return asdict(self)


@dataclass
class BatchMappingResult:
    """Structured report of batch curriculum mapping."""

    total_questions: int
    mapped_count: int
    low_confidence_count: int
    unresolved_count: int
    failed_count: int
    questions: list[dict[str, Any]]
    failed_records: list[dict[str, Any]]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert batch result to standard serializable dictionary."""
        return {
            "total_questions": self.total_questions,
            "mapped_count": self.mapped_count,
            "low_confidence_count": self.low_confidence_count,
            "unresolved_count": self.unresolved_count,
            "failed_count": self.failed_count,
            "questions": self.questions,
            "failed_records": self.failed_records,
            "summary": self.summary,
        }


# ==============================================================================
# 2. Excerpt Extraction & Lesson ID Normalization
# ==============================================================================


def extract_evidence_excerpt(page_content: str, query_terms: list[str], max_chars: int = MAX_EVIDENCE_EXCERPT_CHARS) -> str:
    """
    Extracts the most relevant contiguous passage or sentence from a chunk
    that contains the question or answer query terms.
    """
    text = (page_content or "").strip()
    if not text:
        return ""

    # Split into sentences
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        return text[:max_chars].rsplit(" ", 1)[0] + "..." if len(text) > max_chars else text

    # Score sentences based on matching query keywords
    term_set = {t.lower() for t in query_terms if len(t) >= 3}
    best_sentence = sentences[0]
    best_score = -1

    for s in sentences:
        s_words = set(re.findall(r"\w+", s.lower()))
        score = len(s_words & term_set)
        if score > best_score:
            best_score = score
            best_sentence = s

    if best_score > 0:
        return best_sentence[:max_chars]

    if len(text) <= max_chars:
        return text

    return text[:max_chars].rsplit(" ", 1)[0] + "..."


def extract_lesson_id_from_text(lesson_text: Any) -> Optional[str]:
    """
    Normalizes a lesson string into a standard lesson_id (e.g. 'Lesson 1-1 ...' -> '1-1').
    """
    if not lesson_text:
        return None
    s = str(lesson_text).strip()
    # Match standard patterns like '1-1', 'Lesson 1-1', 'Unit 1-2'
    match = re.search(r"\b(\d+-\d+)\b", s)
    if match:
        return match.group(1)
    return None


def extract_chapter_id_from_text(chapter_text: Any) -> Optional[int]:
    """
    Extracts an integer chapter_id from strings like 'Unit One', 'Chapter 2', '1 Information Tech'.
    """
    if not chapter_text:
        return None
    s = str(chapter_text).strip()
    # Numeric match first
    match = re.search(r"\b(\d+)\b", s)
    if match:
        return int(match.group(1))
    # Word match
    word_map = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    for word, num in word_map.items():
        if re.search(rf"\b{word}\b", s, flags=re.IGNORECASE):
            return num
    return None


# ==============================================================================
# 3. Vector Store Retrieval & Similarity Normalization
# ==============================================================================


def _safely_get_vectorstore(
    store: Any = None,
    persist_dir: str | Path | None = None,
    collection_name: str = "curriculum",
) -> Optional[Any]:
    """
    Returns an active Chroma store instance or loads one safely.
    Returns None if the directory does not exist or collection is missing.
    """
    if store is not None:
        return store

    target_dir = Path(persist_dir) if persist_dir is not None else VECTOR_DB_PATH
    if not target_dir.exists():
        return None

    try:
        from scripts.generation import load_curriculum_store
        return load_curriculum_store(persist_dir=target_dir, collection_name=collection_name)
    except Exception as exc:
        logger.debug("Curriculum vector store could not be loaded: %s", exc)
        return None


def _normalize_relevance_score(raw_score: Any, is_distance: bool = True) -> float:
    """
    Normalizes Chroma distance or similarity scores to a [0.0, 1.0] scale where
    1.0 means identical/maximally relevant and 0.0 means unrelated.

    When raw_score is a distance (default for Chroma similarity_search_with_score):
      - In Chroma, cosine distance is d = 1 - cos_sim, so cos_sim = 1 - d.
      - If d in [0, 1], similarity is 1.0 - d.
      - If d in (1, 2], similarity is max(0.0, 1.0 - (d / 2.0)).
      - If d <= 0, similarity is 1.0.

    When raw_score is already a relevance/similarity score (is_distance=False):
      - Clamped to [0.0, 1.0].
    """
    if raw_score is None:
        return 0.0
    try:
        val = float(raw_score)
    except (ValueError, TypeError):
        return 0.0

    if not is_distance:
        return round(max(0.0, min(1.0, val)), 4)

    # raw_score is distance: smaller distance means HIGHER similarity
    if val <= 0.0:
        return 1.0
    if val <= 1.0:
        return round(1.0 - val, 4)
    if val <= 2.0:
        return round(max(0.0, 1.0 - (val / 2.0)), 4)
    return round(max(0.0, 1.0 / (1.0 + val)), 4)

# ==============================================================================
# 4. Single Question Curriculum Mapping
# ==============================================================================


def map_single_question(
    question_dict: dict[str, Any],
    store: Any = None,
    top_k: int = 3,
    min_confidence: float = DEFAULT_MIN_MAPPING_CONFIDENCE,
    persist_dir: str | Path | None = None,
    collection_name: str = "curriculum",
) -> MappedQuestionRecord:
    """
    Maps an individual question to the curriculum vector store.

    Checks:
      1. Is vector store accessible and non-empty? If not, marks status as 'unresolved'.
      2. Constructs targeted semantic query from question text and model answer.
      3. Retrieves top_k supporting curriculum chunks using metadata filtering if available.
      4. Validates chunk metadata and extracts verbatim evidence excerpts.
      5. Calibrates confidence score:
           * If confidence >= min_confidence -> status: 'mapped'
           * If 0 < confidence < min_confidence -> status: 'low_confidence', needs_review: True
           * If no chunks retrieved -> status: 'unresolved', needs_review: True
      6. Preserves original question metadata separately from grounded curriculum evidence.
    """
    qid = question_dict.get("question_id", "unknown")
    q_text = question_dict.get("question_text", "")
    correct_ans = question_dict.get("correct_answer", "")

    # Preserve original question bank source metadata separately
    orig_source_meta = {
        "source_file": question_dict.get("source_file"),
        "chapter": question_dict.get("chapter"),
        "lesson": question_dict.get("lesson"),
        "page_number": question_dict.get("page_number"),
        "answer_source": question_dict.get("answer_source"),
        "verification_status": question_dict.get("verification_status"),
        "source_metadata": question_dict.get("source_metadata"),
    }

    # Upstream review flags and reasons
    upstream_reasons = list(question_dict.get("review_reasons", []))
    upstream_needs_review = bool(question_dict.get("needs_teacher_review", False))

    # Safely obtain vector store
    vstore = _safely_get_vectorstore(store=store, persist_dir=persist_dir, collection_name=collection_name)
    if vstore is None:
        mapping_details = CurriculumMappingDetails(
            mapping_status="unresolved",
            confidence_score=0.0,
            matched_chunk_id=None,
            matched_source_document=None,
            matched_chapter_id=None,
            matched_chapter_title=None,
            matched_lesson_id=None,
            matched_lesson_title=None,
            matched_page_start=None,
            matched_page_end=None,
            evidence_excerpt=None,
            supporting_chunks=[],
            needs_review=True,
            review_reasons=["Curriculum vector store is not available or empty."],
        )
        combined_reasons = list(upstream_reasons) + mapping_details.review_reasons
        return _build_mapped_question_record(
            question_dict=question_dict,
            orig_source_meta=orig_source_meta,
            mapping_details=mapping_details,
            needs_review=True,
            review_reasons=combined_reasons,
        )

    # Build semantic query
    query_str = f"{q_text} {correct_ans}".strip() if correct_ans else q_text.strip()
    query_keywords = re.findall(r"\w+", query_str)

    # Optional metadata filter based on lesson_id if identifiable from question metadata
    filter_dict = None
    lesson_id = extract_lesson_id_from_text(question_dict.get("lesson"))
    chapter_id = extract_chapter_id_from_text(question_dict.get("chapter"))

    # Attempt retrieval
    retrieved_items: list[tuple[Any, float]] = []
    is_distance = False
    try:
        # Check if vectorstore supports relevance scores
        if hasattr(vstore, "similarity_search_with_relevance_scores"):
            retrieved_items = vstore.similarity_search_with_relevance_scores(
                query=query_str,
                k=top_k,
                filter={"lesson_id": lesson_id} if lesson_id else None,
            )
            is_distance = False
        elif hasattr(vstore, "similarity_search_with_score"):
            retrieved_items = vstore.similarity_search_with_score(
                query=query_str,
                k=top_k,
                filter={"lesson_id": lesson_id} if lesson_id else None,
            )
            is_distance = True
        else:
            docs = vstore.similarity_search(query=query_str, k=top_k)
            retrieved_items = [(doc, 0.8) for doc in docs]
            is_distance = False
    except Exception as exc:
        logger.warning("Retrieval error for question %s: %s", qid, exc)
        retrieved_items = []

    # If filtered search returned zero results, retry without filter
    if not retrieved_items and lesson_id:
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
        except Exception:
            retrieved_items = []

    # Handle zero retrieved items
    if not retrieved_items:
        mapping_details = CurriculumMappingDetails(
            mapping_status="unresolved",
            confidence_score=0.0,
            matched_chunk_id=None,
            matched_source_document=None,
            matched_chapter_id=None,
            matched_chapter_title=None,
            matched_lesson_id=None,
            matched_lesson_title=None,
            matched_page_start=None,
            matched_page_end=None,
            evidence_excerpt=None,
            supporting_chunks=[],
            needs_review=True,
            review_reasons=["No supporting curriculum chunks retrieved for question."],
        )
        combined_reasons = list(upstream_reasons) + mapping_details.review_reasons
        return _build_mapped_question_record(
            question_dict=question_dict,
            orig_source_meta=orig_source_meta,
            mapping_details=mapping_details,
            needs_review=True,
            review_reasons=combined_reasons,
        )

    # Process retrieved chunks
    supporting_chunks: list[dict[str, Any]] = []
    for doc, raw_score in retrieved_items:
        meta = getattr(doc, "metadata", {}) or {}
        cid = str(meta.get("chunk_id", "unknown")).strip()
        doc_name = str(meta.get("source", "curriculum")).strip()
        c_id = meta.get("chapter_id")
        c_title = meta.get("chapter_title")
        l_id = meta.get("lesson_id")
        l_title = meta.get("lesson_title")
        p_start = meta.get("pdf_page_start") or meta.get("printed_page_start")
        p_end = meta.get("pdf_page_end") or meta.get("printed_page_end")

        sim_score = _normalize_relevance_score(raw_score, is_distance=is_distance)
        excerpt = extract_evidence_excerpt(getattr(doc, "page_content", ""), query_keywords)

        supporting_chunks.append({
            "chunk_id": cid,
            "source_document": doc_name,
            "chapter_id": c_id,
            "chapter_title": c_title,
            "lesson_id": l_id,
            "lesson_title": l_title,
            "page_start": p_start,
            "page_end": p_end,
            "similarity_score": sim_score,
            "evidence_excerpt": excerpt,
        })

    # Top match is primary curriculum grounding
    top_chunk = supporting_chunks[0]
    top_score = top_chunk["similarity_score"]

    review_reasons: list[str] = []
    if top_score >= min_confidence:
        mapping_status = "mapped"
    else:
        mapping_status = "low_confidence"
        review_reasons.append(
            f"Curriculum mapping similarity below threshold ({top_score:.2f} < {min_confidence:.2f})"
        )

    # Check for missing chunk metadata in retrieved document
    if top_chunk["chunk_id"] == "unknown" or not top_chunk["source_document"]:
        review_reasons.append("Retrieved curriculum chunk lacks required chunk_id or source metadata")
        mapping_status = "low_confidence"

    mapping_details = CurriculumMappingDetails(
        mapping_status=mapping_status,
        confidence_score=top_score,
        matched_chunk_id=top_chunk["chunk_id"] if top_chunk["chunk_id"] != "unknown" else None,
        matched_source_document=top_chunk["source_document"] if top_chunk["source_document"] != "unknown" else None,
        matched_chapter_id=top_chunk["chapter_id"],
        matched_chapter_title=top_chunk["chapter_title"],
        matched_lesson_id=top_chunk["lesson_id"],
        matched_lesson_title=top_chunk["lesson_title"],
        matched_page_start=top_chunk["page_start"],
        matched_page_end=top_chunk["page_end"],
        evidence_excerpt=top_chunk["evidence_excerpt"],
        supporting_chunks=supporting_chunks,
        needs_review=(len(review_reasons) > 0),
        review_reasons=review_reasons,
    )

    combined_needs_review = upstream_needs_review or mapping_details.needs_review
    combined_reasons = list(upstream_reasons) + mapping_details.review_reasons

    return _build_mapped_question_record(
        question_dict=question_dict,
        orig_source_meta=orig_source_meta,
        mapping_details=mapping_details,
        needs_review=combined_needs_review,
        review_reasons=combined_reasons,
    )


def _build_mapped_question_record(
    question_dict: dict[str, Any],
    orig_source_meta: dict[str, Any],
    mapping_details: CurriculumMappingDetails,
    needs_review: bool,
    review_reasons: list[str],
) -> MappedQuestionRecord:
    """Helper to assemble MappedQuestionRecord while preserving all fields."""
    return MappedQuestionRecord(
        question_id=question_dict.get("question_id", "unknown"),
        original_question_id=question_dict.get("original_question_id"),
        question_type=question_dict.get("question_type", "mcq"),
        question_text=question_dict.get("question_text", ""),
        options=question_dict.get("options") or [],
        correct_option=question_dict.get("correct_option"),
        correct_answer=question_dict.get("correct_answer", ""),
        bloom_level=question_dict.get("bloom_level"),
        difficulty=question_dict.get("difficulty"),
        learning_objective=question_dict.get("learning_objective"),
        learning_objective_grounded=bool(question_dict.get("learning_objective_grounded", False)),
        classification_reasoning=question_dict.get("classification_reasoning"),
        analysis_confidence=question_dict.get("confidence"),
        needs_teacher_review=needs_review,
        review_reasons=review_reasons,
        curriculum_mapping=asdict(mapping_details),
        original_source_metadata=orig_source_meta,
        validation_warnings=list(question_dict.get("validation_warnings", [])),
    )


# ==============================================================================
# 5. Batch Curriculum Mapping
# ==============================================================================


def map_questions_batch(
    questions: list[dict[str, Any]],
    store: Any = None,
    top_k: int = 3,
    min_confidence: float = DEFAULT_MIN_MAPPING_CONFIDENCE,
    persist_dir: str | Path | None = None,
    collection_name: str = "curriculum",
    allow_partial: bool = True,
) -> BatchMappingResult:
    """
    Executes curriculum mapping across a collection of analyzed question records.

    Args:
      questions: Sequence of question records.
      store: Optional loaded vector store instance (or loaded automatically).
      top_k: Number of candidate chunks to retrieve per question.
      min_confidence: Minimum score threshold for 'mapped' status.
      persist_dir: Optional custom vector store directory.
      collection_name: Vector collection name ('curriculum').
      allow_partial: If True, failures on individual records do not abort the batch.

    Returns:
      BatchMappingResult detailing mapped questions, failure records, and statistical summary.
    """
    mapped_questions: list[dict[str, Any]] = []
    failed_records: list[dict[str, Any]] = []

    status_counts = {"mapped": 0, "low_confidence": 0, "unresolved": 0}

    # Pre-load store once if possible
    vstore = _safely_get_vectorstore(store=store, persist_dir=persist_dir, collection_name=collection_name)

    for idx, q in enumerate(questions, start=1):
        qid = q.get("question_id", f"Q-{idx:04d}")
        try:
            mapped_record = map_single_question(
                q,
                store=vstore,
                top_k=top_k,
                min_confidence=min_confidence,
                persist_dir=persist_dir,
                collection_name=collection_name,
            )
            mapped_dict = mapped_record.to_dict()
            mapped_questions.append(mapped_dict)

            status = mapped_record.curriculum_mapping["mapping_status"]
            status_counts[status] = status_counts.get(status, 0) + 1
        except Exception as exc:
            logger.error("Failed to map question %s to curriculum: %s", qid, exc)
            if not allow_partial:
                raise
            failed_records.append({
                "index": idx,
                "question_id": qid,
                "question_text": q.get("question_text", ""),
                "error": str(exc),
            })

    summary = {
        "total_input": len(questions),
        "mapped_count": status_counts.get("mapped", 0),
        "low_confidence_count": status_counts.get("low_confidence", 0),
        "unresolved_count": status_counts.get("unresolved", 0),
        "failed_count": len(failed_records),
        "mapping_rate": round(status_counts.get("mapped", 0) / len(questions), 4) if questions else 0.0,
    }

    return BatchMappingResult(
        total_questions=len(questions),
        mapped_count=status_counts.get("mapped", 0),
        low_confidence_count=status_counts.get("low_confidence", 0),
        unresolved_count=status_counts.get("unresolved", 0),
        failed_count=len(failed_records),
        questions=mapped_questions,
        failed_records=failed_records,
        summary=summary,
    )
