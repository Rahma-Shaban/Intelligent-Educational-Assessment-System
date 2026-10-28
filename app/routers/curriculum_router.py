"""Curriculum ingestion, document library, and lesson exploration endpoints."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.database import get_db
from app.models import Curriculum, User
from app.schemas import CurriculumResponse, CurriculumSummary, LessonItem
from scripts.config import PROCESSED_DATA_DIR, RAW_DATA_DIR, VECTOR_DB_PATH
from scripts.generation import list_curriculum_lessons, load_curriculum_store
from scripts.ingestion import (
    build_vectorstore,
    chunk_pages,
    extract_pages,
    get_embeddings,
    save_chunks_jsonl,
)

router = APIRouter(tags=["Curriculum"])


def _document_visible_to(document: Curriculum, user: User) -> bool:
    """Professors see their own uploads; NULL professor_id marks legacy shared docs."""
    if user.role == "professor":
        return document.professor_id in (None, user.id)
    return document.professor_id is None


def _get_owned_document(
    curriculum_id: int, db: Session, current_user: User
) -> Curriculum:
    """Fetch a curriculum document and enforce professor ownership."""
    document = db.scalar(select(Curriculum).where(Curriculum.id == curriculum_id))
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {curriculum_id} not found.",
        )
    if (
        current_user.role == "professor"
        and document.professor_id is not None
        and document.professor_id != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: this document belongs to another professor.",
        )
    return document


def _parse_lessons(document: Curriculum) -> list[dict]:
    try:
        lessons = json.loads(document.lessons_json or "[]")
        return lessons if isinstance(lessons, list) else []
    except Exception:
        return []


def _collection_name(document: Curriculum) -> str:
    """Legacy documents live in the shared 'curriculum' collection."""
    return document.collection_name or "curriculum"


@router.post(
    "/upload",
    response_model=CurriculumResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and ingest curriculum PDF (Professor only)",
)
def upload_curriculum(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> CurriculumResponse:
    """
    Accepts a curriculum PDF file, extracts and semantically chunks pages,
    generates embeddings, constructs a dedicated Chroma vector store collection
    for this document, and records professor-scoped metadata in the database.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be a valid PDF document.",
        )

    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DATA_DIR.mkdir(parents=True, exist_ok=True)

    dest_path = RAW_DATA_DIR / file.filename
    try:
        with dest_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save uploaded PDF: {exc}",
        )

    # Reserve the row first so each document gets its own vector collection
    document = Curriculum(
        filename=file.filename,
        lessons_json=json.dumps([]),
        vector_store_path=str(VECTOR_DB_PATH),
        professor_id=current_user.id,
        collection_name=None,
        uploaded_at=datetime.now(timezone.utc),
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    collection_name = f"curriculum_{document.id}"
    try:
        pages = extract_pages(dest_path)
        if not pages:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No readable lesson pages could be extracted from the PDF.",
            )

        chunks = chunk_pages(pages)
        chunks_file = PROCESSED_DATA_DIR / f"{Path(file.filename).stem}_chunks.jsonl"
        save_chunks_jsonl(chunks, chunks_file)

        embeddings = get_embeddings()
        store = build_vectorstore(
            chunks=chunks,
            embeddings=embeddings,
            persist_dir=VECTOR_DB_PATH,
            collection_name=collection_name,
        )
        lessons_data = list_curriculum_lessons(store)
    except HTTPException:
        db.delete(document)
        db.commit()
        raise
    except Exception as exc:
        db.delete(document)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion pipeline failure: {exc}",
        )

    document.lessons_json = json.dumps(lessons_data)
    document.collection_name = collection_name
    db.commit()
    db.refresh(document)

    return CurriculumResponse(
        id=document.id,
        filename=document.filename,
        lessons=[LessonItem(**item) for item in lessons_data],
        uploaded_at=document.uploaded_at,
        professor_id=document.professor_id,
        collection_name=document.collection_name,
        lesson_count=len(lessons_data),
    )


@router.get(
    "",
    response_model=list[CurriculumSummary],
    summary="List the professor's uploaded documents (Document Library)",
)
@router.get(
    "/",
    response_model=list[CurriculumSummary],
    include_in_schema=False,
)
def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> list[CurriculumSummary]:
    """
    Returns all curriculum documents visible to the current professor
    (their own uploads plus legacy shared documents), newest first.
    """
    documents = db.scalars(
        select(Curriculum)
        .where(or_(Curriculum.professor_id == current_user.id, Curriculum.professor_id.is_(None)))
        .order_by(Curriculum.uploaded_at.desc())
    ).all()

    results: list[CurriculumSummary] = []
    for doc in documents:
        lessons = _parse_lessons(doc)
        results.append(
            CurriculumSummary(
                id=doc.id,
                filename=doc.filename,
                uploaded_at=doc.uploaded_at,
                professor_id=doc.professor_id,
                lesson_count=len(lessons),
                lessons=[LessonItem(**item) for item in lessons],
            )
        )
    return results


@router.get(
    "/{curriculum_id}/lessons",
    response_model=list[LessonItem],
    summary="List lessons belonging to one document (Professor only)",
)
def get_document_lessons(
    curriculum_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("professor")),
) -> list[LessonItem]:
    """
    Returns only the lessons extracted from the given document. Used by the
    textbook-first exam creation flow so lessons never leak across textbooks.
    """
    document = _get_owned_document(curriculum_id, db, current_user)
    lessons = _parse_lessons(document)
    if not lessons:
        # Fall back to reading the dedicated vector store if metadata is empty
        try:
            store = load_curriculum_store(
                persist_dir=document.vector_store_path or VECTOR_DB_PATH,
                collection_name=_collection_name(document),
            )
            lessons = list_curriculum_lessons(store)
        except Exception:
            lessons = []

    return [LessonItem(**item) for item in lessons]


@router.get(
    "/lessons",
    response_model=list[LessonItem],
    summary="List lessons from the professor's most recent document",
)
def get_lessons(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[LessonItem]:
    """
    Backward-compatible endpoint: returns unique lessons from the professor's
    latest document (or the latest legacy shared document).
    """
    latest_document = db.scalar(
        select(Curriculum)
        .where(or_(Curriculum.professor_id == current_user.id, Curriculum.professor_id.is_(None)))
        .order_by(Curriculum.uploaded_at.desc())
    )
    if latest_document and latest_document.lessons_json:
        cached_lessons = _parse_lessons(latest_document)
        if cached_lessons:
            return [LessonItem(**item) for item in cached_lessons]

    try:
        store = load_curriculum_store()
        lessons_data = list_curriculum_lessons(store)
        return [LessonItem(**item) for item in lessons_data]
    except (FileNotFoundError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No curriculum vector store found. Please upload a curriculum PDF first.",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve lessons: {exc}",
        )
