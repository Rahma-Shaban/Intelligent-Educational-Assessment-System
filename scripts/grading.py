"""Automated assessment grading module for the Intelligent Educational Assessment System.

Provides deterministic grading for multiple-choice questions (MCQs), LLM-based rubric
evaluation for open-ended short-answer and essay questions via the Google Gemini API,
and end-to-end exam submission grading.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from scripts.config import GEMINI_API_KEY, LLM_MODEL_NAME, LLM_PROVIDER

logger = logging.getLogger(__name__)

MAX_COMPLETION_ATTEMPTS = 2
MAX_GRADING_TOKENS = 4096
RETRY_GRADING_TOKENS = 8192


def _send_grading_completion(
    prompt: str,
    *,
    max_tokens: int = MAX_GRADING_TOKENS,
    max_attempts: int = MAX_COMPLETION_ATTEMPTS,
) -> str:
    """Send a structured completion request to active LLM (Gemini or Ollama) with JSON output mode."""
    from scripts.generation import _send_completion
    return _send_completion(prompt, max_tokens=max_tokens, max_attempts=max_attempts)


def _extract_json_object(raw_output: str) -> dict[str, Any]:
    """Extract and parse a JSON dictionary from model output text."""
    text = raw_output.strip()
    if not text:
        raise ValueError("Empty response from model")

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text, flags=re.IGNORECASE)

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0))

    if not isinstance(value, dict):
        raise ValueError("Model response must contain a JSON object")
    return value


def _normalize_mcq_token(value: str) -> tuple[str, str]:
    """Parse an MCQ answer string into (normalized_letter, normalized_body_text)."""
    cleaned = str(value).strip()
    match = re.match(r"^\s*([A-Da-d1-4])(?:[\s.:)\-]+(.*))?$", cleaned)
    if match:
        raw_prefix = match.group(1).upper()
        letter = "ABCD"[int(raw_prefix) - 1] if raw_prefix in "1234" else raw_prefix
        body = (match.group(2) or "").strip().casefold()
        return letter, body
    return "", cleaned.casefold()


def grade_mcq(student_answer: str, correct_answer: str, max_score: float = 1.0) -> dict[str, Any]:
    """Deterministic MCQ grading. Returns {'score': float, 'max_score': float, 'is_correct': bool, 'feedback': str}."""
    max_score_val = float(max_score)
    s_clean = str(student_answer).strip()
    c_clean = str(correct_answer).strip()

    if not s_clean:
        return {
            "score": 0.0,
            "max_score": max_score_val,
            "is_correct": False,
            "feedback": f"No answer provided. Expected answer: '{c_clean}'.",
        }

    s_letter, s_body = _normalize_mcq_token(s_clean)
    c_letter, c_body = _normalize_mcq_token(c_clean)

    is_correct = False
    if s_letter and c_letter and s_letter == c_letter:
        is_correct = True
    elif s_clean.casefold() == c_clean.casefold():
        is_correct = True
    elif s_body and c_body and s_body == c_body:
        is_correct = True
    elif s_body and s_body == c_clean.casefold():
        is_correct = True
    elif c_body and s_clean.casefold() == c_body:
        is_correct = True

    score = max_score_val if is_correct else 0.0
    if is_correct:
        feedback = f"Correct! Selected answer '{s_clean}' matches the reference answer."
    else:
        feedback = f"Incorrect. Selected answer: '{s_clean}'. Expected answer: '{c_clean}'."

    return {
        "score": score,
        "max_score": max_score_val,
        "is_correct": is_correct,
        "feedback": feedback,
    }


def grade_open_ended(
    question_text: str,
    question_type: str,  # 'short_answer' or 'essay'
    student_answer: str,
    reference_answer: str,
    rubric: list[dict[str, Any]],
    max_score: float,
) -> dict[str, Any]:
    """LLM-based grading using Gemini. Send the question, student answer, reference answer, and rubric to Gemini.
    Ask it to return JSON with per-criterion scores and feedback.
    Returns {'score': float, 'max_score': float, 'criterion_scores': list[dict], 'feedback': str, 'strengths': list[str], 'weaknesses': list[str]}
    """
    max_score_val = float(max_score)
    s_clean = str(student_answer).strip()

    effective_rubric = rubric if isinstance(rubric, list) and rubric else [
        {
            "criterion": "Response Quality",
            "points": max_score_val,
            "description": "Accuracy, completeness, and reasoning relative to the model answer.",
        }
    ]

    # Handle unattempted / empty submissions without consuming API quota
    if not s_clean:
        criterion_scores = [
            {
                "criterion": str(item.get("criterion", f"Criterion {idx + 1}")),
                "score": 0.0,
                "max_score": float(item.get("points", 1.0)),
                "feedback": "No response was provided for this criterion.",
            }
            for idx, item in enumerate(effective_rubric)
        ]
        return {
            "score": 0.0,
            "max_score": max_score_val,
            "criterion_scores": criterion_scores,
            "feedback": "No response was submitted for this question.",
            "strengths": [],
            "weaknesses": ["No answer provided."],
        }

    prompt = f"""
