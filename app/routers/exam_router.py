"""Exam generation, professor-scoped retrieval, and question editing endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.database import get_db
from app.models import Curriculum, Exam, User
from app.schemas import (
    ExamGenerateRequest,
    ExamListItem,
    ExamPublishRequest,
    ExamResponse,
    QuestionUpdateRequest,
)
from scripts.generation import _validate_question, generate_exam

router = APIRouter(tags=["Exams"])


def _sanitize_for_student(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Strips solution keys and evaluation rubrics from questions to maintain exam integrity.
    """
    sensitive_keys = {
        "correct_answer",
        "reference_answer",
        "explanation",
        "rubric",
        "source_refs",
    }
    sanitized: list[dict[str, Any]] = []
    for q in questions:
        cleaned = {k: v for k, v in q.items() if k not in sensitive_keys}
        sanitized.append(cleaned)
    return sanitized


def _load_exam_questions(exam: Exam) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        data = json.loads(exam.exam_json)
        raw_questions = data.get("questions", [])
        warnings = data.get("warnings", [])
    except Exception:
        raw_questions = []
        warnings = []
    return raw_questions, warnings


def _build_exam_response(
    exam: Exam,
    questions: list[dict[str, Any]],
    warnings: list[str],
) -> ExamResponse:
    return ExamResponse(
        id=exam.id,
        title=exam.title,
        lesson_id=exam.lesson_id,
        topic=exam.topic,
        difficulty=exam.difficulty,
        bloom_level=exam.bloom_level,
        total_points=exam.total_points,
        question_count=len(questions),
        is_published=exam.is_published,
        created_at=exam.created_at,
        curriculum_id=exam.curriculum_id,
        questions=questions,
        warnings=warnings,
    )


def _ensure_student_visible(exam: Exam, student: User) -> None:
    """
    Students may only access published exams from the professor they selected.
    """
    if not exam.is_published:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This assessment has not been published by the instructor yet.",
        )
    if student.selected_professor_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Select a professor first to access their exams.",
        )
    if exam.created_by != student.selected_professor_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This exam belongs to a professor other than your selected professor.",
        )


def _ensure_professor_owns(exam: Exam, professor: User) -> None:
    if exam.created_by != professor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: this exam was created by another professor.",
        )


@router.post(
    "/generate",
    response_model=ExamResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate assessment questions from a selected textbook (Professor only)",
)
def create_exam(
    payload: ExamGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> ExamResponse:
    """
    Generates curriculum-grounded assessment questions via the configured LLM.
    Retrieval is restricted to the vector collection of the professor-selected
    textbook (curriculum_id) and the chosen lesson within it.
    """
    document = db.scalar(select(Curriculum).where(Curriculum.id == payload.curriculum_id))
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {payload.curriculum_id} not found. Upload the textbook first.",
        )
    if document.professor_id is not None and document.professor_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: this textbook belongs to another professor.",
        )

    topic = payload.topic.strip() if payload.topic else ""
    if not topic:
        topic = f"Lesson {payload.lesson_id}"

    collection_name = document.collection_name or "curriculum"
    try:
        exam_dict, _ = generate_exam(
            topic=topic,
            lesson_id=payload.lesson_id,
            difficulty=payload.difficulty,
            bloom_level=payload.bloom_level,
            question_types=payload.question_types,
            number_of_questions=payload.number_of_questions,
            allow_partial=True,
            language=payload.language,
            collection_name=collection_name,
        )
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Exam generation failed: {exc}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected error during exam generation: {exc}",
        )

    questions = exam_dict.get("questions", [])
    total_pts = float(exam_dict.get("total_points", sum(q.get("max_score", 1.0) for q in questions)))
    title = exam_dict.get("exam_title", f"{payload.topic.title()} Assessment")

    exam_record = Exam(
        title=title,
        curriculum_id=document.id,
        lesson_id=payload.lesson_id,
        topic=topic,
        difficulty=payload.difficulty,
        bloom_level=payload.bloom_level,
        exam_json=json.dumps(exam_dict),
        total_points=total_pts,
        is_published=False,
        created_by=current_user.id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(exam_record)
    db.commit()
    db.refresh(exam_record)

    return _build_exam_response(exam_record, questions, exam_dict.get("warnings", []))


@router.patch(
    "/{exam_id}/questions/{question_index}",
    response_model=ExamResponse,
    summary="Edit one generated question before publishing (Professor only)",
)
def update_exam_question(
    exam_id: int,
    question_index: int,
    payload: QuestionUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> ExamResponse:
    """
    Applies professor edits to a single generated question. The full question
    specification (prompt, options, reference answer, explanation, rubric, and
    score) is re-validated against the same rules used during generation, so
    automated grading keeps grading the edited question against its updated
    rubric and reference answer.
    """
    exam = db.scalar(select(Exam).where(Exam.id == exam_id))
    if not exam:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exam with ID {exam_id} not found.",
        )
    _ensure_professor_owns(exam, current_user)

    raw_questions, warnings = _load_exam_questions(exam)
    if question_index < 0 or question_index >= len(raw_questions):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Question index {question_index} is out of range for this exam.",
        )

    original = raw_questions[question_index]
    updated: dict[str, Any] = dict(original)

    updated["question"] = payload.question.strip()
    updated["question_type"] = payload.question_type
    updated["difficulty"] = payload.difficulty
    updated["bloom_level"] = payload.bloom_level
    updated["options"] = list(payload.options) if payload.question_type == "mcq" else []
    updated["correct_answer"] = payload.correct_answer if payload.question_type == "mcq" else ""
    updated["reference_answer"] = payload.reference_answer.strip()
    updated["explanation"] = payload.explanation.strip()
    updated["max_score"] = payload.max_score
    updated["rubric"] = [item.model_dump() for item in payload.rubric]
    if payload.bloom_rationale is not None and payload.bloom_rationale.strip():
        updated["bloom_rationale"] = payload.bloom_rationale.strip()
    elif not str(updated.get("bloom_rationale", "") or "").strip():
        updated["bloom_rationale"] = "Reviewed and confirmed by the professor."

    # Preserve curriculum grounding metadata from generation
    if not updated.get("source_refs"):
        updated["source_refs"] = [
            {
                "source": exam.topic,
                "chunk_id": f"professor-edit-{exam.id}-{question_index}",
                "evidence_quote": updated["reference_answer"],
            }
        ]

    try:
        _validate_question(updated)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid question edit: {exc}",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid question edit: {exc}",
        )

    raw_questions[question_index] = updated

    exam_dict: dict[str, Any] = {}
    try:
        exam_dict = json.loads(exam.exam_json)
    except Exception:
        exam_dict = {"questions": raw_questions, "warnings": warnings}
    exam_dict["questions"] = raw_questions
    exam.total_points = float(sum(q.get("max_score", 1.0) for q in raw_questions))
    exam.exam_json = json.dumps(exam_dict)
    exam.updated_at = datetime.now(timezone.utc) if hasattr(exam, "updated_at") else exam.created_at
    db.commit()
    db.refresh(exam)

    return _build_exam_response(exam, raw_questions, warnings)


