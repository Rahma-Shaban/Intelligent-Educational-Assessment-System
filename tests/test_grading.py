import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import grading


class GradingModuleTests(unittest.TestCase):
    def test_grade_mcq_exact_letter(self):
        result = grading.grade_mcq("A", "A", max_score=1.0)
        self.assertTrue(result["is_correct"])
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["max_score"], 1.0)

    def test_grade_mcq_case_insensitive_and_stripped(self):
        result = grading.grade_mcq("  b ", "B", max_score=2.0)
        self.assertTrue(result["is_correct"])
        self.assertEqual(result["score"], 2.0)

    def test_grade_mcq_numeric_index(self):
        result = grading.grade_mcq("2", "B")
        self.assertTrue(result["is_correct"])
        self.assertEqual(result["score"], 1.0)

    def test_grade_mcq_letter_with_text(self):
        result = grading.grade_mcq("A: Supervised Learning", "A: Supervised Learning")
        self.assertTrue(result["is_correct"])

        result2 = grading.grade_mcq("A", "A: Supervised Learning")
        self.assertTrue(result2["is_correct"])

        result3 = grading.grade_mcq("Supervised Learning", "A: Supervised Learning")
        self.assertTrue(result3["is_correct"])

    def test_grade_mcq_incorrect(self):
        result = grading.grade_mcq("C", "A", max_score=1.0)
        self.assertFalse(result["is_correct"])
        self.assertEqual(result["score"], 0.0)
        self.assertIn("Incorrect", result["feedback"])

    def test_grade_mcq_empty_submission(self):
        result = grading.grade_mcq("", "A", max_score=1.0)
        self.assertFalse(result["is_correct"])
        self.assertEqual(result["score"], 0.0)
        self.assertIn("No answer provided", result["feedback"])

    def test_grade_open_ended_empty_submission_no_llm_call(self):
        rubric = [
            {"criterion": "Accuracy", "points": 2.0, "description": "Factual accuracy"},
            {"criterion": "Completeness", "points": 1.0, "description": "All parts answered"},
        ]
        result = grading.grade_open_ended(
            question_text="Explain gradient descent.",
            question_type="short_answer",
            student_answer="",
            reference_answer="An optimization algorithm.",
            rubric=rubric,
            max_score=3.0,
        )
        self.assertEqual(result["score"], 0.0)
        self.assertEqual(result["max_score"], 3.0)
        self.assertEqual(len(result["criterion_scores"]), 2)
        self.assertEqual(result["criterion_scores"][0]["score"], 0.0)
        self.assertEqual(result["weaknesses"], ["No answer provided."])

    def test_grade_open_ended_with_llm(self):
        rubric = [
            {"criterion": "Concept", "points": 2.0, "description": "Defines concept"},
            {"criterion": "Example", "points": 1.0, "description": "Provides example"},
        ]
        llm_response = {
            "criterion_scores": [
                {"criterion": "Concept", "score": 2.0, "max_score": 2.0, "feedback": "Well defined."},
                {"criterion": "Example", "score": 1.0, "max_score": 1.0, "feedback": "Good example."},
            ],
            "feedback": "Strong answer overall.",
            "strengths": ["Clear definitions", "Accurate examples"],
            "weaknesses": [],
        }

        with patch.object(grading, "_send_grading_completion", return_value=json.dumps(llm_response)):
            result = grading.grade_open_ended(
                question_text="Explain supervised learning.",
                question_type="short_answer",
                student_answer="Learning with labeled input-output pairs like spam detection.",
                reference_answer="Supervised learning trains on labeled data.",
                rubric=rubric,
                max_score=3.0,
            )

        self.assertEqual(result["score"], 3.0)
        self.assertEqual(result["max_score"], 3.0)
        self.assertEqual(len(result["criterion_scores"]), 2)
        self.assertEqual(result["feedback"], "Strong answer overall.")
        self.assertEqual(result["strengths"], ["Clear definitions", "Accurate examples"])

    def test_grade_open_ended_clamps_excessive_score(self):
        rubric = [
            {"criterion": "Accuracy", "points": 2.0, "description": "Accuracy"},
        ]
        # LLM awards 5.0 points on a 2.0 point criterion
        llm_response = {
            "criterion_scores": [
                {"criterion": "Accuracy", "score": 5.0, "max_score": 2.0, "feedback": "Superb"},
            ],
            "feedback": "Excellent",
            "strengths": ["High accuracy"],
            "weaknesses": [],
        }

        with patch.object(grading, "_send_grading_completion", return_value=json.dumps(llm_response)):
            result = grading.grade_open_ended(
                question_text="What is AI?",
                question_type="short_answer",
                student_answer="AI is artificial intelligence.",
                reference_answer="AI is...",
                rubric=rubric,
                max_score=2.0,
            )

        self.assertEqual(result["score"], 2.0)
        self.assertEqual(result["criterion_scores"][0]["score"], 2.0)

    def test_grade_open_ended_handles_fenced_json(self):
        rubric = [{"criterion": "Main Idea", "points": 1.0, "description": "Core idea"}]
        llm_response = {
            "criterion_scores": [{"criterion": "Main Idea", "score": 1.0, "max_score": 1.0, "feedback": "Correct"}],
            "feedback": "Good",
            "strengths": [],
            "weaknesses": [],
        }
        fenced_output = f"```json\n{json.dumps(llm_response)}\n```"

        with patch.object(grading, "_send_grading_completion", return_value=fenced_output):
            result = grading.grade_open_ended(
                question_text="Q?",
                question_type="short_answer",
                student_answer="Ans",
                reference_answer="Ref",
                rubric=rubric,
                max_score=1.0,
            )

        self.assertEqual(result["score"], 1.0)

    def test_grade_open_ended_retries_malformed_json(self):
        rubric = [{"criterion": "Accuracy", "points": 1.0, "description": "Accuracy"}]
        valid_response = {
            "criterion_scores": [{"criterion": "Accuracy", "score": 1.0, "max_score": 1.0, "feedback": "OK"}],
            "feedback": "OK",
            "strengths": [],
            "weaknesses": [],
        }
        with patch.object(
            grading,
            "_send_grading_completion",
            side_effect=["{not valid json", json.dumps(valid_response)],
        ) as mock_send:
            result = grading.grade_open_ended(
                question_text="Q?",
                question_type="short_answer",
                student_answer="Ans",
                reference_answer="Ref",
                rubric=rubric,
                max_score=1.0,
            )

        self.assertEqual(result["score"], 1.0)
        self.assertEqual(mock_send.call_count, 2)

    def test_grade_exam_submission_full_workflow(self):
        exam = {
            "lesson_id": "1-1",
            "total_points": 4.0,
            "questions": [
                {
                    "question_id": "Q01",
                    "question_type": "mcq",
                    "question": "What is Python?",
                    "correct_answer": "B",
                    "max_score": 1.0,
                    "topic": "Programming",
                },
                {
                    "question_id": "Q02",
                    "question_type": "short_answer",
                    "question": "Explain recursion.",
                    "reference_answer": "A function calling itself.",
                    "rubric": [{"criterion": "Definition", "points": 3.0, "description": "Defines recursion"}],
                    "max_score": 3.0,
                    "topic": "Algorithms",
                },
            ],
        }

        student_answers = {
            "Q01": "B",
            "Q02": "A function that calls itself with a base condition.",
        }

        llm_q2 = {
            "criterion_scores": [{"criterion": "Definition", "score": 3.0, "max_score": 3.0, "feedback": "Accurate"}],
            "feedback": "Complete answer.",
            "strengths": ["Identified base condition"],
            "weaknesses": [],
        }

        with patch.object(grading, "_send_grading_completion", return_value=json.dumps(llm_q2)):
            submission_result = grading.grade_exam_submission(exam, student_answers)

        self.assertEqual(submission_result["total_score"], 4.0)
        self.assertEqual(submission_result["max_possible_score"], 4.0)
        self.assertEqual(submission_result["percentage"], 100.0)
        self.assertEqual(len(submission_result["graded_answers"]), 2)
        self.assertTrue(submission_result["graded_answers"][0]["is_correct"])
        self.assertEqual(submission_result["graded_answers"][0]["lesson_id"], "1-1")
        self.assertEqual(submission_result["graded_answers"][1]["lesson_id"], "1-1")
        self.assertEqual(submission_result["graded_answers"][1]["score"], 3.0)


if __name__ == "__main__":
    unittest.main()
