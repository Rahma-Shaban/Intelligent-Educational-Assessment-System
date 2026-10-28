"""Authentication routes: registration, login, and user profile."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user, hash_password, require_role, verify_password
from app.database import get_db
from app.models import User
from app.schemas import (
    LoginRequest,
    ProfessorOption,
    RegisterRequest,
    SelectProfessorRequest,
    TokenResponse,
    UserResponse,
)

router = APIRouter(tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new student or professor account",
)
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
) -> UserResponse:
    """
    Registers a new user account.
    Verifies that the email address is unique before creating the record.
    """
    clean_email = payload.email.strip().lower()
    existing = db.scalar(select(User).where(User.email == clean_email))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email address already exists.",
        )

    user = User(
        name=payload.name.strip(),
        email=clean_email,
        hashed_password=hash_password(payload.password),
        role=payload.role.strip().lower(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate and receive a JWT access token",
)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    """
    Authenticates user credentials and returns a signed JWT token.
    """
    clean_email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == clean_email))
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        data={"sub": str(user.id), "email": user.email, "role": user.role}
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current authenticated user profile",
)
def get_me(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """
    Returns the profile of the currently authenticated user.
    """
    return UserResponse.model_validate(current_user)


@router.get(
    "/professors",
    response_model=list[ProfessorOption],
    summary="List professors available for student enrollment",
)
def list_professors(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ProfessorOption]:
    """
    Returns all professor accounts so students can choose whom to enroll with.
    """
    professors = db.scalars(
        select(User).where(User.role == "professor").order_by(User.name)
    ).all()
    return [ProfessorOption(id=p.id, name=p.name, email=p.email) for p in professors]


@router.put(
    "/select-professor",
    response_model=UserResponse,
    summary="Persist the student's selected professor (Student only)",
)
def select_professor(
    payload: SelectProfessorRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("student")),
) -> UserResponse:
    """
    Persists the professor a student is enrolled with on their account.
    Exam visibility and attempt access are scoped to this selection.
    """
    professor = db.scalar(
        select(User).where(User.id == payload.professor_id, User.role == "professor")
    )
    if not professor:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The selected professor account does not exist.",
        )

    current_user.selected_professor_id = professor.id
    db.commit()
    db.refresh(current_user)
    return UserResponse.model_validate(current_user)
