"""
Comprehensive Unit Tests for Curriculum Mapping Module.

Tests Stage 3 capabilities:
  - Successful curriculum chunk mapping with chunk ID, chapter, lesson, and page metadata
  - Extraction of supporting evidence excerpts from chunk content
  - Separation between question bank original source metadata and curriculum evidence
  - Low-confidence similarity threshold flagging and review indicators
  - Safe handling of missing, empty, or uninitialized vector stores (never fabricating chunks)
  - Zero-result and retrieval error tolerance
  - Missing chunk metadata detection
  - Complete preservation of upstream question attributes and analysis results
  - Zero paid API calls (all vector stores and embeddings mocked)
"""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from scripts import curriculum_mapping as cm


def create_mock_doc(
    content: str = "Moore's Law describes an empirical observation where transistor counts double every two years.",
    chunk_id: str = "1-1-002",
    source: str = "curriculum.pdf",
    chapter_id: int = 1,
    chapter_title: str = "Information Technology and Society",
    lesson_id: str = "1-1",
    lesson_title: str = "Development of Information Technology",
    pdf_page_start: int = 3,
    pdf_page_end: int = 4,
    printed_page_start: int = 3,
    printed_page_end: int = 4,
) -> SimpleNamespace:
    return SimpleNamespace(
        page_content=content,
        metadata={
            "chunk_id": chunk_id,
            "source": source,
            "chapter_id": chapter_id,
            "chapter_title": chapter_title,
            "lesson_id": lesson_id,
            "lesson_title": lesson_title,
            "pdf_page_start": pdf_page_start,
            "pdf_page_end": pdf_page_end,
            "printed_page_start": printed_page_start,
            "printed_page_end": printed_page_end,
            "content_type": "text",
        },
    )


def create_sample_analyzed_question(
    qid: str = "Q-0001",
    qtext: str = "What is the empirical observation that describes transistor doubling?",
    correct_ans: str = "Moore's Law",
    lesson: str = "Lesson 1-1 Development of Information Technology",
    chapter: str = "Unit One: Information Technology",
    status: str = "Solved by AI",
) -> dict:
    return {
        "question_id": qid,
        "original_question_id": "MCQ-002",
        "question_type": "mcq",
        "question_text": qtext,
        "options": ["Cloud computing", "Moore's Law", "Edge computing", "Quantum"],
        "correct_option": "B",
        "correct_answer": correct_ans,
        "bloom_level": "remember",
        "difficulty": "easy",
        "learning_objective": "The student will be able to identify Moore's Law.",
        "learning_objective_grounded": True,
        "classification_reasoning": "Direct recall of empirical observation.",
        "confidence": 0.95,
        "needs_teacher_review": False,
        "review_reasons": [],
        "chapter": chapter,
        "lesson": lesson,
        "page_number": 3,
        "source_file": "Programming-AI-Assessments.pdf",
        "answer_source": "Book Content",
        "verification_status": status,
        "source_metadata": {"Source": "1, 2"},
        "validation_warnings": [],
    }


