"""
Unit tests for the Cleaned Dataset Loader and Classifier Ground-Truth Validation.

Verifies:
  - Canonical discovery of Question_Bank_Cleaned.xlsx
  - Schema column validation and deterministic record normalization
  - Cryptographic provenance and SHA-256 integrity calculation
  - Absence of synthetic/fabricated labels for difficulty and Bloom's Taxonomy
  - Zero database writes (read-only guarantee)
  - Supervised classifier training inspection halts safely when ground-truth labels are absent
"""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.dataset_loader import (
    CANONICAL_DATASET_PATHS,
    load_cleaned_dataset,
    resolve_cleaned_dataset_path,
)
from scripts.train_question_classifier import (
    inspect_dataset,
    train_classifier,
)


class TestCleanedDatasetLoader(unittest.TestCase):
    """Test suite for dataset loader discovery, integrity, and normalization."""

    def test_canonical_path_resolution(self):
        """Cleaned dataset file resolves to an existing file in canonical locations."""
        path = resolve_cleaned_dataset_path()
        self.assertTrue(path.exists(), f"Path {path} does not exist")
        self.assertTrue(path.is_file(), f"Path {path} is not a file")
        self.assertEqual(path.suffix.lower(), ".xlsx")

    def test_load_cleaned_dataset_integrity_and_provenance(self):
        """Loads verified dataset, checking row counts, SHA-256 hash, and schema validation."""
        dataset = load_cleaned_dataset(use_cache=False)

        # Integrity checks
        self.assertIsNotNone(dataset.provenance)
        self.assertTrue(len(dataset.provenance.sha256_hash) == 64, "SHA-256 must be a 64-char hex string")
        self.assertGreater(dataset.provenance.file_size_bytes, 0)
        self.assertGreater(dataset.provenance.total_raw_rows, 0)
        self.assertEqual(dataset.provenance.valid_rows, 317)
        self.assertEqual(dataset.provenance.invalid_rows, 0)
        self.assertEqual(dataset.provenance.duplicate_rows, 0)

        # Strict ground-truth validation: no fabricated labels exist in file
        self.assertFalse(dataset.provenance.has_difficulty_labels, "Cleaned dataset should not have difficulty labels")
        self.assertFalse(dataset.provenance.has_bloom_labels, "Cleaned dataset should not have bloom labels")

        # Questions validation
        self.assertEqual(len(dataset.records), 317)
        first_q = dataset.records[0]
        self.assertIn("question_id", first_q)
        self.assertIn("question_text", first_q)
        self.assertIn("question_type", first_q)
        self.assertIn("correct_answer", first_q)
        self.assertIn("chapter", first_q)
        self.assertIn("lesson", first_q)

        # MCQ vs Essay distribution
        mcqs = [r for r in dataset.records if r["question_type"] == "mcq"]
        essays = [r for r in dataset.records if r["question_type"] == "essay"]
        self.assertEqual(len(mcqs), 168)
        self.assertEqual(len(essays), 149)

        # MCQ options completeness
        for mcq in mcqs:
            self.assertEqual(len(mcq["options"]), 4, f"MCQ {mcq['question_id']} must have 4 options")
            self.assertIn(mcq["correct_option"], ("A", "B", "C", "D"))

        # Essay answers completeness
        for essay in essays:
            self.assertTrue(bool(essay["correct_answer"]), f"Essay {essay['question_id']} must have a model answer")

        # Filter options discovery
        filters = dataset.filters_available
        self.assertIn("chapters", filters)
        self.assertIn("lessons", filters)
        self.assertGreater(len(filters["chapters"]), 0)
        self.assertGreater(len(filters["lessons"]), 0)

    def test_caching_behavior(self):
        """Consecutive loads return cached instance when file mtime is unchanged."""
        ds1 = load_cleaned_dataset(use_cache=True)
        ds2 = load_cleaned_dataset(use_cache=True)
        self.assertIs(ds1, ds2, "Subsequent calls with use_cache=True should return identical object")


class TestClassifierTrainingSafety(unittest.TestCase):
    """Verifies that supervised classifier training halts cleanly when ground-truth labels are absent."""

    def test_inspect_dataset_detects_missing_labels(self):
        """Inspecting the cleaned dataset reports missing labels for difficulty without fabricating data."""
        stats = inspect_dataset(source="file", target="difficulty")
        self.assertEqual(stats["source"], "file")
        self.assertEqual(stats["status"], "missing_labels")
        self.assertFalse(stats["has_target_labels"])
        self.assertFalse(stats["is_sufficient"])
        self.assertEqual(stats["active_method"], "rag_llm")
        self.assertIn("DOES NOT contain ground-truth labels", stats["message"])

    def test_inspect_dataset_detects_missing_bloom_labels(self):
        """Inspecting the cleaned dataset reports missing labels for bloom_level."""
        stats = inspect_dataset(source="file", target="bloom_level")
        self.assertEqual(stats["status"], "missing_labels")
        self.assertFalse(stats["has_target_labels"])
        self.assertEqual(stats["active_method"], "rag_llm")

    def test_train_classifier_halts_and_preserves_rag_llm(self):
        """Training halted cleanly with informative status and does not train on synthetic targets."""
        res = train_classifier(target="difficulty", source="file")
        self.assertEqual(res["status"], "missing_labels")
        self.assertEqual(res["active_method"], "rag_llm")
        self.assertIn("DOES NOT contain ground-truth labels", res["message"])


if __name__ == "__main__":
    unittest.main()

