"""Exam attempt and automated submission grading endpoints."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.database import get_db
from app.models import Exam, ExamAttempt, StudentCluster, User
from app.schemas import (
    AttemptResponse,
    AttemptStartRequest,
    AttemptStartResponse,
    AttemptSubmitRequest,
)
from scripts.grading import grade_exam_submission

logger = logging.getLogger(__name__)
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

    exam_title = attempt.exam.title if attempt.exam else None

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
        exam_title=exam_title,
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

    if not getattr(exam, "is_published", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot start an attempt on an unpublished exam.",
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

    # Real-time student profiling using trained StudentAnalyticsEngine
    try:
        from scripts.analytics import StudentAnalyticsEngine
        import numpy as np

        all_student_attempts = db.scalars(
            select(ExamAttempt).where(
                ExamAttempt.student_id == current_user.id,
                ExamAttempt.submitted_at.is_not(None),
            )
        ).all()

        scores = [
            float(att.total_score / att.max_possible_score * 100.0)
            for att in all_student_attempts
            if att.max_possible_score and att.max_possible_score > 0 and att.total_score is not None
        ]

        if scores:
            engine = StudentAnalyticsEngine()
            pred = engine.predict_student(scores)
            c_label = pred.get("student_level", "Under Evaluation")

            features_dict = {
                "avg_percentage": round(float(np.mean(scores)), 2),
                "max_percentage": round(float(np.max(scores)), 2),
                "min_percentage": round(float(np.min(scores)), 2),
                "exams_taken": len(scores),
                "std_percentage": round(float(np.std(scores, ddof=1)), 2) if len(scores) > 1 else 0.0,
                "level_code": pred.get("level_code", -1),
            }

            cluster_rec = db.scalar(
                select(StudentCluster).where(StudentCluster.student_id == current_user.id)
            )
            now_cluster = datetime.now(timezone.utc)
            if cluster_rec:
                cluster_rec.cluster_label = c_label
                cluster_rec.features_json = json.dumps(features_dict)
                cluster_rec.updated_at = now_cluster
            else:
                new_cluster_rec = StudentCluster(
                    student_id=current_user.id,
                    cluster_label=c_label,
                    features_json=json.dumps(features_dict),
                    updated_at=now_cluster,
                )
                db.add(new_cluster_rec)
            db.commit()
    except Exception as exc:
        logger.warning("Could not update student proficiency profile: %s", exc)

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
