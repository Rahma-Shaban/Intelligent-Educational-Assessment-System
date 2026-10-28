"""
Student Improvement logic (pure Python, no FastAPI / DB imports).

1. compute_weak_lessons      -> per-lesson diagnosis from past graded attempts
2. suggest_practice_settings -> difficulty / Bloom level matched to the student's level
3. build_practice_topic      -> retrieval query that targets the student's gaps
4. summarize_practice_history -> per-lesson practice scores over time + trend

All functions return JSON-serializable dicts/lists so they can be returned by the API directly.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# Text stored by the frontend when the student leaves the exam screen (auto-skip)
AUTO_SKIP_TEXT = "تم التخطي تلقائياً (رصد مغادرة شاشة الاختبار)"
AUTO_SKIP_MARKER = "تم التخطي تلقائياً"

WRONG_THRESHOLD = 0.5          # correctness below this counts as a wrong answer
WEAK_THRESHOLD = 60.0          # accuracy below this -> "weak"
STRONG_THRESHOLD = 80.0        # accuracy at/above this -> "strong"
MIN_QUESTIONS_FOR_STATUS = 3   # fewer graded questions -> "not_enough_data"
TREND_DELTA = 5.0              # percentage points needed to call a trend
MAX_SAMPLE_WRONG = 3
MAX_TOPIC_LENGTH = 249         # topic must stay below 250 characters

DEFAULT_PRACTICE_TYPES = ["mcq", "short_answer"]
DEFAULT_PRACTICE_QUESTIONS = 5



# ------------------------------------------------------------------------------
# Small helpers
# ------------------------------------------------------------------------------

def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _truncate(text: Any, limit: int) -> str:
    value = str(text or "").strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _time_key(value: Any) -> str:
    """Sortable string for datetimes / ISO strings / None."""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def is_empty_or_skipped(answer: Any) -> bool:
    """Empty answers and the auto-skip text are always treated as wrong."""
    if answer is None:
        return False
    text = str(answer).strip()
    return not text or AUTO_SKIP_MARKER in text


def answer_correctness(entry: dict[str, Any]) -> tuple[float, float] | None:
    """
    Return (score, max_score) for one graded answer, or None if it cannot be used.
    Uses score/max_score (partial credit), not is_correct. Empty/skipped answers score 0.
    """
    max_score = _to_float(entry.get("max_score"), 0.0)
    if max_score <= 0:
        return None
    ans = entry.get("student_answer")
    if ans is not None and is_empty_or_skipped(ans):
        return 0.0, max_score
    score = min(max(_to_float(entry.get("score"), 0.0), 0.0), max_score)
    return score, max_score


def _status_for(accuracy: float, total_questions: int) -> str:
    if total_questions < MIN_QUESTIONS_FOR_STATUS:
        return "not_enough_data"
    if accuracy < WEAK_THRESHOLD:
        return "weak"
    if accuracy < STRONG_THRESHOLD:
        return "developing"
    return "strong"


def compute_trend(percentages: list[float]) -> str:
    """Compare the older half of attempts with the newer half (input is oldest -> newest)."""
    if len(percentages) < 2:
        return "unknown"
    middle = len(percentages) // 2
    older = percentages[:middle]
    newer = percentages[middle:]
    diff = (sum(newer) / len(newer)) - (sum(older) / len(older))
    if diff > TREND_DELTA:
        return "improving"
    if diff < -TREND_DELTA:
        return "declining"
    return "stable"


# ------------------------------------------------------------------------------
# 1. Diagnosis
# ------------------------------------------------------------------------------

def compute_weak_lessons(
    attempt_rows: list[dict[str, Any]],
    lesson_titles: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """
    Aggregate graded answers per lesson.

    attempt_rows: [{attempt_id, exam_id, lesson_id (resolved from Exam), submitted_at, graded_answers}]
    The caller must pass only REAL (non-practice) attempts.
    An answer's own "lesson_id" wins; otherwise the row's resolved lesson_id is used (legacy data).
    """
    lesson_titles = lesson_titles or {}
    lessons: dict[str, dict[str, Any]] = {}

    for row in attempt_rows or []:
        if not isinstance(row, dict):
            continue
        answers = row.get("graded_answers")
        if not isinstance(answers, list):
            continue  # malformed / missing graded_answers_json

        submitted_at = row.get("submitted_at")
        # Per-attempt totals for each lesson (used for the trend)
        per_attempt: dict[str, list[float]] = {}

        for entry in answers:
            if not isinstance(entry, dict):
                continue
            lesson_id = str(entry.get("lesson_id") or row.get("lesson_id") or "").strip()
            if not lesson_id:
                continue
            result = answer_correctness(entry)
            if result is None:
                continue
            score, max_score = result

            stats = lessons.setdefault(
                lesson_id,
                {
                    "lesson_id": lesson_id,
                    "total_questions": 0,
                    "questions_wrong": 0,
                    "score_sum": 0.0,
                    "max_sum": 0.0,
                    "attempt_ids": set(),
                    "last_attempt_key": "",
                    "last_attempt_at": None,
                    "wrong_samples": [],
                    "attempt_points": [],
                },
            )
            stats["total_questions"] += 1
            stats["score_sum"] += score
            stats["max_sum"] += max_score
            stats["attempt_ids"].add(row.get("attempt_id"))
            if _time_key(submitted_at) >= stats["last_attempt_key"]:
                stats["last_attempt_key"] = _time_key(submitted_at)
                stats["last_attempt_at"] = _iso(submitted_at)

            skipped = is_empty_or_skipped(entry.get("student_answer"))
            if skipped or (score / max_score) < WRONG_THRESHOLD:
                stats["questions_wrong"] += 1
                stats["wrong_samples"].append(
                    {
                        "time_key": _time_key(submitted_at),
                        "question": _truncate(entry.get("question"), 220),
                        "student_answer": "" if skipped else _truncate(entry.get("student_answer"), 160),
                        "skipped": skipped,
                        "question_type": entry.get("question_type"),
                        "score": round(score, 2),
                        "max_score": round(max_score, 2),
                    }
                )

            totals = per_attempt.setdefault(lesson_id, [0.0, 0.0])
            totals[0] += score
            totals[1] += max_score

        for lesson_id, (score_sum, max_sum) in per_attempt.items():
            if max_sum > 0:
                lessons[lesson_id]["attempt_points"].append(
                    (_time_key(submitted_at), score_sum / max_sum * 100.0)
                )

    results: list[dict[str, Any]] = []
    for lesson_id, stats in lessons.items():
        accuracy = (stats["score_sum"] / stats["max_sum"] * 100.0) if stats["max_sum"] > 0 else 0.0
        points = sorted(stats["attempt_points"], key=lambda p: p[0])

        # Most recent wrong questions first, without duplicate question texts
        samples: list[dict[str, Any]] = []
        seen: set[str] = set()
        for sample in sorted(stats["wrong_samples"], key=lambda s: s["time_key"], reverse=True):
            if sample["question"] in seen:
                continue
            seen.add(sample["question"])
            samples.append({k: v for k, v in sample.items() if k != "time_key"})
            if len(samples) >= MAX_SAMPLE_WRONG:
                break

        results.append(
            {
                "lesson_id": lesson_id,
                "lesson_title": lesson_titles.get(lesson_id) or lesson_id,
                "total_questions": stats["total_questions"],
                "questions_wrong": stats["questions_wrong"],
                "accuracy_pct": round(accuracy, 1),
                "attempts_count": len(stats["attempt_ids"]),
                "last_attempt_at": stats["last_attempt_at"],
                "trend": compute_trend([p[1] for p in points]),
                "status": _status_for(accuracy, stats["total_questions"]),
                "sample_wrong_questions": samples,
            }
        )

    # Weakest first; lessons without enough data go last
    results.sort(
        key=lambda item: (
            item["status"] == "not_enough_data",
            item["accuracy_pct"],
            -item["questions_wrong"],
        )
    )
    return results


def compute_overall_accuracy(attempt_rows: list[dict[str, Any]]) -> float | None:
    """Overall accuracy (sum score / sum max_score * 100) across all graded answers."""
    score_sum = 0.0
    max_sum = 0.0
    for row in attempt_rows or []:
        answers = row.get("graded_answers") if isinstance(row, dict) else None
        if not isinstance(answers, list):
            continue
        for entry in answers:
            if not isinstance(entry, dict):
                continue
            result = answer_correctness(entry)
            if result is None:
                continue
            score_sum += result[0]
            max_sum += result[1]
    if max_sum <= 0:
        return None
    return round(score_sum / max_sum * 100.0, 1)


# ------------------------------------------------------------------------------
# 2. Practice settings
# ------------------------------------------------------------------------------

def normalize_level_label(level_label: str | None) -> str | None:
    """
    Map both label families to one key:
      ML pipeline:  Needs Support / Intermediate / Advanced
      Fallback KMeans: Needs Intervention / Proficient / Advanced
    """
    text = str(level_label or "").strip().lower()
    if not text:
        return None
    if "advanced" in text:
        return "advanced"
    if "intermediate" in text or "proficient" in text:
        return "intermediate"
    if "support" in text or "intervention" in text or "risk" in text:
        return "needs_support"
    return None


def suggest_practice_settings(
    accuracy_pct: float | None,
    level_label: str | None = None,
) -> dict[str, Any]:
    """Pick difficulty and Bloom level from the student's accuracy in the lesson."""
    level = normalize_level_label(level_label)

    if accuracy_pct is None:
        # No data for this lesson yet: start in the middle
        difficulty, bloom = "medium", "understand"
    elif accuracy_pct < 50:
        difficulty, bloom = "easy", "understand"
    elif accuracy_pct < 75:
        difficulty = "medium"
        bloom = "apply" if level == "advanced" else "understand"
    else:
        difficulty, bloom = "hard", "apply"

    return {
        "difficulty": difficulty,
        "bloom_level": bloom,
        # Essay is avoided by default because every essay costs extra LLM grading calls
        "question_types": list(DEFAULT_PRACTICE_TYPES),
        "number_of_questions": DEFAULT_PRACTICE_QUESTIONS,
        "level": level,
    }


