
"""
Database helpers for the Student Improvement feature.

Bridges the DB (ExamAttempt / Exam / Curriculum / StudentCluster) and the pure logic
in scripts/improvement.py. Shared by analytics_router (diagnosis) and exam_router (practice).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Curriculum, Exam, ExamAttempt, StudentCluster, User
from scripts.improvement import (
    compute_overall_accuracy,
    compute_weak_lessons,
    suggest_practice_settings,
    summarize_practice_history,
)

logger = logging.getLogger(__name__)


def real_exam_filter():
    """SQL condition that keeps only real (non-practice) exams. NULL counts as real (legacy rows)."""
    return or_(Exam.is_practice == False, Exam.is_practice.is_(None))  # noqa: E712


def practice_exam_filter():
    return Exam.is_practice == True  # noqa: E712


# ------------------------------------------------------------------------------
# Loading attempts
# ------------------------------------------------------------------------------

def load_submitted_attempts(
    db: Session,
    student_id: int,
    practice: bool,
) -> list[tuple[ExamAttempt, Exam]]:
    """Submitted attempts of one student joined with their exam (practice or real only)."""
    condition = practice_exam_filter() if practice else real_exam_filter()
    rows = db.execute(
        select(ExamAttempt, Exam)
        .join(Exam, ExamAttempt.exam_id == Exam.id)
        .where(
            ExamAttempt.student_id == student_id,
            ExamAttempt.submitted_at.is_not(None),
            condition,
        )
        .order_by(ExamAttempt.submitted_at.asc())
    ).all()
    return [(row[0], row[1]) for row in rows]


def _parse_graded_answers(attempt: ExamAttempt) -> list[dict[str, Any]] | None:
    if not attempt.graded_answers_json:
        return None
    try:
        data = json.loads(attempt.graded_answers_json)
    except Exception:
        return None
    if isinstance(data, dict):
        return list(data.values()) if all(isinstance(v, dict) for v in data.values()) else None
    return data if isinstance(data, list) else None


def build_attempt_rows(pairs: list[tuple[ExamAttempt, Exam]]) -> list[dict[str, Any]]:
    """Rows for compute_weak_lessons. Exam.lesson_id is the fallback for legacy answers."""
    rows: list[dict[str, Any]] = []
    for attempt, exam in pairs:
        answers = _parse_graded_answers(attempt)
        if answers is None:
            continue  # malformed or missing graded answers: skip safely
        rows.append(
            {
                "attempt_id": attempt.id,
                "exam_id": exam.id,
                "lesson_id": exam.lesson_id,
                "submitted_at": attempt.submitted_at,
                "graded_answers": answers,
            }
        )
    return rows


def attempt_percentage(attempt: ExamAttempt) -> float | None:
    if attempt.total_score is None or not attempt.max_possible_score:
        return None
    if attempt.max_possible_score <= 0:
        return None
    return round(attempt.total_score / attempt.max_possible_score * 100.0, 1)


# ------------------------------------------------------------------------------
# Lesson titles and curriculum resolution
# ------------------------------------------------------------------------------

def _curriculum_lessons(curriculum: Curriculum | None) -> list[dict[str, Any]]:
    if curriculum is None or not curriculum.lessons_json:
        return []
    try:
        lessons = json.loads(curriculum.lessons_json)
    except Exception:
        return []
    return [item for item in lessons if isinstance(item, dict)] if isinstance(lessons, list) else []


def _store_lessons(collection_name: str) -> list[dict[str, Any]]:
    """Read lessons from the vector store. Slow and may fail, so never let it raise."""
    try:
        from scripts.generation import list_curriculum_lessons, load_curriculum_store

        return list_curriculum_lessons(load_curriculum_store(collection_name=collection_name))
    except Exception as exc:
        logger.info("Vector store lessons unavailable for '%s': %s", collection_name, exc)
        return []


def resolve_lesson_titles(
    db: Session,
    lesson_ids: set[str],
    exams: list[Exam],
) -> dict[str, str]:
    """
    Title lookup order:
      1. Curriculum.lessons_json of the exams' textbooks (fast, written at upload time)
      2. lesson_title saved inside the exam JSON by generate_exam
      3. vector store via list_curriculum_lessons (only for still-missing titles; wrapped in try/except)
      4. the lesson_id itself (done by the caller)
    """
    titles: dict[str, str] = {}
    curriculum_ids = {ex.curriculum_id for ex in exams if ex.curriculum_id}
    curricula = (
        db.scalars(select(Curriculum).where(Curriculum.id.in_(curriculum_ids))).all()
        if curriculum_ids
        else []
    )
    for curriculum in curricula:
        for lesson in _curriculum_lessons(curriculum):
            lid = str(lesson.get("lesson_id") or "")
            if lid in lesson_ids and lesson.get("lesson_title") and lid not in titles:
                titles[lid] = str(lesson["lesson_title"])

    for ex in exams:
        if ex.lesson_id in titles or ex.lesson_id not in lesson_ids:
            continue
        try:
            title = json.loads(ex.exam_json or "{}").get("lesson_title")
        except Exception:
            title = None
        if title:
            titles[ex.lesson_id] = str(title)

    missing = lesson_ids - set(titles)
    if missing:
        collections = {c.collection_name or "curriculum" for c in curricula} or {"curriculum"}
        for collection_name in collections:
            for lesson in _store_lessons(collection_name):
                lid = str(lesson.get("lesson_id") or "")
                if lid in missing and lesson.get("lesson_title"):
                    titles[lid] = str(lesson["lesson_title"])
            if not (lesson_ids - set(titles)):
                break
    return titles


def _lesson_in(lessons: list[dict[str, Any]], lesson_id: str) -> bool:
    return any(str(item.get("lesson_id")) == lesson_id for item in lessons)


def _vector_store_exists() -> bool:
    try:
        from scripts.generation import resolve_vectorstore_dir

        return resolve_vectorstore_dir(None).exists()
    except Exception:
        return False


def resolve_practice_source(
    db: Session,
    student: User,
    lesson_id: str,
    verify_with_store: bool = False,
) -> dict[str, Any]:
    """
    Find which textbook (vector collection) a practice exam for this lesson should use.

    1. The most recent REAL exam this student took for the lesson (its curriculum_id).
    2. Otherwise any textbook of the student's selected professor (or legacy shared ones)
       that lists this lesson.
    Returns {available, reason, curriculum, collection_name, language, lesson_title}.
    """
    result: dict[str, Any] = {
        "available": False,
        "reason": None,
        "curriculum": None,
        "collection_name": "curriculum",
        "language": "en",
        "lesson_title": None,
    }

    source_exam = db.scalar(
        select(Exam)
        .join(ExamAttempt, ExamAttempt.exam_id == Exam.id)
        .where(
            ExamAttempt.student_id == student.id,
            Exam.lesson_id == lesson_id,
            real_exam_filter(),
        )
        .order_by(ExamAttempt.started_at.desc())
    )
    if source_exam is not None:
        try:
            exam_data = json.loads(source_exam.exam_json or "{}")
            result["language"] = exam_data.get("language") or "en"
            result["lesson_title"] = exam_data.get("lesson_title")
        except Exception:
            pass

    curriculum: Curriculum | None = None
    if source_exam is not None and source_exam.curriculum_id:
        curriculum = db.scalar(select(Curriculum).where(Curriculum.id == source_exam.curriculum_id))

    if curriculum is None:
        owners = [Curriculum.professor_id.is_(None)]
        if student.selected_professor_id is not None:
            owners.append(Curriculum.professor_id == student.selected_professor_id)
        for candidate in db.scalars(
            select(Curriculum).where(or_(*owners)).order_by(Curriculum.uploaded_at.desc())
        ).all():
            if _lesson_in(_curriculum_lessons(candidate), lesson_id):
                curriculum = candidate
                break

    if curriculum is not None:
        result["curriculum"] = curriculum
        result["collection_name"] = curriculum.collection_name or "curriculum"
        lessons = _curriculum_lessons(curriculum)
        if not lessons and verify_with_store:
            lessons = _store_lessons(result["collection_name"])
        if lessons and not _lesson_in(lessons, lesson_id):
            result["reason"] = "This lesson no longer exists in the curriculum."
            return result
        if not lessons and verify_with_store:
            result["reason"] = "The curriculum vector store is unavailable right now."
            return result
        for item in lessons:
            if str(item.get("lesson_id")) == lesson_id and item.get("lesson_title"):
                result["lesson_title"] = result["lesson_title"] or str(item["lesson_title"])
    elif source_exam is not None:
        # Legacy exam without a curriculum row: it used the shared "curriculum" collection
        if verify_with_store:
            lessons = _store_lessons("curriculum")
            if not lessons:
                result["reason"] = "The curriculum vector store is unavailable right now."
                return result
            if not _lesson_in(lessons, lesson_id):
                result["reason"] = "This lesson no longer exists in the curriculum."
                return result
    else:
        result["reason"] = "This lesson was not found in your professor's curriculum."
        return result

    if not _vector_store_exists():
        result["reason"] = "The curriculum vector store is unavailable, so practice cannot be generated."
        return result

    result["available"] = True
    return result


# ------------------------------------------------------------------------------
# Student level and full improvement payload
# ------------------------------------------------------------------------------

def get_student_level(
    db: Session,
    student_id: int,
    attempts_percentages: list[float] | None = None,
) -> str | None:
    record = db.scalar(select(StudentCluster).where(StudentCluster.student_id == student_id))
    if record and record.cluster_label:
        return record.cluster_label
    if attempts_percentages:
        try:
            from scripts.analytics import StudentAnalyticsEngine

            engine = StudentAnalyticsEngine()
            pred = engine.predict_student(attempts_percentages)
            return pred.get("student_level")
        except Exception:
            pass
    return None


def get_lesson_diagnosis(db: Session, student: User) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[Exam]]:
    """(weak lesson list, attempt rows, real exams) from the student's real attempts."""
    pairs = load_submitted_attempts(db, student.id, practice=False)
    rows = build_attempt_rows(pairs)
    exams = [exam for _, exam in pairs]
    lesson_ids = {str(r["lesson_id"]) for r in rows if r.get("lesson_id")}
    for row in rows:
        for entry in row["graded_answers"]:
            if isinstance(entry, dict) and entry.get("lesson_id"):
                lesson_ids.add(str(entry["lesson_id"]))
    titles = resolve_lesson_titles(db, lesson_ids, exams) if lesson_ids else {}
    return compute_weak_lessons(rows, titles), rows, exams


