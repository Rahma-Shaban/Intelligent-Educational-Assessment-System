"""
Unit tests for scripts/improvement.py logic.
Tests:
- compute_weak_lessons:
  - statuses: weak (<60%), developing (60-80%), strong (>=80%), not_enough_data (<3 questions)
  - empty and auto-skipped answers counted wrong
  - partial credit via score/max_score
  - trend calculation (improving, declining, stable, unknown)
  - sorting (weakest first, not_enough_data last)
  - legacy rows where answers lack lesson_id (resolved from row lesson_id)
  - sample wrong questions capped at 3 and deduplicated
- suggest_practice_settings:
  - all label variants: "Needs Support", "Needs Intervention", "Intermediate", "Proficient", "Advanced"
  - accuracy tiers (<50, 50-75, >=75, None)
- build_practice_topic:
  - length strictly limited to < 250 characters
  - focuses on wrong question snippets
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from scripts.improvement import (
    AUTO_SKIP_TEXT,
    build_practice_topic,
    compute_trend,
    compute_weak_lessons,
    normalize_level_label,
    suggest_practice_settings,
)


class TestImprovementLogic(unittest.TestCase):
    def test_status_and_accuracy_categories(self):
        """Verify weak (<60), developing (60-80), strong (>=80), and not_enough_data (<3)."""
        now = datetime.now(timezone.utc)

        # Lesson 1: 4 questions, 1/4 correct (25%) -> weak
        # Lesson 2: 4 questions, 3/4 correct (75%) -> developing
        # Lesson 3: 4 questions, 4/4 correct (100%) -> strong
        # Lesson 4: 2 questions, 0/2 correct (0%) -> not_enough_data (fewer than 3 questions)
        rows = [
            {
                "attempt_id": 1,
                "exam_id": 101,
                "lesson_id": "L1",
                "submitted_at": now.isoformat(),
                "graded_answers": [
                    {"question_id": "Q1", "lesson_id": "L1", "score": 1.0, "max_score": 1.0, "question": "Q1 text"},
                    {"question_id": "Q2", "lesson_id": "L1", "score": 0.0, "max_score": 1.0, "question": "Q2 text"},
                    {"question_id": "Q3", "lesson_id": "L1", "score": 0.0, "max_score": 1.0, "question": "Q3 text"},
                    {"question_id": "Q4", "lesson_id": "L1", "score": 0.0, "max_score": 1.0, "question": "Q4 text"},
                    {"question_id": "Q5", "lesson_id": "L2", "score": 1.0, "max_score": 1.0, "question": "Q5 text"},
                    {"question_id": "Q6", "lesson_id": "L2", "score": 1.0, "max_score": 1.0, "question": "Q6 text"},
                    {"question_id": "Q7", "lesson_id": "L2", "score": 1.0, "max_score": 1.0, "question": "Q7 text"},
                    {"question_id": "Q8", "lesson_id": "L2", "score": 0.0, "max_score": 1.0, "question": "Q8 text"},
                    {"question_id": "Q9", "lesson_id": "L3", "score": 1.0, "max_score": 1.0, "question": "Q9 text"},
                    {"question_id": "Q10", "lesson_id": "L3", "score": 1.0, "max_score": 1.0, "question": "Q10 text"},
                    {"question_id": "Q11", "lesson_id": "L3", "score": 1.0, "max_score": 1.0, "question": "Q11 text"},
                    {"question_id": "Q12", "lesson_id": "L3", "score": 1.0, "max_score": 1.0, "question": "Q12 text"},
                    {"question_id": "Q13", "lesson_id": "L4", "score": 0.0, "max_score": 1.0, "question": "Q13 text"},
                    {"question_id": "Q14", "lesson_id": "L4", "score": 0.0, "max_score": 1.0, "question": "Q14 text"},
                ],
            }
        ]

        titles = {"L1": "Lesson One", "L2": "Lesson Two", "L3": "Lesson Three", "L4": "Lesson Four"}
        results = compute_weak_lessons(rows, lesson_titles=titles)

        by_id = {r["lesson_id"]: r for r in results}
        self.assertEqual(by_id["L1"]["status"], "weak")
        self.assertEqual(by_id["L1"]["accuracy_pct"], 25.0)
        self.assertEqual(by_id["L1"]["questions_wrong"], 3)

        self.assertEqual(by_id["L2"]["status"], "developing")
        self.assertEqual(by_id["L2"]["accuracy_pct"], 75.0)

        self.assertEqual(by_id["L3"]["status"], "strong")
        self.assertEqual(by_id["L3"]["accuracy_pct"], 100.0)

        self.assertEqual(by_id["L4"]["status"], "not_enough_data")

        # Sorting: weakest first (L1), then developing (L2), then strong (L3), not_enough_data last (L4)
        order = [r["lesson_id"] for r in results]
        self.assertEqual(order, ["L1", "L2", "L3", "L4"])

    def test_empty_and_autoskipped_answers_counted_wrong(self):
        """Empty answers or auto-skip marker must count as wrong and give 0 score."""
        rows = [
            {
                "attempt_id": 1,
                "exam_id": 1,
                "lesson_id": "L1",
                "submitted_at": "2026-10-20T10:00:00Z",
                "graded_answers": [
                    # Empty answer
                    {"question_id": "Q1", "student_answer": "", "score": 0.0, "max_score": 2.0, "question": "Prompt 1"},
                    # Whitespace answer
                    {"question_id": "Q2", "student_answer": "   ", "score": 0.0, "max_score": 2.0, "question": "Prompt 2"},
                    # Auto-skipped text
                    {"question_id": "Q3", "student_answer": AUTO_SKIP_TEXT, "score": 0.0, "max_score": 2.0, "question": "Prompt 3"},
                ],
            }
        ]
        results = compute_weak_lessons(rows)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["questions_wrong"], 3)
        self.assertEqual(r["accuracy_pct"], 0.0)
        self.assertEqual(r["status"], "weak")

    def test_partial_credit_open_ended(self):
        """Correctness uses score / max_score (partial credit), not boolean is_correct."""
        rows = [
            {
                "attempt_id": 1,
                "exam_id": 1,
                "lesson_id": "L1",
                "submitted_at": "2026-10-20T10:00:00Z",
                "graded_answers": [
                    # 1.5 / 2.0 = 75% -> correctness >= 0.5, so not counted as wrong
                    {"question_id": "Q1", "student_answer": "Good partial", "score": 1.5, "max_score": 2.0, "question": "Q1"},
                    # 0.5 / 2.0 = 25% -> correctness < 0.5, counted as wrong
                    {"question_id": "Q2", "student_answer": "Weak partial", "score": 0.5, "max_score": 2.0, "question": "Q2"},
                    # 2.0 / 2.0 = 100% -> full credit
                    {"question_id": "Q3", "student_answer": "Perfect", "score": 2.0, "max_score": 2.0, "question": "Q3"},
                ],
            }
        ]
        results = compute_weak_lessons(rows)
        r = results[0]
        # Total score: 1.5 + 0.5 + 2.0 = 4.0 / 6.0 = 66.7%
        self.assertEqual(r["accuracy_pct"], 66.7)
        self.assertEqual(r["status"], "developing")
        self.assertEqual(r["questions_wrong"], 1)  # Only Q2 (< 0.5)

    def test_legacy_rows_fallback_to_exam_lesson_id(self):
        """Old attempts where individual answers lack lesson_id fall back to the row's lesson_id."""
        rows = [
            {
                "attempt_id": 99,
                "exam_id": 42,
                "lesson_id": "legacy-2-1",
                "submitted_at": "2026-10-15T12:00:00Z",
                "graded_answers": [
                    {"question_id": "Q1", "score": 1.0, "max_score": 1.0, "question": "Old question 1"},
                    {"question_id": "Q2", "score": 1.0, "max_score": 1.0, "question": "Old question 2"},
                    {"question_id": "Q3", "score": 1.0, "max_score": 1.0, "question": "Old question 3"},
                ],
            }
        ]
        results = compute_weak_lessons(rows)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["lesson_id"], "legacy-2-1")
        self.assertEqual(results[0]["accuracy_pct"], 100.0)
        self.assertEqual(results[0]["status"], "strong")

    def test_trend_calculation(self):
        """Test compute_trend for improving, declining, stable, unknown."""
        # < 2 attempts -> unknown
        self.assertEqual(compute_trend([]), "unknown")
        self.assertEqual(compute_trend([50.0]), "unknown")

        # Improving: older [40.0], newer [80.0] -> diff +40 (> 5.0)
        self.assertEqual(compute_trend([40.0, 80.0]), "improving")
        self.assertEqual(compute_trend([30.0, 40.0, 70.0, 85.0]), "improving")

        # Declining: older [85.0, 80.0], newer [40.0, 30.0]
        self.assertEqual(compute_trend([85.0, 80.0, 40.0, 30.0]), "declining")

        # Stable: older [70.0], newer [72.0] -> diff 2 (within +-5)
        self.assertEqual(compute_trend([70.0, 72.0]), "stable")

    def test_suggest_practice_settings_all_labels(self):
        """Test suggest_practice_settings across accuracy brackets and label variants."""
        # Bracket 1: accuracy < 50 -> easy, understand
        s1 = suggest_practice_settings(35.0, "Needs Support")
        self.assertEqual(s1["difficulty"], "easy")
        self.assertEqual(s1["bloom_level"], "understand")

        s1_fallback = suggest_practice_settings(45.0, "Needs Intervention")
        self.assertEqual(s1_fallback["difficulty"], "easy")
        self.assertEqual(s1_fallback["bloom_level"], "understand")

        # Bracket 2: 50 <= accuracy < 75 -> medium, understand (or apply for Advanced)
        s2_mid = suggest_practice_settings(60.0, "Intermediate")
        self.assertEqual(s2_mid["difficulty"], "medium")
        self.assertEqual(s2_mid["bloom_level"], "understand")

        s2_proficient = suggest_practice_settings(65.0, "Proficient")
        self.assertEqual(s2_proficient["difficulty"], "medium")
        self.assertEqual(s2_proficient["bloom_level"], "understand")

        s2_adv = suggest_practice_settings(70.0, "Advanced")
        self.assertEqual(s2_adv["difficulty"], "medium")
        self.assertEqual(s2_adv["bloom_level"], "apply")

        # Bracket 3: accuracy >= 75 -> hard, apply
        s3 = suggest_practice_settings(85.0, "Intermediate")
        self.assertEqual(s3["difficulty"], "hard")
        self.assertEqual(s3["bloom_level"], "apply")

        # None (no attempts yet) -> medium, understand
        s_none = suggest_practice_settings(None, None)
        self.assertEqual(s_none["difficulty"], "medium")
        self.assertEqual(s_none["bloom_level"], "understand")

    def test_build_practice_topic_length_limit(self):
        """build_practice_topic must always be strictly below 250 characters."""
        long_title = "A" * 200
        wrong_questions = [
            {"question": "What is the computational complexity of nested loop vectorization in dense graph algorithms?"},
            {"question": "Explain gradient descent backpropagation with Adam optimizer momentum terms in deep learning."},
            {"question": "How does cache coherence protocol handle simultaneous cache line invalidation in multicore SMP?"},
        ]
        topic = build_practice_topic(long_title, wrong_questions)
        self.assertLess(len(topic), 250)
        self.assertTrue(topic.startswith(long_title[:100]))

    def test_sample_wrong_questions_capped_at_three(self):
        """Only up to 3 distinct wrong questions should be preserved in sample_wrong_questions."""
        now = datetime.now(timezone.utc)
        rows = [
            {
                "attempt_id": 1,
                "exam_id": 1,
                "lesson_id": "L1",
                "submitted_at": now.isoformat(),
                "graded_answers": [
                    {"question_id": f"Q{i}", "score": 0.0, "max_score": 1.0, "question": f"Wrong Question #{i}"}
                    for i in range(10)
                ],
            }
        ]
        results = compute_weak_lessons(rows)
        self.assertEqual(len(results), 1)
        self.assertLessEqual(len(results[0]["sample_wrong_questions"]), 3)


if __name__ == "__main__":
    unittest.main()

