"""
Unit and integration tests for Question Bank API endpoints and classification workflows.
"""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import create_access_token, hash_password
from app.database import Base, get_db
from app.main import app
from app.models import QuestionBankItem, User

TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


Base.metadata.create_all(bind=test_engine)


class TestQuestionBankAPI(unittest.TestCase):
    """Test suite covering Question Bank endpoints, authentication, and review lifecycles."""

    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

        # Seed test users
        with TestingSessionLocal() as session:
            session.query(QuestionBankItem).delete()
            session.query(User).delete()
            prof = User(
                id=1,
                name="Prof. Turing",
                email="prof.turing@university.edu",
                hashed_password=hash_password("profpass123"),
                role="professor",
            )
            student = User(
                id=2,
                name="Alice Student",
                email="alice@student.edu",
                hashed_password=hash_password("studentpass123"),
                role="student",
            )
            session.add_all([prof, student])
            session.commit()

        cls.prof_token = create_access_token({"sub": "1", "role": "professor"})
        cls.student_token = create_access_token({"sub": "2", "role": "student"})

    @classmethod
    def tearDownClass(cls):
        app.dependency_overrides.pop(get_db, None)

    def setUp(self):
        app.dependency_overrides[get_db] = override_get_db
        with TestingSessionLocal() as session:
            session.query(QuestionBankItem).delete()
            session.commit()

    # -----------------------------------------------------------------------
    # Authentication & Role Authorization Tests
    # -----------------------------------------------------------------------

    def test_student_forbidden_from_listing_question_bank(self):
        """Students must receive 403 Forbidden on Question Bank endpoints."""
        headers = {"Authorization": f"Bearer {self.student_token}"}
        res = self.client.get("/api/question-bank", headers=headers)
        self.assertEqual(res.status_code, 403)

    def test_student_forbidden_from_importing_questions(self):
        headers = {"Authorization": f"Bearer {self.student_token}"}
        res = self.client.post("/api/question-bank/import", headers=headers)
        self.assertEqual(res.status_code, 403)

    def test_unauthenticated_request_rejected(self):
        res = self.client.get("/api/question-bank")
        self.assertEqual(res.status_code, 401)

    def test_professor_can_list_question_bank(self):
        """Authorized professors can query the Question Bank successfully."""
        headers = {"Authorization": f"Bearer {self.prof_token}"}
        res = self.client.get("/api/question-bank", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("items", data)
        self.assertIn("total", data)
        self.assertEqual(data["total"], 0)

    # -----------------------------------------------------------------------
    # Question Classification & Grounding Tests
    # -----------------------------------------------------------------------

    @patch("scripts.question_analysis._send_analysis_completion")
    @patch("scripts.curriculum_mapping._safely_get_vectorstore")
    def test_on_demand_question_classification(self, mock_vstore, mock_llm):
        """Verifies grounded curriculum classification with chunk citations."""
        # Mock vector store retrieval
        mock_doc = MagicMock()
        mock_doc.metadata = {
            "chunk_id": "1-1-001",
            "source": "Programming-AI.pdf",
            "chapter_id": 1,
            "chapter_title": "AI Fundamentals",
            "lesson_id": "1-1",
            "lesson_title": "Introduction to AI",
            "pdf_page_start": 4,
            "pdf_page_end": 5,
        }
        mock_doc.page_content = "Machine learning focuses on learning representations from data."
        mock_store = MagicMock()
        mock_store.similarity_search_with_relevance_scores.return_value = [(mock_doc, 0.88)]
        mock_vstore.return_value = mock_store

        # Mock LLM structured response
        mock_llm.return_value = json.dumps({
            "subject": "Artificial Intelligence",
            "unit": "Unit 1",
            "lesson": "Introduction to AI",
            "page_number": "4",
            "supporting_chunk_ids": ["1-1-001"],
            "source_evidence": "Machine learning focuses on learning representations from data.",
            "evidence_sufficient": True,
            "bloom_level": "Understand",
            "difficulty": "Easy",
            "classification_reasoning": "Requires recalling foundational definition of AI.",
            "reported_confidence": 0.90,
        })

        headers = {"Authorization": f"Bearer {self.prof_token}"}
        payload = {
            "question_text": "What is the primary objective of machine learning?",
            "question_type": "mcq",
            "options": ["Predict patterns", "Compile code", "Design circuits", "Format drives"],
            "correct_answer": "Predict patterns",
            "top_k": 3,
            "persist": False,
        }
        res = self.client.post("/api/question-bank/classify", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["bloom_level"], "Understand")
        self.assertEqual(body["difficulty"], "Easy")
        self.assertEqual(body["lesson"], "Introduction to AI")
        self.assertEqual(body["source_chunk_ids"], ["1-1-001"])
        self.assertEqual(body["classification_status"], "pending_review")
        self.assertFalse(body["needs_teacher_review"])

    @patch("scripts.question_analysis._send_analysis_completion")
    @patch("scripts.curriculum_mapping._safely_get_vectorstore")
    def test_unsupported_evidence_triggers_needs_review(self, mock_vstore, mock_llm):
        """When curriculum evidence is missing or unrelated, status must be needs_review."""
        # Zero documents retrieved
        mock_store = MagicMock()
        mock_store.similarity_search_with_relevance_scores.return_value = []
        mock_vstore.return_value = mock_store

        mock_llm.return_value = json.dumps({
            "subject": "Unknown",
            "unit": "Unknown",
            "lesson": "Unknown",
            "page_number": None,
            "supporting_chunk_ids": ["hallucinated-chunk-999"],  # must be stripped!
            "source_evidence": None,
            "evidence_sufficient": False,
            "bloom_level": "Analyze",
            "difficulty": "Hard",
            "classification_reasoning": "Evidence not found in curriculum.",
            "reported_confidence": 0.30,
        })

        headers = {"Authorization": f"Bearer {self.prof_token}"}
        payload = {
            "question_text": "Explain quantum entanglement in superconducting qubits.",
            "question_type": "essay",
            "correct_answer": "Superconducting qubits exhibit entangled states...",
            "persist": True,
        }
        res = self.client.post("/api/question-bank/classify", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)
        body = res.json()

        # Hallucinated chunk must be stripped
        self.assertEqual(body["source_chunk_ids"], [])
        self.assertEqual(body["classification_status"], "needs_review")
        self.assertTrue(body["needs_teacher_review"])
        self.assertIsNotNone(body["persisted_item"])

    # -----------------------------------------------------------------------
    # Review Lifecycle Tests (Approval, Rejection, Edits)
    # -----------------------------------------------------------------------

    def test_approve_question_records_corrections_and_reviewer(self):
        """Approving a question updates status, timestamps, and saves teacher corrections."""
        with TestingSessionLocal() as session:
            item = QuestionBankItem(
                question_id="Q-TEST-001",
                question_type="mcq",
                question_text="What is gradient descent?",
                correct_answer="Optimization algorithm",
                bloom_level="Remember",
                difficulty="Easy",
                classification_status="needs_review",
                needs_teacher_review=True,
            )
            session.add(item)
            session.commit()

        headers = {"Authorization": f"Bearer {self.prof_token}"}
        payload = {
            "corrections": {
                "bloom_level": "Understand",
                "difficulty": "Medium",
            },
            "notes": "Upgraded difficulty due to multi-step conceptual understanding.",
        }
        res = self.client.post(
            "/api/question-bank/Q-TEST-001/approve", json=payload, headers=headers
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["classification_status"], "approved")
        self.assertEqual(body["bloom_level"], "Understand")
        self.assertEqual(body["difficulty"], "Medium")
        self.assertEqual(body["reviewed_by"], "Prof. Turing")
        self.assertIsNotNone(body["reviewed_at"])
        self.assertEqual(body["review_notes"], "Upgraded difficulty due to multi-step conceptual understanding.")
        self.assertIsNotNone(body["teacher_corrections"])

    def test_reject_question_records_reviewer_notes(self):
        with TestingSessionLocal() as session:
            item = QuestionBankItem(
                question_id="Q-TEST-002",
                question_type="mcq",
                question_text="Flawed question with ambiguous choices",
                correct_answer="None",
                classification_status="pending_review",
            )
            session.add(item)
            session.commit()

        headers = {"Authorization": f"Bearer {self.prof_token}"}
        payload = {"notes": "Distractors are ambiguous; question rejected."}
        res = self.client.post(
            "/api/question-bank/Q-TEST-002/reject", json=payload, headers=headers
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["classification_status"], "rejected")
        self.assertEqual(body["review_notes"], "Distractors are ambiguous; question rejected.")

    def test_patch_question_updates_fields(self):
        with TestingSessionLocal() as session:
            item = QuestionBankItem(
                question_id="Q-TEST-003",
                question_type="mcq",
                question_text="Old question prompt?",
                correct_answer="Old Answer",
                classification_status="pending_review",
            )
            session.add(item)
            session.commit()

        headers = {"Authorization": f"Bearer {self.prof_token}"}
        patch_payload = {
            "question_text": "Refined and clarified question prompt?",
            "difficulty": "Hard",
            "bloom_level": "Apply",
        }
        res = self.client.patch(
            "/api/question-bank/Q-TEST-003", json=patch_payload, headers=headers
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["question_text"], "Refined and clarified question prompt?")
        self.assertEqual(body["difficulty"], "Hard")
        self.assertEqual(body["bloom_level"], "Apply")

    # -----------------------------------------------------------------------
    # Multi-format Import Endpoints (JSON, CSV, DOCX, PDF)
    # -----------------------------------------------------------------------

    def test_import_json_questions(self):
        headers = {"Authorization": f"Bearer {self.prof_token}"}
        json_data = [
            {
                "question_id": "IMP-JSON-001",
                "question_type": "mcq",
                "question_text": "What is backpropagation?",
                "option_A": "Algorithm for calculating gradients",
                "option_B": "Database transaction",
                "option_C": "Hardware clock",
                "option_D": "Cache policy",
                "correct_option": "A",
                "correct_answer": "Algorithm for calculating gradients",
            }
        ]
        file_bytes = json.dumps(json_data).encode("utf-8")
        files = {"file": ("test_questions.json", file_bytes, "application/json")}
        data = {"auto_classify": "false", "skip_embedding": "true"}

        res = self.client.post(
            "/api/question-bank/import", files=files, data=data, headers=headers
        )
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["valid_count"], 1)
        self.assertEqual(body["inserted"], 1)

    def test_import_unsupported_format_returns_clear_error(self):
        headers = {"Authorization": f"Bearer {self.prof_token}"}
        files = {"file": ("unsupported_data.xyz", b"fake binary content", "application/octet-stream")}
        res = self.client.post("/api/question-bank/import", files=files, headers=headers)
        self.assertEqual(res.status_code, 400)
        self.assertIn("Unsupported file format", res.json()["detail"])

    # -----------------------------------------------------------------------
    # Summary Statistics & Learning Readiness Tests
    # -----------------------------------------------------------------------

    def test_summary_statistics_endpoint(self):
        with TestingSessionLocal() as session:
            q1 = QuestionBankItem(
                question_id="Q-STAT-1",
                question_type="mcq",
                question_text="Q1",
                correct_answer="A1",
                difficulty="Easy",
                bloom_level="Remember",
                classification_status="approved",
            )
            q2 = QuestionBankItem(
                question_id="Q-STAT-2",
                question_type="essay",
                question_text="Q2",
                correct_answer="A2",
                difficulty="Hard",
                bloom_level="Evaluate",
                classification_status="needs_review",
            )
            session.add_all([q1, q2])
            session.commit()

        headers = {"Authorization": f"Bearer {self.prof_token}"}
        res = self.client.get("/api/question-bank/summary", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total_questions"], 2)
        self.assertEqual(data["approved_count"], 1)
        self.assertEqual(data["needs_review_count"], 1)
        self.assertEqual(data["difficulty_distribution"].get("Easy"), 1)
        self.assertEqual(data["difficulty_distribution"].get("Hard"), 1)

    def test_learning_stats_reports_active_method_and_sample_counts(self):
        headers = {"Authorization": f"Bearer {self.prof_token}"}
        res = self.client.get("/api/question-bank/learning-stats", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["active_method"], "rag_llm")
        self.assertIn("approved_sample_count", data)
        self.assertIn("is_ready_for_supervised_training", data)
        self.assertFalse(data["is_ready_for_supervised_training"])
        self.assertIn("guidance", data)

    # -----------------------------------------------------------------------
    # Regression Tests for Correct Options, Error Handling, and Grounding
    # -----------------------------------------------------------------------

    def test_empty_question_bank_does_not_fabricate_questions(self):
        """Empty question bank must return empty list, not any fabricated/sample questions."""
        headers = {"Authorization": f"Bearer {self.prof_token}"}
        res = self.client.get("/api/question-bank", headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["items"], [])

    @patch("scripts.question_analysis._send_analysis_completion")
    @patch("scripts.curriculum_mapping._safely_get_vectorstore")
    def test_mcq_correct_options_a_b_c_d_preserved(self, mock_vstore, mock_llm):
        """Verify that MCQ options A, B, C, and D are preserved accurately and not defaulted to A."""
        mock_vstore.return_value = None
        mock_llm.return_value = json.dumps({
            "bloom_level": "Understand",
            "difficulty": "Medium",
            "evidence_sufficient": False,
            "subject": "Unknown",
            "unit": "Unknown",
            "lesson": "Unknown",
            "page_number": None,
            "supporting_chunk_ids": [],
            "source_evidence": None,
            "classification_reasoning": "Standard cognitive task.",
            "reported_confidence": 0.85,
        })
        headers = {"Authorization": f"Bearer {self.prof_token}"}

        options = ["Option 1", "Option 2", "Option 3", "Option 4"]
        for letter, idx in [("A", 0), ("B", 1), ("C", 2), ("D", 3)]:
            payload = {
                "question_text": f"Question testing option {letter}?",
                "question_type": "mcq",
                "options": options,
                "correct_option": letter,
                "correct_answer": options[idx],
                "persist": True,
            }
            res = self.client.post("/api/question-bank/classify", json=payload, headers=headers)
            self.assertEqual(res.status_code, 200)
            body = res.json()
            self.assertEqual(body["correct_option"], letter)
            self.assertEqual(body["correct_answer"], options[idx])
            self.assertIsNotNone(body["persisted_item"])
            self.assertEqual(body["persisted_item"]["correct_option"], letter)
            self.assertEqual(body["persisted_item"]["correct_answer"], options[idx])

    def test_mcq_missing_correct_answer_is_rejected(self):
        """MCQ with missing correct_option and non-matching correct_answer must be rejected (422), never defaulted to A."""
        headers = {"Authorization": f"Bearer {self.prof_token}"}
        payload = {
            "question_text": "What is the capital of France?",
            "question_type": "mcq",
            "options": ["London", "Berlin", "Madrid", "Rome"],
            "correct_option": None,
            "correct_answer": "",
            "persist": False,
        }
        res = self.client.post("/api/question-bank/classify", json=payload, headers=headers)
        self.assertEqual(res.status_code, 422)

    @patch("scripts.question_analysis._send_analysis_completion")
    @patch("scripts.curriculum_mapping._safely_get_vectorstore")
    def test_llm_failure_reported_honestly(self, mock_vstore, mock_llm):
        """When the LLM model call fails, API must return an error status, not a fake successful 200 classification."""
        mock_vstore.return_value = None
        mock_llm.side_effect = Exception("Groq rate limit exceeded or connection timeout")

        headers = {"Authorization": f"Bearer {self.prof_token}"}
        payload = {
            "question_text": "Describe binary search algorithm.",
            "question_type": "essay",
            "correct_answer": "Divide and conquer search algorithm.",
            "persist": False,
        }
        res = self.client.post("/api/question-bank/classify", json=payload, headers=headers)
        self.assertEqual(res.status_code, 503)
        self.assertIn("Groq rate limit exceeded", res.json()["detail"])

    @patch("scripts.question_analysis._send_analysis_completion")
    @patch("scripts.curriculum_mapping._safely_get_vectorstore")
    def test_insufficient_evidence_produces_explicit_warning(self, mock_vstore, mock_llm):
        """When question is outside the curriculum, lesson must be Unknown with explicit review warning."""
        mock_store = MagicMock()
        mock_store.similarity_search_with_relevance_scores.return_value = []
        mock_vstore.return_value = mock_store

        mock_llm.return_value = json.dumps({
            "bloom_level": "Remember",
            "difficulty": "Easy",
            "evidence_sufficient": False,
            "subject": "Unknown",
            "unit": "Unknown",
            "lesson": "Unknown",
            "page_number": None,
            "supporting_chunk_ids": [],
            "source_evidence": None,
            "classification_reasoning": "Recall of factual capital city.",
            "reported_confidence": 0.90,
        })

        headers = {"Authorization": f"Bearer {self.prof_token}"}
        payload = {
            "question_text": "What is the capital of Canada?",
            "question_type": "mcq",
            "options": ["Toronto", "Ottawa", "Montreal", "Vancouver"],
            "correct_option": "B",
            "correct_answer": "Ottawa",
            "persist": False,
        }
        res = self.client.post("/api/question-bank/classify", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["bloom_level"], "Remember")
        self.assertEqual(body["difficulty"], "Easy")
        self.assertEqual(body["lesson"], "Unknown")
        self.assertTrue(body["needs_teacher_review"])
        self.assertTrue(any("curriculum" in r.lower() for r in body["review_reasons"]))
        self.assertEqual(body["source_chunk_ids"], [])
    @patch("scripts.question_analysis._send_analysis_completion")
    @patch("scripts.curriculum_mapping._safely_get_vectorstore")
    def test_bloom_and_difficulty_classified_without_curriculum_match(self, mock_vstore, mock_llm):
        """Bloom and Difficulty must be classified from question cognitive demand even when curriculum retrieval finds no chunks."""
        mock_store = MagicMock()
        mock_store.similarity_search_with_relevance_scores.return_value = []
        mock_vstore.return_value = mock_store

        mock_llm.return_value = json.dumps({
            "bloom_level": "Remember",
            "difficulty": "Easy",
            "evidence_sufficient": False,
            "subject": "Unknown",
            "unit": "Unknown",
            "lesson": "Unknown",
            "page_number": None,
            "supporting_chunk_ids": [],
            "source_evidence": None,
            "classification_reasoning": "Recalls LIFO vs FIFO data structure fundamentals.",
            "reported_confidence": 0.85,
        })

        headers = {"Authorization": f"Bearer {self.prof_token}"}
        payload = {
            "question_text": "What is the primary difference between a stack and a queue?",
            "question_type": "mcq",
            "options": ["Stack is LIFO, Queue is FIFO", "Stack is FIFO, Queue is LIFO", "Both are LIFO", "Both are FIFO"],
            "correct_option": "A",
            "correct_answer": "Stack is LIFO, Queue is FIFO",
            "persist": False,
        }
        res = self.client.post("/api/question-bank/classify", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)
        body = res.json()

        # Decoupled behavior: Bloom & Difficulty preserved, Subject & Lesson unmapped
        self.assertEqual(body["bloom_level"], "Remember")
        self.assertEqual(body["difficulty"], "Easy")
        self.assertEqual(body["subject"], "Unknown")
        self.assertEqual(body["lesson"], "Unknown")
        # Confidence reflects cognitive classification certainty, not penalized to 20%
        self.assertEqual(body["classification_confidence"], 0.85)
        self.assertEqual(body["grounding_confidence"], 0.0)
        self.assertTrue(body["needs_teacher_review"])
        self.assertTrue(any("curriculum" in r.lower() for r in body["review_reasons"]))

    @patch("scripts.question_analysis._send_analysis_completion")
    @patch("scripts.curriculum_mapping._safely_get_vectorstore")
    def test_llm_success_never_returns_unknown_bloom_or_difficulty(self, mock_vstore, mock_llm):
        """When LLM succeeds but returns invalid/unknown labels, fallbacks must be valid levels (not Unknown)."""
        mock_vstore.return_value = None
        mock_llm.return_value = json.dumps({
            "bloom_level": "InvalidTaxonomyLevel",
            "difficulty": "SuperHard",
            "evidence_sufficient": False,
            "subject": "Unknown",
            "unit": "Unknown",
            "lesson": "Unknown",
            "supporting_chunk_ids": [],
            "reported_confidence": 0.75,
        })

        headers = {"Authorization": f"Bearer {self.prof_token}"}
        payload = {
            "question_text": "Define recursion in programming.",
            "question_type": "essay",
            "correct_answer": "A function calling itself.",
            "persist": False,
        }
        res = self.client.post("/api/question-bank/classify", json=payload, headers=headers)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertIn(body["bloom_level"], ["Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create"])
        self.assertIn(body["difficulty"], ["Easy", "Medium", "Hard"])
        self.assertNotEqual(body["bloom_level"], "Unknown")
        self.assertNotEqual(body["difficulty"], "Unknown")


    # ---------------------------------------------------------------------------
    # Cleaned Dataset Endpoint Tests (Stage 4 / Cleaned Dataset Integration)
    # ---------------------------------------------------------------------------

    def test_cleaned_dataset_endpoint_requires_professor(self):
        """Students or unauthenticated callers cannot access cleaned dataset."""
        res_no_auth = self.client.get("/api/question-bank/cleaned-dataset")
        self.assertEqual(res_no_auth.status_code, 401)

        student_headers = {"Authorization": f"Bearer {self.student_token}"}
        res_student = self.client.get("/api/question-bank/cleaned-dataset", headers=student_headers)
        self.assertEqual(res_student.status_code, 403)

    def test_cleaned_dataset_endpoint_success(self):
        """Professors can query paginated cleaned dataset questions with provenance."""
        headers = {"Authorization": f"Bearer {self.prof_token}"}
        res = self.client.get("/api/question-bank/cleaned-dataset", params={"page": 1, "page_size": 15}, headers=headers)
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["total"], 317)
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["page_size"], 15)
        self.assertEqual(len(data["items"]), 15)
        self.assertGreater(data["total_pages"], 1)

        # Check provenance
        prov = data["provenance"]
        self.assertEqual(prov["valid_rows"], 317)
        self.assertEqual(len(prov["sha256_hash"]), 64)
        self.assertFalse(prov["has_difficulty_labels"])
        self.assertFalse(prov["has_bloom_labels"])

        # Check item structure
        first_item = data["items"][0]
        self.assertIn("question_id", first_item)
        self.assertIn("question_text", first_item)
        self.assertIn("question_type", first_item)
        self.assertIn("correct_answer", first_item)

    def test_cleaned_dataset_endpoint_filtering(self):
        """Filters by question_type, search, and chapter work accurately."""
        headers = {"Authorization": f"Bearer {self.prof_token}"}

        # Filter by mcq
        res_mcq = self.client.get("/api/question-bank/cleaned-dataset", params={"question_type": "mcq"}, headers=headers)
        self.assertEqual(res_mcq.status_code, 200)
        data_mcq = res_mcq.json()
        self.assertEqual(data_mcq["total"], 168)
        for it in data_mcq["items"]:
            self.assertEqual(it["question_type"], "mcq")
            self.assertEqual(len(it["options"]), 4)

        # Filter by essay
        res_essay = self.client.get("/api/question-bank/cleaned-dataset", params={"question_type": "essay"}, headers=headers)
        self.assertEqual(res_essay.status_code, 200)
        data_essay = res_essay.json()
        self.assertEqual(data_essay["total"], 149)
        for it in data_essay["items"]:
            self.assertEqual(it["question_type"], "essay")

    def test_cleaned_dataset_provenance_endpoint(self):
        """Dedicated provenance endpoint returns valid file metadata."""
        headers = {"Authorization": f"Bearer {self.prof_token}"}
        res = self.client.get("/api/question-bank/cleaned-dataset/provenance", headers=headers)
        self.assertEqual(res.status_code, 200)
        prov = res.json()
        self.assertEqual(prov["valid_rows"], 317)
        self.assertEqual(len(prov["sha256_hash"]), 64)

    def test_cleaned_dataset_does_not_mutate_db(self):
        """Read-only guarantee: querying the cleaned dataset does NOT write to SQLite."""
        headers = {"Authorization": f"Bearer {self.prof_token}"}
        with TestingSessionLocal() as session:
            count_before = session.query(QuestionBankItem).count()

        res = self.client.get("/api/question-bank/cleaned-dataset", params={"page": 1, "page_size": 50}, headers=headers)
        self.assertEqual(res.status_code, 200)

        with TestingSessionLocal() as session:
            count_after = session.query(QuestionBankItem).count()

        self.assertEqual(count_before, count_after, "Cleaned dataset queries must be 100% read-only with zero DB mutations")