@router.patch(
    "/{exam_id}/publish",
    response_model=ExamResponse,
    summary="Publish or unpublish an assessment for students (Professor only)",
)
def publish_exam(
    exam_id: int,
    payload: ExamPublishRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> ExamResponse:
    """
    Sets the publication visibility of an exam. Published exams are accessible
    to students enrolled with the owning professor.
    """
    exam = db.scalar(select(Exam).where(Exam.id == exam_id))
    if not exam:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exam with ID {exam_id} not found.",
        )

    if current_user.role == "professor":
        _ensure_professor_owns(exam, current_user)
    else:
        _ensure_student_visible(exam, current_user)

    exam.is_published = payload.is_published
    db.commit()
    db.refresh(exam)

    raw_questions, warnings = _load_exam_questions(exam)
    return _build_exam_response(exam, raw_questions, warnings)


@router.get(
    "",
    response_model=list[ExamListItem],
    summary="List exams scoped to the current user",
)
@router.get(
    "/",
    response_model=list[ExamListItem],
    include_in_schema=False,
)
def list_exams(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ExamListItem]:
    """
    Professors receive their own generated assessments.
    Students receive only published exams created by their selected professor;
    if no professor is selected the list is empty.
    """
    if current_user.role == "student":
        if current_user.selected_professor_id is None:
            return []
        query = select(Exam).where(
            Exam.is_published == True,  # noqa: E712
            Exam.created_by == current_user.selected_professor_id,
        )
    else:
        query = select(Exam).where(Exam.created_by == current_user.id)

    query = query.order_by(Exam.created_at.desc())
    exams = db.scalars(query).all()
    results: list[ExamListItem] = []
    for ex in exams:
        raw_questions, _ = _load_exam_questions(ex)
        results.append(
            ExamListItem(
                id=ex.id,
                title=ex.title,
                lesson_id=ex.lesson_id,
                topic=ex.topic,
                difficulty=ex.difficulty,
                bloom_level=ex.bloom_level,
                total_points=ex.total_points,
                question_count=len(raw_questions),
                is_published=ex.is_published,
                created_at=ex.created_at,
                curriculum_id=ex.curriculum_id,
            )
        )
    return results


@router.get(
    "/{exam_id}",
    response_model=ExamResponse,
    summary="Get single exam by ID (sanitized for students)",
)
def get_exam_by_id(
    exam_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExamResponse:
    """
    Retrieves a single exam by ID. Students may only open published exams from
    their selected professor, with answer keys and rubrics stripped.
    """
    exam = db.scalar(select(Exam).where(Exam.id == exam_id))
    if not exam:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exam with ID {exam_id} not found.",
        )

    if current_user.role == "student":
        _ensure_student_visible(exam, current_user)

    raw_questions, warnings = _load_exam_questions(exam)
    questions = (
        _sanitize_for_student(raw_questions)
        if current_user.role == "student"
        else raw_questions
    )

    return _build_exam_response(exam, questions, warnings)
