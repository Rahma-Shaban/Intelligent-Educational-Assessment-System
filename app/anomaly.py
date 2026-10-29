"""Exam-attempt anomaly screening helpers.

The Isolation Forest result is a statistical review indicator only. It is not
proof of cheating, fraud, or any other form of student misconduct.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from scripts.exam_anomaly_service import ExamAnomalyService

logger = logging.getLogger(__name__)

# Fail-safe values used when the model is unavailable or inspect_attempt fails.
# anomaly_score stays None so dashboards can show "Not assessed" instead of "Normal".
ANOMALY_FALLBACK: dict[str, Any] = {
    "is_suspicious": False,
    "suspicion_status": "Normal",
    "suspicion_reason": None,
    "anomaly_score": None,
}

_anomaly_service: ExamAnomalyService | None = None


def init_exam_anomaly_service() -> None:
    """Load the pre-trained pipeline once per process. Submission stays available on failure."""
    global _anomaly_service
    try:
        _anomaly_service = ExamAnomalyService()
        logger.info("Exam anomaly screening model loaded.")
    except Exception:
        logger.exception("Failed to initialize exam anomaly screening; submissions will skip scoring.")
        _anomaly_service = None


def get_anomaly_service() -> ExamAnomalyService | None:
    return _anomaly_service


def set_anomaly_service(service: ExamAnomalyService | None) -> None:
    """Test hook to replace or clear the process-wide service instance."""
    global _anomaly_service
    _anomaly_service = service


def count_exam_question_types(exam_spec: dict[str, Any]) -> tuple[int, int]:
    """Count MCQ vs open-ended questions from the exam specification, not from answers."""
    questions = exam_spec.get("questions") or []
    mcq_count = 0
    essay_count = 0
    for question in questions:
        qtype = str(question.get("question_type") or "").strip().lower()
        if qtype == "mcq":
            mcq_count += 1
        else:
            # essay and short_answer are open-ended; the model exposes a single essay_count feature
            essay_count += 1
    return mcq_count, essay_count


def compute_score_percentage(total_score: Any, max_possible_score: Any) -> float:
    """Return 0.0 when the maximum score is missing or not positive."""
    try:
        max_score = float(max_possible_score) if max_possible_score is not None else 0.0
    except (TypeError, ValueError):
        max_score = 0.0
    if max_score <= 0:
        return 0.0
    try:
        earned = float(total_score) if total_score is not None else 0.0
    except (TypeError, ValueError):
        earned = 0.0
    return round((earned / max_score) * 100.0, 2)


def resolve_attempt_duration_seconds(
    started_at: datetime | None,
    submitted_at: datetime,
    client_duration_seconds: int | None = None,
) -> int:
    """Prefer elapsed time from start to submit over an unvalidated client duration."""
    if started_at is not None:
        start = started_at
        end = submitted_at
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        return max(0, int((end - start).total_seconds()))
    try:
        return max(0, int(client_duration_seconds or 0))
    except (TypeError, ValueError):
        return 0


def screen_exam_attempt(
    mcq_count: int,
    essay_count: int,
    duration_seconds: float,
    score_percentage: float,
) -> dict[str, Any]:
    """Run inspect_attempt and map the result onto persisted screening fields."""
    service = get_anomaly_service()
    if service is None:
        return dict(ANOMALY_FALLBACK)

    try:
        result = service.inspect_attempt(
            mcq_count=mcq_count,
            essay_count=essay_count,
            duration_seconds=duration_seconds,
            score_percentage=score_percentage,
        )
    except Exception:
        logger.exception("Exam anomaly screening failed; allowing submission to complete.")
        return dict(ANOMALY_FALLBACK)

    is_anomaly = bool(result.get("is_anomaly"))
    decision_score = result.get("decision_score")
    try:
        anomaly_score = float(decision_score) if decision_score is not None else None
    except (TypeError, ValueError):
        anomaly_score = None

    flag_reason = result.get("flag_reason")
    if not is_anomaly:
        # Neutral stored reason for non-flagged attempts; Arabic text is kept when the service sends it.
        stored_reason = flag_reason if flag_reason and flag_reason != "محاولة طبيعية متناسقة" else None
    else:
        stored_reason = flag_reason

    return {
        "is_suspicious": is_anomaly,
        "suspicion_status": result.get("status") or ("Suspicious / Flagged" if is_anomaly else "Normal"),
        "suspicion_reason": stored_reason,
        "anomaly_score": anomaly_score,
    }
