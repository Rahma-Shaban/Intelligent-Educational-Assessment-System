"""
Comprehensive Unit Tests for Question Analysis Module.

Tests Stage 2 capabilities:
  - All six Bloom taxonomy levels (remember, understand, apply, analyze, evaluate, create)
  - All three difficulty levels (easy, medium, hard)
  - Grounded learning objective derivation vs. unresolved missing context
  - Preservation of verified human metadata, IDs, options, and answers
  - Separation between question format (MCQ/Essay) and cognitive level
  - Review flagging on low confidence, unresolved objectives, or ingestion warnings
  - Output schema validation, malformed model response retries, and provider error handling
  - Zero paid API calls (all LLM completions strictly mocked)
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts import question_analysis as qa


def make_canonical_question(
    qid: str = "Q-001",
    qtype: str = "mcq",
    qtext: str = "What is Moore's Law?",
    options: list[str] | None = None,
    correct_opt: str = "A",
    correct_ans: str = "Transistor density doubles every 2 years.",
    chapter: str = "Unit 1",
    lesson: str = "Lesson 1-1",
    status: str = "Unverified",
    bloom: str | None = None,
    difficulty: str | None = None,
) -> dict:
    return {
        "question_id": qid,
        "original_question_id": f"ORIG-{qid}",
        "question_type": qtype,
        "question_text": qtext,
        "options": options or ["Transistor density doubles every 2 years.", "Opt B", "Opt C", "Opt D"],
        "correct_option": correct_opt if qtype == "mcq" else None,
        "correct_answer": correct_ans,
        "chapter": chapter,
        "lesson": lesson,
        "page_number": 4,
        "source_file": "textbook.pdf",
        "answer_source": "Book Content",
        "verification_status": status,
        "source_metadata": {"edition": 2},
        "validation_warnings": [],
        "bloom_level": bloom,
        "difficulty": difficulty,
    }


class QuestionAnalysisBloomAndDifficultyTests(unittest.TestCase):
    """Tests classification for all 6 Bloom levels and 3 difficulty tiers."""

    def test_classify_all_six_bloom_levels(self):
        bloom_levels = ["remember", "understand", "apply", "analyze", "evaluate", "create"]
        for bloom in bloom_levels:
            with self.subTest(bloom=bloom):
                mock_response = {
                    "bloom_level": bloom,
                    "difficulty": "medium",
                    "learning_objective": f"The student will be able to demonstrate {bloom} level competency.",
                    "learning_objective_grounded": True,
                    "classification_reasoning": f"Tests cognitive domain of {bloom}.",
                    "confidence": 0.90,
                }
                with patch.object(qa, "_send_analysis_completion", return_value=json.dumps(mock_response)):
                    q = make_canonical_question()
                    res = qa.analyze_single_question(q, curriculum_context="Lesson context on computing.")

                self.assertEqual(res.bloom_level, bloom)
                self.assertEqual(res.difficulty, "medium")
                self.assertTrue(res.learning_objective_grounded)
                self.assertFalse(res.needs_teacher_review)

    def test_classify_all_difficulty_levels(self):
        difficulties = ["easy", "medium", "hard"]
        for diff in difficulties:
            with self.subTest(difficulty=diff):
                mock_response = {
                    "bloom_level": "apply",
                    "difficulty": diff,
                    "learning_objective": "The student will be able to apply algorithms.",
                    "learning_objective_grounded": True,
                    "classification_reasoning": f"Cognitive complexity calibrated as {diff}.",
                    "confidence": 0.85,
                }
                with patch.object(qa, "_send_analysis_completion", return_value=json.dumps(mock_response)):
                    q = make_canonical_question()
                    res = qa.analyze_single_question(q, curriculum_context="Algorithm analysis context.")

                self.assertEqual(res.difficulty, diff)
                self.assertEqual(res.bloom_level, "apply")


class LearningObjectiveAndGroundingTests(unittest.TestCase):
    """Tests curriculum context grounding and unresolved objective marking."""

    def test_learning_objective_grounded_when_context_available(self):
        mock_response = {
            "bloom_level": "understand",
            "difficulty": "easy",
            "learning_objective": "The student will be able to explain the exponential trend of Moore's Law.",
            "learning_objective_grounded": True,
            "classification_reasoning": "Identifies standard definition from lesson 1-1.",
            "confidence": 0.92,
        }
        with patch.object(qa, "_send_analysis_completion", return_value=json.dumps(mock_response)):
            q = make_canonical_question(chapter="Unit 1", lesson="Lesson 1-1")
            res = qa.analyze_single_question(q, curriculum_context="Transistor counts roughly double every 24 months.")

        self.assertEqual(
            res.learning_objective,
            "The student will be able to explain the exponential trend of Moore's Law.",
        )
        self.assertTrue(res.learning_objective_grounded)
        self.assertFalse(res.needs_teacher_review)

    def test_learning_objective_unresolved_when_context_missing(self):
        # When context is missing, model returns null and false
        mock_response = {
            "bloom_level": "understand",
            "difficulty": "medium",
            "learning_objective": None,
            "learning_objective_grounded": False,
            "classification_reasoning": "Sufficient curriculum context is unavailable to ground specific objective.",
            "confidence": 0.85,
        }
        with patch.object(qa, "_send_analysis_completion", return_value=json.dumps(mock_response)):
            q = make_canonical_question(chapter=None, lesson=None)
            res = qa.analyze_single_question(q, curriculum_context=None)

        self.assertIsNone(res.learning_objective)
        self.assertFalse(res.learning_objective_grounded)
        # Missing grounded objective must automatically flag review
        self.assertTrue(res.needs_teacher_review)
        self.assertTrue(any("Learning objective could not be grounded" in r for r in res.review_reasons))


class MetadataPreservationAndReviewFlagsTests(unittest.TestCase):
    """Tests preservation of original question data and review flag triggers."""

    def test_preserves_verified_human_metadata_without_llm_call(self):
        q = make_canonical_question(
            status="Verified from Source",
            bloom="evaluate",
            difficulty="hard",
        )
        q["learning_objective"] = "Existing verified objective."
        q["classification_reasoning"] = "Human expert certified."

        # Should NOT invoke LLM when verified source metadata is already present
        with patch.object(qa, "_send_analysis_completion") as mock_llm:
            res = qa.analyze_single_question(q, override_verified=False)
            mock_llm.assert_not_called()

        self.assertEqual(res.bloom_level, "evaluate")
        self.assertEqual(res.difficulty, "hard")
        self.assertEqual(res.learning_objective, "Existing verified objective.")
        self.assertEqual(res.confidence, 1.0)
        self.assertFalse(res.needs_teacher_review)

    def test_preserves_original_ids_options_and_answers(self):
        mock_response = {
            "bloom_level": "analyze",
            "difficulty": "hard",
            "learning_objective": "The student will be able to compare memory hierarchies.",
            "learning_objective_grounded": True,
            "classification_reasoning": "Requires analytical distinction between cache levels.",
            "confidence": 0.88,
        }
        with patch.object(qa, "_send_analysis_completion", return_value=json.dumps(mock_response)):
            q = make_canonical_question(
                qid="Q-999",
                qtype="mcq",
                qtext="Which cache level provides lowest latency?",
                options=["L1 Cache", "L2 Cache", "L3 Cache", "DRAM"],
                correct_opt="A",
                correct_ans="L1 Cache",
            )
            res = qa.analyze_single_question(q)

        # Integrity check: original question components must remain pristine
        self.assertEqual(res.question_id, "Q-999")
        self.assertEqual(res.original_question_id, "ORIG-Q-999")
        self.assertEqual(res.question_type, "mcq")
        self.assertEqual(res.question_text, "Which cache level provides lowest latency?")
        self.assertEqual(res.options, ["L1 Cache", "L2 Cache", "L3 Cache", "DRAM"])
        self.assertEqual(res.correct_option, "A")
        self.assertEqual(res.correct_answer, "L1 Cache")

    def test_low_confidence_triggers_teacher_review_flag(self):
        mock_response = {
            "bloom_level": "apply",
            "difficulty": "medium",
            "learning_objective": "The student will be able to calculate metrics.",
            "learning_objective_grounded": True,
            "classification_reasoning": "Borderline between understand and apply.",
            "confidence": 0.65,  # Below 0.75 threshold
        }
        with patch.object(qa, "_send_analysis_completion", return_value=json.dumps(mock_response)):
            q = make_canonical_question()
            res = qa.analyze_single_question(q)

        self.assertTrue(res.needs_teacher_review)
        self.assertTrue(any("Low classification confidence" in r for r in res.review_reasons))

    def test_ingestion_warnings_trigger_teacher_review_flag(self):
        mock_response = {
            "bloom_level": "understand",
            "difficulty": "easy",
            "learning_objective": "The student will be able to understand terminology.",
            "learning_objective_grounded": True,
            "classification_reasoning": "Direct conceptual explanation.",
            "confidence": 0.95,
        }
        with patch.object(qa, "_send_analysis_completion", return_value=json.dumps(mock_response)):
            q = make_canonical_question()
            q["validation_warnings"] = ["Potential normalized duplicate of question 'Q-001'."]
            res = qa.analyze_single_question(q)

        self.assertTrue(res.needs_teacher_review)
        self.assertTrue(any("ingestion validation warnings" in r for r in res.review_reasons))


class OutputSchemaValidationAndErrorHandlingTests(unittest.TestCase):
    """Tests model output schema validation, malformed response recovery, and provider errors."""

    def test_recovers_from_fenced_markdown_json(self):
        valid_data = {
            "bloom_level": "remember",
            "difficulty": "easy",
            "learning_objective": "The student will be able to recall facts.",
            "learning_objective_grounded": True,
            "classification_reasoning": "Basic recall item.",
            "confidence": 0.90,
        }
        fenced_output = f"```json\n{json.dumps(valid_data)}\n```"

        with patch.object(qa, "_send_analysis_completion", return_value=fenced_output):
            q = make_canonical_question()
            res = qa.analyze_single_question(q)

        self.assertEqual(res.bloom_level, "remember")
        self.assertEqual(res.difficulty, "easy")

    def test_retries_on_malformed_json_and_succeeds(self):
        valid_data = {
            "bloom_level": "create",
            "difficulty": "hard",
            "learning_objective": "The student will be able to design a neural network architecture.",
            "learning_objective_grounded": True,
            "classification_reasoning": "Demands original architectural synthesis.",
            "confidence": 0.88,
        }
        with patch.object(
            qa,
            "_send_analysis_completion",
            side_effect=["{invalid json here...", json.dumps(valid_data)],
        ) as mock_send:
            q = make_canonical_question()
            res = qa.analyze_single_question(q)

        self.assertEqual(res.bloom_level, "create")
        self.assertEqual(mock_send.call_count, 2)

    def test_retries_on_invalid_schema_and_succeeds(self):
        invalid_data = {
            "bloom_level": "invalid_bloom_tier",  # Violates schema
            "difficulty": "super_hard",           # Violates schema
            "classification_reasoning": "None",
            "confidence": 1.5,                    # Out of [0, 1] range
        }
        valid_data = {
            "bloom_level": "analyze",
            "difficulty": "medium",
            "learning_objective": "The student will be able to analyze data distributions.",
            "learning_objective_grounded": True,
            "classification_reasoning": "Valid breakdown of data.",
            "confidence": 0.85,
        }
        with patch.object(
            qa,
            "_send_analysis_completion",
            side_effect=[json.dumps(invalid_data), json.dumps(valid_data)],
        ) as mock_send:
            q = make_canonical_question()
            res = qa.analyze_single_question(q)

        self.assertEqual(res.bloom_level, "analyze")
        self.assertEqual(res.difficulty, "medium")
        self.assertEqual(mock_send.call_count, 2)

    def test_provider_error_raises_clear_runtime_error(self):
        with (
            patch.object(qa, "_send_analysis_completion", side_effect=ConnectionError("Connection timed out")),
            self.assertRaises(RuntimeError) as ctx,
        ):
            q = make_canonical_question()
            qa.analyze_single_question(q, max_retries=1)

        self.assertIn("Connection timed out", str(ctx.exception))


class BatchAnalysisTests(unittest.TestCase):
    """Tests batch analysis with mixed success and partial failure tolerance."""

    def test_batch_analysis_full_workflow(self):
        q1 = make_canonical_question(qid="Q-01", qtext="Define supervised learning.")
        q2 = make_canonical_question(qid="Q-02", qtext="Explain gradient descent.", qtype="essay")

        resp1 = {
            "bloom_level": "remember",
            "difficulty": "easy",
            "learning_objective": "The student will be able to define supervised learning.",
            "learning_objective_grounded": True,
            "classification_reasoning": "Definitional recall.",
            "confidence": 0.95,
        }
        resp2 = {
            "bloom_level": "understand",
            "difficulty": "medium",
            "learning_objective": "The student will be able to explain gradient descent optimization.",
            "learning_objective_grounded": True,
            "classification_reasoning": "Requires algorithmic explanation.",
            "confidence": 0.85,
        }

        with patch.object(qa, "_send_analysis_completion", side_effect=[json.dumps(resp1), json.dumps(resp2)]):
            batch_res = qa.analyze_questions_batch([q1, q2])

        self.assertEqual(batch_res.total_questions, 2)
        self.assertEqual(batch_res.analyzed_count, 2)
        self.assertEqual(batch_res.failed_count, 0)
        self.assertEqual(batch_res.summary["bloom_distribution"]["remember"], 1)
        self.assertEqual(batch_res.summary["bloom_distribution"]["understand"], 1)
        self.assertEqual(batch_res.summary["difficulty_distribution"]["easy"], 1)
        self.assertEqual(batch_res.summary["difficulty_distribution"]["medium"], 1)

    def test_batch_analysis_handles_individual_failures_without_aborting(self):
        q1 = make_canonical_question(qid="Q-01", qtext="Valid question 1.")
        q2 = make_canonical_question(qid="Q-02", qtext="Failed question 2.")
        q3 = make_canonical_question(qid="Q-03", qtext="Valid question 3.")

        valid_resp = {
            "bloom_level": "apply",
            "difficulty": "medium",
            "learning_objective": "The student will be able to apply concepts.",
            "learning_objective_grounded": True,
            "classification_reasoning": "Standard application.",
            "confidence": 0.90,
        }

        with patch.object(
            qa,
            "_send_analysis_completion",
            side_effect=[
                json.dumps(valid_resp),                     # Q-01 attempt 1 (success)
                RuntimeError("Model quota exceeded"),       # Q-02 attempt 1 (fails)
                RuntimeError("Model quota exceeded"),       # Q-02 attempt 2 (fails permanently)
                json.dumps(valid_resp),                     # Q-03 attempt 1 (success)
            ],
        ):
            batch_res = qa.analyze_questions_batch([q1, q2, q3], allow_partial=True)

        self.assertEqual(batch_res.total_questions, 3)
        self.assertEqual(batch_res.analyzed_count, 2)
        self.assertEqual(batch_res.failed_count, 1)
        self.assertEqual(batch_res.failed_records[0]["question_id"], "Q-02")
        self.assertIn("Model quota exceeded", batch_res.failed_records[0]["error"])
        self.assertAlmostEqual(batch_res.summary["success_rate"], 2 / 3, places=2)


if __name__ == "__main__":
    unittest.main()