class SuccessfulCurriculumMappingTests(unittest.TestCase):
    """Tests accurate mapping against curriculum chunks and metadata grounding."""

    def test_successful_mapping_with_evidence_and_grounding(self):
        doc = create_mock_doc()
        mock_store = MagicMock()
        mock_store.similarity_search_with_relevance_scores.return_value = [(doc, 0.88)]

        question = create_sample_analyzed_question()
        result = cm.map_single_question(question, store=mock_store, min_confidence=0.65)

        mapping = result.curriculum_mapping
        self.assertEqual(mapping["mapping_status"], "mapped")
        self.assertAlmostEqual(mapping["confidence_score"], 0.88)
        self.assertEqual(mapping["matched_chunk_id"], "1-1-002")
        self.assertEqual(mapping["matched_source_document"], "curriculum.pdf")
        self.assertEqual(mapping["matched_chapter_id"], 1)
        self.assertEqual(mapping["matched_chapter_title"], "Information Technology and Society")
        self.assertEqual(mapping["matched_lesson_id"], "1-1")
        self.assertEqual(mapping["matched_lesson_title"], "Development of Information Technology")
        self.assertEqual(mapping["matched_page_start"], 3)
        self.assertEqual(mapping["matched_page_end"], 4)
        self.assertIn("transistor counts double", mapping["evidence_excerpt"])
        self.assertFalse(mapping["needs_review"])
        self.assertEqual(len(mapping["supporting_chunks"]), 1)

    def test_distinguishes_original_metadata_from_curriculum_evidence(self):
        doc = create_mock_doc(
            chunk_id="1-1-005",
            source="curriculum_textbook.pdf",
            chapter_id=1,
            chapter_title="Curriculum Unit 1",
            lesson_id="1-1",
            lesson_title="Curriculum Lesson 1",
            pdf_page_start=12,
            pdf_page_end=13,
        )
        mock_store = MagicMock()
        mock_store.similarity_search_with_relevance_scores.return_value = [(doc, 0.82)]

        question = create_sample_analyzed_question(
            lesson="Original Lesson Name",
            chapter="Original Chapter Name",
            status="Raw Question Bank Input",
        )
        result = cm.map_single_question(question, store=mock_store)

        # Original source metadata remains distinct
        orig = result.original_source_metadata
        self.assertEqual(orig["source_file"], "Programming-AI-Assessments.pdf")
        self.assertEqual(orig["lesson"], "Original Lesson Name")
        self.assertEqual(orig["chapter"], "Original Chapter Name")
        self.assertEqual(orig["verification_status"], "Raw Question Bank Input")

        # Curriculum mapping contains actual retrieved chunk data
        curr = result.curriculum_mapping
        self.assertEqual(curr["matched_source_document"], "curriculum_textbook.pdf")
        self.assertEqual(curr["matched_chunk_id"], "1-1-005")
        self.assertEqual(curr["matched_page_start"], 12)
        self.assertEqual(curr["matched_chapter_title"], "Curriculum Unit 1")


class LowConfidenceAndMissingContextTests(unittest.TestCase):
    """Tests low-similarity matches, missing vector stores, and zero results."""

    def test_low_confidence_similarity_triggers_review_flag(self):
        doc = create_mock_doc()
        mock_store = MagicMock()
        # Similarity score 0.50 is below default threshold 0.65
        mock_store.similarity_search_with_relevance_scores.return_value = [(doc, 0.50)]

        question = create_sample_analyzed_question()
        result = cm.map_single_question(question, store=mock_store, min_confidence=0.65)

        mapping = result.curriculum_mapping
        self.assertEqual(mapping["mapping_status"], "low_confidence")
        self.assertAlmostEqual(mapping["confidence_score"], 0.50)
        self.assertTrue(mapping["needs_review"])
        self.assertTrue(result.needs_teacher_review)
        self.assertTrue(any("below threshold" in r for r in mapping["review_reasons"]))

    def test_missing_vector_store_reports_unresolved_without_fabricating(self):
        # Store is None and directory does not exist
        question = create_sample_analyzed_question()
        with patch("scripts.curriculum_mapping._safely_get_vectorstore", return_value=None):
            result = cm.map_single_question(question, store=None)

        mapping = result.curriculum_mapping
        self.assertEqual(mapping["mapping_status"], "unresolved")
        self.assertEqual(mapping["confidence_score"], 0.0)
        self.assertIsNone(mapping["matched_chunk_id"])
        self.assertIsNone(mapping["matched_source_document"])
        self.assertIsNone(mapping["matched_page_start"])
        self.assertIsNone(mapping["evidence_excerpt"])
        self.assertTrue(mapping["needs_review"])
        self.assertTrue(result.needs_teacher_review)
        self.assertTrue(any("vector store is not available" in r for r in mapping["review_reasons"]))

    def test_zero_retrieved_documents_reports_unresolved(self):
        mock_store = MagicMock()
        mock_store.similarity_search_with_relevance_scores.return_value = []

        question = create_sample_analyzed_question()
        result = cm.map_single_question(question, store=mock_store)

        mapping = result.curriculum_mapping
        self.assertEqual(mapping["mapping_status"], "unresolved")
        self.assertEqual(mapping["confidence_score"], 0.0)
        self.assertIsNone(mapping["matched_chunk_id"])
        self.assertTrue(mapping["needs_review"])
        self.assertTrue(any("No supporting curriculum chunks" in r for r in mapping["review_reasons"]))

    def test_missing_chunk_metadata_flags_low_confidence(self):
        doc = create_mock_doc(chunk_id="unknown", source="")
        mock_store = MagicMock()
        mock_store.similarity_search_with_relevance_scores.return_value = [(doc, 0.90)]

        question = create_sample_analyzed_question()
        result = cm.map_single_question(question, store=mock_store)

        mapping = result.curriculum_mapping
        self.assertEqual(mapping["mapping_status"], "low_confidence")
        self.assertTrue(mapping["needs_review"])
        self.assertTrue(any("lacks required chunk_id" in r for r in mapping["review_reasons"]))


