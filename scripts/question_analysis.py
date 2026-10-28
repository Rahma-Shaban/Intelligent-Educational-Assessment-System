"""
Question Analysis Module for Intelligent Educational Assessment System.

Stage 2 implementation:
  - Classifies questions into Bloom's Taxonomy levels (remember, understand, apply, analyze, evaluate, create).
  - Classifies difficulty (easy, medium, hard) based on multi-dimensional cognitive complexity criteria.
  - Derives grounded learning objectives from curriculum context (or marks them unresolved when context is insufficient).
  - Preserves original question text, options, answers, IDs, and human-verified metadata.
  - Maintains strict separation between question_type, bloom_level, difficulty, and learning_objective.
  - Generates classification reasoning, confidence scoring, and teacher review flags for uncertain classifications.
  - Reuses project LLM provider configuration and handles malformed outputs or provider errors gracefully.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import logging
import re
from typing import Any, Optional

from scripts.config import (
    GEMINI_API_KEY,
    GROQ_API_KEY,
    LLM_MODEL_NAME,
    LLM_PROVIDER,
    OLLAMA_BASE_URL,
)

logger = logging.getLogger(__name__)

# Valid cognitive domains according to Bloom's Revised Taxonomy
VALID_BLOOM_LEVELS: tuple[str, ...] = (
    "remember",
    "understand",
    "apply",
    "analyze",
    "evaluate",
    "create",
)

# Valid difficulty tiers with clearly defined complexity criteria
VALID_DIFFICULTY_LEVELS: tuple[str, ...] = ("easy", "medium", "hard")

MAX_ANALYSIS_TOKENS: int = 2048
ANALYSIS_TEMPERATURE: float = 0.2
MIN_HIGH_CONFIDENCE_THRESHOLD: float = 0.75


# ==============================================================================
# 1. Data Models & Containers
# ==============================================================================


@dataclass
class QuestionAnalysisResult:
    """Structured result of analyzing an individual question record."""

    question_id: str
    original_question_id: Optional[str]
    question_type: str
    question_text: str
    options: list[str]
    correct_option: Optional[str]
    correct_answer: str

    # Analysis attributes (strictly separated)
    bloom_level: str
    difficulty: str
    learning_objective: Optional[str]
    learning_objective_grounded: bool
    classification_reasoning: str
    confidence: float
    needs_teacher_review: bool
    review_reasons: list[str] = field(default_factory=list)

    # Preserved curriculum & source metadata
    chapter: Optional[str] = None
    lesson: Optional[str] = None
    page_number: Optional[Any] = None
    source_file: Optional[str] = None
    answer_source: Optional[str] = None
    verification_status: Optional[str] = None
    source_metadata: Optional[dict[str, Any]] = None
    validation_warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert analysis result to standard serializable dictionary."""
        return asdict(self)