def build_improvement_payload(db: Session, student: User) -> dict[str, Any]:
    """Everything the Improvement page needs (diagnosis + practice progress)."""
    real_pairs = load_submitted_attempts(db, student.id, practice=False)
    real_percentages = [
        round(attempt.total_score / attempt.max_possible_score * 100.0, 1)
        for attempt, _ in real_pairs
        if attempt.max_possible_score and attempt.max_possible_score > 0 and attempt.total_score is not None
    ]
    level = get_student_level(db, student.id, real_percentages)
    rows = build_attempt_rows(real_pairs)
    real_exams = [exam for _, exam in real_pairs]
    lesson_ids = {str(r["lesson_id"]) for r in rows if r.get("lesson_id")}
    for row in rows:
        for entry in row["graded_answers"]:
            if isinstance(entry, dict) and entry.get("lesson_id"):
                lesson_ids.add(str(entry["lesson_id"]))
    titles = resolve_lesson_titles(db, lesson_ids, real_exams) if lesson_ids else {}
    lessons = compute_weak_lessons(rows, titles)

    for lesson in lessons:
        accuracy = lesson["accuracy_pct"] if lesson["status"] != "not_enough_data" else None
        lesson["suggested_practice"] = suggest_practice_settings(accuracy, level)
        source = resolve_practice_source(db, student, lesson["lesson_id"], verify_with_store=False)
        lesson["practice_available"] = bool(source["available"])
        lesson["practice_unavailable_reason"] = source["reason"]

    practice_pairs = load_submitted_attempts(db, student.id, practice=True)
    practice_rows = [
        {
            "attempt_id": attempt.id,
            "exam_id": exam.id,
            "lesson_id": exam.lesson_id,
            "submitted_at": attempt.submitted_at,
            "percentage": attempt_percentage(attempt),
            "difficulty": exam.difficulty,
        }
        for attempt, exam in practice_pairs
    ]
    history = summarize_practice_history(practice_rows)

    known_titles = {lesson["lesson_id"]: lesson["lesson_title"] for lesson in lessons}
    missing = {h["lesson_id"] for h in history if h["lesson_id"] not in known_titles}
    if missing:
        known_titles.update(
            resolve_lesson_titles(db, missing, real_exams + [exam for _, exam in practice_pairs])
        )
    for item in history:
        item["lesson_title"] = known_titles.get(item["lesson_id"]) or item["lesson_id"]

    return {
        "student_id": student.id,
        "student_level": level,
        "overall_accuracy": compute_overall_accuracy(rows),
        "real_attempts_count": len(rows),
        "lessons": lessons,
        "practice_history": history,
    }

