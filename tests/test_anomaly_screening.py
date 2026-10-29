"""Tests for exam-attempt anomaly screening, persistence, serialization, and migrations."""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.anomaly import (
    ANOMALY_FALLBACK,
    compute_score_percentage,
    count_exam_question_types,
    resolve_attempt_duration_seconds,
    screen_exam_attempt,
    set_anomaly_service,
)
from app.database import Base, get_db
from app.main import app, apply_schema_migrations, on_startup
from app.models import Exam, ExamAttempt, User


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


MCQ_EXAM_JSON = json.dumps(
    {
        "exam_title": "Screening Exam",
        "total_points": 2,
        "questions": [
            {
                "question_id": "Q01",
                "question": "2+2?",
                "question_type": "mcq",
                "options": ["A. 3", "B. 4", "C. 5", "D. 6"],
                "correct_answer": "B",
                "reference_answer": "B",
                "max_score": 1,
            },
            {
                "question_id": "Q02",
                "question": "Explain gravity.",
                "question_type": "essay",
                "reference_answer": "Mass attracts mass.",
                "max_score": 1,
                "rubric": [{"criterion": "accuracy", "description": "correct", "points": 1}],
            },
        ],
    }
)


class AnomalyHelpersTestCase(unittest.TestCase):
    def test_question_counts_come_from_exam_not_answers(self):
        exam = json.loads(MCQ_EXAM_JSON)
        mcq_count, essay_count = count_exam_question_types(exam)
        self.assertEqual(mcq_count, 1)
        self.assertEqual(essay_count, 1)

    def test_zero_or_missing_max_score_percentage(self):
        self.assertEqual(compute_score_percentage(10, 0), 0.0)
        self.assertEqual(compute_score_percentage(10, None), 0.0)
        self.assertEqual(compute_score_percentage(8, 10), 80.0)

    def test_duration_prefers_server_elapsed_time(self):
        started = datetime(2026, 10, 29, 10, 0, tzinfo=timezone.utc)
        submitted = started + timedelta(seconds=90)
        duration = resolve_attempt_duration_seconds(started, submitted, client_duration_seconds=5)
        self.assertEqual(duration, 90)

    def test_screen_fallback_on_inference_error(self):
        service = MagicMock()
        service.inspect_attempt.side_effect = RuntimeError("model exploded")
        set_anomaly_service(service)
        try:
            result = screen_exam_attempt(1, 1, 90, 80)
            self.assertEqual(result, ANOMALY_FALLBACK)
        finally:
            set_anomaly_service(None)


