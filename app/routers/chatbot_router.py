"""Chatbot router – intelligent conversational Q&A grounded in the curriculum vector store.

Features:
- Thread-safe lazy vectorstore singleton with asynchronous background warm-up.
- Non-blocking retrieval: avoids server lockups during warm-up.
- Dedicated fast LLM model (CHATBOT_MODEL_NAME via Groq) with clear error handling.
- Intelligent intent understanding: handles casual talk, educational questions,
  clarifications, follow-ups, and platform queries in Arabic, Egyptian dialect, and English.
- Real platform integration: answers student queries about exams, attempts, results,
  and instructors from live database records without hallucination.
- Strict role-based isolation: students can only access published exams and their own attempts.
- Grounded curriculum RAG with deduplicated chunks and transparent citation.
- End-to-end latency measurement and diagnostic logging without logging PII or API keys.
"""

from __future__ import annotations

import json
import logging
import re 
import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Exam, ExamAttempt, User
from scripts.config import (
    CHATBOT_MODEL_NAME,
    GROQ_API_KEY,
    GROQ_BASE_URL,
    HF_EMBEDDING_MODEL_NAME,
    VECTOR_DB_PATH,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chatbot"])

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class ConversationTurn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_history: list[ConversationTurn] = Field(default_factory=list, max_length=10)
    language: str = Field(default="auto", max_length=10)


class SourceInfo(BaseModel):
    lesson_id: str
    lesson_title: str
    chunk_id: str


class ChatResponse(BaseModel):
    reply: str
    sources: list[SourceInfo]
    language: str


# ---------------------------------------------------------------------------
# Thread-safe Lazy Singletons with Non-blocking Warmup
# ---------------------------------------------------------------------------

_warmup_event = threading.Event()
_warmup_lock = threading.Lock()
_embeddings: Any = None
_vectorstore: Any = None
_warmup_started: bool = False
_warmup_error: str | None = None


def _init_vectorstore_worker() -> None:
    """Worker function to initialize embeddings and vector store once."""
    global _embeddings, _vectorstore, _warmup_error
    try:
        t0 = time.monotonic()
        logger.info("Chatbot: Pre-warming Hugging Face embeddings and Chroma vector store...")
        from scripts.ingestion import get_embeddings, load_vectorstore

        emb = get_embeddings(HF_EMBEDDING_MODEL_NAME)
        store = load_vectorstore(emb, persist_dir=VECTOR_DB_PATH, collection_name="curriculum")

        _embeddings = emb
        _vectorstore = store
        _warmup_event.set()
        elapsed = time.monotonic() - t0
        logger.info("Chatbot: Vector store pre-warmed successfully in %.2fs.", elapsed)
    except Exception as exc:
        _warmup_error = str(exc)
        _warmup_event.set()
        logger.warning("Chatbot: Vector store pre-warming failed: %s", exc)


def warmup_vectorstore_async() -> None:
    """Trigger background warm-up of the vector store at application startup."""
    global _warmup_started
    with _warmup_lock:
        if not _warmup_started:
            _warmup_started = True
            thread = threading.Thread(target=_init_vectorstore_worker, daemon=True, name="ChatbotWarmup")
            thread.start()


def get_vectorstore_singleton(timeout: float = 3.0) -> Any:
    """Return the vector store singleton.

    Waits up to `timeout` seconds if warm-up is still in progress.
    If initialization is still underway or failed, returns None safely to avoid blocking.
    """
    global _warmup_started
    if _vectorstore is not None:
        return _vectorstore

    with _warmup_lock:
        if not _warmup_started:
            warmup_vectorstore_async()

    # Wait briefly for background warm-up without freezing the client
    if not _warmup_event.is_set():
        _warmup_event.wait(timeout=timeout)

    return _vectorstore


# ---------------------------------------------------------------------------
# Language & Text Helpers
# ---------------------------------------------------------------------------

_ARABIC_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
_TASHKEEL_RE = re.compile(r"[\u064B-\u065F\u0670]")


def normalize_text(text: str) -> str:
    """Strip Arabic tashkeel (diacritics), punctuation, and lowercase."""
    cleaned = _TASHKEEL_RE.sub("", text)
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def detect_language(text: str) -> str:
    """Return 'ar' if Arabic characters are present, otherwise 'en'."""
    return "ar" if _ARABIC_RE.search(text) else "en"


_GREETING_WORDS_AR = {
    "مرحبا", "اهلا", "سلام", "السلام عليكم",
    "صباح الخير", "مساء الخير", "ازيك", "عامل ايه", "يا هلا", "هاي", "الو", "شخبارك"
}
_GREETING_WORDS_EN = {
    "hi", "hello", "hey", "good morning", "good evening", "how are you", "what's up", "sup"
}
_THANKS_WORDS_AR = {
    "شكرا", "شكرا لك", "تسلم", "الف شكر", "جزاك الله خيرا", "ربنا يخليك",
    "شكرا جزيلا", "مشكور", "جزيلا"
}
_THANKS_WORDS_EN = {
    "thanks", "thank you", "thx", "appreciate it", "great thanks", "thanks a lot"
}


def is_trivial_greeting(message: str, history_len: int) -> bool:
    """Identify standalone introductory greetings without preceding context."""
    if history_len > 0:
        return False
    clean = normalize_text(message)
    if clean in _GREETING_WORDS_AR or clean in _GREETING_WORDS_EN:
        return True
    words = clean.split()
    return 1 <= len(words) <= 3 and all(w in _GREETING_WORDS_AR or w in _GREETING_WORDS_EN for w in words)


def is_trivial_thanks(message: str) -> bool:
    """Identify standalone closure / gratitude phrases."""
    clean = normalize_text(message)
    if clean in _THANKS_WORDS_AR or clean in _THANKS_WORDS_EN:
        return True
    words = clean.split()
    return 1 <= len(words) <= 3 and any(w in _THANKS_WORDS_AR or w in _THANKS_WORDS_EN for w in words)


# ---------------------------------------------------------------------------
# Platform Context Collector (Real App Data & Routes)
# ---------------------------------------------------------------------------

def build_student_platform_context(current_user: User, db: Session) -> str:
    """Retrieve real-time platform data for the student while respecting role boundaries."""
    # 1. Instructor Info
    instructor_name = "Not selected yet"
    instructor_email = "N/A"
    if current_user.selected_professor_id:
        prof = db.query(User).filter(User.id == current_user.selected_professor_id, User.role == "professor").first()
        if prof:
            instructor_name = prof.name
            instructor_email = prof.email

    # 2. Available Published Exams
    if current_user.selected_professor_id:
        exams = db.query(Exam).filter(
            Exam.is_published == True,
            Exam.created_by == current_user.selected_professor_id
        ).all()
        if not exams:
            exams = db.query(Exam).filter(Exam.is_published == True).all()
    else:
        exams = db.query(Exam).filter(Exam.is_published == True).all()

    if exams:
        exam_lines = []
        for e in exams[:5]:
            exam_lines.append(f"- ID {e.id}: '{e.title}' | Topic: {e.topic} | Difficulty: {e.difficulty} | Points: {e.total_points}")
        available_exams_text = "\n".join(exam_lines)
    else:
        available_exams_text = "No published exams currently available."

    # 3. Student's Recent Attempts & Results
    attempts = (
        db.query(ExamAttempt)
        .filter(ExamAttempt.student_id == current_user.id)
        .order_by(ExamAttempt.submitted_at.desc())
        .limit(5)
        .all()
    )

    if attempts:
        attempt_lines = []
        for att in attempts:
            ex = db.query(Exam).filter(Exam.id == att.exam_id).first()
            title = ex.title if ex else f"Exam #{att.exam_id}"
            score = f"{att.total_score}/{att.max_possible_score}" if att.total_score is not None else "In Progress"
            date_str = att.submitted_at.strftime("%Y-%m-%d") if att.submitted_at else "Ongoing"
            attempt_lines.append(f"- Exam '{title}': Score {score} (Submitted on {date_str})")
        recent_attempts_text = "\n".join(attempt_lines)
    else:
        recent_attempts_text = "No exams attempted yet."

    return (
        f"- Current Student: {current_user.name} (Role: student)\n"
        f"- Assigned Instructor: {instructor_name} ({instructor_email})\n"
        f"- Available Published Exams:\n{available_exams_text}\n"
        f"- Student's Recent Exam Attempts:\n{recent_attempts_text}\n"
        "- Real Platform Routes:\n"
        "  * Start Exam: Student Dashboard -> published exams (/api/attempts/start)\n"
        "  * View History & Grades: Student Analytics dashboard (/api/attempts/my/history, /api/analytics/dashboard/student)\n"
        "  * Select Professor: Select Professor menu (/api/auth/select-professor)"
    )


# ---------------------------------------------------------------------------
# Retrieval & Context Selection
# ---------------------------------------------------------------------------

_PLATFORM_KEYWORDS = (
    "منصة", "المنصة", "امتحان", "الامتحان", "امتحانات", "الامتحانات", "درجات", "درجاتي",
    "نتيجة", "نتائج", "استاذ", "أستاذ", "دكتور", "دكتوري", "تسجيل", "دخول", "حسابي",
    "exam", "exams", "grade", "grades", "score", "scores", "professor", "instructor",
    "result", "results", "attempt", "attempts", "platform", "login"
)


def should_retrieve_curriculum(message: str) -> bool:
    """Determine whether the message requires curriculum vector store retrieval.

    Avoids querying vector DB for platform mechanics or generic casual conversation.
    """
    clean = normalize_text(message)

    # Pure platform entities without explicit course/curriculum concepts
    platform_hits = any(kw in clean for kw in (
        "منصة", "امتحان", "درجات", "درجتي", "نتيجة", "نتائج", "استاذ",
        "دكتور", "تسجيل", "دخول", "حساب", "حسابي", "exam", "grade", "score",
        "professor", "instructor", "result", "attempt", "platform", "login"
    ))

    academic_topics = any(kw in clean for kw in (
        "درس", "خوارزمية", "كود", "برمجة", "ذكاء", "شبكة", "بيانات", "مجتمع",
        "تكنولوجيا", "algorithm", "code", "programming", "ai", "artificial intelligence",
        "neural", "technology", "society", "model", "python", "java", "oop", "recursion",
        "supervised", "unsupervised", "classification", "regression", "sorting"
    ))

    if platform_hits and not academic_topics:
        return False

    return True


def formulate_retrieval_query(message: str, history: list[ConversationTurn]) -> str:
    """Resolve context-dependent follow-ups (e.g. 'explain differently', 'give an example')

    using recent user and assistant turns.
    """
    clean = message.strip()
    words = clean.split()

    follow_up_triggers = {
        "explain differently", "explain more", "give me an example", "why", "how",
        "اشرح بشكل أبسط", "اشرحها تاني", "وضح اكتر", "وضح أكثر", "مثال", "ليه", "ازاي"
    }
    is_follow_up = len(words) <= 4 or any(t in clean.lower() for t in follow_up_triggers)

    if is_follow_up and history:
        for turn in reversed(history[-4:]):
            if turn.role in {"user", "student"} and turn.content:
                prev_clean = turn.content.strip()
                if len(prev_clean.split()) > 2 and prev_clean != clean:
                    return f"{prev_clean} {clean}"

    return clean


def retrieve_curriculum_context(
    query: str,
    k: int = 4,
) -> tuple[list[str], list[SourceInfo]]:
    """Retrieve and deduplicate relevant curriculum chunks from Chroma."""
    store = get_vectorstore_singleton(timeout=2.0)
    if store is None:
        logger.info("Chatbot: Vector store unavailable or still warming up; skipping retrieval.")
        return [], []

    try:
        from scripts.ingestion import retrieve

        docs = retrieve(store, query=query, k=k + 2)
    except Exception as exc:
        logger.warning("Chatbot retrieval error: %s", exc)
        return [], []

    context_snippets: list[str] = []
    sources: list[SourceInfo] = []
    seen_chunk_ids: set[str] = set()
    seen_texts: set[str] = set()
    total_chars = 0

    for doc in docs:
        content = getattr(doc, "page_content", "") or ""
        content = content.strip()
        if not content or len(content) < 30:
            continue

        normalized_prefix = content[:120].lower()
        if normalized_prefix in seen_texts:
            continue
        seen_texts.add(normalized_prefix)

        meta = getattr(doc, "metadata", {}) or {}
        chunk_id = str(meta.get("chunk_id", "")).strip()

        if chunk_id and chunk_id in seen_chunk_ids:
            continue
        if chunk_id:
            seen_chunk_ids.add(chunk_id)

        lesson_id = str(meta.get("lesson_id", "")).strip()
        lesson_title = str(meta.get("lesson_title", "")).strip()

        if total_chars + len(content) > 3500:
            break

        header = f"[Source: Lesson {lesson_id} - {lesson_title}]" if lesson_title else "[Source: Curriculum]"
        context_snippets.append(f"{header}\n{content}")
        total_chars += len(content)

        if chunk_id and (lesson_id or lesson_title):
            sources.append(
                SourceInfo(
                    lesson_id=lesson_id,
                    lesson_title=lesson_title or lesson_id,
                    chunk_id=chunk_id,
                )
            )

    return context_snippets, sources


# ---------------------------------------------------------------------------
# Direct Fast Groq Completion
# ---------------------------------------------------------------------------

def _call_chatbot_llm(messages: list[dict[str, str]], temperature: float = 0.3) -> str:
    """Invoke the dedicated CHATBOT_MODEL_NAME via Groq with strict timeout and clear error reporting."""
    if not GROQ_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chatbot AI service key is not configured.",
        )

    import httpx
    from scripts.generation import _build_ssl_context

    base_url = (GROQ_BASE_URL or "https://api.groq.com/openai/v1").rstrip("/")
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": CHATBOT_MODEL_NAME,
        "messages": messages,
        "temperature": temperature,
        "max_completion_tokens": 1024,
    }

    try:
        with httpx.Client(timeout=20.0, verify=_build_ssl_context()) as client:
            response = client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
    except httpx.TimeoutException:
        logger.error("Chatbot LLM call timed out after 20s.")
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="The AI assistant timed out while generating a response. Please try again.",
        )
    except httpx.RequestError as exc:
        logger.error("Chatbot network error contacting Groq: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unable to reach AI service. Please check your connection.",
        )

    if response.status_code != 200:
        safe_err = response.text.replace(GROQ_API_KEY, "[REDACTED]")
        logger.error("Chatbot Groq error (%d): %s", response.status_code, safe_err)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI service returned error ({response.status_code}): {response.reason_phrase}",
        )

    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI service returned an empty response.",
        )

    content = choices[0].get("message", {}).get("content", "").strip()
    return content


