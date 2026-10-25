"""Analytics, student clustering, and diagnostic dashboard endpoints."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.database import get_db
from app.models import ExamAttempt, StudentCluster, User
from app.routers.attempt_router import _format_attempt_response
from app.schemas import (
    ClusterResponse,
    ProfessorDashboardResponse,
    StudentDashboardResponse,
    UserResponse,
)
from scripts.analytics import build_feature_matrix, cluster_students, get_class_analytics
from scripts.feedback import generate_class_summary, generate_student_feedback

router = APIRouter(tags=["Analytics"])

# In-memory cache for generated class summaries to keep dashboard loading instant
_SUMMARY_CACHE: dict[str, Any] = {}


@router.post(
    "/cluster",
    response_model=list[ClusterResponse],
    summary="Compute and update student performance clusters (Professor only)",
)
def compute_clustering(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> list[ClusterResponse]:
    """
    Extracts student performance feature vectors, executes unsupervised clustering,
    and updates student profile classifications in the database.
    """
    attempts = db.scalars(
        select(ExamAttempt).where(ExamAttempt.submitted_at.is_not(None))
    ).all()

    if not attempts:
        return []

    attempts_data: list[dict[str, Any]] = []
    for att in attempts:
        max_s = float(att.max_possible_score) if att.max_possible_score else 0.0
        tot_s = float(att.total_score) if att.total_score is not None else 0.0
        pct = (tot_s / max_s * 100.0) if max_s > 0 else 0.0
        attempts_data.append(
            {
                "student_id": att.student_id,
                "total_score": tot_s,
                "max_possible_score": max_s,
                "percentage": pct,
                "duration_seconds": att.duration_seconds or 0,
            }
        )

    features, student_ids, feature_names = build_feature_matrix(attempts_data)
    cluster_result = cluster_students(features, student_ids, feature_names=feature_names)

    engine = None
    student_scores_map: dict[str, list[float]] = {}
    try:
        from scripts.analytics import StudentAnalyticsEngine
        engine = StudentAnalyticsEngine()
        for att in attempts_data:
            s_key = str(att["student_id"])
            student_scores_map.setdefault(s_key, []).append(float(att["percentage"]))
    except Exception:
        engine = None

    output: list[ClusterResponse] = []
    now = datetime.now(timezone.utc)

    for item in cluster_result.get("clusters", []):
        raw_sid = item["student_id"]
        c_label = item.get("label", "Unknown")
        features_dict = dict(item.get("features", {}))

        # Use trained StudentAnalyticsEngine if available
        if engine and raw_sid in student_scores_map:
            pred = engine.predict_student(student_scores_map[raw_sid])
            if pred.get("is_evaluated"):
                c_label = pred["student_level"]
            features_dict["level_code"] = pred.get("level_code", -1)
            features_dict["student_level"] = c_label

        # student_ids from build_feature_matrix are strings; convert to int for DB
        try:
            s_id = int(raw_sid)
        except (ValueError, TypeError):
            continue

        existing_record = db.scalar(
            select(StudentCluster).where(StudentCluster.student_id == s_id)
        )
        if existing_record:
            existing_record.cluster_label = c_label
            existing_record.features_json = json.dumps(features_dict)
            existing_record.updated_at = now
        else:
            new_record = StudentCluster(
                student_id=s_id,
                cluster_label=c_label,
                features_json=json.dumps(features_dict),
                updated_at=now,
            )
            db.add(new_record)

        output.append(
            ClusterResponse(
                student_id=s_id,
                cluster_label=c_label,
                features=features_dict,
            )
        )

    db.commit()
    return output


def _build_student_dashboard(
    student_id: int,
    db: Session,
) -> StudentDashboardResponse:
    """Helper to assemble personalized dashboard response for a student."""
    student_user = db.scalar(select(User).where(User.id == student_id))
    if not student_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {student_id} not found.",
        )

    attempts = db.scalars(
        select(ExamAttempt)
        .where(
            ExamAttempt.student_id == student_id,
            ExamAttempt.submitted_at.is_not(None),
        )
        .order_by(ExamAttempt.started_at.desc())
    ).all()

    cluster_record = db.scalar(
        select(StudentCluster).where(StudentCluster.student_id == student_id)
    )

    cluster_data: dict[str, Any] | None = None
    cluster_response: ClusterResponse | None = None
    if cluster_record:
        try:
            feats = json.loads(cluster_record.features_json)
        except Exception:
            feats = {}
        cluster_data = {
            "cluster_label": cluster_record.cluster_label,
            "features": feats,
        }
        cluster_response = ClusterResponse(
            student_id=student_id,
            cluster_label=cluster_record.cluster_label,
            features=feats,
        )

    attempts_dicts: list[dict[str, Any]] = []
    for att in attempts:
        max_s = float(att.max_possible_score) if att.max_possible_score else 0.0
        tot_s = float(att.total_score) if att.total_score is not None else 0.0
        pct = (tot_s / max_s * 100.0) if max_s > 0 else 0.0
        attempts_dicts.append(
            {
                "total_score": tot_s,
                "max_possible_score": max_s,
                "percentage": pct,
                "duration_seconds": att.duration_seconds or 0,
            }
        )

    if cluster_response is None and attempts_dicts:
        try:
            from scripts.analytics import StudentAnalyticsEngine
            import numpy as np
            engine = StudentAnalyticsEngine()
            p_scores = [a["percentage"] for a in attempts_dicts]
            pred = engine.predict_student(p_scores)
            c_label = pred.get("student_level", "Under Evaluation")
            dyn_feats = {
                "avg_percentage": round(float(np.mean(p_scores)), 2),
                "exams_taken": len(p_scores),
                "level_code": pred.get("level_code", -1),
            }
            cluster_response = ClusterResponse(
                student_id=student_id,
                cluster_label=c_label,
                features=dyn_feats,
            )
            cluster_data = {"cluster_label": c_label, "features": dyn_feats}
        except Exception:
            pass

    cluster_label_str = cluster_data["cluster_label"] if cluster_data else "Under Evaluation"
    if not attempts_dicts:
        feedback = {
            "summary": f"Welcome, {student_user.name}. Complete your first assessment to view personalized AI diagnostics and feedback.",
            "strengths": ["Account ready"],
            "weaknesses": [],
            "recommendations": ["Select an available published assessment to begin."],
            "study_plan": "Review introductory course materials and take published quizzes.",
            "cluster_label": cluster_label_str,
        }
    else:
        feedback = generate_student_feedback(
            student_name=student_user.name,
            attempts=attempts_dicts,
            cluster_label=cluster_label_str,
        )

    return StudentDashboardResponse(
        student=UserResponse.model_validate(student_user),
        attempts=[_format_attempt_response(a) for a in attempts],
        cluster=cluster_response,
        feedback=feedback,
    )


@router.get(
    "/dashboard/student",
    response_model=StudentDashboardResponse,
    summary="Get diagnostics dashboard for current student",
)
def get_own_student_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StudentDashboardResponse:
    """
    Returns diagnostics and performance feedback for the currently authenticated student.
    """
    return _build_student_dashboard(student_id=current_user.id, db=db)


@router.get(
    "/dashboard/student/{student_id}",
    response_model=StudentDashboardResponse,
    summary="Get diagnostics dashboard for a specific student",
)
def get_student_dashboard(
    student_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StudentDashboardResponse:
    """
    Returns student diagnostic indicators and remedial advice.
    Students may only query their own dashboard; professors may query any student.
    """
    if current_user.role == "student" and current_user.id != student_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: students are not permitted to inspect diagnostics of other students.",
        )

    return _build_student_dashboard(student_id=student_id, db=db)


@router.get(
    "/dashboard/professor",
    response_model=ProfessorDashboardResponse,
    summary="Get aggregated class analytics and teaching recommendations (Professor only)",
)
def get_professor_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> ProfessorDashboardResponse:
    """
    Computes class-wide distribution, topic masteries, student clusters,
    and automated instructional interventions.
    """
    all_attempts = db.scalars(
        select(ExamAttempt).where(ExamAttempt.submitted_at.is_not(None))
    ).all()

    attempts_data: list[dict[str, Any]] = []
    for att in all_attempts:
        max_s = float(att.max_possible_score) if att.max_possible_score else 0.0
        tot_s = float(att.total_score) if att.total_score is not None else 0.0
        pct = (tot_s / max_s * 100.0) if max_s > 0 else 0.0
        attempts_data.append(
            {
                "student_id": att.student_id,
                "exam_id": att.exam_id,
                "total_score": tot_s,
                "max_possible_score": max_s,
                "percentage": pct,
                "duration_seconds": att.duration_seconds or 0,
            }
        )

    class_analytics = get_class_analytics(attempts_data)

    cluster_records = db.scalars(select(StudentCluster)).all()
    cluster_list: list[ClusterResponse] = []
    cluster_dicts: list[dict[str, Any]] = []

    for cr in cluster_records:
        try:
            feats = json.loads(cr.features_json)
        except Exception:
            feats = {}

        item = {
            "student_id": cr.student_id,
            "cluster_label": cr.cluster_label,
            "features": feats,
        }
        cluster_dicts.append(item)
        cluster_list.append(ClusterResponse(**item))

    if not all_attempts:
        summary = {
            "overall_assessment": "No assessment submissions have been recorded yet. As students complete published assessments, automated class-wide analytics and instructional recommendations will appear here.",
            "key_findings": ["No student submission data available yet."],
            "topic_recommendations": {},
            "intervention_needed": [],
            "class_strengths": [],
        }
    else:
        cache_key = f"{len(all_attempts)}_{sum(a.id for a in all_attempts)}_{len(cluster_records)}"
        if cache_key in _SUMMARY_CACHE:
            summary = _SUMMARY_CACHE[cache_key]
        else:
            summary = generate_class_summary(class_analytics, {"clusters": cluster_dicts})
            _SUMMARY_CACHE[cache_key] = summary

    return ProfessorDashboardResponse(
        class_analytics=class_analytics,
        clusters=cluster_list,
        summary=summary,
    )