class AnomalyMigrationTestCase(unittest.TestCase):
    def test_existing_sqlite_table_receives_anomaly_columns(self):
        migrate_engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        with migrate_engine.connect() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE exam_attempts (
                        id INTEGER PRIMARY KEY,
                        exam_id INTEGER NOT NULL,
                        student_id INTEGER NOT NULL,
                        started_at DATETIME NOT NULL,
                        submitted_at DATETIME,
                        duration_seconds INTEGER,
                        total_score FLOAT,
                        max_possible_score FLOAT,
                        graded_answers_json TEXT
                    )
                    """
                )
            )
            conn.commit()

        before = {c["name"] for c in inspect(migrate_engine).get_columns("exam_attempts")}
        self.assertNotIn("is_suspicious", before)

        applied = apply_schema_migrations(migrate_engine)
        after = {c["name"] for c in inspect(migrate_engine).get_columns("exam_attempts")}
        self.assertIn("exam_attempts.is_suspicious", applied)
        self.assertIn("is_suspicious", after)
        self.assertIn("suspicion_status", after)
        self.assertIn("suspicion_reason", after)
        self.assertIn("anomaly_score", after)

        # Idempotence: running migrations again applies nothing and raises no error
        second_applied = apply_schema_migrations(migrate_engine)
        self.assertEqual(second_applied, [])

    def test_startup_migration_failure_logs_and_raises(self):
        with patch("app.main.apply_schema_migrations", side_effect=RuntimeError("disk failure")):
            with patch("app.main.logger.exception") as mock_log:
                with self.assertRaises(RuntimeError):
                    on_startup()
                mock_log.assert_called_once()
                self.assertIn("Database schema migration failed", mock_log.call_args[0][0])


class AnomalySubmitApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)
        cls.client.post(
            "/api/auth/register",
            json={
                "name": "Prof Screen",
                "email": "prof_screen@univ.edu",
                "password": "password123",
                "role": "professor",
            },
        )
        prof_login = cls.client.post(
            "/api/auth/login",
            json={"email": "prof_screen@univ.edu", "password": "password123"},
        )
        cls.prof_token = prof_login.json()["access_token"]
        cls.prof_id = prof_login.json()["user"]["id"]

        cls.client.post(
            "/api/auth/register",
            json={
                "name": "Student Screen",
                "email": "student_screen@univ.edu",
                "password": "password123",
                "role": "student",
            },
        )
        st_login = cls.client.post(
            "/api/auth/login",
            json={"email": "student_screen@univ.edu", "password": "password123"},
        )
        cls.st_token = st_login.json()["access_token"]
        cls.st_id = st_login.json()["user"]["id"]
        cls.client.put(
            "/api/auth/select-professor",
            headers={"Authorization": f"Bearer {cls.st_token}"},
            json={"professor_id": cls.prof_id},
        )

        db = TestingSessionLocal()
        exam = Exam(
            title="Screening Exam",
            lesson_id="1-1",
            topic="Screening",
            difficulty="medium",
            bloom_level="apply",
            exam_json=MCQ_EXAM_JSON,
            total_points=2.0,
            is_published=True,
            created_by=cls.prof_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(exam)
        db.commit()
        cls.exam_id = exam.id
        db.close()

    def _start_attempt(self) -> int:
        response = self.client.post(
            "/api/attempts/start",
            headers={"Authorization": f"Bearer {self.st_token}"},
            json={"exam_id": self.exam_id},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["attempt_id"]

    def _submit(self, attempt_id: int, duration: int = 5):
        with patch(
            "app.routers.attempt_router.grade_exam_submission",
            return_value={
                "total_score": 2.0,
                "max_possible_score": 2.0,
                "percentage": 100.0,
                "graded_answers": [],
            },
        ):
            return self.client.post(
                "/api/attempts/submit",
                headers={"Authorization": f"Bearer {self.st_token}"},
                json={
                    "attempt_id": attempt_id,
                    "answers": {"Q01": "B", "Q02": "Mass attracts mass."},
                    "duration_seconds": duration,
                },
            )

    def test_normal_attempt_is_persisted_and_hidden_from_student(self):
        attempt_id = self._start_attempt()
        screening = {
            "is_suspicious": False,
            "suspicion_status": "Normal",
            "suspicion_reason": None,
            "anomaly_score": 0.21,
        }
        with patch("app.routers.attempt_router.screen_exam_attempt", return_value=screening):
            response = self._submit(attempt_id, duration=999)
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertIsNone(body.get("is_suspicious"))
        self.assertIsNone(body.get("anomaly_score"))

        db = TestingSessionLocal()
        stored = db.scalar(select(ExamAttempt).where(ExamAttempt.id == attempt_id))
        self.assertFalse(stored.is_suspicious)
        self.assertEqual(stored.suspicion_status, "Normal")
        self.assertIsNone(stored.suspicion_reason)
        self.assertEqual(stored.anomaly_score, 0.21)
        self.assertLess(stored.duration_seconds, 120)
        db.close()

        student_get = self.client.get(
            f"/api/attempts/{attempt_id}",
            headers={"Authorization": f"Bearer {self.st_token}"},
        )
        self.assertEqual(student_get.status_code, 200)
        self.assertIsNone(student_get.json().get("is_suspicious"))

        prof_get = self.client.get(
            f"/api/attempts/{attempt_id}",
            headers={"Authorization": f"Bearer {self.prof_token}"},
        )
        self.assertEqual(prof_get.status_code, 200)
        self.assertFalse(prof_get.json()["is_suspicious"])
        self.assertEqual(prof_get.json()["suspicion_status"], "Normal")
        self.assertEqual(prof_get.json()["anomaly_score"], 0.21)

    def test_flagged_attempt_persists_arabic_reason(self):
        attempt_id = self._start_attempt()
        screening = {
            "is_suspicious": True,
            "suspicion_status": "Suspicious / Flagged",
            "suspicion_reason": "درجة مرتفعة مع زمن قراءة مستحيل (اشتباه غش/تسريب)",
            "anomaly_score": -0.42,
        }
        with patch("app.routers.attempt_router.screen_exam_attempt", return_value=screening):
            response = self._submit(attempt_id)
        self.assertEqual(response.status_code, 200, response.text)

        db = TestingSessionLocal()
        stored = db.scalar(select(ExamAttempt).where(ExamAttempt.id == attempt_id))
        self.assertTrue(stored.is_suspicious)
        self.assertEqual(stored.suspicion_status, "Suspicious / Flagged")
        self.assertIn("درجة مرتفعة", stored.suspicion_reason)
        self.assertEqual(stored.anomaly_score, -0.42)
        db.close()

        prof_get = self.client.get(
            f"/api/attempts/{attempt_id}",
            headers={"Authorization": f"Bearer {self.prof_token}"},
        )
        self.assertTrue(prof_get.json()["is_suspicious"])
        self.assertEqual(
            prof_get.json()["suspicion_reason"],
            "درجة مرتفعة مع زمن قراءة مستحيل (اشتباه غش/تسريب)",
        )

    def test_inference_error_does_not_block_submission(self):
        attempt_id = self._start_attempt()
        service = MagicMock()
        service.inspect_attempt.side_effect = RuntimeError("model exploded")
        set_anomaly_service(service)
        try:
            response = self._submit(attempt_id)
        finally:
            set_anomaly_service(None)
        self.assertEqual(response.status_code, 200, response.text)
        db = TestingSessionLocal()
        stored = db.scalar(select(ExamAttempt).where(ExamAttempt.id == attempt_id))
        self.assertFalse(stored.is_suspicious)
        self.assertEqual(stored.suspicion_status, "Normal")
        self.assertIsNone(stored.suspicion_reason)
        self.assertIsNone(stored.anomaly_score)
        db.close()

    def test_grading_failure_is_not_converted_into_success(self):
        attempt_id = self._start_attempt()
        with patch(
            "app.routers.attempt_router.grade_exam_submission",
            side_effect=RuntimeError("grader down"),
        ):
            response = self.client.post(
                "/api/attempts/submit",
                headers={"Authorization": f"Bearer {self.st_token}"},
                json={"attempt_id": attempt_id, "answers": {"Q01": "B"}, "duration_seconds": 10},
            )
        self.assertEqual(response.status_code, 500)
        db = TestingSessionLocal()
        stored = db.scalar(select(ExamAttempt).where(ExamAttempt.id == attempt_id))
        self.assertIsNone(stored.submitted_at)
        db.close()


class ExamStudentResultsApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.dependency_overrides[get_db] = override_get_db
        cls.client = TestClient(app)

        cls.client.post(
            "/api/auth/register",
            json={
                "name": "Prof Results A",
                "email": "prof_results_a@univ.edu",
                "password": "password123",
                "role": "professor",
            },
        )
        login_a = cls.client.post(
            "/api/auth/login",
            json={"email": "prof_results_a@univ.edu", "password": "password123"},
        )
        cls.prof_a_token = login_a.json()["access_token"]
        cls.prof_a_id = login_a.json()["user"]["id"]

        cls.client.post(
            "/api/auth/register",
            json={
                "name": "Prof Results B",
                "email": "prof_results_b@univ.edu",
                "password": "password123",
                "role": "professor",
            },
        )
        login_b = cls.client.post(
            "/api/auth/login",
            json={"email": "prof_results_b@univ.edu", "password": "password123"},
        )
        cls.prof_b_token = login_b.json()["access_token"]

        cls.client.post(
            "/api/auth/register",
            json={
                "name": "Maya Student",
                "email": "maya_results@univ.edu",
                "password": "password123",
                "role": "student",
            },
        )
        st_login = cls.client.post(
            "/api/auth/login",
            json={"email": "maya_results@univ.edu", "password": "password123"},
        )
        cls.student_id = st_login.json()["user"]["id"]
        cls.student_token = st_login.json()["access_token"]

        db = TestingSessionLocal()
        exam = Exam(
            title="Owned Exam",
            lesson_id="2-1",
            topic="Results",
            difficulty="easy",
            bloom_level="remember",
            exam_json=MCQ_EXAM_JSON,
            total_points=2.0,
            is_published=True,
            created_by=cls.prof_a_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(exam)
        db.commit()
        cls.exam_id = exam.id

        now = datetime.now(timezone.utc)
        db.add_all(
            [
                ExamAttempt(
                    exam_id=cls.exam_id,
                    student_id=cls.student_id,
                    started_at=now - timedelta(minutes=20),
                    submitted_at=now - timedelta(minutes=10),
                    duration_seconds=600,
                    total_score=1.5,
                    max_possible_score=2.0,
                    is_suspicious=False,
                    suspicion_status="Normal",
                    suspicion_reason=None,
                    anomaly_score=0.11,
                ),
                ExamAttempt(
                    exam_id=cls.exam_id,
                    student_id=cls.student_id,
                    started_at=now - timedelta(minutes=8),
                    submitted_at=now - timedelta(minutes=5),
                    duration_seconds=180,
                    total_score=2.0,
                    max_possible_score=2.0,
                    is_suspicious=True,
                    suspicion_status="Suspicious / Flagged",
                    suspicion_reason="سلوك شاذ إحصائياً مقارنة بمتوسط التوزيع العام للطلاب",
                    anomaly_score=-0.33,
                ),
                ExamAttempt(
                    exam_id=cls.exam_id,
                    student_id=cls.student_id,
                    started_at=now - timedelta(minutes=2),
                    submitted_at=None,
                    duration_seconds=None,
                    total_score=None,
                    max_possible_score=None,
                ),
                ExamAttempt(
                    exam_id=cls.exam_id,
                    student_id=cls.student_id,
                    started_at=now - timedelta(minutes=40),
                    submitted_at=now - timedelta(minutes=30),
                    duration_seconds=400,
                    total_score=1.0,
                    max_possible_score=2.0,
                    is_suspicious=False,
                    suspicion_status="Normal",
                    suspicion_reason=None,
                    anomaly_score=None,
                ),
            ]
        )
        db.commit()
        db.close()

    def test_owner_retrieves_grouped_submitted_attempts(self):
        response = self.client.get(
            f"/api/exams/{self.exam_id}/results",
            headers={"Authorization": f"Bearer {self.prof_a_token}"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertEqual(payload["exam_id"], self.exam_id)
        self.assertEqual(payload["distinct_submitted_students_count"], 1)
        self.assertEqual(len(payload["students"]), 1)
        student = payload["students"][0]
        self.assertEqual(student["student_id"], self.student_id)
        self.assertEqual(student["student_name"], "Maya Student")
        self.assertEqual(student["submitted_attempt_count"], 3)
        self.assertEqual(student["unsubmitted_attempt_count"], 1)
        self.assertEqual(len(student["attempts"]), 3)

        assessed = [item for item in student["attempts"] if item["anomaly_assessed"]]
        not_assessed = [item for item in student["attempts"] if not item["anomaly_assessed"]]
        self.assertEqual(len(not_assessed), 1)
        self.assertIsNone(not_assessed[0]["anomaly_score"])
        flagged = [item for item in assessed if item["is_suspicious"]]
        self.assertEqual(len(flagged), 1)
        self.assertIn("سلوك شاذ", flagged[0]["suspicion_reason"])
        self.assertEqual(flagged[0]["score"], 2.0)
        self.assertEqual(flagged[0]["score_percentage"], 100.0)

    def test_other_professor_and_student_are_forbidden(self):
        other = self.client.get(
            f"/api/exams/{self.exam_id}/results",
            headers={"Authorization": f"Bearer {self.prof_b_token}"},
        )
        self.assertEqual(other.status_code, 403)

        student = self.client.get(
            f"/api/exams/{self.exam_id}/results",
            headers={"Authorization": f"Bearer {self.student_token}"},
        )
        self.assertEqual(student.status_code, 403)

    def test_empty_results_for_exam_without_submissions(self):
        db = TestingSessionLocal()
        exam = Exam(
            title="Empty Exam",
            lesson_id="9-9",
            topic="Empty",
            difficulty="easy",
            bloom_level="remember",
            exam_json=MCQ_EXAM_JSON,
            total_points=1.0,
            is_published=True,
            created_by=self.prof_a_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(exam)
        db.commit()
        exam_id = exam.id
        db.close()

        response = self.client.get(
            f"/api/exams/{exam_id}/results",
            headers={"Authorization": f"Bearer {self.prof_a_token}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["distinct_submitted_students_count"], 0)
        self.assertEqual(response.json()["students"], [])

    def test_distinct_students_summary_excludes_unsubmitted_and_deduplicates(self):
        # Register two additional students
        db = TestingSessionLocal()
        s2 = User(name="Student Two", email="st2@univ.edu", hashed_password="pw", role="student")
        s3 = User(name="Student Three", email="st3@univ.edu", hashed_password="pw", role="student")
        db.add_all([s2, s3])
        db.commit()
        s2_id = s2.id
        s3_id = s3.id

        exam = Exam(
            title="Multi Student Exam",
            lesson_id="3-1",
            topic="Summary",
            difficulty="medium",
            bloom_level="apply",
            exam_json=MCQ_EXAM_JSON,
            total_points=2.0,
            is_published=True,
            created_by=self.prof_a_id,
            created_at=datetime.now(timezone.utc),
        )
        db.add(exam)
        db.commit()
        exam_id = exam.id

        now = datetime.now(timezone.utc)
        # Student 1 (self.student_id): 2 submitted attempts + 1 unsubmitted
        # Student 2 (s2_id): 1 unsubmitted attempt ONLY (must be excluded)
        # Student 3 (s3_id): 1 submitted attempt
        db.add_all([
            ExamAttempt(exam_id=exam_id, student_id=self.student_id, started_at=now, submitted_at=now, duration_seconds=60, total_score=2.0, max_possible_score=2.0),
            ExamAttempt(exam_id=exam_id, student_id=self.student_id, started_at=now, submitted_at=now, duration_seconds=80, total_score=1.5, max_possible_score=2.0),
            ExamAttempt(exam_id=exam_id, student_id=self.student_id, started_at=now, submitted_at=None),
            ExamAttempt(exam_id=exam_id, student_id=s2_id, started_at=now, submitted_at=None),
            ExamAttempt(exam_id=exam_id, student_id=s3_id, started_at=now, submitted_at=now, duration_seconds=120, total_score=2.0, max_possible_score=2.0),
        ])
        db.commit()
        db.close()

        response = self.client.get(
            f"/api/exams/{exam_id}/results",
            headers={"Authorization": f"Bearer {self.prof_a_token}"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()

        # Exactly 2 distinct students submitted at least one attempt (self.student_id and s3_id)
        self.assertEqual(payload["distinct_submitted_students_count"], 2)
        self.assertEqual(len(payload["students"]), 2)
        returned_ids = {s["student_id"] for s in payload["students"]}
        self.assertEqual(returned_ids, {self.student_id, s3_id})
        self.assertNotIn(s2_id, returned_ids)
