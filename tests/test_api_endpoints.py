"""End-to-end integration tests for FastAPI REST API endpoints using standard unittest."""

from __future__ import annotations

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
