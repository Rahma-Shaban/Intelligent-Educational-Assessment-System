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
    selected_professor_id: int | None = None


class ProfessorOption(BaseModel):
    """Compact professor entry for student selection lists."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str


class SelectProfessorRequest(BaseModel):
    """Payload for a student to persist their chosen professor."""

    professor_id: int = Field(..., gt=0, description="ID of the professor to enroll with")


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
    professor_id: int | None = None
    collection_name: str | None = None
    lesson_count: int = 0


class CurriculumSummary(BaseModel):
    """Document library entry for a professor's uploaded curriculum."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    uploaded_at: datetime
    professor_id: int | None = None
    lesson_count: int = 0
    lessons: list[LessonItem] = Field(default_factory=list)


# ==============================================================================
# Exam Schemas
# ==============================================================================


class ExamGenerateRequest(BaseModel):
    """Parameters for AI exam generation."""

    curriculum_id: int = Field(
        ...,
        gt=0,
        description="Textbook/document ID whose lessons are eligible for generation",
    )
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
    language: str = Field(default="en", description="Exam language: 'en' or 'ar'")


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
    is_practice: bool = False
    created_at: datetime
    curriculum_id: int | None = None


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
    is_practice: bool = False
    created_at: datetime
    curriculum_id: int | None = None
    questions: list[dict[str, Any]] | None = None
    warnings: list[str] = Field(default_factory=list)


class ExamPublishRequest(BaseModel):
    """Parameters for publishing or unpublishing an assessment."""
    is_published: bool = True


class RubricItemUpdate(BaseModel):
    """Single grading criterion inside an edited question."""

    criterion: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    points: float = Field(..., gt=0)


class ExamAttemptResultItem(BaseModel):
    """One submitted attempt in a professor exam-results view."""

    attempt_id: int
    score: float | None = None
    max_possible_score: float | None = None
    score_percentage: float | None = None
    submitted_at: datetime | None = None
    duration_seconds: int | None = None
    is_suspicious: bool | None = None
    suspicion_status: str | None = None
    suspicion_reason: str | None = None
    anomaly_score: float | None = None
    anomaly_assessed: bool = False


class ExamStudentResultItem(BaseModel):
    """Per-student submitted-attempt summary for a professor-owned exam."""

    student_id: int
    student_name: str
    submitted_attempt_count: int
    unsubmitted_attempt_count: int = 0
    attempts: list[ExamAttemptResultItem] = Field(default_factory=list)


class ExamStudentResultsResponse(BaseModel):
    """Professor-facing student results for a single exam."""

    exam_id: int
    exam_title: str
    distinct_submitted_students_count: int = Field(
        default=0,
        description="Total distinct students who submitted at least one attempt",
    )
    students: list[ExamStudentResultItem] = Field(default_factory=list)


class QuestionUpdateRequest(BaseModel):
    """Professor-provided edits for one generated exam question."""

    question: str = Field(..., min_length=1, description="Question prompt text")
    question_type: str = Field(..., pattern="^(mcq|short_answer|essay)$")
    difficulty: str = Field(..., pattern="^(easy|medium|hard)$")
    bloom_level: str = Field(
        ...,
        pattern="^(remember|understand|apply|analyze|evaluate|create)$",
    )
    options: list[str] = Field(default_factory=list, description="MCQ options (exactly 4 for MCQ)")
    correct_answer: str = Field(default="", description="MCQ correct letter (A-D)")
    reference_answer: str = Field(..., min_length=1, description="Model answer used by grading")
    explanation: str = Field(..., min_length=1, description="Teaching explanation of the answer")
    max_score: float = Field(..., gt=0, description="Must equal the sum of rubric points")
    rubric: list[RubricItemUpdate] = Field(..., min_length=1)
    bloom_rationale: str | None = Field(default=None, description="Optional Bloom classification rationale")


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
    exam_title: str | None = None
    is_practice: bool = False
    lesson_id: str | None = None
    # Instructor-only screening fields; omitted/null in student-facing payloads
    is_suspicious: bool | None = None
    suspicion_status: str | None = None
    suspicion_reason: str | None = None
    anomaly_score: float | None = None


# ==============================================================================
# Analytics Schemas
# ==============================================================================


class ClusterResponse(BaseModel):
    """Cluster classification and diagnostic feature vectors."""

    model_config = ConfigDict(from_attributes=True)

    student_id: int
    cluster_label: str
    features: dict[str, Any]
    student_name: str | None = None
    student_email: str | None = None


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


# ==============================================================================
# Student Improvement Schemas
# ==============================================================================


class PracticeSettings(BaseModel):
    """Practice exam settings chosen by the backend from the student's level."""

    difficulty: str
    bloom_level: str
    question_types: list[str]
    number_of_questions: int
    level: str | None = None