class ExcerptAndNormalizationTests(unittest.TestCase):
    """Tests evidence excerpt extraction and lesson/chapter ID parsing."""

    def test_extract_evidence_excerpt_selects_most_relevant_sentence(self):
        text = (
            "First sentence introduces technology history. "
            "In autonomous driving systems, sensor fusion integrates cameras and lidar for real-time localization. "
            "Concluding sentence discusses ethical standards in society."
        )
        excerpt = cm.extract_evidence_excerpt(text, ["autonomous", "driving", "sensor", "lidar"])
        self.assertIn("sensor fusion integrates cameras", excerpt)
        self.assertNotIn("First sentence introduces", excerpt)

    def test_extract_lesson_id_from_various_formats(self):
        self.assertEqual(cm.extract_lesson_id_from_text("Lesson 1-1 Development"), "1-1")
        self.assertEqual(cm.extract_lesson_id_from_text("2-3 Machine Learning Models"), "2-3")
        self.assertEqual(cm.extract_lesson_id_from_text("1-1"), "1-1")
        self.assertIsNone(cm.extract_lesson_id_from_text("Overview of AI"))

    def test_extract_chapter_id_from_various_formats(self):
        self.assertEqual(cm.extract_chapter_id_from_text("Unit One: Information"), 1)
        self.assertEqual(cm.extract_chapter_id_from_text("Chapter 3: Deep Learning"), 3)
        self.assertEqual(cm.extract_chapter_id_from_text("2 Data Analysis"), 2)
        self.assertIsNone(cm.extract_chapter_id_from_text("General Introduction"))


class BatchMappingWorkflowTests(unittest.TestCase):
    """Tests batch curriculum mapping and failure resilience."""

    def test_batch_mapping_workflow_success(self):
        doc1 = create_mock_doc(chunk_id="1-1-001")
        doc2 = create_mock_doc(chunk_id="1-2-001")

        mock_store = MagicMock()
        mock_store.similarity_search_with_relevance_scores.side_effect = [
            [(doc1, 0.85)],
            [(doc2, 0.82)],
        ]

        q1 = create_sample_analyzed_question(qid="Q-01")
        q2 = create_sample_analyzed_question(qid="Q-02")

        batch_res = cm.map_questions_batch([q1, q2], store=mock_store)

        self.assertEqual(batch_res.total_questions, 2)
        self.assertEqual(batch_res.mapped_count, 2)
        self.assertEqual(batch_res.low_confidence_count, 0)
        self.assertEqual(batch_res.unresolved_count, 0)
        self.assertEqual(batch_res.failed_count, 0)
        self.assertEqual(batch_res.summary["mapping_rate"], 1.0)

    def test_batch_mapping_handles_retrieval_exception_with_partial_tolerance(self):
        doc1 = create_mock_doc(chunk_id="1-1-001")
        mock_store = MagicMock()
        mock_store.similarity_search_with_relevance_scores.side_effect = [
            [(doc1, 0.85)],
            RuntimeError("Chroma client connection terminated"),
        ]

        q1 = create_sample_analyzed_question(qid="Q-01")
        q2 = create_sample_analyzed_question(qid="Q-02")

        batch_res = cm.map_questions_batch([q1, q2], store=mock_store, allow_partial=True)

        self.assertEqual(batch_res.total_questions, 2)
        # Q-01 mapped, Q-02 caught retrieval error safely and resolved as 'unresolved'
        self.assertEqual(batch_res.mapped_count, 1)
        self.assertEqual(batch_res.unresolved_count, 1)
        self.assertEqual(batch_res.failed_count, 0)


if __name__ == "__main__":
    unittest.main()
