"""
Integration tests for Student Improvement and Practice Exams:
- GET /api/analytics/improvement returns per-lesson diagnosis and practice history.
- POST /api/exams/practice creates an is_practice exam.
- Practice exams do NOT leak into GET /api/exams (for students or professors).
- Another student receives 403 when trying to access or start the practice exam.
- Sensitive answer keys and rubrics are stripped for students.
- Professor dashboard and clustering ignore practice attempts.
"""

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
from app.models import Curriculum, Exam, ExamAttempt, User

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


class PracticeApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

        # 1. Register Professor
        cls.client.post("/api/auth/register", json={
            "name": "Prof Improvement",
            "email": "prof_imp@univ.edu",
            "password": "password123",
            "role": "professor",
        })
        prof_login = cls.client.post("/api/auth/login", json={
            "email": "prof_imp@univ.edu", "password": "password123"
        })
        cls.prof_token = prof_login.json()["access_token"]
        cls.prof_id = prof_login.json()["user"]["id"]

        # 2. Register Student 1
        cls.client.post("/api/auth/register", json={
            "name": "Student One",
            "email": "student1_imp@univ.edu",
            "password": "password123",
            "role": "student",
        })
        st1_login = cls.client.post("/api/auth/login", json={
            "email": "student1_imp@univ.edu", "password": "password123"
        })
        cls.st1_token = st1_login.json()["access_token"]
        cls.st1_id = st1_login.json()["user"]["id"]

        # 3. Register Student 2
        cls.client.post("/api/auth/register", json={
            "name": "Student Two",
            "email": "student2_imp@univ.edu",
            "password": "password123",
            "role": "student",
        })
        st2_login = cls.client.post("/api/auth/login", json={
            "email": "student2_imp@univ.edu", "password": "password123"
        })
        cls.st2_token = st2_login.json()["access_token"]
        cls.st2_id = st2_login.json()["user"]["id"]

        # 4. Student 1 and 2 select the professor
        cls.client.put(
            "/api/auth/select-professor",
            headers={"Authorization": f"Bearer {cls.st1_token}"},
            json={"professor_id": cls.prof_id},
        )
        cls.client.put(
            "/api/auth/select-professor",
            headers={"Authorization": f"Bearer {cls.st2_token}"},
            json={"professor_id": cls.prof_id},
        )

        # 5. Seed a Curriculum and a published REAL exam for Lesson 1-1
        db = TestingSessionLocal()
        curriculum = Curriculum(
            filename="ml_curriculum.pdf",
            lessons_json=json.dumps([
                {"lesson_id": "1-1", "lesson_title": "Supervised Learning Intro"},
            ]),
            vector_store_path="data/processed/chroma_db",
            professor_id=cls.prof_id,
            collection_name=f"test_coll_{cls.prof_id}",
            uploaded_at=datetime.now(timezone.utc),
        )
        db.add(curriculum)
        db.commit()
        db.refresh(curriculum)
        cls.curriculum_id = curriculum.id

        real_exam_dict = {
            "exam_title": "Supervised Learning Quiz",
            "lesson_id": "1-1",
            "lesson_title": "Supervised Learning Intro",
            "total_points": 2.0,
            "questions": [
                {
                    "question_id": "Q01",
                    "lesson_id": "1-1",
                    "question_type": "mcq",
                    "question": "What is overfitting?",
                    "options": ["A. High bias", "B. Memorizing noise", "C. Fast convergence", "D. None"],
                    "correct_answer": "B",
                    "reference_answer": "B. Memorizing noise",
                    "explanation": "Overfitting fits training noise.",
                    "max_score": 1.0,
                    "rubric": [{"criterion": "Option", "points": 1.0, "description": "Correct choice"}],
                },
                {
                    "question_id": "Q02",
                    "lesson_id": "1-1",
                    "question_type": "mcq",
                    "question": "What is regularization?",
                    "options": ["A. Penalizing complexity", "B. Adding layers", "C. Removing data", "D. None"],
                    "correct_answer": "A",
                    "reference_answer": "A. Penalizing complexity",
                    "explanation": "Regularization penalizes weights.",
                    "max_score": 1.0,
                    "rubric": [{"criterion": "Option", "points": 1.0, "description": "Correct choice"}],
                },
            ],
        }

        real_exam = Exam(
            title="Supervised Learning Quiz",
            curriculum_id=curriculum.id,
            lesson_id="1-1",
            topic="Supervised Learning Intro",
            difficulty="medium",
            bloom_level="understand",
            exam_json=json.dumps(real_exam_dict),
            total_points=2.0,
            is_published=True,
            is_practice=False,
            created_by=cls.prof_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(real_exam)
        db.commit()
        db.refresh(real_exam)
        cls.real_exam_id = real_exam.id

        # 6. Student 1 completes the real exam and answers Q01 wrong (0/1), Q02 right (1/1) -> 50%
        attempt = ExamAttempt(
            exam_id=real_exam.id,
            student_id=cls.st1_id,
            started_at=datetime.now(timezone.utc),
            submitted_at=datetime.now(timezone.utc),
            duration_seconds=120,
            total_score=1.0,
            max_possible_score=2.0,
            graded_answers_json=json.dumps([
                {
                    "question_id": "Q01",
                    "lesson_id": "1-1",
                    "question_type": "mcq",
                    "question": "What is overfitting?",
                    "student_answer": "A",
                    "score": 0.0,
                    "max_score": 1.0,
                    "is_correct": False,
                    "feedback": "Incorrect",
                },
                {
                    "question_id": "Q02",
                    "lesson_id": "1-1",
                    "question_type": "mcq",
                    "question": "What is regularization?",
                    "student_answer": "A",
                    "score": 1.0,
                    "max_score": 1.0,
                    "is_correct": True,
                    "feedback": "Correct",
                },
            ]),
        )
        db.add(attempt)
        db.commit()
        db.close()

    def test_01_improvement_diagnosis_endpoint(self):
        """Student 1 checks GET /api/analytics/improvement and sees lesson 1-1."""
        headers = {"Authorization": f"Bearer {self.st1_token}"}
        resp = self.client.get("/api/analytics/improvement", headers=headers)
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()

        self.assertEqual(data["student_id"], self.st1_id)
        self.assertEqual(data["real_attempts_count"], 1)
        self.assertEqual(data["overall_accuracy"], 50.0)

        # Lesson 1-1: 2 questions, 1 wrong -> not enough data (<3) or weak
        self.assertTrue(any(l["lesson_id"] == "1-1" for l in data["lessons"]))
        l1 = next(l for l in data["lessons"] if l["lesson_id"] == "1-1")
        self.assertEqual(l1["questions_wrong"], 1)
        self.assertEqual(len(l1["sample_wrong_questions"]), 1)
        self.assertIn("overfitting", l1["sample_wrong_questions"][0]["question"].lower())

    def test_02_practice_exam_creation_and_isolation(self):
        """POST /api/exams/practice generates practice exam, stripped for student, hidden from lists."""
        headers_st1 = {"Authorization": f"Bearer {self.st1_token}"}
        headers_st2 = {"Authorization": f"Bearer {self.st2_token}"}
        headers_prof = {"Authorization": f"Bearer {self.prof_token}"}

        mocked_exam = {
            "exam_title": "Practice: Supervised Learning",
            "lesson_id": "1-1",
            "lesson_title": "Supervised Learning Intro",
            "total_points": 3.0,
            "question_count": 3,
            "questions": [
                {
                    "question_id": "PQ1",
                    "lesson_id": "1-1",
                    "question_type": "mcq",
                    "question": "Practice Question 1",
                    "options": ["A. X", "B. Y", "C. Z", "D. W"],
                    "correct_answer": "B",
                    "reference_answer": "B. Y",
                    "explanation": "Y is correct",
                    "max_score": 1.0,
                    "rubric": [{"criterion": "C", "points": 1.0, "description": "D"}],
                    "difficulty": "medium",
                    "bloom_level": "understand",
                },
                {
                    "question_id": "PQ2",
                    "lesson_id": "1-1",
                    "question_type": "short_answer",
                    "question": "Practice Question 2",
                    "options": [],
                    "correct_answer": "",
                    "reference_answer": "Sample answer",
                    "explanation": "Sample explanation",
                    "max_score": 1.0,
                    "rubric": [{"criterion": "C", "points": 1.0, "description": "D"}],
                    "difficulty": "medium",
                    "bloom_level": "understand",
                },
                {
                    "question_id": "PQ3",
                    "lesson_id": "1-1",
                    "question_type": "mcq",
                    "question": "Practice Question 3",
                    "options": ["A. 1", "B. 2", "C. 3", "D. 4"],
                    "correct_answer": "A",
                    "reference_answer": "A. 1",
                    "explanation": "1 is correct",
                    "max_score": 1.0,
                    "rubric": [{"criterion": "C", "points": 1.0, "description": "D"}],
                    "difficulty": "medium",
                    "bloom_level": "understand",
                },
            ],
            "warnings": [],
        }

        with (
            patch("app.routers.exam_router.resolve_practice_source", return_value={
                "available": True,
                "reason": None,
                "curriculum": None,
                "collection_name": "curriculum",
                "language": "en",
                "lesson_title": "Supervised Learning Intro",
            }),
            patch("app.routers.exam_router.generate_exam", return_value=(mocked_exam, Path("mock.json"))),
            patch("app.routers.analytics_router.generate_class_summary", return_value={
                "overall_assessment": "Mock summary",
                "key_findings": [],
                "topic_recommendations": {},
                "intervention_needed": [],
                "class_strengths": [],
            }),
        ):
            resp = self.client.post(
                "/api/exams/practice",
                headers=headers_st1,
                json={"lesson_id": "1-1", "number_of_questions": 3},
            )

        self.assertEqual(resp.status_code, 201, resp.text)
        exam_data = resp.json()
        self.assertTrue(exam_data["is_practice"])
        practice_exam_id = exam_data["id"]

        # Sensitive keys MUST be stripped for student
        for q in exam_data["questions"]:
            self.assertNotIn("correct_answer", q)
            self.assertNotIn("reference_answer", q)
            self.assertNotIn("explanation", q)
            self.assertNotIn("rubric", q)

        # Verify Practice exam does NOT appear in GET /api/exams for Student 1
        st1_exams = self.client.get("/api/exams", headers=headers_st1).json()
        self.assertFalse(any(e["id"] == practice_exam_id for e in st1_exams))

        # Verify Practice exam does NOT appear in GET /api/exams for Professor
        prof_exams = self.client.get("/api/exams", headers=headers_prof).json()
        self.assertFalse(any(e["id"] == practice_exam_id for e in prof_exams))

        # Verify Student 2 receives 403 on this practice exam
        r_forbidden = self.client.get(f"/api/exams/{practice_exam_id}", headers=headers_st2)
        self.assertEqual(r_forbidden.status_code, 403)

        r_start_forbidden = self.client.post(
            "/api/attempts/start",
            headers=headers_st2,
            json={"exam_id": practice_exam_id},
        )
        self.assertEqual(r_start_forbidden.status_code, 403)

        # Student 1 starts and submits practice attempt
        start_res = self.client.post(
            "/api/attempts/start",
            headers=headers_st1,
            json={"exam_id": practice_exam_id},
        )
        self.assertEqual(start_res.status_code, 201)
        attempt_id = start_res.json()["attempt_id"]

        with patch("scripts.grading._send_grading_completion") as mock_grade:
            mock_grade.return_value = json.dumps({
                "criterion_scores": [{"criterion": "C", "score": 1.0, "max_score": 1.0, "feedback": "Good"}],
                "feedback": "Well done",
                "strengths": [],
                "weaknesses": [],
            })
            submit_res = self.client.post(
                "/api/attempts/submit",
                headers=headers_st1,
                json={
                    "attempt_id": attempt_id,
                    "answers": {"PQ1": "B", "PQ2": "Sample answer", "PQ3": "A"},
                    "duration_seconds": 60,
                },
            )
        self.assertEqual(submit_res.status_code, 200, submit_res.text)
        attempt_data = submit_res.json()
        self.assertTrue(attempt_data["is_practice"])
        self.assertEqual(attempt_data["total_score"], 3.0)

        # Verify practice attempt is tracked in improvement.practice_history
        imp_res = self.client.get("/api/analytics/improvement", headers=headers_st1)
        self.assertEqual(imp_res.status_code, 200)
        imp_data = imp_res.json()
        self.assertTrue(any(h["lesson_id"] == "1-1" for h in imp_data["practice_history"]))
        p_hist = next(h for h in imp_data["practice_history"] if h["lesson_id"] == "1-1")
        self.assertEqual(p_hist["practice_count"], 1)
        self.assertEqual(p_hist["latest_percentage"], 100.0)

        # Verify class analytics / professor dashboard ignore this practice attempt
        prof_dash = self.client.get("/api/analytics/dashboard/professor", headers=headers_prof).json()
        # Only the 1 real attempt should be counted
        self.assertEqual(prof_dash["class_analytics"]["total_attempts"], 1)


if __name__ == "__main__":
    unittest.main()