# ------------------------------------------------------------------------------
# 3. Retrieval topic
# ------------------------------------------------------------------------------

def _snippet(text: str, max_words: int = 7) -> str:
    """First few words of a question, without punctuation noise."""
    cleaned = re.sub(r"[\s\u200f\u200e]+", " ", str(text or "")).strip()
    cleaned = re.sub(r"[?؟!.:;,،\"'()\[\]{}]", " ", cleaned)
    words = [w for w in cleaned.split() if w]
    return " ".join(words[:max_words])


def build_practice_topic(lesson_title: str | None, wrong_questions: list[Any] | None) -> str:
    """
    Topic = lesson title + short snippets of the questions the student got wrong.
    It is used as the RAG retrieval query so the new questions target the student's gaps.
    """
    title = str(lesson_title or "").strip() or "Lesson practice"
    snippets: list[str] = []
    for item in wrong_questions or []:
        text = item.get("question") if isinstance(item, dict) else item
        snip = _snippet(text or "")
        if snip and snip not in snippets:
            snippets.append(snip)

    topic = title
    if snippets:
        topic = f"{title} - focus: " + "; ".join(snippets)
    if len(topic) > MAX_TOPIC_LENGTH:
        topic = topic[:MAX_TOPIC_LENGTH].rstrip(" ;-:")
    return topic