@dataclass
class BatchAnalysisResult:
    """Structured report of batch question analysis."""

    total_questions: int
    analyzed_count: int
    failed_count: int
    review_recommended_count: int
    questions: list[dict[str, Any]]
    failed_records: list[dict[str, Any]]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert batch result to standard serializable dictionary."""
        return {
            "total_questions": self.total_questions,
            "analyzed_count": self.analyzed_count,
            "failed_count": self.failed_count,
            "review_recommended_count": self.review_recommended_count,
            "questions": self.questions,
            "failed_records": self.failed_records,
            "summary": self.summary,
        }


# ==============================================================================
# 2. LLM Communication & JSON Extraction
# ==============================================================================


def _send_analysis_completion(prompt: str, temperature: float = ANALYSIS_TEMPERATURE) -> str:
    """
    Sends structured completion request using the project's active LLM configuration.
    Delegates to scripts.generation._send_completion to inherit exponential backoff,
    rate-limit throttling, and fallback provider chains.
    """
    from scripts.generation import _send_completion

    return _send_completion(
        prompt,
        max_tokens=MAX_ANALYSIS_TOKENS,
        temperature=temperature,
    )


def _extract_json_object(raw_output: str) -> dict[str, Any]:
    """Extract and parse a JSON dictionary from model output text."""
    text = raw_output.strip()
    if not text:
        raise ValueError("Empty response received from analysis model")

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text, flags=re.IGNORECASE)

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise ValueError(f"Failed to extract JSON object from analysis output: {text[:200]}")
        value = json.loads(match.group(0))

    if not isinstance(value, dict):
        raise ValueError("Analysis model output must be a JSON dictionary")
    return value


# ==============================================================================
# 3. Prompt Construction
# ==============================================================================


BLOOM_TAXONOMY_GUIDE = """
Bloom's Revised Taxonomy Levels:
1. 'remember': Direct retrieval, recognition, or recall of isolated facts, definitions, naming, terminology, or dates.
2. 'understand': Constructing meaning, explaining concepts in own words, classifying, summarizing, interpreting, or comparing principles.
3. 'apply': Executing or implementing a rule, algorithm, formula, or concept to solve an unfamiliar problem or practical scenario.
4. 'analyze': Breaking down information into constituent parts, examining relationships, contrasting competing methods, or identifying architectural trade-offs.
5. 'evaluate': Making judgments based on explicit criteria, justifying architectural decisions, critiquing models, or validating assumptions.
6. 'create': Synthesizing elements into a novel whole, designing a pipeline, proposing a novel solution, or formulating an original workflow.
""".strip()

DIFFICULTY_CRITERIA_GUIDE = """
Difficulty Calibration Criteria (do NOT rely solely on question length or keywords):
- 'easy': Single-step cognitive operation; straightforward recall or simple classification; clear and unambiguous question cues; obvious distractors.
- 'medium': Two- to three-step cognitive operations; transferring a principle to a scenario; subtle distractor distinctions requiring precise conceptual boundaries.
- 'hard': Multi-step synthesis or deep analytical reasoning; evaluating edge cases, trade-offs, or multiple interacting constraints; complex open-ended justification.
""".strip()


def build_analysis_prompt(
    question_dict: dict[str, Any],
    curriculum_context: Optional[str] = None,
) -> str:
    """Constructs prompt for question analysis and curriculum grounding."""
    q_text = question_dict.get("question_text", "")
    q_type = question_dict.get("question_type", "mcq")
    options = question_dict.get("options") or []
    correct_opt = question_dict.get("correct_option")
    correct_ans = question_dict.get("correct_answer") or ""

    chapter = question_dict.get("chapter")
    lesson = question_dict.get("lesson")
    page_number = question_dict.get("page_number")
    source_file = question_dict.get("source_file")

    context_lines = []
    if chapter:
        context_lines.append(f"Chapter/Unit: {chapter}")
    if lesson:
        context_lines.append(f"Lesson/Topic: {lesson}")
    if page_number:
        context_lines.append(f"Page(s): {page_number}")
    if source_file:
        context_lines.append(f"Source Document: {source_file}")
    if curriculum_context and curriculum_context.strip():
        context_lines.append(f"Curriculum Passage / Context:\n{curriculum_context.strip()}")

    curriculum_info = "\n".join(context_lines) if context_lines else "None provided."

    formatted_options = ""
    if q_type == "mcq" and options:
        opt_letters = ("A", "B", "C", "D")
        formatted_options = "\n".join(
            f"  {opt_letters[i]}: {opt}" for i, opt in enumerate(options[:4])
        )

    options_block = f"- Options:\n{formatted_options}" if formatted_options else ""
    correct_opt_block = f"- Correct Option Key: {correct_opt}" if correct_opt else ""

    return f"""
You are an expert psychometrician and curriculum assessment analyst.
Analyze the following educational question rigorously and output a structured JSON evaluation.

