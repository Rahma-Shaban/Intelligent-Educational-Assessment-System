"""Tests for professor-scoped documents, student professor selection,
published-exam visibility, and professor question editing."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Curriculum, Exam, User

TEST_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
Base.metadata.create_all(bind=engine)


def _make_valid_question(index: int = 1) -> dict:
    return {
        "question": f"Identify concept{index} principle{index}.",
        "question_type": "short_answer",
        "difficulty": "medium",
        "bloom_level": "apply",
        "bloom_rationale": "Applies a distinct curriculum fact.",
        "options": [],
        "correct_answer": "",
        "reference_answer": f"Evidence answer{index}.",
        "explanation": "The cited curriculum passage supports the answer.",
        "max_score": 2,
        "rubric": [
            {
                "criterion": "Identifies the fact",
                "points": 1,
                "description": "Names the distinct supported fact.",
            },
            {
                "criterion": "Explains the principle",
                "points": 1,
                "description": "Connects the fact to its underlying principle.",
            },
        ],
        "source_refs": [
            {
                "source": "textbook_a.pdf",
                "chunk_id": f"1-1-{index:03d}",
                "evidence_quote": "Curriculum fact number %d." % index,
            }
        ],
    }


def _make_mcq_question() -> dict:
    return {
        "question": "Which structure maps keys to values?",
        "question_type": "mcq",
        "difficulty": "easy",
        "bloom_level": "remember",
        "bloom_rationale": "Recalls a definition.",
        "options": ["A. List", "B. Dictionary", "C. Set", "D. Tuple"],
        "correct_answer": "B",
        "reference_answer": "B. Dictionary",
        "explanation": "Dictionaries map keys to values.",
        "max_score": 1,
        "rubric": [
            {
                "criterion": "Selects the correct option",
                "points": 1,
                "description": "Chooses the dictionary option.",
            }
        ],
        "source_refs": [
            {
                "source": "textbook_a.pdf",
                "chunk_id": "1-1-001",
                "evidence_quote": "Dictionaries map keys to values.",
            }
        ],
    }


class ProfessorScopingTestCase(unittest.TestCase):
    """Document library scoping, professor selection, exam visibility, editing."""

    @classmethod
    def setUpClass(cls):
        # Re-assert this module's DB override in case another test module
        # registered its own override on the shared app singleton earlier.
        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

        # Register two professors and one student
        cls.client.post("/api/auth/register", json={
            "name": "Dr. Adams", "email": "adams@uni.edu",
            "password": "password123", "role": "professor",
        })
        cls.client.post("/api/auth/register", json={
            "name": "Dr. Baker", "email": "baker@uni.edu",
            "password": "password123", "role": "professor",
        })
        cls.client.post("/api/auth/register", json={
            "name": "Chico Student", "email": "chico@student.edu",
            "password": "password123", "role": "student",
        })

        cls.adams = cls._login("adams@uni.edu")
        cls.baker = cls._login("baker@uni.edu")
        cls.chico = cls._login("chico@student.edu")

        # Seed one owned document per professor
        db = TestingSessionLocal()
        adams_user = db.query(User).filter_by(email="adams@uni.edu").first()
        baker_user = db.query(User).filter_by(email="baker@uni.edu").first()
        db.add(Curriculum(
            filename="textbook_a.pdf",
            lessons_json=json.dumps([
                {"lesson_id": "1-1", "lesson_title": "Lesson One"},
                {"lesson_id": "1-2", "lesson_title": "Lesson Two"},
            ]),
            vector_store_path="data/processed/chroma_db",
            professor_id=adams_user.id,
            collection_name="curriculum_seed_a",
            uploaded_at=datetime.now(timezone.utc),
        ))
        db.add(Curriculum(
            filename="textbook_b.pdf",
            lessons_json=json.dumps([
                {"lesson_id": "9-1", "lesson_title": "Baker Lesson"},
            ]),
            vector_store_path="data/processed/chroma_db",
            professor_id=baker_user.id,
            collection_name="curriculum_seed_b",
            uploaded_at=datetime.now(timezone.utc),
        ))
        db.commit()
        db.close()

    @classmethod
    def _login(cls, email: str) -> dict:
        res = cls.client.post("/api/auth/login", json={
            "email": email, "password": "password123",
        })
        assert res.status_code == 200, res.text
        user = res.json()["user"]
        return {"token": res.json()["access_token"], "user": user}

    def _headers(self, who: dict) -> dict:
        return {"Authorization": f"Bearer {who['token']}"}

    # ------------------------------------------------------------------
    # 1. Document library scoping
    # ------------------------------------------------------------------
    def test_01_document_library_is_professor_scoped(self):
        r = self.client.get("/api/curriculum", headers=self._headers(self.adams))
        self.assertEqual(r.status_code, 200)
        docs = r.json()
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["filename"], "textbook_a.pdf")
        self.assertEqual(docs[0]["lesson_count"], 2)
        self.assertEqual(docs[0]["professor_id"], self.adams["user"]["id"])

        r_b = self.client.get("/api/curriculum", headers=self._headers(self.baker))
        self.assertEqual(r_b.status_code, 200)
        filenames = [d["filename"] for d in r_b.json()]
        self.assertEqual(filenames, ["textbook_b.pdf"])

    def test_02_lessons_endpoint_scoped_to_document(self):
        db = TestingSessionLocal()
        doc_a = db.query(Curriculum).filter_by(filename="textbook_a.pdf").first()
        doc_b = db.query(Curriculum).filter_by(filename="textbook_b.pdf").first()
        db.close()

        r = self.client.get(
            f"/api/curriculum/{doc_a.id}/lessons", headers=self._headers(self.adams)
        )
        self.assertEqual(r.status_code, 200)
        lesson_ids = [ls["lesson_id"] for ls in r.json()]
        self.assertEqual(lesson_ids, ["1-1", "1-2"])

        # Baker's lessons never leak into Adams' document
        r_b = self.client.get(
            f"/api/curriculum/{doc_b.id}/lessons", headers=self._headers(self.baker)
        )
        self.assertEqual(r_b.status_code, 200)
        self.assertEqual([ls["lesson_id"] for ls in r_b.json()], ["9-1"])

    def test_03_other_professor_cannot_read_foreign_document(self):
        db = TestingSessionLocal()
        doc_b = db.query(Curriculum).filter_by(filename="textbook_b.pdf").first()
        db.close()

        r = self.client.get(
            f"/api/curriculum/{doc_b.id}/lessons", headers=self._headers(self.adams)
        )
        self.assertEqual(r.status_code, 403)

    # ------------------------------------------------------------------
    # 2. Exam generation requires owned textbook + scoped lessons
    # ------------------------------------------------------------------
    def test_04_generation_requires_existing_textbook(self):
        r = self.client.post("/api/exams/generate", headers=self._headers(self.adams), json={
            "curriculum_id": 999999,
            "lesson_id": "1-1",
            "topic": "Lesson One",
            "question_types": ["short_answer"],
            "number_of_questions": 2,
        })
        self.assertEqual(r.status_code, 404)

    def test_05_generation_rejects_foreign_textbook(self):
        db = TestingSessionLocal()
        doc_b = db.query(Curriculum).filter_by(filename="textbook_b.pdf").first()
        db.close()
        r = self.client.post("/api/exams/generate", headers=self._headers(self.adams), json={
            "curriculum_id": doc_b.id,
            "lesson_id": "9-1",
            "topic": "Baker Lesson",
            "question_types": ["short_answer"],
            "number_of_questions": 2,
        })
        self.assertEqual(r.status_code, 403)

    def test_06_generation_with_owned_textbook_creates_scoped_exam(self):
        db = TestingSessionLocal()
        doc_a = db.query(Curriculum).filter_by(filename="textbook_a.pdf").first()
        curriculum_id = doc_a.id
        db.close()

        docs = [
            type("Document", (), {
                "page_content": f"Curriculum fact number {i}.",
                "metadata": {"source": "textbook_a.pdf", "lesson_id": "1-1",
                             "lesson_title": "Lesson One", "chunk_id": f"1-1-{i:03d}"},
            })()
            for i in (1, 2)
        ]
        docs_by_id = {doc.metadata["chunk_id"]: doc for doc in docs}

        def mocked_model(prompt, **kwargs):
            import re as _re
            match = _re.search(r"this chunk_id: ([A-Za-z0-9_-]+)", prompt)
            chunk_id = match.group(1)
            index = int(chunk_id.rsplit("-", 1)[1])
            document = docs_by_id[chunk_id]
            question = _make_valid_question(index)
            question["source_refs"] = [{
                "source": "textbook_a.pdf",
                "chunk_id": chunk_id,
                "evidence_quote": document.page_content,
            }]
            return json.dumps(question)

        with (
            patch("scripts.generation.validate_configuration", return_value=(True, [], "mock-model")),
            patch("scripts.generation.retrieve_curriculum_context", return_value=docs),
            patch("scripts.generation._send_completion", side_effect=mocked_model),
            patch("scripts.generation.save_exam", return_value=Path("mock-exam.json")),
        ):
            r = self.client.post("/api/exams/generate", headers=self._headers(self.adams), json={
                "curriculum_id": curriculum_id,
                "lesson_id": "1-1",
                "topic": "Lesson One",
                "question_types": ["short_answer"],
                "number_of_questions": 2,
            })

        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertEqual(body["curriculum_id"], curriculum_id)
        self.assertFalse(body["is_published"])

        # Professor list contains own exam; Baker sees none
        r_list = self.client.get("/api/exams", headers=self._headers(self.adams))
        self.assertEqual(r_list.status_code, 200)
        self.assertEqual(len(r_list.json()), 1)

        r_list_b = self.client.get("/api/exams", headers=self._headers(self.baker))
        self.assertEqual(r_list_b.status_code, 200)
        self.assertEqual(len(r_list_b.json()), 0)

        # Professor cannot publish someone else's exam
        exam_id = body["id"]
        r_baker_publish = self.client.patch(
            f"/api/exams/{exam_id}/publish",
            headers=self._headers(self.baker),
            json={"is_published": True},
        )
        self.assertEqual(r_baker_publish.status_code, 403)

    # ------------------------------------------------------------------
    # 3. Student professor selection + published exam visibility
    # ------------------------------------------------------------------
    def test_07_professor_listing_and_invalid_selection(self):
        r = self.client.get("/api/auth/professors", headers=self._headers(self.chico))
        self.assertEqual(r.status_code, 200)
        names = [p["name"] for p in r.json()]
        self.assertIn("Dr. Adams", names)
        self.assertIn("Dr. Baker", names)

        # Invalid professor id rejected
        r_bad = self.client.put(
            "/api/auth/select-professor",
            headers=self._headers(self.chico),
            json={"professor_id": 999999},
        )
        self.assertEqual(r_bad.status_code, 400)

        # Professors cannot select professors
        r_role = self.client.put(
            "/api/auth/select-professor",
            headers=self._headers(self.adams),
            json={"professor_id": 1},
        )
        self.assertEqual(r_role.status_code, 403)

    def test_08_student_sees_nothing_before_selection(self):
        r = self.client.get("/api/exams", headers=self._headers(self.chico))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_09_student_scoped_to_selected_professor(self):
        db = TestingSessionLocal()
        adams_exam = db.query(Exam).filter_by(topic="Lesson One").first()
        self.assertIsNotNone(adams_exam)
        adams_user = db.query(User).filter_by(email="adams@uni.edu").first()
        db.close()

        # Select Adams
        r_sel = self.client.put(
            "/api/auth/select-professor",
            headers=self._headers(self.chico),
            json={"professor_id": adams_user.id},
        )
        self.assertEqual(r_sel.status_code, 200)
        self.assertEqual(r_sel.json()["selected_professor_id"], adams_user.id)

        # Unpublished exam not visible even from selected professor
        r_unpub = self.client.get("/api/exams", headers=self._headers(self.chico))
        self.assertEqual(r_unpub.status_code, 200)
        self.assertEqual(r_unpub.json(), [])

        r_unpub_detail = self.client.get(
            f"/api/exams/{adams_exam.id}", headers=self._headers(self.chico)
        )
        self.assertEqual(r_unpub_detail.status_code, 403)

        # Publish Adams' exam -> now visible, sanitized
        r_pub = self.client.patch(
            f"/api/exams/{adams_exam.id}/publish",
            headers=self._headers(self.adams),
            json={"is_published": True},
        )
        self.assertEqual(r_pub.status_code, 200)
        self.assertTrue(r_pub.json()["is_published"])

        r_vis = self.client.get("/api/exams", headers=self._headers(self.chico))
        self.assertEqual(r_vis.status_code, 200)
        self.assertEqual(len(r_vis.json()), 1)
        self.assertEqual(r_vis.json()[0]["id"], adams_exam.id)

        # Answer keys stripped for students
        r_detail = self.client.get(
            f"/api/exams/{adams_exam.id}", headers=self._headers(self.chico)
        )
        self.assertEqual(r_detail.status_code, 200)
        for q in r_detail.json()["questions"]:
            self.assertNotIn("correct_answer", q)
            self.assertNotIn("reference_answer", q)
            self.assertNotIn("rubric", q)

        # Attempt on the selected professor's published exam succeeds
        r_start = self.client.post(
            "/api/attempts/start",
            headers=self._headers(self.chico),
            json={"exam_id": adams_exam.id},
        )
        self.assertEqual(r_start.status_code, 201, r_start.text)

        # Switching selection hides the previous professor's exams
        db = TestingSessionLocal()
        baker_user = db.query(User).filter_by(email="baker@uni.edu").first()
        db.close()
        r_switch = self.client.put(
            "/api/auth/select-professor",
            headers=self._headers(self.chico),
            json={"professor_id": baker_user.id},
        )
        self.assertEqual(r_switch.status_code, 200)

        r_after = self.client.get("/api/exams", headers=self._headers(self.chico))
        self.assertEqual(r_after.status_code, 200)
        self.assertEqual(r_after.json(), [])

        r_start_foreign = self.client.post(
            "/api/attempts/start",
            headers=self._headers(self.chico),
            json={"exam_id": adams_exam.id},
        )
        self.assertEqual(r_start_foreign.status_code, 403)

        # Restore selection for later tests
        self.client.put(
            "/api/auth/select-professor",
            headers=self._headers(self.chico),
            json={"professor_id": adams_user.id},
        )

    # ------------------------------------------------------------------
    # 4. Professor question editing with rubric-aware grading integrity
    # ------------------------------------------------------------------
    def test_10_question_edit_updates_exam_and_grading_source(self):
        db = TestingSessionLocal()
        adams_exam = db.query(Exam).filter_by(topic="Lesson One").first()
        exam_id = adams_exam.id
        original = json.loads(adams_exam.exam_json)
        db.close()
        self.assertEqual(original["questions"][0]["reference_answer"], "Evidence answer1.")

        payload = {
            "question": "Explain how concept1 differs from concept2.",
            "question_type": "short_answer",
            "difficulty": "hard",
            "bloom_level": "analyze",
            "options": [],
            "correct_answer": "",
            "reference_answer": "Concept1 focuses on X while concept2 focuses on Y.",
            "explanation": "Comparison requires contrasting the two definitions.",
            "max_score": 3,
            "rubric": [
                {"criterion": "Names concept1", "points": 1, "description": "States X."},
                {"criterion": "Names concept2", "points": 1, "description": "States Y."},
                {"criterion": "Contrasts them", "points": 1, "description": "Explicit contrast."},
            ],
            "bloom_rationale": "Requires analysis of two related concepts.",
        }

        r = self.client.patch(
            f"/api/exams/{exam_id}/questions/0",
            headers=self._headers(self.adams),
            json=payload,
        )
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        edited = body["questions"][0]
        self.assertEqual(edited["question"], payload["question"])
        self.assertEqual(edited["reference_answer"], payload["reference_answer"])
        self.assertEqual(len(edited["rubric"]), 3)
        # Q1 edited to 3 pts + Q2 untouched at 2 pts
        self.assertEqual(body["total_points"], 5.0)

        # Professor-only: Baker and the student cannot edit
        r_baker = self.client.patch(
            f"/api/exams/{exam_id}/questions/0",
            headers=self._headers(self.baker),
            json=payload,
        )
        self.assertEqual(r_baker.status_code, 403)

        r_student = self.client.patch(
            f"/api/exams/{exam_id}/questions/0",
            headers=self._headers(self.chico),
            json=payload,
        )
        self.assertEqual(r_student.status_code, 403)

    def test_11_question_edit_rejects_rubric_score_mismatch(self):
        db = TestingSessionLocal()
        adams_exam = db.query(Exam).filter_by(topic="Lesson One").first()
        exam_id = adams_exam.id
        db.close()

        payload = {
            "question": "Bad rubric question.",
            "question_type": "short_answer",
            "difficulty": "medium",
            "bloom_level": "apply",
            "options": [],
            "correct_answer": "",
            "reference_answer": "Some answer.",
            "explanation": "Some explanation.",
            "max_score": 5,  # rubric sums to 2 -> must be rejected
            "rubric": [
                {"criterion": "A", "points": 1, "description": "a."},
                {"criterion": "B", "points": 1, "description": "b."},
            ],
        }
        r = self.client.patch(
            f"/api/exams/{exam_id}/questions/0",
            headers=self._headers(self.adams),
            json=payload,
        )
        self.assertEqual(r.status_code, 400)

    def test_12_question_edit_rejects_bad_mcq(self):
        db = TestingSessionLocal()
        adams_exam = db.query(Exam).filter_by(topic="Lesson One").first()
        exam_id = adams_exam.id
        db.close()

        payload = {
            "question": "Broken MCQ?",
            "question_type": "mcq",
            "difficulty": "easy",
            "bloom_level": "remember",
            "options": ["A. Only one option"],  # needs exactly 4
            "correct_answer": "A",
            "reference_answer": "A. Only one option",
            "explanation": "Broken.",
            "max_score": 1,
            "rubric": [
                {"criterion": "Pick", "points": 1, "description": "Pick correct."},
            ],
        }
        r = self.client.patch(
            f"/api/exams/{exam_id}/questions/0",
            headers=self._headers(self.adams),
            json=payload,
        )
        self.assertEqual(r.status_code, 400)

    def test_13_question_edit_out_of_range(self):
        db = TestingSessionLocal()
        adams_exam = db.query(Exam).filter_by(topic="Lesson One").first()
        exam_id = adams_exam.id
        question_count = len(json.loads(adams_exam.exam_json)["questions"])
        db.close()

        payload = {
            "question": "Valid text.",
            "question_type": "short_answer",
            "difficulty": "medium",
            "bloom_level": "apply",
            "options": [],
            "correct_answer": "",
            "reference_answer": "Ref.",
            "explanation": "Expl.",
            "max_score": 1,
            "rubric": [
                {"criterion": "C", "points": 1, "description": "d."},
            ],
        }
        r = self.client.patch(
            f"/api/exams/{exam_id}/questions/{question_count + 5}",
            headers=self._headers(self.adams),
            json=payload,
        )
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
