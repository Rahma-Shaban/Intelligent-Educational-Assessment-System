"""
Comprehensive Unit Tests for Question Ingestion, Cleaning, Extraction, and Validation.

Tests all Stage 1 capabilities:
  - Input formats (Dict, List, DataFrame, CSV, XLSX, JSON, in-memory bytes)
  - Cleaning and normalization rules
  - Schema mapping and metadata preservation
  - Valid and invalid MCQs
  - Valid and invalid essay / short-answer questions
  - Duplicate detection (exact and normalized) without record loss
  - Empty files, malformed records, and structured error reporting
  - Real cleaned question bank dataset verification (Question_Bank_Cleaned.xlsx)
"""

from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from scripts import question_processing as qp


class QuestionParsingTests(unittest.TestCase):
    """Tests parsing from all supported data formats and streams."""

    def test_parse_single_dict(self):
        record = {"question_text": "What is AI?", "question_type": "essay", "correct_answer": "Artificial intelligence."}
        res = qp.parse_question_source(record)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["question_text"], "What is AI?")

    def test_parse_list_of_dicts(self):
        records = [
            {"question_text": "Q1", "question_type": "essay", "correct_answer": "A1"},
            {"question_text": "Q2", "question_type": "essay", "correct_answer": "A2"},
        ]
        res = qp.parse_question_source(records)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[1]["question_text"], "Q2")

    def test_parse_dataframe(self):
        df = pd.DataFrame([
            {"question_text": "Q1", "question_type": "essay", "correct_answer": "A1"},
            {"question_text": "Q2", "question_type": "essay", "correct_answer": "A2"},
        ])
        res = qp.parse_question_source(df)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]["question_text"], "Q1")

    def test_parse_json_file_and_stream(self):
        data = [
            {"question_text": "JSON Q1", "question_type": "essay", "correct_answer": "Ans 1"},
            {"question_text": "JSON Q2", "question_type": "essay", "correct_answer": "Ans 2"},
        ]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(data, f)
            temp_path = Path(f.name)

        try:
            res = qp.parse_question_source(temp_path)
            self.assertEqual(len(res), 2)
            self.assertEqual(res[0]["question_text"], "JSON Q1")

            # Stream / bytes test
            with open(temp_path, "rb") as f_bytes:
                res_stream = qp.parse_question_source(f_bytes, file_format="json")
                self.assertEqual(len(res_stream), 2)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_parse_csv_file_and_stream(self):
        csv_content = (
            "question_text,question_type,correct_answer\n"
            "What is supervised learning?,essay,Learning with labeled data.\n"
            "What is unsupervised learning?,essay,Learning from unlabeled data.\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
            f.write(csv_content)
            temp_path = Path(f.name)

        try:
            res = qp.parse_question_source(temp_path)
            self.assertEqual(len(res), 2)
            self.assertEqual(res[0]["question_text"], "What is supervised learning?")

            # In-memory StringIO stream
            stream = io.StringIO(csv_content)
            res_stream = qp.parse_question_source(stream, file_format="csv")
            self.assertEqual(len(res_stream), 2)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def test_parse_excel_file(self):
        df = pd.DataFrame([
            {
                "question_id": "MCQ-001",
                "question_text": "What is Python?",
                "option_A": "Language",
                "option_B": "Snake",
                "option_C": "Car",
                "option_D": "Planet",
                "correct_option": "A",
                "correct_answer": "Language",
                "question_type": "MCQ",
            }
        ])
        temp_file = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        temp_path = Path(temp_file.name)
        temp_file.close()

        try:
            with pd.ExcelWriter(temp_path, engine="openpyxl") as writer:
                df.to_excel(writer, sheet_name="All_Questions", index=False)

            res = qp.parse_question_source(temp_path)
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["question_id"], "MCQ-001")
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass

    def test_parse_empty_source(self):
        res = qp.parse_question_source([])
        self.assertEqual(res, [])


