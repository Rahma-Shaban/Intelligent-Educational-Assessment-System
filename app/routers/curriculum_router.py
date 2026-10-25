"""Curriculum ingestion and lesson exploration endpoints."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_role
from app.database import get_db
from app.models import Curriculum, User
from app.schemas import CurriculumResponse, LessonItem
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
    generates embeddings, constructs a Chroma vector store collection, and
    records curriculum metadata in the database.
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
            collection_name="curriculum",
        )
        lessons_data = list_curriculum_lessons(store)
    except FileExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Curriculum collection already exists in vector store. "
                f"Details: {exc}"
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingestion pipeline failure: {exc}",
        )

    curriculum = Curriculum(
        filename=file.filename,
        lessons_json=json.dumps(lessons_data),
        vector_store_path=str(VECTOR_DB_PATH),
        uploaded_at=datetime.now(timezone.utc),
    )
    db.add(curriculum)
    db.commit()
    db.refresh(curriculum)

    return CurriculumResponse(
        id=curriculum.id,
        filename=curriculum.filename,
        lessons=[LessonItem(**item) for item in lessons_data],
        uploaded_at=curriculum.uploaded_at,
    )


@router.get(
    "/lessons",
    response_model=list[LessonItem],
    summary="List available curriculum lessons and chunk counts",
)
def get_lessons(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[LessonItem]:
    """
    Returns unique lessons and their chunk counts from the active curriculum store.
    """
    try:
        store = load_curriculum_store()
        lessons_data = list_curriculum_lessons(store)
        return [LessonItem(**item) for item in lessons_data]
    except (FileNotFoundError, ValueError):
        # Fallback to latest database record if store is loaded elsewhere
        latest_curriculum = db.scalar(
            select(Curriculum).order_by(Curriculum.uploaded_at.desc())
        )
        if latest_curriculum and latest_curriculum.lessons_json:
            try:
                cached_lessons = json.loads(latest_curriculum.lessons_json)
                return [LessonItem(**item) for item in cached_lessons]
            except Exception:
                pass

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No curriculum vector store found. Please upload a curriculum PDF first.",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve lessons: {exc}",
        )