# ---------------------------------------------------------------------------
# Prompt Assembly
# ---------------------------------------------------------------------------

_SYSTEM_INSTRUCTIONS = (
    "You are an intelligent, pedagogically skilled academic AI tutor and assistant on the "
    "Intelligent Educational Assessment System platform.\n\n"
    "Core Capabilities & Rules:\n"
    "1. Language & Dialect: Naturally match the student's language. If the student writes in Egyptian Arabic "
    "(العامية المصرية), Modern Standard Arabic (الفصحى), English, or mixed tech-Arabic, reply in the same natural dialect "
    "and style. Keep explanations engaging, clear, encouraging, and conversational.\n"
    "2. Platform Questions: When asked about platform mechanics, exams, grades, attempts, or professors, "
    "use ONLY the provided [STUDENT PLATFORM CONTEXT]. Never invent instructor names, exam names, or student grades. "
    "Respect student boundaries (students cannot access professor admin tools or other students' data).\n"
    "3. Curriculum Questions & RAG Grounding:\n"
    "   - When [CURRICULUM TEXTBOOK CONTEXT] is provided, ground your explanation in these verified course materials. "
    "Cite the lesson name naturally where relevant.\n"
    "   - If the provided curriculum context does NOT contain the answer, or if context is empty, transparently inform the "
    "student that this topic is not covered in the current uploaded course materials, and then provide a clear, accurate "
    "general academic explanation based on standard Computer Science and AI principles.\n"
    "   - NEVER hallucinate fake textbook page numbers or fake lesson citations.\n"
    "4. Conversational Flow & Multi-Turn: Use the conversation history to seamlessly resolve follow-up questions, "
    "requests for alternative explanations, examples, or code samples without asking the student to repeat context.\n"
    "5. Output Format: Write directly in clear, beautifully formatted Markdown with bullet points, bold key terms, "
    "and code blocks where appropriate. Do NOT wrap your output in JSON."
)