class CleaningAndExtractionTests(unittest.TestCase):
    """Tests cleaning and schema extraction rules."""

    def test_clean_cell_value_nan_and_whitespace(self):
        self.assertIsNone(qp.clean_cell_value(None))
        self.assertIsNone(qp.clean_cell_value(float("nan")))
        self.assertIsNone(qp.clean_cell_value("  "))
        self.assertIsNone(qp.clean_cell_value("NaN"))
        self.assertIsNone(qp.clean_cell_value("null"))
        self.assertIsNone(qp.clean_cell_value("n/a"))
        self.assertEqual(qp.clean_cell_value("  valid string  "), "valid string")
        self.assertEqual(qp.clean_cell_value(42), 42)

    def test_normalize_question_type(self):
        self.assertEqual(qp.normalize_question_type("MCQ"), "mcq")
        self.assertEqual(qp.normalize_question_type("multiple choice"), "mcq")
        self.assertEqual(qp.normalize_question_type("Multiple-Choice"), "mcq")
        self.assertEqual(qp.normalize_question_type("Essay"), "essay")
        self.assertEqual(qp.normalize_question_type("text-based"), "essay")
        self.assertEqual(qp.normalize_question_type("short answer"), "short_answer")
        self.assertEqual(qp.normalize_question_type(""), "")

    def test_strip_option_prefix(self):
        self.assertEqual(qp.strip_option_prefix("A) Cloud Computing"), "Cloud Computing")
        self.assertEqual(qp.strip_option_prefix("b. Moore's Law"), "Moore's Law")
        self.assertEqual(qp.strip_option_prefix("C: Remote Work"), "Remote Work")
        self.assertEqual(qp.strip_option_prefix("4 - Supervised"), "Supervised")
        self.assertEqual(qp.strip_option_prefix("No prefix here"), "No prefix here")

    def test_normalize_correct_option(self):
        self.assertEqual(qp.normalize_correct_option("b"), "B")
        self.assertEqual(qp.normalize_correct_option(" 1 "), "A")
        self.assertEqual(qp.normalize_correct_option("2"), "B")
        self.assertEqual(qp.normalize_correct_option("3"), "C")
        self.assertEqual(qp.normalize_correct_option("4"), "D")
        self.assertEqual(qp.normalize_correct_option("C: Remote Work"), "C")
        self.assertIsNone(qp.normalize_correct_option(None))

    def test_extract_question_preserves_original_id_and_metadata(self):
        raw = {
            "question_id": "MCQ-001",
            "question_text": "What is AI?",
            "option_A": "A) Smart machine",
            "option_B": "B) Dumb machine",
            "option_C": "C) Animal",
            "option_D": "D) Plant",
            "correct_option": "A",
            "chapter": "Chapter 1",
            "lesson": "Lesson 1-1",
            "page_number": "3, 5",
            "source_file": "curriculum.pdf",
            "answer_source": "Book Content",
            "verification_status": "Verified from Source",
            "Source": "1, 2",
            "custom_tag": "intro",
        }
        cleaned = qp.clean_question_record(raw)
        extracted = qp.extract_question(cleaned, default_id_index=1)

        self.assertEqual(extracted["question_id"], "MCQ-001")
        self.assertEqual(extracted["original_question_id"], "MCQ-001")
        self.assertEqual(extracted["question_type"], "mcq")
        self.assertEqual(extracted["options"][0], "Smart machine")
        self.assertEqual(extracted["correct_option"], "A")
        self.assertEqual(extracted["correct_answer"], "Smart machine")
        self.assertEqual(extracted["chapter"], "Chapter 1")
        self.assertEqual(extracted["lesson"], "Lesson 1-1")
        self.assertEqual(extracted["page_number"], "3, 5")
        self.assertEqual(extracted["source_file"], "curriculum.pdf")
        self.assertEqual(extracted["verification_status"], "Verified from Source")
        self.assertIn("Source", extracted["source_metadata"])
        self.assertIn("custom_tag", extracted["source_metadata"])

    def test_extract_essay_maps_model_answer(self):
        raw = {
            "question_id": "TEXT-001",
            "question_type": "Essay",
            "question_text": "Explain gradient descent.",
            "model_answer": "An optimization algorithm calculating loss gradients.",
            "chapter": "Unit 2",
            "lesson": "Lesson 2-1",
        }
        cleaned = qp.clean_question_record(raw)
        extracted = qp.extract_question(cleaned, default_id_index=1)

        self.assertEqual(extracted["question_type"], "essay")
        self.assertEqual(extracted["correct_answer"], "An optimization algorithm calculating loss gradients.")
        self.assertEqual(extracted["options"], [])
        self.assertIsNone(extracted["correct_option"])


