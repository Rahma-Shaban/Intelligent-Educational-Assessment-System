"""
Unit tests for the RAG Evaluation and Observability Module (scripts/evaluation.py).

All tests run completely offline and do not require live external API calls or credentials.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd

from scripts.evaluation import (
    aggregate_evaluation_results,
    generate_grounded_answer,
    load_and_validate_dataset,
    mask_credential,
    retrieve_contexts,
    run_rag_batch,
    run_rag_pipeline_for_case,
    save_evaluation_outputs,
    validate_eval_environment,
)


class TestEvaluationModule(unittest.TestCase):
    """Test suite for RAG evaluation utilities."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    # 1. Credential Masking & Secret Leak Prevention
    def test_mask_credential(self):
        self.assertEqual(mask_credential(None), "[NOT SET]")
        self.assertEqual(mask_credential(""), "[NOT SET]")
        self.assertEqual(mask_credential("123"), "[CONFIGURED]")
        self.assertEqual(mask_credential("gsk_secret_key_12345"), "*" * 16 + "2345")

    def test_validate_eval_environment_masks_keys(self):
        with patch.dict(os.environ, {
            "GROQ_API_KEY": "gsk_super_secret_groq_key_9999",
            "GEMINI_API_KEY": "AIzaSy_super_secret_gemini_key_8888",
            "LANGSMITH_API_KEY": "lsv2_pt_super_secret_ls_key_7777",
            "LANGSMITH_TRACING": "true",
        }):
            status = validate_eval_environment()
            # Assert raw keys never appear anywhere in the status dict
            status_str = json.dumps(status)
            self.assertNotIn("super_secret_groq_key", status_str)
            self.assertNotIn("super_secret_gemini_key", status_str)
            self.assertNotIn("super_secret_ls_key", status_str)
            self.assertTrue(status["langsmith_tracing_enabled"])
            self.assertTrue(status["langsmith_api_key_configured"])

    # 2. Dataset Loading and Schema Validation
    def test_load_and_validate_valid_dataset(self):
        test_data = [
            {
                "id": "q01",
                "question": "What is AI?",
                "reference_answer": "Artificial intelligence.",
                "source_chapter": "Chapter 1",
            },
            {
                "id": "q02",
                "question": "What is Moore's Law?",
                "reference_answer": "Transistor doubling.",
                "source_chapter": "Chapter 1",
            },
        ]
        file_path = self.temp_path / "valid.json"
        file_path.write_text(json.dumps(test_data), encoding="utf-8")

        valid, invalid = load_and_validate_dataset(file_path)
        self.assertEqual(len(valid), 2)
        self.assertEqual(len(invalid), 0)
        self.assertEqual(valid[0]["id"], "q01")
        self.assertEqual(valid[0]["question"], "What is AI?")
        self.assertEqual(valid[0]["reference_answer"], "Artificial intelligence.")

    def test_load_and_validate_missing_fields_and_duplicates(self):
        test_data = [
            {"id": "q1", "question": "Valid Q1", "reference_answer": "Valid Ref 1"},
            {"id": "q2", "question": "", "reference_answer": "Ref for empty Q"},  # empty Q
            {"id": "q3", "question": "Valid Q3", "reference_answer": ""},  # empty Ref
            {"id": "q4", "question": "Valid Q1", "reference_answer": "Duplicate Q"},  # duplicate
            "Not a dictionary",  # invalid format
        ]
        file_path = self.temp_path / "dirty.json"
        file_path.write_text(json.dumps(test_data), encoding="utf-8")

        valid, invalid = load_and_validate_dataset(file_path)
        self.assertEqual(len(valid), 1)
        self.assertEqual(len(invalid), 4)
        reasons = [inv["exclusion_reason"] for inv in invalid]
        self.assertTrue(any("Missing or empty question" in r for r in reasons))
        self.assertTrue(any("Missing or empty reference answer" in r for r in reasons))
        self.assertTrue(any("Duplicate question" in r for r in reasons))
        self.assertTrue(any("Item is not a dictionary" in r for r in reasons))

    def test_load_nonexistent_and_invalid_json(self):
        with self.assertRaises(FileNotFoundError):
            load_and_validate_dataset(self.temp_path / "does_not_exist.json")

        bad_json_path = self.temp_path / "bad.json"
        bad_json_path.write_text("{ unclosed json", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_and_validate_dataset(bad_json_path)

    # 3. Empty Retrieval Results & Pipeline Execution
    @patch("scripts.generation.retrieve_curriculum_context")
    @patch("scripts.generation._send_completion")
    def test_run_rag_pipeline_success(self, mock_send, mock_retrieve):
        mock_doc = MagicMock()
        mock_doc.page_content = "Moore's Law observation."
        mock_doc.metadata = {"chunk_id": "1-1-005"}
        mock_retrieve.return_value = [mock_doc]
        mock_send.return_value = '{"answer": "Transistors double every two years."}'

        case = {"id": "q01", "question": "What is Moore's Law?", "reference_answer": "Transistors double."}
        res = run_rag_pipeline_for_case(case, k=2)

        self.assertEqual(res["id"], "q01")
        self.assertEqual(res["response"], "Transistors double every two years.")
        self.assertEqual(res["num_retrieved_chunks"], 1)
        self.assertEqual(res["chunk_ids"], ["1-1-005"])
        self.assertEqual(res["status"], "success")
        self.assertGreater(res["total_latency"], 0.0)

    @patch("scripts.generation.retrieve_curriculum_context")
    def test_run_rag_pipeline_empty_retrieval(self, mock_retrieve):
        mock_retrieve.return_value = []
        case = {"id": "q02", "question": "Nonexistent topic", "reference_answer": "Some ref"}
        res = run_rag_pipeline_for_case(case, k=2)

        self.assertEqual(res["num_retrieved_chunks"], 0)
        self.assertEqual(res["status"], "empty_retrieval")
        self.assertIn("unavailable", res["response"].lower())

    @patch("scripts.generation.retrieve_curriculum_context")
    @patch("scripts.generation._send_completion")
    def test_run_rag_pipeline_generation_failure(self, mock_send, mock_retrieve):
        mock_doc = MagicMock()
        mock_doc.page_content = "Valid chunk content."
        mock_doc.metadata = {"chunk_id": "c1"}
        mock_retrieve.return_value = [mock_doc]
        mock_send.side_effect = RuntimeError("LLM rate limit reached")

        case = {"id": "q03", "question": "Question", "reference_answer": "Ref"}
        res = run_rag_pipeline_for_case(case)

        self.assertEqual(res["status"], "generation_error")
        self.assertIn("Generation Error", res["response"])

    # 4. Tracing Enabled and Disabled
    def test_tracing_toggle(self):
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "false"}):
            status = validate_eval_environment()
            self.assertFalse(status["langsmith_tracing_enabled"])

        with patch.dict(os.environ, {"LANGSMITH_TRACING": "true"}):
            status = validate_eval_environment()
            self.assertTrue(status["langsmith_tracing_enabled"])

    # 5. Batch Runner Smoke Test Limit
    @patch("scripts.evaluation.run_rag_pipeline_for_case")
    def test_run_rag_batch_limit(self, mock_run_case):
        mock_run_case.return_value = {"status": "success"}
        cases = [{"id": f"q_{i}", "question": f"Q {i}"} for i in range(10)]

        results = run_rag_batch(cases, max_cases=3)
        self.assertEqual(len(results), 3)
        self.assertEqual(mock_run_case.call_count, 3)

    # 6. Aggregation and Summarization
    def test_aggregate_evaluation_results(self):
        data = {
            "id": ["q1", "q2", "q3"],
            "retrieval_latency": [0.1, 0.2, 0.3],
            "generation_latency": [1.0, 1.5, 2.0],
            "total_latency": [1.1, 1.7, 2.3],
            "context_precision": [1.0, 0.8, None],  # 1 missing
            "context_recall": [1.0, 1.0, 0.5],
            "faithfulness": [1.0, None, None],     # 2 missing
            "answer_relevancy": [0.9, 0.85, 0.95],
            "status": ["evaluated", "evaluated", "empty_retrieval"],
        }
        df = pd.DataFrame(data)
        summary = aggregate_evaluation_results(df)

        self.assertEqual(summary["total_evaluated_cases"], 3)
        self.assertEqual(summary["metrics"]["context_precision"]["valid_count"], 2)
        self.assertEqual(summary["metrics"]["context_precision"]["missing_or_failed_count"], 1)
        self.assertAlmostEqual(summary["metrics"]["context_precision"]["mean"], 0.9)
        self.assertEqual(summary["metrics"]["faithfulness"]["valid_count"], 1)
        self.assertAlmostEqual(summary["latency_summary"]["mean_retrieval_latency"], 0.2)

    # 7. Output Artifact Saving
    def test_save_evaluation_outputs(self):
        df = pd.DataFrame([{
            "id": "q1",
            "question": "What is AI?",
            "response": "Artificial intelligence.",
            "status": "evaluated",
            "faithfulness": 1.0,
        }])
        summary = {"total_evaluated_cases": 1, "metrics": {"faithfulness": {"mean": 1.0}}}
        detailed = [{"id": "q1", "question": "What is AI?", "secret_key": "should_be_stripped"}]

        out_paths = save_evaluation_outputs(df, summary, detailed, output_dir=self.temp_path)

        self.assertTrue(out_paths["csv"].exists())
        self.assertTrue(out_paths["summary_json"].exists())
        self.assertTrue(out_paths["results_json"].exists())
        self.assertTrue(out_paths["manifest_jsonl"].exists())

        # Check secret stripping in manifest
        manifest_text = out_paths["manifest_jsonl"].read_text(encoding="utf-8")
        self.assertNotIn("should_be_stripped", manifest_text)


if __name__ == "__main__":
    unittest.main()
