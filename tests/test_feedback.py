import json
import unittest
from unittest.mock import patch

from scripts import feedback


class FeedbackModuleTests(unittest.TestCase):
    def test_generate_student_feedback_success(self):
        attempts = [
            {
                "student_id": "S01",
                "percentage": 85.0,
                "duration": 600,
                "topic": "Supervised Learning",
                "graded_answers": [
                    {
                        "strengths": ["Clear classification intuition"],
                        "weaknesses": ["Minor confusion on regularization"],
                    }
                ],
            }
        ]

        llm_output = {
            "summary": "Alice has demonstrated solid proficiency with strong conceptual grasp of classification.",
            "strengths": ["Accurate classification intuition", "Good understanding of loss functions"],
            "weaknesses": ["Needs practice with L1/L2 regularization math"],
            "recommendations": [
                "Review regularization derivations",
                "Work on practical scikit-learn coding exercises",
            ],
            "study_plan": "Week 1: Regularization theory. Week 2: Model evaluation metrics.",
        }

        with patch.object(feedback, "_send_feedback_completion", return_value=json.dumps(llm_output)):
            result = feedback.generate_student_feedback(
                student_name="Alice",
                attempts=attempts,
                cluster_label="Proficient",
            )

        self.assertEqual(result["cluster_label"], "Proficient")
        self.assertIn("Alice", result["summary"])
        self.assertEqual(len(result["strengths"]), 2)
        self.assertEqual(len(result["weaknesses"]), 1)
        self.assertEqual(len(result["recommendations"]), 2)
        self.assertIn("Week 1", result["study_plan"])

    def test_generate_student_feedback_retries_malformed_json(self):
        attempts = [{"student_id": "S02", "percentage": 95.0}]
        valid_output = {
            "summary": "Excellent work by Bob.",
            "strengths": ["Fast problem solving"],
            "weaknesses": [],
            "recommendations": ["Explore advanced topics"],
            "study_plan": "Continue current study routine.",
        }

        with patch.object(
            feedback,
            "_send_feedback_completion",
            side_effect=["not valid json", json.dumps(valid_output)],
        ) as mock_send:
            result = feedback.generate_student_feedback(
                student_name="Bob",
                attempts=attempts,
                cluster_label="Advanced",
            )

        self.assertEqual(result["summary"], "Excellent work by Bob.")
        self.assertEqual(mock_send.call_count, 2)

    def test_generate_class_summary_success(self):
        class_analytics = {
            "total_students": 10,
            "total_attempts": 20,
            "avg_score_pct": 74.5,
            "score_distribution": {"0-20": 0, "21-40": 1, "41-60": 2, "61-80": 4, "81-100": 3},
            "topic_performance": {"Neural Networks": 65.0, "Decision Trees": 84.0},
            "difficulty_breakdown": {"easy": 88.0, "medium": 72.0, "hard": 55.0},
        }

        cluster_results = {
            "clusters": [
                {"student_id": "S01", "cluster": 0, "label": "Advanced"},
                {"student_id": "S02", "cluster": 1, "label": "Proficient"},
                {"student_id": "S03", "cluster": 2, "label": "Needs Intervention"},
            ],
            "labels": ["Advanced", "Proficient", "Needs Intervention"],
        }

        llm_output = {
            "overall_assessment": "The cohort exhibits healthy engagement with standout performance on decision trees.",
            "key_findings": [
                "Students struggle with hard neural network questions.",
                "High variance between basic syntax and architectural design.",
            ],
            "topic_recommendations": {
                "Neural Networks": "Dedicate a lab session to backpropagation derivations."
            },
            "intervention_needed": ["S03"],
            "class_strengths": ["Strong foundational knowledge in decision trees"],
        }

        with patch.object(feedback, "_send_feedback_completion", return_value=json.dumps(llm_output)):
            result = feedback.generate_class_summary(
                class_analytics=class_analytics,
                cluster_results=cluster_results,
            )

        self.assertIn("cohort exhibits", result["overall_assessment"])
        self.assertEqual(len(result["key_findings"]), 2)
        self.assertIn("Neural Networks", result["topic_recommendations"])
        self.assertIn("S03", result["intervention_needed"])
        self.assertEqual(result["class_strengths"], ["Strong foundational knowledge in decision trees"])

    def test_generate_class_summary_preserves_intervention_cluster_students(self):
        class_analytics = {"total_students": 2, "avg_score_pct": 50.0}
        cluster_results = {
            "clusters": [
                {"student_id": "ST_HELP_1", "label": "Needs Intervention"},
                {"student_id": "ST_HELP_2", "label": "Needs Intervention"},
            ]
        }
        # LLM misses ST_HELP_2 in its response
        llm_output = {
            "overall_assessment": "Needs help.",
            "key_findings": ["Low scores"],
            "topic_recommendations": {},
            "intervention_needed": ["ST_HELP_1"],
            "class_strengths": [],
        }

        with patch.object(feedback, "_send_feedback_completion", return_value=json.dumps(llm_output)):
            result = feedback.generate_class_summary(class_analytics, cluster_results)

        # Both ST_HELP_1 and ST_HELP_2 must be present in intervention_needed
        self.assertIn("ST_HELP_1", result["intervention_needed"])
        self.assertIn("ST_HELP_2", result["intervention_needed"])


if __name__ == "__main__":
    unittest.main()