class ValidationTests(unittest.TestCase):
    """Tests rigorous question validation rules."""

    def test_validate_valid_mcq(self):
        mcq = {
            "question_id": "Q-001",
            "question_type": "mcq",
            "question_text": "What is Python?",
            "options": ["Programming language", "Snake species", "Automobile brand", "Operating system"],
            "correct_option": "A",
            "correct_answer": "Programming language",
        }
        is_valid, errors, warnings = qp.validate_question_record(mcq)
        self.assertTrue(is_valid, f"Expected valid MCQ, got errors: {errors}")
        self.assertEqual(errors, [])

    def test_validate_mcq_rejects_missing_text(self):
        mcq = {
            "question_id": "Q-001",
            "question_type": "mcq",
            "question_text": "",
            "options": ["A", "B", "C", "D"],
            "correct_option": "A",
            "correct_answer": "A",
        }
        is_valid, errors, _ = qp.validate_question_record(mcq)
        self.assertFalse(is_valid)
        self.assertTrue(any("Question text is required" in e for e in errors))

    def test_validate_mcq_rejects_wrong_options_count(self):
        mcq = {
            "question_id": "Q-001",
            "question_type": "mcq",
            "question_text": "Valid question?",
            "options": ["Opt 1", "Opt 2", "Opt 3"],  # Only 3 options
            "correct_option": "A",
            "correct_answer": "Opt 1",
        }
        is_valid, errors, _ = qp.validate_question_record(mcq)
        self.assertFalse(is_valid)
        self.assertTrue(any("requires exactly 4 options" in e for e in errors))

    def test_validate_mcq_rejects_duplicate_options(self):
        mcq = {
            "question_id": "Q-001",
            "question_type": "mcq",
            "question_text": "Valid question?",
            "options": ["Repeated option", "Repeated option", "Different option", "Another option"],
            "correct_option": "A",
            "correct_answer": "Repeated option",
        }
        is_valid, errors, _ = qp.validate_question_record(mcq)
        self.assertFalse(is_valid)
        self.assertTrue(any("distinct" in e for e in errors))

    def test_validate_mcq_rejects_prohibited_distractors(self):
        for bad_distractor in ["all of the above", "None of the above", "Both A and B", "neither a nor b"]:
            mcq = {
                "question_id": "Q-001",
                "question_type": "mcq",
                "question_text": "Valid question?",
                "options": ["Opt 1", "Opt 2", "Opt 3", bad_distractor],
                "correct_option": "A",
                "correct_answer": "Opt 1",
            }
            is_valid, errors, _ = qp.validate_question_record(mcq)
            self.assertFalse(is_valid)
            self.assertTrue(any("prohibited low-quality distractor" in e for e in errors))

    def test_validate_mcq_rejects_invalid_correct_option_key(self):
        mcq = {
            "question_id": "Q-001",
            "question_type": "mcq",
            "question_text": "Valid question?",
            "options": ["Opt 1", "Opt 2", "Opt 3", "Opt 4"],
            "correct_option": "E",  # Invalid key
            "correct_answer": "Opt 1",
        }
        is_valid, errors, _ = qp.validate_question_record(mcq)
        self.assertFalse(is_valid)
        self.assertTrue(any("correct_option must be one of" in e for e in errors))

    def test_validate_essay_success_and_missing_answer_failure(self):
        valid_essay = {
            "question_id": "Q-002",
            "question_type": "essay",
            "question_text": "Describe the stages of data processing.",
            "correct_answer": "Collection, preparation, input, processing, output, and storage.",
            "options": [],
        }
        is_valid, errors, _ = qp.validate_question_record(valid_essay)
        self.assertTrue(is_valid)

        invalid_essay = {
            "question_id": "Q-003",
            "question_type": "essay",
            "question_text": "Describe gradient descent.",
            "correct_answer": "",  # Missing model answer
            "options": [],
        }
        is_valid2, errors2, _ = qp.validate_question_record(invalid_essay)
        self.assertFalse(is_valid2)
        self.assertTrue(any("missing a model/correct answer" in e for e in errors2))

    def test_validate_short_answer_success(self):
        valid_sa = {
            "question_id": "Q-004",
            "question_type": "short_answer",
            "question_text": "State Moore's Law.",
            "correct_answer": "Transistor density doubles approximately every two years.",
            "options": [],
        }
        is_valid, errors, _ = qp.validate_question_record(valid_sa)
        self.assertTrue(is_valid)