# ------------------------------------------------------------------------------
# 4. Practice progress
# ------------------------------------------------------------------------------

def summarize_practice_history(practice_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    practice_rows: [{attempt_id, exam_id, lesson_id, submitted_at, percentage, difficulty}]
    Returns per lesson the practice scores (oldest -> newest) and a trend.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in practice_rows or []:
        if not isinstance(row, dict) or row.get("percentage") is None:
            continue
        lesson_id = str(row.get("lesson_id") or "").strip()
        if not lesson_id:
            continue
        grouped.setdefault(lesson_id, []).append(row)

    history: list[dict[str, Any]] = []
    for lesson_id, rows in grouped.items():
        rows.sort(key=lambda r: _time_key(r.get("submitted_at")))
        scores = [
            {
                "attempt_id": r.get("attempt_id"),
                "exam_id": r.get("exam_id"),
                "submitted_at": _iso(r.get("submitted_at")),
                "percentage": round(_to_float(r.get("percentage")), 1),
                "difficulty": r.get("difficulty"),
            }
            for r in rows
        ]
        values = [s["percentage"] for s in scores]
        history.append(
            {
                "lesson_id": lesson_id,
                "practice_count": len(scores),
                "best_percentage": max(values),
                "latest_percentage": values[-1],
                "trend": compute_trend(values),
                "scores": scores,
            }
        )
    history.sort(key=lambda h: h["lesson_id"])
    return history