def build_prompt_messages(
    message: str,
    platform_context: str,
    curriculum_snippets: list[str],
    history: list[ConversationTurn],
) -> list[dict[str, str]]:
    """Assemble system prompt, bounded history, and current message for the LLM."""
    messages: list[dict[str, str]] = []

    system_text = _SYSTEM_INSTRUCTIONS + "\n\n"
    system_text += f"[STUDENT PLATFORM CONTEXT]:\n{platform_context}\n\n"

    if curriculum_snippets:
        context_block = "\n---\n".join(curriculum_snippets)
        system_text += f"[CURRICULUM TEXTBOOK CONTEXT]:\n{context_block}\n"
    else:
        system_text += "[CURRICULUM TEXTBOOK CONTEXT]:\n(No specific textbook chunks retrieved for this query.)\n"

    messages.append({"role": "system", "content": system_text})

    # Add bounded conversation history (last 6-8 turns)
    for turn in history[-8:]:
        role = "assistant" if turn.role in {"assistant", "bot"} else "user"
        content = (turn.content or "").strip()
        if content:
            messages.append({"role": role, "content": content})

    # Add current user turn
    messages.append({"role": "user", "content": message.strip()})
    return messages


# ---------------------------------------------------------------------------
# API Route
# ---------------------------------------------------------------------------

