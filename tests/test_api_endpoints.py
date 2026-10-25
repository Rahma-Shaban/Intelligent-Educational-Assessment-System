"""End-to-end integration tests for FastAPI REST API endpoints using standard unittest."""

from __future__ import annotations

import json
import re
from pathlib import Path
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app

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


class ApiEndpointsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_01_health_check(self):
        """Verify system health endpoint."""
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("status", data)
        self.assertIn("active_model", data)

    def test_02_auth_workflow(self):
        """Verify registration, login, JWT claims, and RBAC."""
        # 1. Register Professor
        prof_payload = {
            "name": "Dr. Smith",
            "email": "drsmith@university.edu",
            "password": "securepassword123",
            "role": "professor",
        }
        r = self.client.post("/api/auth/register", json=prof_payload)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["email"], prof_payload["email"])

        # 2. Register Student
        student_payload = {
            "name": "Alice Johnson",
            "email": "alice@student.edu",
            "password": "studentpass123",
            "role": "student",
        }
        r = self.client.post("/api/auth/register", json=student_payload)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["role"], "student")

        # 3. Duplicate email rejected
        r = self.client.post("/api/auth/register", json=student_payload)
        self.assertEqual(r.status_code, 400)

        # 4. Login Professor
        login_prof = self.client.post(
            "/api/auth/login",
            json={"email": prof_payload["email"], "password": prof_payload["password"]},
        )
        self.assertEqual(login_prof.status_code, 200)
        prof_token = login_prof.json()["access_token"]
        self.assertTrue(prof_token)

        # 5. Login Student
        login_student = self.client.post(
            "/api/auth/login",
            json={"email": student_payload["email"], "password": student_payload["password"]},
        )
        self.assertEqual(login_student.status_code, 200)
        student_token = login_student.json()["access_token"]
        self.assertTrue(student_token)

        # 6. /api/auth/me
        headers_prof = {"Authorization": f"Bearer {prof_token}"}
        r_me = self.client.get("/api/auth/me", headers=headers_prof)
        self.assertEqual(r_me.status_code, 200)
        self.assertEqual(r_me.json()["email"], prof_payload["email"])

        # 7. Student role restriction (RBAC 403 on professor route)
        headers_student = {"Authorization": f"Bearer {student_token}"}
        r_forbidden = self.client.post("/api/analytics/cluster", headers=headers_student)
        self.assertEqual(r_forbidden.status_code, 403)

        # 8. Professor access permitted
        r_allowed = self.client.post("/api/analytics/cluster", headers=headers_prof)
        self.assertEqual(r_allowed.status_code, 200)
        self.assertIsInstance(r_allowed.json(), list)

    def test_03_exam_listing(self):
        """Verify exams list endpoint."""
        login_res = self.client.post(
            "/api/auth/login",
            json={"email": "drsmith@university.edu", "password": "securepassword123"},
        )
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        r = self.client.get("/api/exams", headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_04_exam_generation_returns_twenty_mocked_questions(self):
        login_response = self.client.post(
            "/api/auth/login",
            json={"email": "drsmith@university.edu", "password": "securepassword123"},
        )
        if login_response.status_code != 200:
            self.client.post(
                "/api/auth/register",
                json={
                    "name": "Dr. Smith",
                    "email": "drsmith@university.edu",
                    "password": "securepassword123",
                    "role": "professor",
                },
            )
            login_response = self.client.post(
                "/api/auth/login",
                json={"email": "drsmith@university.edu", "password": "securepassword123"},
            )
        self.assertEqual(login_response.status_code, 200)
        headers = {"Authorization": f"Bearer {login_response.json()['access_token']}"}
        docs = []
        for index in range(20):
            chunk_id = f"1-1-{index + 1:03d}"
            docs.append(
                type(
                    "Document",
                    (),
                    {
                        "page_content": f"Curriculum fact number {index + 1} supports a lesson objective.",
                        "metadata": {
                            "source": "curriculum.pdf",
                            "lesson_id": "1-1",
                            "lesson_title": "Lesson One",
                            "chunk_id": chunk_id,
                        },
                    },
                )()
            )
        docs_by_id = {doc.metadata["chunk_id"]: doc for doc in docs}

        def mocked_model(prompt, **kwargs):
            match = re.search(r"this chunk_id: ([A-Za-z0-9_-]+)", prompt)
            self.assertIsNotNone(match)
            chunk_id = match.group(1)
            index = int(chunk_id.rsplit("-", 1)[1])
            document = docs_by_id[chunk_id]
            return json.dumps({
                "question": f"Identify concept{index} principle{index}.",
                "question_type": "short_answer",
                "difficulty": "medium",
                "bloom_level": "apply",
                "bloom_rationale": "Applies a distinct curriculum fact.",
                "options": [],
                "correct_answer": "",
                "reference_answer": f"Evidence answer{index}.",
                "explanation": "The cited curriculum passage supports the answer.",
                "max_score": 1,
                "rubric": [{
                    "criterion": "Identifies the fact",
                    "points": 1,
                    "description": "Names the distinct supported fact.",
                }],
                "source_refs": [{
                    "source": "curriculum.pdf",
                    "chunk_id": chunk_id,
                    "evidence_quote": document.page_content,
                }],
            })

        with (
            patch("scripts.generation.validate_configuration", return_value=(True, [], "mock-model")),
            patch("scripts.generation.retrieve_curriculum_context", return_value=docs),
            patch("scripts.generation._send_completion", side_effect=mocked_model),
            patch("scripts.generation.save_exam", return_value=Path("mock-exam.json")),
        ):
            response = self.client.post(
                "/api/exams/generate",
                headers=headers,
                json={
                    "lesson_id": "1-1",
                    "topic": "Lesson One",
                    "difficulty": "medium",
                    "bloom_level": "apply",
                    "question_types": ["short_answer"],
                    "number_of_questions": 20,
                },
            )

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["question_count"], 20)
        self.assertEqual(len(response.json()["questions"]), 20)

    @patch("app.routers.analytics_router.generate_student_feedback")
    def test_04_student_dashboard(self, mock_feedback):
        """Verify student personal dashboard diagnostics endpoint."""
        mock_feedback.return_value = {
            "summary": "Great progress overall.",
            "strengths": ["Consistent practice"],
            "weaknesses": ["None noted"],
            "recommendations": ["Keep practicing"],
            "study_plan": "Continue current pace.",
            "cluster_label": "Proficient",
        }

        login_res = self.client.post(
            "/api/auth/login",
            json={"email": "alice@student.edu", "password": "studentpass123"},
        )
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        r = self.client.get("/api/analytics/dashboard/student", headers=headers)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("student", data)
        self.assertIn("feedback", data)
        self.assertEqual(data["student"]["email"], "alice@student.edu")
        self.assertEqual(data["feedback"]["summary"], "Great progress overall.")


if __name__ == "__main__":
    unittest.main()
