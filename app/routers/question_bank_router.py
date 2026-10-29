"""
Question Bank API Router.

Stage 4B / Phase 5 implementation:
Provides dedicated endpoints for Question Bank ingestion, automated curriculum-grounded
classification, search and filtering, review workflows (approval/rejection/editing),
learning from teacher approvals, and embedding reconciliation.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from starlette import status as http_status
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.database import get_db
from app.models import Curriculum, QuestionBankItem, QuestionBankPracticeSubmission, User
from app.schemas import (
    CleanedDatasetItem,
    CleanedDatasetPaginatedResponse,
    CleanedDatasetProvenance,
    QuestionBankItemCreate,
    QuestionBankItemResponse,
    QuestionBankItemUpdate,
    QuestionBankPaginatedResponse,
    QuestionBankReviewAction,
    QuestionBankStatsResponse,
    QuestionClassificationRequest,
    QuestionClassificationResponse,
    QuestionPracticeSubmitRequest,
    QuestionPracticeGradingResponse,
)
from scripts.config import VECTOR_DB_PATH
from scripts.question_bank_service import (
    QUESTION_BANK_CHROMA_COLLECTION,
    approve_question_item,
    classify_and_ground_question,
    get_question_bank_statistics,
    get_supervised_learning_evaluation,
    import_questions_to_db,
    query_question_bank_paginated,
    question_item_to_dict,
    reconcile_pending_embeddings,
    reject_question_item,
    update_question_item,
)
from scripts.question_processing import parse_question_source, process_question_source
from scripts.dataset_loader import load_cleaned_dataset

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/question-bank", tags=["Question Bank"])


# ---------------------------------------------------------------------------
# 1. Ingestion & Import Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/import",
    summary="Import questions from file (PDF, DOCX, XLSX, CSV, JSON) or payload",
)
async def import_question_bank_file(
    file: Optional[UploadFile] = File(None),
    curriculum_id: Optional[str] = Form(None),
    auto_classify: bool = Form(True),
    skip_embedding: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> dict[str, Any]:
    """
    Imports questions from an uploaded document (PDF, DOCX, XLSX, CSV, JSON).
    Executes parsing, schema validation, non-destructive duplicate detection,
    and stages/persists records into SQLite and the isolated Chroma question_bank collection.
    """
    if not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No file provided. Please upload a PDF, DOCX, XLSX, CSV, or JSON question file.",
        )

    filename = file.filename or "uploaded_questions"
    file_ext = Path(filename).suffix.lstrip(".").lower()
    allowed_extensions = {"xlsx", "xls", "csv", "json", "pdf", "docx"}
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file format '.{file_ext}'. "
                f"Supported formats are: {', '.join(sorted(allowed_extensions)).upper()}."
            ),
        )

    try:
        content = await file.read()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not read uploaded file: {exc}",
        )

    # Stage 1: Parse and validate records
    try:
        proc_result = process_question_source(
            source=content,
            file_format=file_ext,
        )
    except Exception as exc:
        logger.error("Processing error on file %s: %s", filename, exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to parse question document: {exc}",
        )

    valid_records = proc_result.valid_records
    if not valid_records:
        return {
            "status": "warning",
            "message": "No valid question records could be extracted from the file.",
            "total_extracted": proc_result.total_records,
            "invalid_count": proc_result.invalid_count,
            "invalid_records": proc_result.invalid_records,
            "warnings": proc_result.warnings,
        }

    # Attach source file, curriculum reference and user ownership to each record
    for rec in valid_records:
        if not rec.get("source_file"):
            rec["source_file"] = filename
        rec["created_by"] = current_user.id
        if curriculum_id:
            rec["curriculum_id"] = str(curriculum_id)

    # Optional auto-classification for each item
    if auto_classify:
        for rec in valid_records:
            try:
                classified = classify_and_ground_question(
                    question_dict=rec,
                    db=db,
                    curriculum_id=curriculum_id,
                    confidence_threshold=0.70,
                )
                rec["bloom_level"] = classified["bloom_level"]
                rec["difficulty"] = classified["difficulty"]
                rec["subject"] = classified["subject"]
                rec["unit"] = classified["unit"]
                rec["lesson"] = classified["lesson"]
                rec["page_number"] = classified["page_number"]
                rec["classification_confidence"] = classified["classification_confidence"]
                rec["classification_status"] = classified["classification_status"]
                rec["needs_teacher_review"] = classified["needs_teacher_review"]
                rec["review_reasons"] = classified["review_reasons"]
                rec["source_chunk_ids"] = classified["source_chunk_ids"]
                rec["source_evidence"] = classified["source_evidence"]
                rec["classification_reasoning"] = classified["classification_reasoning"]
            except Exception as exc:
                logger.warning("Auto-classification failed for record: %s", exc)

    # Stage 2: Persist into SQLite and Chroma question_bank collection
    import_result = import_questions_to_db(
        records=valid_records,
        db=db,
        chroma_persist_dir=VECTOR_DB_PATH,
        imported_from=f"File: {filename}",
        skip_embedding=skip_embedding,
    )

    return {
        "status": "success",
        "filename": filename,
        "total_extracted": proc_result.total_records,
        "valid_count": proc_result.valid_count,
        "invalid_count": proc_result.invalid_count,
        "duplicate_count": proc_result.duplicate_count,
        "inserted": import_result.inserted,
        "updated": import_result.updated,
        "skipped": import_result.skipped,
        "outcomes": [o.to_dict() for o in import_result.outcomes],
        "collisions": import_result.collision_report,
        "invalid_records": proc_result.invalid_records,
    }


# ---------------------------------------------------------------------------
# 2. On-Demand Classification Endpoint
# ---------------------------------------------------------------------------


@router.post(
    "/classify",
    response_model=QuestionClassificationResponse,
    summary="Ground and classify an individual question via RAG and psychometric analysis",
)
def classify_question(
    request: QuestionClassificationRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> QuestionClassificationResponse:
    """
    On-demand classification of a manual question input.
    Retrieves evidence from Chroma curriculum chunks, selects only verified citations,
    predicts Bloom level and cognitive difficulty independently, and calculates confidence.
    """
    # Strict validation of correct_option & correct_answer
    options = request.options or []
    correct_opt = request.correct_option
    correct_ans = (request.correct_answer or "").strip()

    if request.question_type == "mcq":
        if len(options) != 4 or not all(str(o).strip() for o in options):
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="MCQ requires exactly 4 non-empty options.",
            )
        if not correct_opt or str(correct_opt).strip().upper() not in ("A", "B", "C", "D"):
            # Check if correct_answer matches an option text
            found_idx = None
            for idx, opt in enumerate(options):
                if str(opt).strip().casefold() == correct_ans.casefold() and correct_ans:
                    found_idx = idx
                    break
            if found_idx is not None:
                correct_opt = ["A", "B", "C", "D"][found_idx]
                correct_ans = options[found_idx]
            else:
                raise HTTPException(
                    status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="MCQ requires an explicitly selected correct option ('A', 'B', 'C', or 'D').",
                )
        else:
            correct_opt = str(correct_opt).strip().upper()
            idx = ["A", "B", "C", "D"].index(correct_opt)
            if not correct_ans and idx < len(options):
                correct_ans = str(options[idx]).strip()
    else:
        if not correct_ans:
            raise HTTPException(
                status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{request.question_type.replace('_', ' ').title()} question requires a model/correct answer.",
            )

    q_dict = {
        "question_text": request.question_text,
        "question_type": request.question_type,
        "options": options if request.question_type == "mcq" else [],
        "correct_option": correct_opt if request.question_type == "mcq" else None,
        "correct_answer": correct_ans,
        "explanation": request.explanation,
    }

    try:
        result = classify_and_ground_question(
            question_dict=q_dict,
            db=db,
            curriculum_id=request.curriculum_id,
            collection_name=request.collection_name,
            top_k=request.top_k,
            confidence_threshold=request.confidence_threshold,
            allow_fallback=False,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Question classification pipeline failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Classification service unavailable: {exc}",
        )

    persisted_item = None
    if request.persist:
        # Save as QuestionBankItem
        import_record = dict(result)
        import_record["created_by"] = current_user.id
        import_res = import_questions_to_db(
            records=[import_record],
            db=db,
            chroma_persist_dir=VECTOR_DB_PATH,
            imported_from="Manual Entry",
            skip_embedding=False,
        )
        if import_res.outcomes:
            outcome = import_res.outcomes[0]
            if outcome.status in ("inserted", "updated", "skipped"):
                item = db.query(QuestionBankItem).filter_by(question_id=result["question_id"]).first()
                if item:
                    persisted_item = QuestionBankItemResponse(**question_item_to_dict(item))
            elif outcome.status == "error":
                err_msg = "; ".join(outcome.errors) if outcome.errors else "Database persistence failed"
                raise HTTPException(status_code=500, detail=f"فشل حفظ السؤال في قاعدة البيانات: {err_msg}")
            elif outcome.status == "invalid":
                err_msg = "; ".join(outcome.errors) if outcome.errors else "Invalid question record"
                raise HTTPException(status_code=422, detail=f"بيانات السؤال غير صالحة للحفظ: {err_msg}")

    return QuestionClassificationResponse(
        question_id=result["question_id"],
        question_text=result["question_text"],
        question_type=result["question_type"],
        options=result.get("options") or [],
        correct_option=result.get("correct_option"),
        correct_answer=result["correct_answer"],
        explanation=result.get("explanation"),
        subject=result.get("subject"),
        unit=result.get("unit"),
        lesson=result.get("lesson"),
        page_number=result.get("page_number"),
        bloom_level=result["bloom_level"],
        difficulty=result["difficulty"],
        classification_reasoning=result["classification_reasoning"],
        classification_confidence=result["classification_confidence"],
        grounding_confidence=result.get("grounding_confidence"),
        classification_status=result["classification_status"],
        source_chunk_ids=result.get("source_chunk_ids") or [],
        source_evidence=result.get("source_evidence"),
        needs_teacher_review=result["needs_teacher_review"],
        review_reasons=result.get("review_reasons") or [],
        supporting_chunks=result.get("supporting_chunks") or [],
        persisted_item=persisted_item,
    )


# ---------------------------------------------------------------------------
# 3. Query, Search, and Statistics Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=QuestionBankPaginatedResponse,
    summary="Search and filter persisted question bank items with pagination",
)
def list_question_bank_items(
    search: Optional[str] = Query(None, description="Search question text or model answer"),
    status: Optional[str] = Query(
        None, description="Filter by status: pending_review, approved, rejected, needs_review"
    ),
    difficulty: Optional[str] = Query(None, description="Filter: Easy, Medium, Hard"),
    bloom_level: Optional[str] = Query(None, description="Filter: Remember, Understand, Apply, etc."),
    curriculum_id: Optional[str] = Query(None, description="Filter by curriculum document ID"),
    lesson: Optional[str] = Query(None, description="Filter by lesson title or code"),
    question_type: Optional[str] = Query(None, description="Filter by mcq, essay, short_answer"),
    page: int = Query(1, ge=1, description="Page index (1-based)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuestionBankPaginatedResponse:
    """
    Returns paginated question bank items matching the criteria.
    Professors can query all questions with full evaluation and answer metadata.
    Students receive only approved questions for practice, with answers and evaluation notes redacted.
    """
    if current_user.role == "student":
        effective_status = "approved"
    elif current_user.role == "professor":
        effective_status = status
    else:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: role not authorized to access question bank",
        )

    res = query_question_bank_paginated(
        db=db,
        search=search,
        status=effective_status,
        difficulty=difficulty,
        bloom_level=bloom_level,
        curriculum_id=curriculum_id,
        lesson=lesson,
        question_type=question_type,
        current_user_id=current_user.id,
        page=page,
        page_size=page_size,
    )
    items = res["items"]
    if current_user.role == "student":
        for it in items:
            it["correct_answer"] = ""
            it["correct_option"] = None
            it["explanation"] = None
            it["review_notes"] = None
            it["teacher_corrections"] = None
            it["review_reasons"] = []

    return QuestionBankPaginatedResponse(
        total=res["total"],
        page=res["page"],
        page_size=res["page_size"],
        total_pages=res["total_pages"],
        items=[QuestionBankItemResponse(**it) for it in items],
    )


@router.get(
    "/summary",
    response_model=QuestionBankStatsResponse,
    summary="Get question bank statistics, review counts, and taxonomy distribution",
)
def get_question_bank_summary_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> QuestionBankStatsResponse:
    """Returns overview statistics of the Question Bank."""
    stats = get_question_bank_statistics(db=db, current_user_id=current_user.id)
    return QuestionBankStatsResponse(
        total_questions=stats["total_questions"],
        approved_count=stats["approved_count"],
        rejected_count=stats["rejected_count"],
        needs_review_count=stats["needs_review_count"],
        pending_review_count=stats["pending_review_count"],
        difficulty_distribution=stats["difficulty_distribution"],
        bloom_distribution=stats["bloom_distribution"],
        type_distribution=stats["type_distribution"],
    )


@router.get(
    "/learning-stats",
    summary="Get approved dataset metrics and supervised classifier training readiness",
)
def get_learning_readiness(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> dict[str, Any]:
    """
    Evaluates whether sufficient teacher-approved classifications have been accumulated
    to justify training a supervised model, avoiding premature or invalid training.
    """
    return get_supervised_learning_evaluation(db)


@router.get(
    "/cleaned-dataset",
    response_model=CleanedDatasetPaginatedResponse,
    summary="Get paginated items and provenance from the cleaned question bank dataset",
)
def get_cleaned_dataset_endpoint(
    search: Optional[str] = Query(None, description="Search question text or answer"),
    question_type: Optional[str] = Query(None, description="Filter by type (mcq, essay)"),
    chapter: Optional[str] = Query(None, description="Filter by chapter"),
    lesson: Optional[str] = Query(None, description="Filter by lesson"),
    verification_status: Optional[str] = Query(None, description="Filter by verification status"),
    answer_source: Optional[str] = Query(None, description="Filter by answer source"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(15, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(require_role("professor")),
) -> CleanedDatasetPaginatedResponse:
    """
    Safely retrieves paginated questions and provenance from the verified cleaned dataset file.
    Read-only: does NOT insert, update, or mutate the database in any way.
    """
    try:
        dataset = load_cleaned_dataset()
    except FileNotFoundError as fnf_err:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Cleaned dataset file could not be found: {fnf_err}",
        )
    except Exception as exc:
        logger.error("Error loading cleaned dataset: %s", exc)
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load cleaned dataset: {exc}",
        )

    records = dataset.records

    if search:
        search_norm = search.strip().lower()
        records = [
            r for r in records
            if search_norm in r.get("question_text", "").lower()
            or search_norm in r.get("correct_answer", "").lower()
            or search_norm in r.get("question_id", "").lower()
            or search_norm in (r.get("original_question_id") or "").lower()
        ]

    if question_type:
        qtype_lower = question_type.strip().lower()
        records = [r for r in records if r.get("question_type", "").lower() == qtype_lower]

    if chapter:
        ch_str = chapter.strip()
        records = [r for r in records if r.get("chapter") == ch_str]

    if lesson:
        ls_str = lesson.strip()
        records = [r for r in records if r.get("lesson") == ls_str]

    if verification_status:
        v_str = verification_status.strip().lower()
        records = [r for r in records if (r.get("verification_status") or "").lower() == v_str]

    if answer_source:
        ans_src = answer_source.strip().lower()
        records = [r for r in records if (r.get("answer_source") or "").lower() == ans_src]

    total = len(records)
    total_pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 1

    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    page_records = records[start_idx:end_idx]

    prov_dict = dataset.provenance.to_dict()

    return CleanedDatasetPaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        items=[CleanedDatasetItem(**rec) for rec in page_records],
        provenance=CleanedDatasetProvenance(**prov_dict),
        filters_available=dataset.filters_available,
    )


@router.get(
    "/cleaned-dataset/provenance",
    response_model=CleanedDatasetProvenance,
    summary="Get cryptographic provenance and metadata for the cleaned dataset",
)
def get_cleaned_dataset_provenance_endpoint(
    current_user: User = Depends(require_role("professor")),
) -> CleanedDatasetProvenance:
    """Returns cryptographic hash, row counts, and schema validation details."""
    try:
        dataset = load_cleaned_dataset()
    except FileNotFoundError as fnf_err:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Cleaned dataset file could not be found: {fnf_err}",
        )
    return CleanedDatasetProvenance(**dataset.provenance.to_dict())


@router.get(
    "/{question_id}",
    response_model=QuestionBankItemResponse,
    summary="Get detailed information for a single question bank item",
)
def get_question_bank_item(
    question_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> QuestionBankItemResponse:
    """Retrieves an individual question by its stable identifier."""
    item = db.query(QuestionBankItem).filter_by(question_id=question_id).first()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question with ID '{question_id}' not found in question bank.",
        )
    return QuestionBankItemResponse(**question_item_to_dict(item))


# ---------------------------------------------------------------------------
# 4. Review, Approval, Rejection, and Editing Endpoints
# ---------------------------------------------------------------------------


@router.patch(
    "/{question_id}",
    response_model=QuestionBankItemResponse,
    summary="Update or correct a question bank item",
)
def edit_question_bank_item(
    question_id: str,
    patch_data: QuestionBankItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> QuestionBankItemResponse:
    """
    Edits question text, options, answer, or taxonomy attributes.
    If stem or options change, triggers Chroma re-embedding.
    """
    try:
        updated = update_question_item(
            db=db,
            question_id=question_id,
            patch_data=patch_data.model_dump(exclude_unset=True),
            current_user_id=current_user.id,
            chroma_persist_dir=VECTOR_DB_PATH,
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question with ID '{question_id}' not found.",
        )
    except Exception as exc:
        logger.error("Failed to update question %s: %s", question_id, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to update question: {exc}",
        )
    return QuestionBankItemResponse(**question_item_to_dict(updated))


@router.post(
    "/{question_id}/approve",
    response_model=QuestionBankItemResponse,
    summary="Approve a question classification with optional teacher corrections",
)
def approve_question(
    question_id: str,
    action: Optional[QuestionBankReviewAction] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> QuestionBankItemResponse:
    """
    Approves a question, recording reviewer identity, timestamp, and saving
    any teacher corrections to teacher_corrections_json for incremental learning.
    """
    corrections = action.corrections if action else None
    notes = action.notes if action else None

    try:
        approved = approve_question_item(
            db=db,
            question_id=question_id,
            reviewer_name=current_user.name,
            reviewer_id=current_user.id,
            corrections=corrections,
            notes=notes,
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question with ID '{question_id}' not found.",
        )
    except Exception as exc:
        logger.error("Failed to approve question %s: %s", question_id, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Approval failed: {exc}",
        )
    return QuestionBankItemResponse(**question_item_to_dict(approved))


@router.post(
    "/{question_id}/reject",
    response_model=QuestionBankItemResponse,
    summary="Reject a proposed question classification",
)
def reject_question(
    question_id: str,
    action: Optional[QuestionBankReviewAction] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> QuestionBankItemResponse:
    """
    Rejects a question item, keeping full audit logs and reviewer notes.
    """
    notes = action.notes if action else None
    try:
        rejected = reject_question_item(
            db=db,
            question_id=question_id,
            reviewer_name=current_user.name,
            reviewer_id=current_user.id,
            notes=notes,
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question with ID '{question_id}' not found.",
        )
    except Exception as exc:
        logger.error("Failed to reject question %s: %s", question_id, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rejection failed: {exc}",
        )
    return QuestionBankItemResponse(**question_item_to_dict(rejected))


@router.post(
    "/reconcile-embeddings",
    summary="Reconcile and retry pending or failed Chroma question embeddings",
)
def reconcile_embeddings_endpoint(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> dict[str, Any]:
    """Retries Chroma embedding sync for any records marked 'pending' or 'failed'."""
    from scripts.ingestion import get_embeddings
    try:
        embeddings = get_embeddings()
    except Exception:
        embeddings = None

    result = reconcile_pending_embeddings(
        db=db,
        chroma_persist_dir=VECTOR_DB_PATH,
        embeddings=embeddings,
        statuses=("pending", "failed"),
    )
    return result


@router.post(
    "/{question_id}/submit",
    response_model=QuestionPracticeGradingResponse,
    summary="Submit and authoritatively grade student practice answer",
)
@router.post(
    "/{question_id}/practice",
    response_model=QuestionPracticeGradingResponse,
    summary="Practice question grading alias",
)
def grade_practice_question(
    question_id: str,
    payload: QuestionPracticeSubmitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> QuestionPracticeGradingResponse:
    """
    Authoritative backend grading for student practice in the Question Bank:
    - Verifies question is approved for student access.
    - Deterministically grades MCQs against the verified answer key.
    - Protects answer secrecy prior to submission; reveals correct answer & explanation upon submission.
    - Handles missing answer keys safely.
    - For essay and short-answer questions, records submission and confirms teacher review without false 'correct' grading.
    - Persists the practice record in the database.
    """
    from sqlalchemy import select
    from scripts.grading import grade_mcq

    item = db.scalar(
        select(QuestionBankItem).where(QuestionBankItem.question_id == question_id)
    )
    if not item and question_id.isdigit():
        item = db.scalar(
            select(QuestionBankItem).where(QuestionBankItem.id == int(question_id))
        )
    if not item:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail=f"Question with ID '{question_id}' not found in Question Bank.",
        )

    if current_user.role == "student" and item.review_status != "approved":
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Access forbidden: question is not approved for student practice.",
        )

    options: list[str] = []
    if item.options_json:
        try:
            options = json.loads(item.options_json) or []
        except Exception:
            options = []

    submitted_text = (payload.answer_text or "").strip()
    selected_opt = (payload.selected_option or "").strip()

    # Normalize selected_option and submitted_text
    if selected_opt.isdigit() and 0 <= int(selected_opt) < len(options):
        opt_idx = int(selected_opt)
        selected_opt = ["A", "B", "C", "D"][opt_idx]
        if not submitted_text:
            submitted_text = str(options[opt_idx]).strip()
    elif selected_opt.upper() in ("A", "B", "C", "D"):
        selected_opt = selected_opt.upper()
        idx = ["A", "B", "C", "D"].index(selected_opt)
        if not submitted_text and idx < len(options):
            submitted_text = str(options[idx]).strip()
    elif not selected_opt and submitted_text and options:
        for i, opt in enumerate(options):
            if str(opt).strip().casefold() == submitted_text.casefold():
                selected_opt = ["A", "B", "C", "D"][i]
                break

    if item.question_type == "mcq":
        canonical_correct_opt = (item.correct_option or "").strip().upper()
        canonical_correct_ans = (item.correct_answer or "").strip()

        if not canonical_correct_opt and canonical_correct_ans and options:
            for idx, opt in enumerate(options):
                if str(opt).strip().casefold() == canonical_correct_ans.casefold():
                    canonical_correct_opt = ["A", "B", "C", "D"][idx]
                    break

        if not canonical_correct_ans and canonical_correct_opt and options:
            if canonical_correct_opt in ("A", "B", "C", "D"):
                idx = ["A", "B", "C", "D"].index(canonical_correct_opt)
                if idx < len(options):
                    canonical_correct_ans = str(options[idx]).strip()

        # Missing answer key safety check
        if not canonical_correct_opt and not canonical_correct_ans:
            sub = QuestionBankPracticeSubmission(
                question_id=item.question_id,
                student_id=current_user.id,
                selected_option=selected_opt or None,
                submitted_answer=submitted_text or None,
                is_correct=None,
                score=0.0,
                status="unverified_key",
            )
            db.add(sub)
            db.commit()

            return QuestionPracticeGradingResponse(
                question_id=item.question_id,
                question_type="mcq",
                is_correct=None,
                score=0.0,
                max_score=1.0,
                status="unverified_key",
                submitted_answer=submitted_text or selected_opt,
                selected_option=selected_opt or None,
                correct_option=None,
                correct_answer=None,
                explanation=item.explanation,
                feedback_message="تعذر التحقق التلقائي لعدم توفر مفتاح الإجابة الصحيحة لهذا السؤال في النظام. تم تحويل السؤال لمراجعة المعلم.",
                requires_teacher_review=True,
            )

        eval_student = selected_opt if selected_opt else submitted_text
        eval_target = canonical_correct_opt if canonical_correct_opt else canonical_correct_ans
        mcq_eval = grade_mcq(student_answer=eval_student, correct_answer=eval_target, max_score=1.0)
        is_corr = bool(mcq_eval.get("is_correct"))

        if not is_corr and submitted_text and canonical_correct_ans:
            if submitted_text.casefold() == canonical_correct_ans.casefold():
                is_corr = True

        score = 1.0 if is_corr else 0.0
        status_str = "correct" if is_corr else "incorrect"
        feedback = (
            "إجابة صحيحة! أحسنت."
            if is_corr
            else f"إجابة غير صحيحة. الخيار الصحيح هو ({canonical_correct_opt or canonical_correct_ans})."
        )

        sub = QuestionBankPracticeSubmission(
            question_id=item.question_id,
            student_id=current_user.id,
            selected_option=selected_opt or None,
            submitted_answer=submitted_text or None,
            is_correct=is_corr,
            score=score,
            status=status_str,
        )
        db.add(sub)
        db.commit()

        revealed_answer = canonical_correct_ans or (
            options[["A", "B", "C", "D"].index(canonical_correct_opt)]
            if canonical_correct_opt in ("A", "B", "C", "D") and ["A", "B", "C", "D"].index(canonical_correct_opt) < len(options)
            else None
        )

        return QuestionPracticeGradingResponse(
            question_id=item.question_id,
            question_type="mcq",
            is_correct=is_corr,
            score=score,
            max_score=1.0,
            status=status_str,
            submitted_answer=submitted_text or selected_opt,
            selected_option=selected_opt or None,
            correct_option=canonical_correct_opt or None,
            correct_answer=revealed_answer,
            explanation=item.explanation,
            feedback_message=feedback,
            requires_teacher_review=False,
        )
    else:
        # Essay and short-answer questions require teacher review
        sub = QuestionBankPracticeSubmission(
            question_id=item.question_id,
            student_id=current_user.id,
            selected_option=None,
            submitted_answer=submitted_text or None,
            is_correct=None,
            score=0.0,
            status="needs_teacher_review",
        )
        db.add(sub)
        db.commit()

        return QuestionPracticeGradingResponse(
            question_id=item.question_id,
            question_type=item.question_type,
            is_correct=None,
            score=0.0,
            max_score=1.0,
            status="needs_teacher_review",
            submitted_answer=submitted_text,
            selected_option=None,
            correct_option=None,
            correct_answer=item.correct_answer or None,
            explanation=item.explanation,
            feedback_message="تم تسجيل إجابتك وإرسالها لمراجعة المعلم بنجاح. لا يتم التصحيح التلقائي للأسئلة المقالية، وتظهر أدناه الإجابة النموذجية المرجعية.",
            requires_teacher_review=True,
        )

