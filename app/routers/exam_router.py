"""Exam generation and retrieval endpoints."""

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
from app.schemas import ExamGenerateRequest, ExamListItem, ExamPublishRequest, ExamResponse
from scripts.generation import generate_exam

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


@router.post(
    "/generate",
    response_model=ExamResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate assessment questions from curriculum (Professor only)",
)
def create_exam(
    payload: ExamGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> ExamResponse:
    """
    Generates curriculum-grounded assessment questions via the configured LLM and
    persists the resulting exam specification in the database.
    """
    topic = payload.topic.strip() if payload.topic else ""
    if not topic:
        topic = f"Lesson {payload.lesson_id}"

    try:
        exam_dict, _ = generate_exam(
            topic=topic,
            lesson_id=payload.lesson_id,
            difficulty=payload.difficulty,
            bloom_level=payload.bloom_level,
            question_types=payload.question_types,
            number_of_questions=payload.number_of_questions,
            allow_partial=True,
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

    # Associate with latest curriculum if available
    latest_curr = db.scalar(select(Curriculum).order_by(Curriculum.uploaded_at.desc()))
    curr_id = latest_curr.id if latest_curr else None

    questions = exam_dict.get("questions", [])
    total_pts = float(exam_dict.get("total_points", sum(q.get("max_score", 1.0) for q in questions)))
    title = exam_dict.get("exam_title", f"{payload.topic.title()} Assessment")

    exam_record = Exam(
        title=title,
        curriculum_id=curr_id,
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

    return ExamResponse(
        id=exam_record.id,
        title=exam_record.title,
        lesson_id=exam_record.lesson_id,
        topic=exam_record.topic,
        difficulty=exam_record.difficulty,
        bloom_level=exam_record.bloom_level,
        total_points=exam_record.total_points,
        question_count=len(questions),
        is_published=exam_record.is_published,
        created_at=exam_record.created_at,
        questions=questions,
        warnings=exam_dict.get("warnings", []),
    )


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
    Sets the publication visibility of an exam. Published exams are accessible to students.
    """
    exam = db.scalar(select(Exam).where(Exam.id == exam_id))
    if not exam:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exam with ID {exam_id} not found.",
        )

    if current_user.role == "student" and not getattr(exam, "is_published", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This assessment has not been published by the instructor yet.",
        )

    exam.is_published = payload.is_published
    db.commit()
    db.refresh(exam)

    warnings: list[str] = []
    try:
        data = json.loads(exam.exam_json)
        raw_questions = data.get("questions", [])
        warnings = data.get("warnings", [])
    except Exception:
        raw_questions = []

    return ExamResponse(
        id=exam.id,
        title=exam.title,
        lesson_id=exam.lesson_id,
        topic=exam.topic,
        difficulty=exam.difficulty,
        bloom_level=exam.bloom_level,
        total_points=exam.total_points,
        question_count=len(raw_questions),
        is_published=exam.is_published,
        created_at=exam.created_at,
        questions=raw_questions,
        warnings=warnings,
    )


@router.get(
    "",
    response_model=list[ExamListItem],
    summary="List all available exams",
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
    Returns a summary list of all generated assessments.
    """
    if current_user.role == "student":
        query = select(Exam).where(Exam.is_published == True).order_by(Exam.created_at.desc())
    else:
        query = select(Exam).order_by(Exam.created_at.desc())

    exams = db.scalars(query).all()
    results: list[ExamListItem] = []
    for ex in exams:
        q_count = 0
        if ex.exam_json:
            try:
                data = json.loads(ex.exam_json)
                q_count = len(data.get("questions", []))
            except Exception:
                q_count = 0

        results.append(
            ExamListItem(
                id=ex.id,
                title=ex.title,
                lesson_id=ex.lesson_id,
                topic=ex.topic,
                difficulty=ex.difficulty,
                bloom_level=ex.bloom_level,
                total_points=ex.total_points,
                question_count=q_count,
                is_published=getattr(ex, "is_published", False),
                created_at=ex.created_at,
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
    Retrieves a single exam by ID. For student accounts, correct answers,
    reference solutions, explanations, and grading rubrics are automatically stripped.
    """
    exam = db.scalar(select(Exam).where(Exam.id == exam_id))
    if not exam:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exam with ID {exam_id} not found.",
        )

    if current_user.role == "student" and not getattr(exam, "is_published", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This assessment has not been published by the instructor yet.",
        )

    warnings: list[str] = []
    try:
        data = json.loads(exam.exam_json)
        raw_questions = data.get("questions", [])
        warnings = data.get("warnings", [])
    except Exception:
        raw_questions = []

    questions = (
        _sanitize_for_student(raw_questions)
        if current_user.role == "student"
        else raw_questions
    )

    return ExamResponse(
        id=exam.id,
        title=exam.title,
        lesson_id=exam.lesson_id,
        topic=exam.topic,
        difficulty=exam.difficulty,
        bloom_level=exam.bloom_level,
        total_points=exam.total_points,
        question_count=len(raw_questions),
        is_published=getattr(exam, "is_published", False),
        created_at=exam.created_at,
        questions=questions,
        warnings=warnings,
    )