You are an expert pedagogical grader. Assess the following student response objectively and accurately according to the provided reference answer and grading rubric.

Question Type: {question_type}
Question:
{question_text}

Reference / Model Answer:
{reference_answer}

Student Response:
{student_answer}

Grading Rubric:
{json.dumps(effective_rubric, ensure_ascii=False, indent=2)}

Maximum Total Points Allowed: {max_score_val}

Grading Guidelines:
1. For each criterion in the rubric, assign an earned score from 0.0 up to that criterion's maximum points.
2. CRITICAL CONSTRAINT: The criterion score must NEVER exceed that criterion's maximum points.
3. Provide concise, constructive feedback for each criterion explaining why points were awarded or deducted.
4. Provide an overall feedback summary, a list of student strengths, and a list of specific weaknesses or areas for improvement.

Return ONLY a valid JSON object strictly matching this schema:
{{
  "criterion_scores": [
    {{
      "criterion": "<criterion name matching rubric>",
      "score": <float points awarded, between 0.0 and criterion max points>,
      "max_score": <float maximum points for this criterion>,
      "feedback": "<brief rationale for points awarded or deducted>"
    }}
  ],
  "feedback": "<overall qualitative feedback summary>",
  "strengths": ["<strength 1>", "<strength 2>"],
  "weaknesses": ["<weakness 1>", "<weakness 2>"]
}}
""".strip()

    retry_correction: str | None = None
    parsed: dict[str, Any] | None = None

    for attempt in range(MAX_COMPLETION_ATTEMPTS):
        active_prompt = prompt if not retry_correction else f"{prompt}\n\nCorrection required: {retry_correction}"
        raw_output = _send_grading_completion(active_prompt)
        try:
            parsed = _extract_json_object(raw_output)
            break
        except (json.JSONDecodeError, ValueError) as exc:
            if attempt + 1 == MAX_COMPLETION_ATTEMPTS:
                raise ValueError(
                    f"Gemini returned invalid JSON for open-ended grading: {exc}"
                ) from exc
            retry_correction = (
                "Your previous response was not valid JSON. Return strictly a JSON object "
                "with criterion_scores, feedback, strengths, and weaknesses."
            )

    if not isinstance(parsed, dict):
        raise ValueError("Model response could not be parsed into a dictionary")

    raw_criterion_scores = parsed.get("criterion_scores")
    if not isinstance(raw_criterion_scores, list):
        raw_criterion_scores = []

    validated_criterion_scores: list[dict[str, Any]] = []
    for idx, item in enumerate(effective_rubric):
        c_name = str(item.get("criterion", f"Criterion {idx + 1}")).strip()
        c_max = float(item.get("points", 1.0))

        match: dict[str, Any] | None = None
        for entry in raw_criterion_scores:
            if isinstance(entry, dict) and str(entry.get("criterion", "")).strip().casefold() == c_name.casefold():
                match = entry
                break
        if match is None and idx < len(raw_criterion_scores) and isinstance(raw_criterion_scores[idx], dict):
            match = raw_criterion_scores[idx]

        if match and isinstance(match.get("score"), (int, float)):
            awarded = float(match["score"])
            c_feedback = str(match.get("feedback", "")).strip() or "Evaluated according to rubric."
        else:
            awarded = 0.0
            c_feedback = "No criterion-specific feedback provided."

        # Strictly enforce: score cannot exceed criterion maximum or drop below 0.0
        clamped_score = min(c_max, max(0.0, awarded))
        validated_criterion_scores.append({
            "criterion": c_name,
            "score": round(clamped_score, 2),
            "max_score": c_max,
            "feedback": c_feedback,
        })

    total_awarded = sum(c["score"] for c in validated_criterion_scores)
    rubric_total = sum(float(r.get("points", 1.0)) for r in effective_rubric)

    if rubric_total > 0 and abs(rubric_total - max_score_val) > 1e-4:
        total_score = (total_awarded / rubric_total) * max_score_val
    else:
        total_score = total_awarded

    # Strictly enforce: total score never exceeds max_score
    total_score = min(max_score_val, max(0.0, total_score))

    strengths = [
        str(s).strip()
        for s in parsed.get("strengths", [])
        if isinstance(s, str) and s.strip()
    ]
    weaknesses = [
        str(w).strip()
        for w in parsed.get("weaknesses", [])
        if isinstance(w, str) and w.strip()
    ]
    overall_feedback = str(parsed.get("feedback", "")).strip() or "Response evaluated against rubric criteria."

    return {
        "score": round(total_score, 2),
        "max_score": max_score_val,
        "criterion_scores": validated_criterion_scores,
        "feedback": overall_feedback,
        "strengths": strengths,
        "weaknesses": weaknesses,
    }


def grade_exam_submission(
    exam: dict[str, Any],
    student_answers: dict[str, str],
) -> dict[str, Any]:
    """Grade all questions in an exam submission.
    Returns {
        'total_score': float,
        'max_possible_score': float,
        'percentage': float,
        'graded_answers': list[dict]  # Per-question results
    }
    """
    if not isinstance(exam, dict):
        raise ValueError("exam must be a dictionary")

    questions = exam.get("questions")
    if not isinstance(questions, list):
        raise ValueError("exam must contain a 'questions' list")

    from scripts.generation import get_llm_call_count
    start_calls = get_llm_call_count()

    graded_answers: list[dict[str, Any]] = []

    for idx, question in enumerate(questions, start=1):
        if not isinstance(question, dict):
            continue

        qid = str(question.get("question_id") or f"Q{idx:02d}")
        q_type = str(question.get("question_type", "short_answer")).strip().lower()
        student_ans = student_answers.get(qid, "")
        max_score = float(question.get("max_score", 1.0))

        if q_type == "mcq":
            correct_ans = question.get("correct_answer") or question.get("reference_answer", "")
            grade_res = grade_mcq(
                student_answer=str(student_ans),
                correct_answer=str(correct_ans),
                max_score=max_score,
            )
        else:
            grade_res = grade_open_ended(
                question_text=str(question.get("question", "")),
                question_type=q_type,
                student_answer=str(student_ans),
                reference_answer=str(question.get("reference_answer", "")),
                rubric=question.get("rubric") or [],
                max_score=max_score,
            )

        entry: dict[str, Any] = {
            "question_id": qid,
            "question_type": q_type,
            "question": question.get("question", ""),
            "student_answer": student_ans,
            "score": grade_res["score"],
            "max_score": grade_res["max_score"],
            "feedback": grade_res["feedback"],
            "correct_answer": str(question.get("correct_answer") or question.get("reference_answer") or ""),
            "reference_answer": str(question.get("reference_answer") or question.get("correct_answer") or ""),
            "model_answer": str(question.get("reference_answer") or question.get("correct_answer") or ""),
            "explanation": str(question.get("explanation") or ""),
            "rubric_breakdown": grade_res.get("criterion_scores", []),
        }
        if "options" in question:
            entry["options"] = question["options"]
        if "is_correct" in grade_res:
            entry["is_correct"] = grade_res["is_correct"]
        if "criterion_scores" in grade_res:
            entry["criterion_scores"] = grade_res["criterion_scores"]
        if "strengths" in grade_res:
            entry["strengths"] = grade_res["strengths"]
        if "weaknesses" in grade_res:
            entry["weaknesses"] = grade_res["weaknesses"]

        # lesson_id lets the improvement module map each answer to a curriculum lesson
        for meta_key in ("topic", "difficulty", "bloom_level", "lesson_id"):
            val = question.get(meta_key) or exam.get(meta_key)
            if val is not None:
                entry[meta_key] = val

        graded_answers.append(entry)

    total_score = sum(ans["score"] for ans in graded_answers)
    max_possible_score = sum(ans["max_score"] for ans in graded_answers)
    if max_possible_score <= 0 and "total_points" in exam:
        max_possible_score = float(exam["total_points"])

    percentage = (
        round((total_score / max_possible_score) * 100.0, 2)
        if max_possible_score > 0
        else 0.0
    )

    calls_made = get_llm_call_count() - start_calls
    logger.info("Grading complete for %d questions using %d LLM calls", len(graded_answers), calls_made)

    return {
        "total_score": round(total_score, 2),
        "max_possible_score": round(max_possible_score, 2),
        "percentage": percentage,
        "graded_answers": graded_answers,
        "llm_calls_made": calls_made,
    }