@router.post("/message", response_model=ChatResponse)
def chat_message(
    body: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChatResponse:
    """Handle conversational student requests with optional RAG retrieval and fast LLM response."""
    start_time = time.monotonic()

    # 1. Role verification: student only
    if current_user.role != "student":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Chatbot is accessible only to students.",
        )

    # 2. Language detection
    lang = body.language
    if lang == "auto":
        lang = detect_language(body.message)

    # 3. Trivial Case 1: Standalone Greeting (zero prior history)
    if is_trivial_greeting(body.message, len(body.conversation_history)):
        user_name = (current_user.name or "").split()[0]
        if lang == "ar":
            reply = (
                f"أهلاً وسهلاً بك يا {user_name}! 👋\n"
                "أنا مساعدك الذكي في المنصة التعليمية. يمكنك سؤالي عن مفاهيم المنهج، "
                "أو الاستفسار عن امتحاناتك ودرجاتك، أو كيفية استخدام المنصة. بماذا تحب أن نبدأ اليوم؟"
            )
        else:
            reply = (
                f"Hello {user_name}! 👋\n"
                "I am your academic AI assistant. You can ask me about course curriculum concepts, "
                "check your available exams or scores, or ask how to use the platform. How can I help you today?"
            )
        return ChatResponse(reply=reply, sources=[], language=lang)

    # 4. Trivial Case 2: Pure Standalone Thanks
    if is_trivial_thanks(body.message):
        if lang == "ar":
            reply = "العفو! على الرحب والسعة دائماً. أتمنى لك كل التوفيق، وإذا احتجت أي شرح إضافي أنا هنا دائماً! 🌟"
        else:
            reply = "You're very welcome! Best of luck with your studies, and feel free to ask anytime you need help! 🌟"
        return ChatResponse(reply=reply, sources=[], language=lang)

    # 5. Build Student Platform Context from live database
    platform_context = build_student_platform_context(current_user, db)

    # 6. Optional Curriculum Retrieval
    curriculum_snippets: list[str] = []
    sources: list[SourceInfo] = []
    retrieval_duration = 0.0

    if should_retrieve_curriculum(body.message):
        t_ret_start = time.monotonic()
        retrieval_query = formulate_retrieval_query(body.message, body.conversation_history)
        curriculum_snippets, sources = retrieve_curriculum_context(retrieval_query, k=4)
        retrieval_duration = time.monotonic() - t_ret_start

    # 7. Assemble Prompt & Call Dedicated LLM
    messages = build_prompt_messages(
        message=body.message,
        platform_context=platform_context,
        curriculum_snippets=curriculum_snippets,
        history=body.conversation_history,
    )

    t_llm_start = time.monotonic()
    reply = _call_chatbot_llm(messages, temperature=0.3)
    llm_duration = time.monotonic() - t_llm_start

    # Clean JSON wrapping if the LLM output raw JSON
    if reply.startswith("{") and reply.endswith("}"):
        try:
            parsed = json.loads(reply)
            if isinstance(parsed, dict) and "reply" in parsed:
                reply = str(parsed["reply"])
        except Exception:
            pass

    total_duration = time.monotonic() - start_time
    logger.info(
        "Chatbot turn completed in %.2fs (retrieval: %.2fs, llm: %.2fs, chunks: %d, lang: %s)",
        total_duration,
        retrieval_duration,
        llm_duration,
        len(sources),
        lang,
    )

    return ChatResponse(
        reply=reply,
        sources=sources,
        language=lang,
    )
