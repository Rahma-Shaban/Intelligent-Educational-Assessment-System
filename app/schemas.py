"""Pydantic v2 schemas for Intelligent Educational Assessment System."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# ==============================================================================
# Auth Schemas
# ==============================================================================


class RegisterRequest(BaseModel):
    """Payload for user registration."""

    name: str = Field(..., min_length=1, max_length=255, description="Full name of the user")
    email: EmailStr = Field(..., description="Unique email address")
    password: str = Field(..., min_length=6, description="Plain text password (min 6 characters)")
    role: str = Field(
        default="student",
        pattern="^(professor|student)$",
        description="User role: 'professor' or 'student'",
    )


class LoginRequest(BaseModel):
    """Payload for user login."""

    email: EmailStr = Field(..., description="Registered email address")
    password: str = Field(..., min_length=1, description="Account password")


class UserResponse(BaseModel):
    """User profile response representation."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: str
    created_at: datetime


class TokenResponse(BaseModel):
    """JWT bearer token response."""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse | None = None


# ==============================================================================
# Curriculum Schemas
# ==============================================================================


class LessonItem(BaseModel):
    """Representation of an individual curriculum lesson."""

    model_config = ConfigDict(from_attributes=True)

    lesson_id: str
    lesson_title: str
    chapter_id: int | None = None
    chapter_title: str | None = None
    chunk_count: int = 0


class CurriculumResponse(BaseModel):
    """Curriculum upload and overview response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    lessons: list[LessonItem]
    uploaded_at: datetime


# ==============================================================================
# Exam Schemas
# ==============================================================================


class ExamGenerateRequest(BaseModel):
    """Parameters for AI exam generation."""

    lesson_id: str = Field(..., min_length=1, description="Curriculum lesson ID, e.g. '1-1'")
    topic: str = Field(default="", description="Assessment topic title")
    difficulty: str = Field(default="medium", pattern="^(easy|medium|hard)$")
    bloom_level: str = Field(
        default="apply",
        pattern="^(remember|understand|apply|analyze|evaluate|create)$",
    )
    question_types: list[str] = Field(
        default=["mcq", "short_answer", "essay"],
        description="Allowed types: 'mcq', 'short_answer', 'essay'",
    )
    number_of_questions: int = Field(default=5, ge=1, le=25)


class ExamListItem(BaseModel):
    """Compact summary of an exam for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    lesson_id: str
    topic: str
    difficulty: str
    bloom_level: str
    total_points: float
    question_count: int
    is_published: bool = False
    created_at: datetime


class ExamResponse(BaseModel):
    """Detailed exam representation."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    lesson_id: str
    topic: str
    difficulty: str
    bloom_level: str
    total_points: float
    question_count: int
    is_published: bool = False
    created_at: datetime
    questions: list[dict[str, Any]] | None = None
    warnings: list[str] = Field(default_factory=list)


class ExamPublishRequest(BaseModel):
    """Parameters for publishing or unpublishing an assessment."""
    is_published: bool = True


# ==============================================================================
# Attempt Schemas
# ==============================================================================


class AttemptStartRequest(BaseModel):
    """Payload to begin an exam attempt."""

    exam_id: int = Field(..., gt=0, description="Target exam ID")


class AttemptStartResponse(BaseModel):
    """Confirmation of newly initiated attempt."""

    model_config = ConfigDict(from_attributes=True)

    attempt_id: int
    started_at: datetime


class AttemptSubmitRequest(BaseModel):
    """Payload to submit completed answers for an attempt."""

    attempt_id: int = Field(..., gt=0)
    answers: dict[str, str] = Field(
        default_factory=dict,
        description="Mapping of question_id -> student answer string",
    )
    duration_seconds: int = Field(default=0, ge=0)


class AttemptResponse(BaseModel):
    """Graded attempt result."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    exam_id: int
    student_id: int
    started_at: datetime
    submitted_at: datetime | None = None
    duration_seconds: int | None = None
    total_score: float | None = None
    max_possible_score: float | None = None
    percentage: float | None = None
    graded_answers: list[dict[str, Any]] | dict[str, Any] | None = None


# ==============================================================================
# Analytics Schemas
# ==============================================================================


class ClusterResponse(BaseModel):
    """Cluster classification and diagnostic feature vectors."""

    model_config = ConfigDict(from_attributes=True)

    student_id: int
    cluster_label: str
    features: dict[str, Any]


class StudentDashboardResponse(BaseModel):
    """Diagnostic profile and trajectory for an individual student."""

    student: UserResponse
    attempts: list[AttemptResponse]
    cluster: ClusterResponse | None = None
    feedback: dict[str, Any]


class ProfessorDashboardResponse(BaseModel):
    """Aggregate analytics and insights for instructor overview."""

    class_analytics: dict[str, Any]
    clusters: list[ClusterResponse]
    summary: dict[str, Any]