class WeakLessonItem(BaseModel):
    """Per-lesson diagnosis built from the student's real (non-practice) attempts."""

    lesson_id: str
    lesson_title: str
    total_questions: int
    questions_wrong: int
    accuracy_pct: float
    attempts_count: int
    last_attempt_at: str | None = None
    trend: str = "unknown"
    status: str
    sample_wrong_questions: list[dict[str, Any]] = Field(default_factory=list)
    suggested_practice: PracticeSettings | None = None
    practice_available: bool = False
    practice_unavailable_reason: str | None = None


class PracticeScore(BaseModel):
    attempt_id: int | None = None
    exam_id: int | None = None
    submitted_at: str | None = None
    percentage: float
    difficulty: str | None = None


class PracticeHistoryItem(BaseModel):
    """Practice attempts of one lesson over time (oldest -> newest)."""

    lesson_id: str
    lesson_title: str
    practice_count: int
    best_percentage: float
    latest_percentage: float
    trend: str
    scores: list[PracticeScore] = Field(default_factory=list)


class ImprovementResponse(BaseModel):
    """Student Improvement page payload."""

    student_id: int
    student_level: str | None = None
    overall_accuracy: float | None = None
    real_attempts_count: int = 0
    lessons: list[WeakLessonItem] = Field(default_factory=list)
    practice_history: list[PracticeHistoryItem] = Field(default_factory=list)


class PracticeExamRequest(BaseModel):
    """Request a personal practice exam for one lesson (Student only)."""

    lesson_id: str = Field(..., min_length=1, max_length=100)
    number_of_questions: int = Field(default=5, ge=3, le=10)
    question_types: list[str] | None = Field(
        default=None,
        description="Optional override; allowed: 'mcq', 'short_answer', 'essay'",
    )

# ==============================================================================
# Question Bank Schemas
# ==============================================================================


class QuestionBankItemBase(BaseModel):
    """Base fields representing an assessment question."""

    question_text: str = Field(..., description="The main question prompt or stem")
    question_type: str = Field(default="mcq", description="mcq, essay, or short_answer")
    options: list[str] | None = Field(default=None, description="Multiple-choice options list")
    correct_option: str | None = Field(default=None, description="A, B, C, or D for MCQ")
    correct_answer: str = Field(..., description="Canonical model answer or reference solution")
    explanation: str | None = Field(default=None, description="Pedagogical explanation or reasoning")
    subject: str | None = Field(default=None, description="Disciplinary subject area")
    curriculum_id: str | None = Field(default=None, description="Curriculum document ID or reference")
    unit: str | None = Field(default=None, description="Unit name or code")
    chapter: str | None = Field(default=None, description="Chapter title or number")
    lesson: str | None = Field(default=None, description="Lesson title or code")
    page_number: str | None = Field(default=None, description="Verified source page number")
    bloom_level: str | None = Field(default=None, description="Remember, Understand, Apply, Analyze, Evaluate, Create")
    difficulty: str | None = Field(default=None, description="Easy, Medium, Hard, Unknown")


class QuestionBankItemCreate(BaseModel):
    """Payload for manual question entry or batch item ingestion."""

    question_id: str | None = None
    question_text: str = Field(..., min_length=3)
    question_type: str = Field(default="mcq")
    options: list[str] | None = None
    correct_option: str | None = None
    correct_answer: str = Field(...)
    explanation: str | None = None
    subject: str | None = None
    curriculum_id: str | None = None
    unit: str | None = None
    chapter: str | None = None
    lesson: str | None = None
    page_number: str | None = None
    bloom_level: str | None = None
    difficulty: str | None = None
    auto_classify: bool = Field(default=True, description="Whether to ground and classify with curriculum RAG")


class QuestionBankItemUpdate(BaseModel):
    """Fields that can be updated by an instructor during question review."""

    question_text: str | None = None
    options: list[str] | None = None
    correct_option: str | None = None
    correct_answer: str | None = None
    explanation: str | None = None
    subject: str | None = None
    unit: str | None = None
    chapter: str | None = None
    lesson: str | None = None
    page_number: str | None = None
    bloom_level: str | None = None
    difficulty: str | None = None
    classification_status: str | None = None


class QuestionBankReviewAction(BaseModel):
    """Teacher review decision payload."""

    corrections: dict[str, Any] | None = Field(
        default=None, description="Dictionary of instructor corrections"
    )
    notes: str | None = Field(default=None, description="Instructor review comments or rationale")


