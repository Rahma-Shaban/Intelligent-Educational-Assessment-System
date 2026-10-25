"""Exam attempt and automated submission grading endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.database import get_db
from app.models import Exam, ExamAttempt, User
from app.schemas import (
    AttemptResponse,
    AttemptStartRequest,
    AttemptStartResponse,
    AttemptSubmitRequest,
)
from scripts.grading import grade_exam_submission

router = APIRouter(tags=["Attempts"])


def _format_attempt_response(attempt: ExamAttempt) -> AttemptResponse:
    """Helper to convert ExamAttempt ORM object to AttemptResponse schema."""
    percentage = None
    if attempt.total_score is not None and attempt.max_possible_score:
        if attempt.max_possible_score > 0:
            percentage = round(
                (attempt.total_score / attempt.max_possible_score) * 100.0, 2
            )

    graded_answers: list[dict[str, Any]] | None = None
    if attempt.graded_answers_json:
        try:
            graded_answers = json.loads(attempt.graded_answers_json)
        except Exception:
            graded_answers = None

    return AttemptResponse(
        id=attempt.id,
        exam_id=attempt.exam_id,
        student_id=attempt.student_id,
        started_at=attempt.started_at,
        submitted_at=attempt.submitted_at,
        duration_seconds=attempt.duration_seconds,
        total_score=attempt.total_score,
        max_possible_score=attempt.max_possible_score,
        percentage=percentage,
        graded_answers=graded_answers,
    )


@router.post(
    "/start",
    response_model=AttemptStartResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new exam attempt (Student only)",
)
def start_attempt(
    payload: AttemptStartRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("student")),
) -> AttemptStartResponse:
    """
    Initializes a new assessment attempt for the current student.
    """
    exam = db.scalar(select(Exam).where(Exam.id == payload.exam_id))
    if not exam:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exam with ID {payload.exam_id} not found.",
        )

    attempt = ExamAttempt(
        exam_id=payload.exam_id,
        student_id=current_user.id,
        started_at=datetime.now(timezone.utc),
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    return AttemptStartResponse(
        attempt_id=attempt.id,
        started_at=attempt.started_at,
    )


@router.post(
    "/submit",
    response_model=AttemptResponse,
    summary="Submit answers and receive instant grading (Student only)",
)
def submit_attempt(
    payload: AttemptSubmitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("student")),
) -> AttemptResponse:
    """
    Submits student responses for an open attempt, evaluates MCQs and open-ended
    questions against reference answers and rubrics, and records scores.
    """
    attempt = db.scalar(select(ExamAttempt).where(ExamAttempt.id == payload.attempt_id))
    if not attempt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attempt with ID {payload.attempt_id} not found.",
        )

    if attempt.student_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: you cannot submit answers for another student's attempt.",
        )

    if attempt.submitted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This exam attempt has already been submitted and graded.",
        )

    exam = db.scalar(select(Exam).where(Exam.id == attempt.exam_id))
    if not exam:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Associated exam record could not be found.",
        )

    try:
        exam_dict = json.loads(exam.exam_json)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Corrupt exam specification: {exc}",
        )

    now = datetime.now(timezone.utc)
    duration = payload.duration_seconds
    if duration <= 0 and attempt.started_at:
        duration = int((now - attempt.started_at).total_seconds())

    # Execute automated grading pipeline
    try:
        graded_result = grade_exam_submission(
            exam=exam_dict,
            student_answers=payload.answers,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Automated grading failed: {exc}",
        )

    attempt.submitted_at = now
    attempt.duration_seconds = max(0, duration)
    attempt.total_score = graded_result["total_score"]
    attempt.max_possible_score = graded_result["max_possible_score"]
    attempt.graded_answers_json = json.dumps(graded_result["graded_answers"])

    db.commit()
    db.refresh(attempt)

    return _format_attempt_response(attempt)


@router.get(
    "/my/history",
    response_model=list[AttemptResponse],
    summary="Get all attempts for the current student",
)
def get_my_attempts(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("student")),
) -> list[AttemptResponse]:
    """
    Lists historical attempts completed by the authenticated student.
    """
    attempts = db.scalars(
        select(ExamAttempt)
        .where(ExamAttempt.student_id == current_user.id)
        .order_by(ExamAttempt.started_at.desc())
    ).all()

    return [_format_attempt_response(att) for att in attempts]


@router.get(
    "/{attempt_id}",
    response_model=AttemptResponse,
    summary="Get single graded attempt by ID",
)
def get_attempt_by_id(
    attempt_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AttemptResponse:
    """
    Retrieves detailed results and question breakdown for a specific attempt.
    Students may only view their own attempts; professors may view any attempt.
    """
    attempt = db.scalar(select(ExamAttempt).where(ExamAttempt.id == attempt_id))
    if not attempt:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Attempt with ID {attempt_id} not found.",
        )

    if current_user.role == "student" and attempt.student_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: students are not permitted to inspect other students' attempts.",
        )

    return _format_attempt_response(attempt)
