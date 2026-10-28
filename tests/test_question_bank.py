"""
Comprehensive tests for Stage 4B: Question Bank Persistence and Question Embeddings.

Tests:
  1. MCQ and essay persistence, including correct-answer preservation.
  2. Preservation of all original, analysis, and curriculum mapping fields.
  3. Stable IDs, ID collisions, and repeated imports.
  4. Preservation of approved/rejected review decisions.
  5. Exact, normalized, and semantic duplicate detection.
  6. Isolation from the existing curriculum collection.
  7. Chroma insertion failures and SQL persistence failures.
  8. Reconciliation and retry of pending/failed embedding synchronization.
  9. Batch partial failures and invalid input handling.

All tests use isolated in-memory SQLite and temporary Chroma directories.
No paid APIs are called. HuggingFace embeddings are mocked.
"""

from __future__ import annotations

import contextlib
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import QuestionBankItem
from scripts.question_bank_service import (
    QUESTION_BANK_CHROMA_COLLECTION,
    BatchImportResult,
    build_embedding_text,
    close_chroma_client,
    detect_exact_and_normalized_duplicates,
    detect_id_collisions,
    generate_stable_question_id,
    import_questions_to_db,
    reconcile_pending_embeddings,
    validate_record_for_persistence,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def safe_chroma_tempdir():
    """
    Temporary directory fixture that safely terminates any active Chroma PersistentClient
    systems before Windows attempts directory deletion, avoiding WinError 32 PermissionError.
    """
    import gc
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        try:
            yield tmpdir
        finally:
            try:
                from chromadb.api.client import SharedSystemClient
                for system in list(SharedSystemClient._identifier_to_system.values()):
                    try:
                        system.stop()
                    except Exception:
                        pass
                SharedSystemClient.clear_system_cache()
            except Exception:
                pass
            gc.collect()


def make_in_memory_session():
    """Creates an isolated in-memory SQLite session for tests."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session(), engine


def make_valid_mcq(
    qid: str = "MCQ-001",
    text: str = "What is supervised learning?",
    correct_opt: str = "A",
) -> dict:
    return {
        "question_id": qid,
        "original_question_id": qid,
        "question_type": "mcq",
        "question_text": text,
        "options": ["Learning with labeled data", "Learning without labels",
                    "Reinforcement reward", "Genetic algorithm"],
        "correct_option": correct_opt,
        "correct_answer": "Learning with labeled data",
        "chapter": "Chapter 2",
        "lesson": "Lesson 2-1",
        "page_number": "45",
        "source_file": "curriculum.pdf",
        "answer_source": "Book Content",
        "verification_status": "Verified from Source",
        "source_metadata": {"Source": "1, 2", "custom_tag": "ml_basics"},
        "validation_warnings": [],
        "bloom_level": "remember",
        "difficulty": "easy",
        "learning_objective": "The student will be able to define supervised learning.",
        "learning_objective_grounded": True,
        "classification_reasoning": "Direct recall of definition.",
        "analysis_confidence": 0.95,
        "needs_teacher_review": False,
        "review_reasons": [],
        "curriculum_mapping": {
            "mapping_status": "mapped",
            "confidence_score": 0.88,
            "matched_chunk_id": "2-1-003",
            "matched_lesson_id": "2-1",
        },
        "original_source_metadata": {
            "source_file": "curriculum.pdf",
            "chapter": "Chapter 2",
            "lesson": "Lesson 2-1",
            "page_number": "45",
        },
    }


def make_valid_essay(
    qid: str = "TEXT-001",
    text: str = "Explain gradient descent in detail.",
    answer: str = "Gradient descent iteratively minimizes a loss function by computing gradients.",
) -> dict:
    return {
        "question_id": qid,
        "original_question_id": qid,
        "question_type": "essay",
        "question_text": text,
        "options": [],
        "correct_option": None,
        "correct_answer": answer,
        "chapter": "Chapter 3",
        "lesson": "Lesson 3-2",
        "page_number": "78-80",
        "source_file": "textbook.pdf",
        "answer_source": "Solved by AI",
        "verification_status": "Solved by AI",
        "source_metadata": {"difficulty_tag": "advanced"},
        "validation_warnings": [],
        "bloom_level": "understand",
        "difficulty": "medium",
        "learning_objective": "The student will be able to explain gradient descent.",
        "learning_objective_grounded": True,
        "classification_reasoning": "Explanation requires understanding, not mere recall.",
        "analysis_confidence": 0.90,
        "needs_teacher_review": False,
        "review_reasons": [],
        "curriculum_mapping": None,
        "original_source_metadata": None,
    }


def make_mock_embeddings(dim: int = 8):
    """Returns a mock embeddings object that returns fake fixed vectors."""
    mock = MagicMock()
    mock.embed_query.return_value = [0.1] * dim
    return mock


# ---------------------------------------------------------------------------
# 1. MCQ and essay persistence, including correct-answer preservation
# ---------------------------------------------------------------------------

class TestMCQAndEssayPersistence(unittest.TestCase):

    def setUp(self):
        self.db, self.engine = make_in_memory_session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_mcq_persisted_with_all_correct_fields(self):
        mcq = make_valid_mcq()
        result = import_questions_to_db([mcq], self.db, skip_embedding=True)

        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.invalid, 0)

        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertIsNotNone(item)
        self.assertEqual(item.question_type, "mcq")
        self.assertEqual(item.question_text, "What is supervised learning?")
        self.assertEqual(item.correct_option, "A")
        self.assertEqual(item.correct_answer, "Learning with labeled data")
        # Options preserved
        self.assertIsNotNone(item.options_json)
        options = json.loads(item.options_json)
        self.assertEqual(len(options), 4)
        self.assertEqual(options[0], "Learning with labeled data")

    def test_essay_persisted_with_complete_model_answer(self):
        essay = make_valid_essay()
        result = import_questions_to_db([essay], self.db, skip_embedding=True)

        self.assertEqual(result.inserted, 1)
        item = self.db.query(QuestionBankItem).filter_by(question_id="TEXT-001").first()
        self.assertIsNotNone(item)
        self.assertEqual(item.question_type, "essay")
        self.assertIsNone(item.correct_option)
        self.assertEqual(item.correct_answer,
                         "Gradient descent iteratively minimizes a loss function by computing gradients.")
        # options_json should be None or empty for essay
        if item.options_json:
            self.assertEqual(json.loads(item.options_json), [])

    def test_both_correct_option_and_correct_answer_preserved_for_mcq(self):
        mcq = make_valid_mcq(correct_opt="B")
        mcq["correct_answer"] = "Learning without labels"
        mcq["options"][1] = "Learning without labels"
        result = import_questions_to_db([mcq], self.db, skip_embedding=True)

        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertEqual(item.correct_option, "B")
        self.assertEqual(item.correct_answer, "Learning without labels")

    def test_default_embedding_status_is_pending(self):
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)
        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertEqual(item.embedding_status, "pending")

    def test_default_review_status_is_pending_review(self):
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)
        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertEqual(item.review_status, "pending_review")


# ---------------------------------------------------------------------------
# 2. Preservation of all original, analysis, and curriculum mapping fields
# ---------------------------------------------------------------------------

class TestFieldPreservation(unittest.TestCase):

    def setUp(self):
        self.db, self.engine = make_in_memory_session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_source_metadata_preserved_as_json(self):
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)
        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertIsNotNone(item.source_metadata_json)
        meta = json.loads(item.source_metadata_json)
        self.assertEqual(meta["Source"], "1, 2")
        self.assertEqual(meta["custom_tag"], "ml_basics")

    def test_bloom_level_difficulty_and_learning_objective_preserved(self):
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)
        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertEqual(item.bloom_level, "remember")
        self.assertEqual(item.difficulty, "easy")
        self.assertEqual(item.learning_objective, "The student will be able to define supervised learning.")
        self.assertTrue(item.learning_objective_grounded)
        self.assertAlmostEqual(item.analysis_confidence, 0.95, places=4)

    def test_curriculum_mapping_preserved_as_json(self):
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)
        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertIsNotNone(item.curriculum_mapping_json)
        mapping = json.loads(item.curriculum_mapping_json)
        self.assertEqual(mapping["mapping_status"], "mapped")
        self.assertAlmostEqual(mapping["confidence_score"], 0.88, places=4)
        self.assertEqual(mapping["matched_chunk_id"], "2-1-003")

    def test_original_source_metadata_preserved_separately_from_source_metadata(self):
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)
        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        # Both JSON fields must be present and be distinct objects
        self.assertIsNotNone(item.source_metadata_json)
        self.assertIsNotNone(item.original_source_metadata_json)
        src = json.loads(item.source_metadata_json)
        orig = json.loads(item.original_source_metadata_json)
        self.assertIn("custom_tag", src)      # from source_metadata
        self.assertIn("source_file", orig)    # from original_source_metadata

    def test_chapter_lesson_page_source_file_preserved(self):
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)
        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertEqual(item.chapter, "Chapter 2")
        self.assertEqual(item.lesson, "Lesson 2-1")
        self.assertEqual(item.page_number, "45")
        self.assertEqual(item.source_file, "curriculum.pdf")
        self.assertEqual(item.answer_source, "Book Content")
        self.assertEqual(item.verification_status, "Verified from Source")

    def test_created_at_and_updated_at_are_set(self):
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)
        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertIsNotNone(item.created_at)
        self.assertIsNotNone(item.updated_at)


# ---------------------------------------------------------------------------
# 3. Stable IDs, ID collisions, and repeated imports
# ---------------------------------------------------------------------------

class TestStableIDs(unittest.TestCase):

    def setUp(self):
        self.db, self.engine = make_in_memory_session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_question_id_from_record_used_as_stable_id(self):
        qid, is_synthetic = generate_stable_question_id({"question_id": "MCQ-042"}, 0)
        self.assertEqual(qid, "MCQ-042")
        self.assertFalse(is_synthetic)

    def test_original_question_id_fallback(self):
        qid, is_synthetic = generate_stable_question_id(
            {"original_question_id": "TEXT-007", "question_type": "essay", "question_text": "explain"},
            0,
        )
        self.assertEqual(qid, "TEXT-007")
        self.assertFalse(is_synthetic)

    def test_synthetic_id_is_deterministic_and_position_independent(self):
        rec = {"question_type": "mcq", "question_text": "What is 2+2?"}
        qid1, syn1 = generate_stable_question_id(rec, 0)
        qid2, syn2 = generate_stable_question_id(rec, 99)
        self.assertTrue(syn1)
        self.assertTrue(syn2)
        self.assertEqual(qid1, qid2)  # same content => same ID regardless of position

    def test_synthetic_id_differs_for_different_content(self):
        rec1 = {"question_type": "mcq", "question_text": "Question A"}
        rec2 = {"question_type": "mcq", "question_text": "Question B"}
        qid1, _ = generate_stable_question_id(rec1, 0)
        qid2, _ = generate_stable_question_id(rec2, 0)
        self.assertNotEqual(qid1, qid2)

    def test_collision_detected_for_duplicate_ids(self):
        records = [
            make_valid_mcq(qid="MCQ-001"),
            make_valid_mcq(qid="MCQ-001", text="Different question text"),
        ]
        _, collisions = detect_id_collisions(records)
        self.assertEqual(len(collisions), 1)
        self.assertEqual(collisions[0]["question_id"], "MCQ-001")
        self.assertEqual(collisions[0]["collision_count"], 2)

    def test_repeated_import_is_idempotent(self):
        mcq = make_valid_mcq()
        result1 = import_questions_to_db([mcq], self.db, skip_embedding=True)
        result2 = import_questions_to_db([mcq], self.db, skip_embedding=True)

        self.assertEqual(result1.inserted, 1)
        self.assertEqual(result2.inserted, 0)
        self.assertEqual(result2.updated, 1)

        # Exactly 1 row in DB
        count = self.db.query(QuestionBankItem).count()
        self.assertEqual(count, 1)

    def test_content_update_on_reimport(self):
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)

        mcq_updated = make_valid_mcq()
        mcq_updated["question_text"] = "Updated: What is supervised learning?"
        import_questions_to_db([mcq_updated], self.db, skip_embedding=True)

        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertEqual(item.question_text, "Updated: What is supervised learning?")


# ---------------------------------------------------------------------------
# 4. Preservation of approved/rejected review decisions
# ---------------------------------------------------------------------------

class TestReviewDecisionPreservation(unittest.TestCase):

    def setUp(self):
        self.db, self.engine = make_in_memory_session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _set_review_status(self, question_id: str, status: str) -> None:
        item = self.db.query(QuestionBankItem).filter_by(question_id=question_id).first()
        item.review_status = status
        item.review_notes = f"Reviewed by test: {status}"
        item.reviewed_by = "test_teacher"
        item.reviewed_at = datetime.now(timezone.utc)
        self.db.commit()

    def test_approved_decision_preserved_on_reimport(self):
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)
        self._set_review_status("MCQ-001", "approved")

        # Re-import with modified text
        mcq["question_text"] = "MODIFIED text"
        result = import_questions_to_db([mcq], self.db, skip_embedding=True)

        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertEqual(item.review_status, "approved")
        self.assertEqual(item.reviewed_by, "test_teacher")
        # Content update is skipped for approved questions
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.updated, 0)

    def test_rejected_decision_preserved_on_reimport(self):
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)
        self._set_review_status("MCQ-001", "rejected")

        mcq["question_text"] = "MODIFIED text"
        result = import_questions_to_db([mcq], self.db, skip_embedding=True)

        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertEqual(item.review_status, "rejected")
        self.assertEqual(result.skipped, 1)

    def test_pending_review_record_is_updated_on_reimport(self):
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)
        # review_status remains "pending_review" — update should proceed

        mcq["bloom_level"] = "analyze"
        result = import_questions_to_db([mcq], self.db, skip_embedding=True)

        self.assertEqual(result.updated, 1)
        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertEqual(item.bloom_level, "analyze")

    def test_review_notes_and_reviewed_by_not_overwritten(self):
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)
        self._set_review_status("MCQ-001", "approved")

        mcq["question_text"] = "Changed"
        import_questions_to_db([mcq], self.db, skip_embedding=True)

        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertEqual(item.review_notes, "Reviewed by test: approved")
        self.assertEqual(item.reviewed_by, "test_teacher")


# ---------------------------------------------------------------------------
# 5. Exact, normalized, and semantic duplicate detection
# ---------------------------------------------------------------------------

class TestDuplicateDetection(unittest.TestCase):

    def setUp(self):
        self.db, self.engine = make_in_memory_session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_exact_duplicate_detected(self):
        records = [
            make_valid_mcq(qid="MCQ-001"),
            make_valid_mcq(qid="MCQ-002"),  # same text, different ID
        ]
        flags = detect_exact_and_normalized_duplicates(records)
        exact_flags = [f for f in flags if f["duplicate_type"] == "exact"]
        self.assertEqual(len(exact_flags), 1)
        self.assertEqual(exact_flags[0]["question_id"], "MCQ-002")
        self.assertEqual(exact_flags[0]["matches_question_id"], "MCQ-001")

    def test_normalized_duplicate_detected(self):
        records = [
            make_valid_mcq(qid="MCQ-001", text="What is supervised learning?"),
            make_valid_mcq(qid="MCQ-002", text="What is supervised learning"),  # trailing punctuation stripped
        ]
        flags = detect_exact_and_normalized_duplicates(records)
        norm_flags = [f for f in flags if f["duplicate_type"] == "normalized"]
        self.assertEqual(len(norm_flags), 1)
        self.assertEqual(norm_flags[0]["question_id"], "MCQ-002")

    def test_no_false_positive_for_distinct_questions(self):
        records = [
            make_valid_mcq(qid="MCQ-001", text="What is supervised learning?"),
            make_valid_mcq(qid="MCQ-002", text="What is unsupervised learning?"),
        ]
        flags = detect_exact_and_normalized_duplicates(records)
        self.assertEqual(len(flags), 0)

    def test_duplicate_flag_appears_in_import_outcome(self):
        records = [
            make_valid_mcq(qid="MCQ-001"),
            make_valid_mcq(qid="MCQ-002"),  # same text
        ]
        result = import_questions_to_db(records, self.db, skip_embedding=True)
        dup_outcomes = [o for o in result.outcomes if o.duplicate_flags]
        self.assertGreaterEqual(len(dup_outcomes), 1)

    def test_semantic_duplicate_detection_returns_empty_when_no_collection(self):
        from scripts.question_bank_service import detect_semantic_duplicates_against_db
        records = [make_valid_mcq()]
        flags = detect_semantic_duplicates_against_db(
            records, self.db, chroma_collection=None, embeddings=None
        )
        self.assertEqual(flags, [])

    def test_semantic_duplicate_detection_with_mock_chroma(self):
        from scripts.question_bank_service import detect_semantic_duplicates_against_db

        mock_embeddings = make_mock_embeddings()
        mock_collection = MagicMock()
        # Simulate high-similarity result from Chroma (distance near 0 means high cosine similarity)
        mock_collection.query.return_value = {
            "ids": [["MCQ-999"]],
            "distances": [[0.05]],  # cosine distance 0.05 => similarity ~0.975
            "metadatas": [[{}]],
        }

        records = [make_valid_mcq(qid="MCQ-001")]
        flags = detect_semantic_duplicates_against_db(
            records, self.db,
            chroma_collection=mock_collection,
            embeddings=mock_embeddings,
            threshold=0.92,
        )
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["match_type"], "semantic")
        self.assertEqual(flags[0]["candidate_id"], "MCQ-999")
        self.assertGreaterEqual(flags[0]["score"], 0.92)


# ---------------------------------------------------------------------------
# 6. Isolation from the existing curriculum collection
# ---------------------------------------------------------------------------

class TestChromaIsolation(unittest.TestCase):

    def setUp(self):
        self.db, self.engine = make_in_memory_session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_question_bank_collection_name_is_not_curriculum(self):
        self.assertNotEqual(QUESTION_BANK_CHROMA_COLLECTION, "curriculum")

    def test_get_or_create_does_not_touch_curriculum_collection(self):
        with safe_chroma_tempdir() as tmpdir:
            import chromadb
            # Pre-create a 'curriculum' collection in the temp dir
            client = chromadb.PersistentClient(path=tmpdir)
            curriculum_col = client.create_collection("curriculum")
            curriculum_col.add(ids=["doc-1"], documents=["test doc"], embeddings=[[0.1] * 8])
            initial_count = curriculum_col.count()
            del client

            # Now call our service function
            from scripts.question_bank_service import _get_or_create_question_bank_collection
            _get_or_create_question_bank_collection(tmpdir)

            # Verify curriculum collection is untouched
            client2 = chromadb.PersistentClient(path=tmpdir)
            curr = client2.get_collection("curriculum")
            self.assertEqual(curr.count(), initial_count)

    def test_question_bank_collection_created_separately(self):
        with safe_chroma_tempdir() as tmpdir:
            from scripts.question_bank_service import _get_or_create_question_bank_collection
            import chromadb
            col = _get_or_create_question_bank_collection(tmpdir)
            self.assertEqual(col.name, QUESTION_BANK_CHROMA_COLLECTION)

            client = chromadb.PersistentClient(path=tmpdir)
            names = {c.name for c in client.list_collections()}
            self.assertIn(QUESTION_BANK_CHROMA_COLLECTION, names)

    def test_embedding_collection_used_is_question_bank_not_curriculum(self):
        with safe_chroma_tempdir() as tmpdir:
            import chromadb
            # Pre-create curriculum to ensure it exists
            client = chromadb.PersistentClient(path=tmpdir)
            client.create_collection("curriculum")
            del client

            mock_embeddings = make_mock_embeddings()
            mcq = make_valid_mcq()
            import_questions_to_db(
                [mcq], self.db,
                chroma_persist_dir=tmpdir,
                embeddings=mock_embeddings,
                skip_embedding=False,
            )

            client2 = chromadb.PersistentClient(path=tmpdir)
            qb_col = client2.get_collection(QUESTION_BANK_CHROMA_COLLECTION)
            curr_col = client2.get_collection("curriculum")
            self.assertEqual(qb_col.count(), 1)
            self.assertEqual(curr_col.count(), 0)  # unchanged


# ---------------------------------------------------------------------------
# 7. Chroma insertion failures and SQL persistence failures
# ---------------------------------------------------------------------------

class TestFailureHandling(unittest.TestCase):

    def setUp(self):
        self.db, self.engine = make_in_memory_session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_chroma_failure_does_not_roll_back_sql(self):
        """SQL record is committed even when Chroma embedding fails."""
        mock_embeddings = make_mock_embeddings()
        mock_embeddings.embed_query.side_effect = RuntimeError("Chroma unavailable")

        with safe_chroma_tempdir() as tmpdir:
            mcq = make_valid_mcq()
            result = import_questions_to_db(
                [mcq], self.db,
                chroma_persist_dir=tmpdir,
                embeddings=mock_embeddings,
                skip_embedding=False,
            )

        # SQL should be inserted even though embedding failed
        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertIsNotNone(item)
        self.assertEqual(item.embedding_status, "failed")
        self.assertIsNotNone(item.embedding_error)

    def test_embedding_status_failure_recorded_in_outcome(self):
        mock_embeddings = make_mock_embeddings()
        mock_embeddings.embed_query.side_effect = RuntimeError("embed error")

        with safe_chroma_tempdir() as tmpdir:
            mcq = make_valid_mcq()
            result = import_questions_to_db(
                [mcq], self.db,
                chroma_persist_dir=tmpdir,
                embeddings=mock_embeddings,
                skip_embedding=False,
            )

        outcome = result.outcomes[0]
        self.assertEqual(outcome.embedding_status, "failed")
        self.assertTrue(any("Chroma" in w for w in outcome.warnings))

    def test_invalid_record_does_not_enter_db(self):
        """An invalid record (missing question_text) must NOT be persisted."""
        bad_record = {
            "question_id": "BAD-001",
            "question_type": "essay",
            "question_text": "",   # invalid
            "correct_answer": "some answer",
        }
        result = import_questions_to_db([bad_record], self.db, skip_embedding=True)
        self.assertEqual(result.invalid, 1)
        item = self.db.query(QuestionBankItem).filter_by(question_id="BAD-001").first()
        self.assertIsNone(item)

    def test_valid_record_succeeds_when_invalid_record_is_in_batch(self):
        """A valid record in the same batch as an invalid one must still be inserted."""
        bad_record = {
            "question_id": "BAD-001",
            "question_type": "essay",
            "question_text": "",
            "correct_answer": "irrelevant",
        }
        good_record = make_valid_essay()
        result = import_questions_to_db([bad_record, good_record], self.db, skip_embedding=True)

        self.assertEqual(result.invalid, 1)
        self.assertEqual(result.inserted, 1)
        item = self.db.query(QuestionBankItem).filter_by(question_id="TEXT-001").first()
        self.assertIsNotNone(item)


# ---------------------------------------------------------------------------
# 8. Reconciliation and retry of pending/failed embedding synchronization
# ---------------------------------------------------------------------------

class TestReconciliation(unittest.TestCase):

    def setUp(self):
        self.db, self.engine = make_in_memory_session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_reconcile_syncs_pending_embeddings(self):
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)

        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertEqual(item.embedding_status, "pending")

        mock_embeddings = make_mock_embeddings()
        with safe_chroma_tempdir() as tmpdir:
            summary = reconcile_pending_embeddings(self.db, tmpdir, mock_embeddings)

        self.assertEqual(summary["synced"], 1)
        self.assertEqual(summary.get("failed", 0), 0)

        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertEqual(item.embedding_status, "synced")
        self.assertIsNotNone(item.embedding_id)
        self.assertIsNotNone(item.embedded_at)

    def test_reconcile_retries_failed_embeddings(self):
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)

        # Manually set to failed
        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        item.embedding_status = "failed"
        item.embedding_error = "previous error"
        self.db.commit()

        mock_embeddings = make_mock_embeddings()
        with safe_chroma_tempdir() as tmpdir:
            summary = reconcile_pending_embeddings(
                self.db, tmpdir, mock_embeddings, statuses=("failed",)
            )

        self.assertEqual(summary["synced"], 1)
        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertEqual(item.embedding_status, "synced")
        self.assertIsNone(item.embedding_error)

    def test_reconcile_skips_already_synced_embeddings(self):
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)

        # Manually set to synced
        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        item.embedding_status = "synced"
        self.db.commit()

        mock_embeddings = make_mock_embeddings()
        with safe_chroma_tempdir() as tmpdir:
            summary = reconcile_pending_embeddings(
                self.db, tmpdir, mock_embeddings, statuses=("pending", "failed")
            )

        self.assertEqual(summary["synced"], 0)
        self.assertEqual(summary.get("total_processed", 0), 0)

    def test_reconcile_records_failure_on_embed_error(self):
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)

        mock_embeddings = make_mock_embeddings()
        mock_embeddings.embed_query.side_effect = RuntimeError("embed failed")

        with safe_chroma_tempdir() as tmpdir:
            summary = reconcile_pending_embeddings(self.db, tmpdir, mock_embeddings)

        self.assertEqual(summary.get("failed", 0), 1)
        item = self.db.query(QuestionBankItem).filter_by(question_id="MCQ-001").first()
        self.assertEqual(item.embedding_status, "failed")

    def test_reconcile_embedding_is_idempotent(self):
        """Running reconciliation twice must not duplicate Chroma entries."""
        mcq = make_valid_mcq()
        import_questions_to_db([mcq], self.db, skip_embedding=True)

        mock_embeddings = make_mock_embeddings()
        with safe_chroma_tempdir() as tmpdir:
            summary1 = reconcile_pending_embeddings(self.db, tmpdir, mock_embeddings)
            summary2 = reconcile_pending_embeddings(
                self.db, tmpdir, mock_embeddings, statuses=("pending", "failed")
            )

        # Second run finds nothing to process (already synced)
        self.assertEqual(summary1["synced"], 1)
        self.assertEqual(summary2.get("total_processed", 0), 0)


# ---------------------------------------------------------------------------
# 9. Batch partial failures and invalid input handling
# ---------------------------------------------------------------------------

class TestBatchPartialFailures(unittest.TestCase):

    def setUp(self):
        self.db, self.engine = make_in_memory_session()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_empty_batch_returns_zero_counts(self):
        result = import_questions_to_db([], self.db, skip_embedding=True)
        self.assertEqual(result.total_input, 0)
        self.assertEqual(result.inserted, 0)
        self.assertEqual(result.errored, 0)

    def test_invalid_question_type_reported(self):
        record = {
            "question_id": "BAD-002",
            "question_type": "unknown_type",
            "question_text": "A question?",
            "correct_answer": "Some answer",
        }
        result = import_questions_to_db([record], self.db, skip_embedding=True)
        self.assertEqual(result.invalid, 1)
        outcome = result.outcomes[0]
        self.assertEqual(outcome.status, "invalid")
        self.assertTrue(any("invalid" in e.lower() or "question_type" in e for e in outcome.errors))

    def test_mcq_without_4_options_is_invalid(self):
        bad = make_valid_mcq()
        bad["options"] = ["Only one option"]  # must have exactly 4
        result = import_questions_to_db([bad], self.db, skip_embedding=True)
        self.assertEqual(result.invalid, 1)

    def test_mcq_with_invalid_correct_option_is_invalid(self):
        bad = make_valid_mcq()
        bad["correct_option"] = "E"  # not in A/B/C/D
        result = import_questions_to_db([bad], self.db, skip_embedding=True)
        self.assertEqual(result.invalid, 1)

    def test_essay_missing_correct_answer_is_invalid(self):
        bad = make_valid_essay()
        bad["correct_answer"] = ""
        result = import_questions_to_db([bad], self.db, skip_embedding=True)
        self.assertEqual(result.invalid, 1)

    def test_mixed_valid_invalid_batch(self):
        records = [
            make_valid_mcq(qid="MCQ-001"),
            {"question_id": "BAD-003", "question_type": "essay", "question_text": "", "correct_answer": "x"},
            make_valid_essay(qid="TEXT-001"),
            {"question_id": "BAD-004", "question_type": "essay", "question_text": "q", "correct_answer": ""},
        ]
        result = import_questions_to_db(records, self.db, skip_embedding=True)
        self.assertEqual(result.total_input, 4)
        self.assertEqual(result.inserted, 2)
        self.assertEqual(result.invalid, 2)
        self.assertEqual(result.errored, 0)

    def test_batch_result_to_dict_is_serializable(self):
        records = [make_valid_mcq(), make_valid_essay()]
        result = import_questions_to_db(records, self.db, skip_embedding=True)
        d = result.to_dict()
        # Must be JSON-serializable
        import json as json_mod
        serialized = json_mod.dumps(d)
        self.assertIsInstance(serialized, str)
        self.assertIn("MCQ-001", serialized)

    def test_outcome_per_record_is_present(self):
        records = [make_valid_mcq(qid=f"MCQ-{i:03d}") for i in range(1, 6)]
        result = import_questions_to_db(records, self.db, skip_embedding=True)
        self.assertEqual(len(result.outcomes), 5)
        for i, outcome in enumerate(result.outcomes):
            self.assertEqual(outcome.input_index, i)
            self.assertEqual(outcome.status, "inserted")


# ---------------------------------------------------------------------------
# Bonus: build_embedding_text and validate_record_for_persistence unit tests
# ---------------------------------------------------------------------------

class TestBuildEmbeddingText(unittest.TestCase):

    def test_mcq_includes_options_and_answer(self):
        record = make_valid_mcq()
        text = build_embedding_text(record)
        self.assertIn("What is supervised learning?", text)
        self.assertIn("[OPTIONS:", text)
        self.assertIn("A:", text)
        self.assertIn("[ANSWER:", text)
        self.assertIn("Learning with labeled data", text)

    def test_essay_omits_options_section(self):
        record = make_valid_essay()
        text = build_embedding_text(record)
        self.assertIn("Explain gradient descent", text)
        self.assertNotIn("[OPTIONS:", text)
        self.assertIn("[ANSWER:", text)

    def test_empty_question_text_returns_empty_string(self):
        record = {"question_type": "essay", "question_text": "", "correct_answer": ""}
        text = build_embedding_text(record)
        self.assertEqual(text, "")


class TestValidateRecord(unittest.TestCase):

    def test_valid_mcq_passes(self):
        errors = validate_record_for_persistence(make_valid_mcq())
        self.assertEqual(errors, [])

    def test_valid_essay_passes(self):
        errors = validate_record_for_persistence(make_valid_essay())
        self.assertEqual(errors, [])

    def test_missing_question_text_fails(self):
        rec = make_valid_essay()
        rec["question_text"] = ""
        errors = validate_record_for_persistence(rec)
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("question_text" in e for e in errors))

    def test_missing_question_type_fails(self):
        rec = make_valid_essay()
        rec["question_type"] = ""
        errors = validate_record_for_persistence(rec)
        self.assertGreater(len(errors), 0)

    def test_invalid_question_type_fails(self):
        rec = make_valid_essay()
        rec["question_type"] = "quiz"
        errors = validate_record_for_persistence(rec)
        self.assertGreater(len(errors), 0)


if __name__ == "__main__":
    unittest.main()