class QuestionBankItemResponse(BaseModel):
    """Full question bank entity including review lifecycle and grounded evidence."""

    id: int
    question_id: str
    original_question_id: str | None = None
    question_type: str
    question_text: str
    options: list[str] = Field(default_factory=list)
    correct_option: str | None = None
    correct_answer: str
    explanation: str | None = None
    subject: str | None = None
    curriculum_id: str | None = None
    unit: str | None = None
    chapter: str | None = None
    lesson: str | None = None
    page_number: str | None = None
    bloom_level: str | None = None
    difficulty: str | None = None
    learning_objective: str | None = None
    classification_reasoning: str | None = None
    classification_confidence: float | None = None
    grounding_confidence: float | None = None
    classification_status: str
    review_status: str
    needs_teacher_review: bool
    review_reasons: list[str] = Field(default_factory=list)
    review_notes: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    created_by: int | None = None
    teacher_corrections: dict[str, Any] | None = None
    source_chunk_ids: list[str] = Field(default_factory=list)
    source_evidence: str | None = None
    embedding_status: str
    created_at: str | None = None
    updated_at: str | None = None


class QuestionBankPaginatedResponse(BaseModel):
    """Paginated list of question bank items."""

    total: int
    page: int
    page_size: int
    total_pages: int
    items: list[QuestionBankItemResponse]


class QuestionBankStatsResponse(BaseModel):
    """Aggregate statistics for the question bank dashboard."""

    total_questions: int
    approved_count: int
    rejected_count: int
    needs_review_count: int
    pending_review_count: int
    difficulty_distribution: dict[str, int]
    bloom_distribution: dict[str, int]
    type_distribution: dict[str, int]


class QuestionClassificationRequest(BaseModel):
    """Request payload for on-demand curriculum-grounded classification."""

    question_text: str = Field(..., min_length=3)
    question_type: str = Field(default="mcq")
    options: list[str] | None = None
    correct_option: str | None = None
    correct_answer: str = Field(default="")
    explanation: str | None = None
    curriculum_id: int | None = None
    collection_name: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    persist: bool = Field(default=False, description="Persist immediately as a pending_review item in question bank")


class QuestionClassificationResponse(BaseModel):
    """Output of curriculum-grounded classification."""

    question_id: str
    question_text: str
    question_type: str
    options: list[str] = Field(default_factory=list)
    correct_option: str | None = None
    correct_answer: str | None = None
    explanation: str | None = None
    subject: str | None = None
    unit: str | None = None
    lesson: str | None = None
    page_number: str | None = None
    bloom_level: str
    difficulty: str
    classification_reasoning: str
    classification_confidence: float | None = None
    grounding_confidence: float | None = None
    classification_status: str
    source_chunk_ids: list[str] = Field(default_factory=list)
    source_evidence: str | None = None
    needs_teacher_review: bool
    review_reasons: list[str] = Field(default_factory=list)
    supporting_chunks: list[dict[str, Any]] = Field(default_factory=list)
    persisted_item: QuestionBankItemResponse | None = None

class QuestionPracticeSubmitRequest(BaseModel):
    """Payload for student submitting a practice answer."""
    selected_option: str | None = None
    answer_text: str | None = None


class QuestionPracticeGradingResponse(BaseModel):
    """Authoritative evaluation of student practice answer."""
    question_id: str
    question_type: str
    is_correct: bool | None = None
    score: float = 0.0
    max_score: float = 1.0
    status: str
    submitted_answer: str | None = None
    selected_option: str | None = None
    correct_option: str | None = None
    correct_answer: str | None = None
    explanation: str | None = None
    feedback_message: str
    requires_teacher_review: bool = False


# ---------------------------------------------------------------------------
# Cleaned Question Bank Dataset Schemas
# ---------------------------------------------------------------------------


class CleanedDatasetItem(BaseModel):
    """Normalized record from the verified cleaned question dataset."""

    question_id: str
    original_question_id: str | None = None
    question_type: str
    question_text: str
    options: list[str] = Field(default_factory=list)
    option_A: str | None = None
    option_B: str | None = None
    option_C: str | None = None
    option_D: str | None = None
    correct_option: str | None = None
    correct_answer: str = ""
    chapter: str | None = None
    lesson: str | None = None
    page_number: str | None = None
    source_file: str | None = None
    answer_source: str | None = None
    verification_status: str | None = None
    Source: str | None = None
    difficulty: str | None = None
    bloom_level: str | None = None
    is_duplicate: bool = False


class CleanedDatasetProvenance(BaseModel):
    """Cryptographic and file metadata for the cleaned dataset."""

    file_path: str
    file_size_bytes: int
    sha256_hash: str
    loaded_at: str
    sheet_name: str
    total_raw_rows: int
    valid_rows: int
    invalid_rows: int
    duplicate_rows: int
    has_difficulty_labels: bool
    has_bloom_labels: bool
    difficulty_column: str | None = None
    bloom_column: str | None = None


class CleanedDatasetPaginatedResponse(BaseModel):
    """Paginated response containing cleaned dataset questions and provenance."""

    total: int
    page: int
    page_size: int
    total_pages: int
    items: list[CleanedDatasetItem]
    provenance: CleanedDatasetProvenance
    filters_available: dict[str, list[str]] = Field(default_factory=dict)