{BLOOM_TAXONOMY_GUIDE}

{DIFFICULTY_CRITERIA_GUIDE}

Question Specification:
- Question Type: {q_type}
- Question Text: {q_text}
{options_block}
{correct_opt_block}
- Correct / Model Answer: {correct_ans}

Available Curriculum Metadata / Context:
{curriculum_info}

Grounding Instruction for Learning Objective:
- If sufficient curriculum context (topic, lesson, or passage) is present above, derive a measurable learning objective stated in standard instructional form: "The student will be able to [action verb] [concept/skill]..."
- CRITICAL: If curriculum context is absent, vague, or insufficient to ground the objective, return null for "learning_objective" and set "learning_objective_grounded" to false. NEVER invent or hallucinate ungrounded curriculum units.

Required JSON Output Format:
Return a single JSON object with EXACTLY these keys:
{{
  "bloom_level": "remember|understand|apply|analyze|evaluate|create",
  "difficulty": "easy|medium|hard",
  "learning_objective": "The student will be able to ... (or null if context insufficient)",
  "learning_objective_grounded": true|false,
  "classification_reasoning": "Concise 1-3 sentence justification explaining the cognitive task for bloom_level and the step-complexity for difficulty.",
  "confidence": 0.85
}}

Confidence must be a float between 0.0 and 1.0 reflecting your certainty in the Bloom level and difficulty classification.
Do not output markdown code blocks outside the JSON. Return valid JSON only.
""".strip()


# ==============================================================================
# 4. Output Validation & Normalization
# ==============================================================================


def validate_analysis_output(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """
    Validates model analysis response against the expected psychometric schema.
    Returns (is_valid, error_list).
    """
    errors: list[str] = []

    # 1. Bloom level validation
    bloom = str(data.get("bloom_level", "")).strip().lower()
    if bloom not in VALID_BLOOM_LEVELS:
        errors.append(
            f"Invalid bloom_level: '{bloom}'. Must be one of {list(VALID_BLOOM_LEVELS)}."
        )

    # 2. Difficulty validation
    diff = str(data.get("difficulty", "")).strip().lower()
    if diff not in VALID_DIFFICULTY_LEVELS:
        errors.append(
            f"Invalid difficulty: '{diff}'. Must be one of {list(VALID_DIFFICULTY_LEVELS)}."
        )

    # 3. Learning objective validation
    lo = data.get("learning_objective")
    if lo is not None and not isinstance(lo, str):
        errors.append("learning_objective must be a string or null.")

    # 4. Reasoning validation
    reasoning = data.get("classification_reasoning")
    if not isinstance(reasoning, str) or not reasoning.strip():
        errors.append("classification_reasoning must be a non-empty string.")

    # 5. Confidence validation
    conf = data.get("confidence")
    if conf is None or isinstance(conf, bool) or not isinstance(conf, (int, float)):
        errors.append("confidence must be a numeric float between 0.0 and 1.0.")
    elif not (0.0 <= float(conf) <= 1.0):
        errors.append(f"confidence must be in range [0.0, 1.0]; got {conf}.")

    return len(errors) == 0, errors


# ==============================================================================
# 5. Single Question Analysis
# ==============================================================================


def analyze_single_question(
    question_dict: dict[str, Any],
    curriculum_context: Optional[str] = None,
    override_verified: bool = False,
    confidence_threshold: float = MIN_HIGH_CONFIDENCE_THRESHOLD,
    max_retries: int = 2,
) -> QuestionAnalysisResult:
    """
    Analyzes an ingested question record to determine Bloom level, difficulty,
    learning objective, classification reasoning, and review flags.

    Preserves all existing question content, IDs, answers, options, and source metadata.
    If the question already has verified metadata and override_verified is False,
    existing verified attributes are preserved.
    """
    qid = question_dict.get("question_id", "unknown")
    raw_status = str(question_dict.get("verification_status") or "").strip().lower()
    is_verified_source = "verified" in raw_status or "solved" in raw_status

    # Preserve existing attributes if pre-verified
    pre_bloom = str(question_dict.get("bloom_level") or "").strip().lower()
    pre_diff = str(question_dict.get("difficulty") or "").strip().lower()
    has_valid_pre_bloom = pre_bloom in VALID_BLOOM_LEVELS
    has_valid_pre_diff = pre_diff in VALID_DIFFICULTY_LEVELS

    if is_verified_source and has_valid_pre_bloom and has_valid_pre_diff and not override_verified:
        lo = question_dict.get("learning_objective")
        return QuestionAnalysisResult(
            question_id=qid,
            original_question_id=question_dict.get("original_question_id"),
            question_type=question_dict.get("question_type", "mcq"),
            question_text=question_dict.get("question_text", ""),
            options=question_dict.get("options") or [],
            correct_option=question_dict.get("correct_option"),
            correct_answer=question_dict.get("correct_answer", ""),
            bloom_level=pre_bloom,
            difficulty=pre_diff,
            learning_objective=lo,
            learning_objective_grounded=bool(lo),
            classification_reasoning=question_dict.get(
                "classification_reasoning", "Preserved from human-verified source metadata."
            ),
            confidence=1.0,
            needs_teacher_review=False,
            review_reasons=[],
            chapter=question_dict.get("chapter"),
            lesson=question_dict.get("lesson"),
            page_number=question_dict.get("page_number"),
            source_file=question_dict.get("source_file"),
            answer_source=question_dict.get("answer_source"),
            verification_status=question_dict.get("verification_status"),
            source_metadata=question_dict.get("source_metadata"),
            validation_warnings=list(question_dict.get("validation_warnings", [])),
        )

    prompt = build_analysis_prompt(question_dict, curriculum_context=curriculum_context)

    analysis_data: Optional[dict[str, Any]] = None
    last_error: Optional[Exception] = None

    for attempt in range(max_retries):
        try:
            raw_response = _send_analysis_completion(prompt)
            parsed = _extract_json_object(raw_response)
            is_valid, validation_errors = validate_analysis_output(parsed)
            if not is_valid:
                raise ValueError(f"Model output failed schema validation: {', '.join(validation_errors)}")
            analysis_data = parsed
            break
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Analysis attempt %d failed for question %s: %s",
                attempt + 1,
                qid,
                exc,
            )
            # Add error correction to prompt on retry
            prompt += f"\n\nCorrection required: Previous attempt produced an invalid response: {exc}. Please return valid JSON matching the exact schema."

    if analysis_data is None:
        raise RuntimeError(
            f"Question analysis failed for question '{qid}' after {max_retries} attempt(s): {last_error}"
        )

    # Extract classified attributes
    bloom_level = str(analysis_data["bloom_level"]).strip().lower()
    difficulty = str(analysis_data["difficulty"]).strip().lower()
    learning_obj = analysis_data.get("learning_objective")
    if learning_obj and str(learning_obj).strip().lower() in ("null", "none", "unresolved"):
        learning_obj = None
    if learning_obj is not None:
        learning_obj = str(learning_obj).strip()

    lo_grounded = bool(analysis_data.get("learning_objective_grounded", False)) and (learning_obj is not None)
    reasoning = str(analysis_data.get("classification_reasoning", "")).strip()
    confidence = float(analysis_data.get("confidence", 0.7))

    # Evaluate review flags
    review_reasons: list[str] = []
    if confidence < confidence_threshold:
        review_reasons.append(f"Low classification confidence ({confidence:.2f} < {confidence_threshold:.2f})")
    if not lo_grounded:
        review_reasons.append("Learning objective could not be grounded in curriculum context")
    if question_dict.get("validation_warnings"):
        review_reasons.append("Question had ingestion validation warnings")

    needs_review = len(review_reasons) > 0

    return QuestionAnalysisResult(
        question_id=qid,
        original_question_id=question_dict.get("original_question_id"),
        question_type=question_dict.get("question_type", "mcq"),
        question_text=question_dict.get("question_text", ""),
        options=question_dict.get("options") or [],
        correct_option=question_dict.get("correct_option"),
        correct_answer=question_dict.get("correct_answer", ""),
        bloom_level=bloom_level,
        difficulty=difficulty,
        learning_objective=learning_obj,
        learning_objective_grounded=lo_grounded,
        classification_reasoning=reasoning,
        confidence=round(confidence, 3),
        needs_teacher_review=needs_review,
        review_reasons=review_reasons,
        chapter=question_dict.get("chapter"),
        lesson=question_dict.get("lesson"),
        page_number=question_dict.get("page_number"),
        source_file=question_dict.get("source_file"),
        answer_source=question_dict.get("answer_source"),
        verification_status=question_dict.get("verification_status"),
        source_metadata=question_dict.get("source_metadata"),
        validation_warnings=list(question_dict.get("validation_warnings", [])),
    )


# ==============================================================================
# 6. Batch Question Analysis
# ==============================================================================


def analyze_questions_batch(
    questions: list[dict[str, Any]],
    curriculum_context_map: Optional[dict[str, str]] = None,
    allow_partial: bool = True,
    confidence_threshold: float = MIN_HIGH_CONFIDENCE_THRESHOLD,
) -> BatchAnalysisResult:
    """
    Executes question analysis across a collection of canonical question records.

    Args:
      questions: Sequence of canonical question records (from scripts.question_processing).
      curriculum_context_map: Optional mapping of question_id -> curriculum text.
      allow_partial: If True, failures on individual questions are logged without aborting the batch.
      confidence_threshold: Minimum confidence score below which teacher review is flagged.

    Returns:
      BatchAnalysisResult detailing analyzed questions, failure records, and statistical summary.
    """
    analyzed_questions: list[dict[str, Any]] = []
    failed_records: list[dict[str, Any]] = []
    review_count = 0

    ctx_map = curriculum_context_map or {}

    for idx, q in enumerate(questions, start=1):
        qid = q.get("question_id", f"Q-{idx:04d}")
        curriculum_ctx = ctx_map.get(qid)
        try:
            result = analyze_single_question(
                q,
                curriculum_context=curriculum_ctx,
                confidence_threshold=confidence_threshold,
            )
            analyzed_dict = result.to_dict()
            analyzed_questions.append(analyzed_dict)
            if result.needs_teacher_review:
                review_count += 1
        except Exception as exc:
            logger.error("Failed to analyze question %s: %s", qid, exc)
            if not allow_partial:
                raise
            failed_records.append({
                "index": idx,
                "question_id": qid,
                "question_text": q.get("question_text", ""),
                "error": str(exc),
            })

    # Summary statistics
    bloom_counts: dict[str, int] = {}
    difficulty_counts: dict[str, int] = {}
    for aq in analyzed_questions:
        b = aq["bloom_level"]
        d = aq["difficulty"]
        bloom_counts[b] = bloom_counts.get(b, 0) + 1
        difficulty_counts[d] = difficulty_counts.get(d, 0) + 1

    summary = {
        "total_input": len(questions),
        "analyzed_count": len(analyzed_questions),
        "failed_count": len(failed_records),
        "review_recommended_count": review_count,
        "bloom_distribution": bloom_counts,
        "difficulty_distribution": difficulty_counts,
        "success_rate": round(len(analyzed_questions) / len(questions), 4) if questions else 0.0,
    }

    return BatchAnalysisResult(
        total_questions=len(questions),
        analyzed_count=len(analyzed_questions),
        failed_count=len(failed_records),
        review_recommended_count=review_count,
        questions=analyzed_questions,
        failed_records=failed_records,
        summary=summary,
    )