class DuplicateDetectionTests(unittest.TestCase):
    """Tests exact and normalized duplicate reporting without record loss."""

    def test_detects_exact_duplicates(self):
        questions = [
            {
                "question_id": "Q-001",
                "question_type": "mcq",
                "question_text": "What is Moore's Law?",
            },
            {
                "question_id": "Q-002",
                "question_type": "mcq",
                "question_text": "What is Moore's Law?",
            },
        ]
        dups = qp.detect_duplicates(questions)
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["duplicate_type"], "exact")
        self.assertEqual(dups[0]["question_id"], "Q-002")
        self.assertEqual(dups[0]["matches_question_id"], "Q-001")

    def test_detects_normalized_duplicates(self):
        questions = [
            {
                "question_id": "Q-001",
                "question_type": "essay",
                "question_text": "How does cloud computing benefit businesses?",
            },
            {
                "question_id": "Q-002",
                "question_type": "essay",
                "question_text": "  How DOES   cloud computing benefit businesses?  ",
            },
        ]
        dups = qp.detect_duplicates(questions)
        self.assertEqual(len(dups), 1)
        self.assertEqual(dups[0]["duplicate_type"], "normalized")
        self.assertEqual(dups[0]["question_id"], "Q-002")
        self.assertEqual(dups[0]["matches_question_id"], "Q-001")

    def test_distinct_questions_not_flagged(self):
        questions = [
            {"question_id": "Q-001", "question_type": "essay", "question_text": "What is supervised learning?"},
            {"question_id": "Q-002", "question_type": "essay", "question_text": "What is unsupervised learning?"},
        ]
        dups = qp.detect_duplicates(questions)
        self.assertEqual(len(dups), 0)


class FullPipelineTests(unittest.TestCase):
    """Tests end-to-end question processing pipeline."""

    def test_pipeline_with_mixed_valid_and_invalid_records(self):
        batch = [
            # 1. Valid MCQ
            {
                "question_id": "Q-001",
                "question_type": "mcq",
                "question_text": "Which is an AI subfield?",
                "option_A": "Computer Vision",
                "option_B": "Astrology",
                "option_C": "Alchemy",
                "option_D": "Numerology",
                "correct_option": "A",
                "correct_answer": "Computer Vision",
            },
            # 2. Invalid MCQ (missing option D)
            {
                "question_id": "Q-002",
                "question_type": "mcq",
                "question_text": "Incomplete MCQ?",
                "option_A": "Opt A",
                "option_B": "Opt B",
                "option_C": "Opt C",
                "correct_option": "A",
            },
            # 3. Valid Essay
            {
                "question_id": "Q-003",
                "question_type": "essay",
                "question_text": "Explain neural networks.",
                "model_answer": "Layers of interconnected nodes simulating biological neurons.",
            },
            # 4. Duplicate of Q-001
            {
                "question_id": "Q-004",
                "question_type": "mcq",
                "question_text": "Which is an AI subfield?",
                "option_A": "Computer Vision",
                "option_B": "Astrology",
                "option_C": "Alchemy",
                "option_D": "Numerology",
                "correct_option": "A",
                "correct_answer": "Computer Vision",
            },
        ]

        result = qp.process_question_source(batch)

        # Total count must be 4
        self.assertEqual(result.total_records, 4)
        # 3 are valid, 1 is invalid
        self.assertEqual(result.valid_count, 3)
        self.assertEqual(result.invalid_count, 1)
        # Invalid record is logged with error details
        self.assertEqual(result.invalid_records[0]["question_id"], "Q-002")
        self.assertTrue(len(result.invalid_records[0]["errors"]) > 0)
        # Duplicate Q-004 is detected and recorded without deletion
        self.assertEqual(result.duplicate_count, 1)
        self.assertEqual(result.duplicates[0]["question_id"], "Q-004")
        self.assertEqual(result.duplicates[0]["matches_question_id"], "Q-001")
        # Duplicate warning attached to Q-004 valid record
        q4_valid = [r for r in result.valid_records if r["question_id"] == "Q-004"][0]
        self.assertTrue(any("duplicate" in w for w in q4_valid["validation_warnings"]))

    def test_pipeline_on_real_question_bank_file(self):
        """Verifies ingestion on the repository's Question_Bank_Cleaned.xlsx."""
        bank_path = Path("data/processed/Question_Bank_Cleaned.xlsx")
        if not bank_path.exists():
            self.skipTest(f"Question bank file not found at {bank_path}")

        result = qp.process_question_source(bank_path)

        # Cleaned dataset must yield all 317 valid questions without errors
        self.assertEqual(result.total_records, 317)
        self.assertEqual(result.valid_count, 317)
        self.assertEqual(result.invalid_count, 0)
        self.assertEqual(result.summary["type_counts"]["mcq"], 168)
        self.assertEqual(result.summary["type_counts"]["essay"], 149)
        self.assertEqual(result.summary["valid_ratio"], 1.0)


if __name__ == "__main__":
    unittest.main()
