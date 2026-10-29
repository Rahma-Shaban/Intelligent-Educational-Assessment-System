"""SQLAlchemy ORM models for Intelligent Educational Assessment System."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    """User account model for professors and students."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="student")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    exams: Mapped[list["Exam"]] = relationship(
        "Exam",
        back_populates="creator",
        foreign_keys="Exam.created_by",
        cascade="all, delete-orphan",
    )
    attempts: Mapped[list["ExamAttempt"]] = relationship(
        "ExamAttempt",
        back_populates="student",
        cascade="all, delete-orphan",
    )
    cluster: Mapped[Optional["StudentCluster"]] = relationship(
        "StudentCluster",
        back_populates="student",
        uselist=False,
        cascade="all, delete-orphan",
    )
    # Professor a student is enrolled with (students only; persisted selection)
    selected_professor_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )


class Curriculum(Base):
    """Uploaded curriculum documents and vector store references."""

    __tablename__ = "curriculums"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    lessons_json: Mapped[str] = mapped_column(Text, nullable=False)
    vector_store_path: Mapped[str] = mapped_column(String(500), nullable=False)
    # Professor who uploaded this document (NULL for legacy pre-scoping rows)
    professor_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Chroma collection used for retrieval; NULL means legacy shared "curriculum"
    collection_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    exams: Mapped[list["Exam"]] = relationship(
        "Exam",
        back_populates="curriculum",
    )


class Exam(Base):
    """Generated exam records with full question specifications."""

    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    curriculum_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("curriculums.id", ondelete="SET NULL"),
        nullable=True,
    )
    lesson_id: Mapped[str] = mapped_column(String(100), nullable=False)
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    difficulty: Mapped[str] = mapped_column(String(50), nullable=False)
    bloom_level: Mapped[str] = mapped_column(String(50), nullable=False)
    exam_json: Mapped[str] = mapped_column(Text, nullable=False)
    total_points: Mapped[float] = mapped_column(Float, nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Student Improvement: personal practice exams are hidden from exam lists and analytics
    is_practice: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    practice_for_student_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    created_by: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    creator: Mapped["User"] = relationship("User", back_populates="exams", foreign_keys=[created_by])
    curriculum: Mapped[Optional["Curriculum"]] = relationship("Curriculum", back_populates="exams")
    attempts: Mapped[list["ExamAttempt"]] = relationship(
        "ExamAttempt",
        back_populates="exam",
        cascade="all, delete-orphan",
    )


class ExamAttempt(Base):
    """Individual student exam attempt and graded responses."""

    __tablename__ = "exam_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    exam_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("exams.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_possible_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    graded_answers_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Statistical screening indicators for instructor review (not a misconduct finding)
    is_suspicious: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    suspicion_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    suspicion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    anomaly_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Relationships
    exam: Mapped["Exam"] = relationship("Exam", back_populates="attempts")
    student: Mapped["User"] = relationship("User", back_populates="attempts")


class StudentCluster(Base):
    """Clustering profile and behavioral/performance features per student."""

    __tablename__ = "student_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    student_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    cluster_label: Mapped[str] = mapped_column(String(100), nullable=False)
    features_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    student: Mapped["User"] = relationship("User", back_populates="cluster")


class QuestionBankItem(Base):
    """Persisted question bank item with full field preservation, evidence mapping, and review lifecycle."""

    __tablename__ = "question_bank_items"

    # --- Primary key and stable IDs ---
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    question_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    original_question_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # --- Core question fields ---
    question_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "mcq", "essay", etc.
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    options_json: Mapped[str | None] = mapped_column(Text, nullable=True)     # JSON array of strings
    correct_option: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 'A','B','C','D' for MCQ
    correct_answer: Mapped[str] = mapped_column(Text, nullable=False)          # model answer text
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Curriculum & Source Metadata ---
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    curriculum_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    unit: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chapter: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lesson: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    page_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_file: Mapped[str | None] = mapped_column(String(500), nullable=True)
    answer_source: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verification_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON: extra fields
    validation_warnings_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array

    # --- Classification & Psychometric Analysis ---
    bloom_level: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    difficulty: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    learning_objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    learning_objective_grounded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    classification_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    analysis_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    classification_method: Mapped[str | None] = mapped_column(String(100), nullable=True, default="rag_llm")
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # --- Source Evidence & Grounding ---
    source_chunk_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of chunk IDs
    source_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    curriculum_mapping_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # full mapping dict
    original_source_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Review & Approval Lifecycle ---
    # Allowed: "pending_review", "approved", "rejected", "needs_review"
    classification_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending_review", index=True
    )
    review_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending_review", index=True
    )
    needs_teacher_review: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    review_reasons_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # --- Incremental Learning from Teacher Approvals ---
    teacher_corrections_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # proposed vs approved diff

    # --- Duplicate Detection ---
    is_duplicate_candidate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    duplicate_of_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duplicate_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    duplicate_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Question Bank Embedding Sync ---
    embedding_id: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True, index=True)
    embedding_status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending", index=True
    )  # "pending" | "synced" | "failed"
    embedding_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    imported_from: Mapped[str | None] = mapped_column(String(500), nullable=True)

class QuestionBankPracticeSubmission(Base):
    """Persisted student self-practice submission and authoritative grading record."""

    __tablename__ = "question_bank_practice_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    question_id: Mapped[str] = mapped_column(String(100), ForeignKey("question_bank_items.question_id", ondelete="CASCADE"), index=True, nullable=False)
    student_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    selected_option: Mapped[str | None] = mapped_column(String(10), nullable=True)
    submitted_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="graded")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
