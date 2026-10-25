"""Feedback and instructor summary module for the Intelligent Educational Assessment System.

Provides LLM-powered personalized student feedback and actionable class-wide diagnostic
summaries for teacher dashboards using the Google Gemini API.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from scripts.config import GEMINI_API_KEY, LLM_MODEL_NAME, LLM_PROVIDER

logger = logging.getLogger(__name__)

MAX_COMPLETION_ATTEMPTS = 2
MAX_FEEDBACK_TOKENS = 4096
RETRY_FEEDBACK_TOKENS = 8192


def _send_feedback_completion(
    prompt: str,
    *,
    max_tokens: int = MAX_FEEDBACK_TOKENS,
    max_attempts: int = MAX_COMPLETION_ATTEMPTS,
) -> str:
    """Send a structured completion request to Gemini with JSON output mode."""
    if LLM_PROVIDER != "gemini":
        raise ValueError("LLM_PROVIDER must be 'gemini'")
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is missing from the current project configuration")
    if not LLM_MODEL_NAME:
        raise ValueError("LLM_MODEL_NAME is missing from the current project configuration")
    if max_tokens < 1 or max_attempts < 1:
        raise ValueError("max_tokens and max_attempts must be positive")

    from google import genai
    from google.genai import errors, types

    empty_response_details: list[str] = []
    client = genai.Client(api_key=GEMINI_API_KEY)
    try:
        for attempt in range(max_attempts):
            output_budget = max_tokens if attempt == 0 else RETRY_FEEDBACK_TOKENS
            try:
                response = client.models.generate_content(
                    model=LLM_MODEL_NAME,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0,
                        max_output_tokens=output_budget,
                        response_mime_type="application/json",
                    ),
                )
            except errors.APIError as exc:
                status = exc.code
                if status in {400, 404}:
                    raise ValueError(
                        f"Gemini model '{LLM_MODEL_NAME}' is unavailable or the request is "
                        f"unsupported (HTTP {status}). Check the model name and API access."
                    ) from exc
                if status in {401, 403}:
                    raise ValueError(
                        "Gemini API authentication or permission failed. Verify GEMINI_API_KEY "
                        "and that the Gemini API is enabled for its Google AI Studio project."
                    ) from exc
                if status == 429:
                    raise ValueError(
                        "Gemini API quota or rate limit exceeded. Check the project's model quota "
                        "and billing in Google AI Studio, then retry."
                    ) from exc
                if status is not None and status >= 500:
                    raise ValueError(f"Gemini API server error (HTTP {status}); retry later.") from exc
                detail = str(exc).replace(GEMINI_API_KEY, "[REDACTED]")
                raise ValueError(f"Gemini API request failed: {detail}") from exc

            content = response.text
            if isinstance(content, str) and content.strip():
                return content
            empty_response_details.append("model returned empty content")
    finally:
        client.close()

    details = ", ".join(empty_response_details)
    raise ValueError(
        f"Gemini returned empty assistant content after {max_attempts} attempts ({details})."
    )


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


def generate_student_feedback(
    student_name: str,
    attempts: list[dict[str, Any]],  # List of graded attempt records
    cluster_label: str,  # e.g. 'Advanced', 'Proficient', 'Needs Intervention'
) -> dict[str, Any]:
    """Generate personalized diagnostic feedback using Gemini.
    Returns {
        'summary': str,
        'strengths': list[str],
        'weaknesses': list[str],
        'recommendations': list[str],
        'study_plan': str,
        'cluster_label': str
    }
    """
    scores: list[float] = []
    durations: list[float] = []
    topics_summary: dict[str, list[float]] = {}
    aggregated_strengths: list[str] = []
    aggregated_weaknesses: list[str] = []

    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue

        pct = attempt.get("percentage")
        if pct is None and "total_score" in attempt and "max_possible_score" in attempt:
            m = float(attempt["max_possible_score"])
            pct = (float(attempt["total_score"]) / m * 100.0) if m > 0 else 0.0
        elif pct is None and "score" in attempt and "max_score" in attempt:
            m = float(attempt["max_score"])
            pct = (float(attempt["score"]) / m * 100.0) if m > 0 else 0.0
        elif pct is None:
            pct = float(attempt.get("score", 0.0))
        scores.append(float(pct))

        if "duration" in attempt and attempt["duration"] is not None:
            durations.append(float(attempt["duration"]))

        if attempt.get("topic"):
            topics_summary.setdefault(str(attempt["topic"]), []).append(float(pct))
        if "topic_performance" in attempt and isinstance(attempt["topic_performance"], dict):
            for t, v in attempt["topic_performance"].items():
                topics_summary.setdefault(str(t), []).append(float(v))

        # Check answers for granular feedback
        for ans in attempt.get("graded_answers") or []:
            if isinstance(ans, dict):
                for s in ans.get("strengths") or []:
                    if isinstance(s, str) and s.strip():
                        aggregated_strengths.append(s.strip())
                for w in ans.get("weaknesses") or []:
                    if isinstance(w, str) and w.strip():
                        aggregated_weaknesses.append(w.strip())

    avg_score = round(float(sum(scores) / len(scores)), 2) if scores else 0.0
    avg_duration = round(float(sum(durations) / len(durations)), 2) if durations else 0.0
    topic_breakdown = {
        t: round(float(sum(v) / len(v)), 2) for t, v in sorted(topics_summary.items())
    }

    prompt = f"""
You are an expert pedagogical advisor providing personalized, constructive academic feedback to a student.

Student Profile:
- Name: {student_name}
- Proficiency Tier: {cluster_label}
- Total Assessments Completed: {len(scores)}
- Average Assessment Score: {avg_score}%
- Average Duration per Attempt: {avg_duration} seconds
- Topic Mastery Breakdown: {json.dumps(topic_breakdown, ensure_ascii=False)}
- Prior Question Strengths: {json.dumps(aggregated_strengths[:6], ensure_ascii=False)}
- Prior Question Areas for Improvement: {json.dumps(aggregated_weaknesses[:6], ensure_ascii=False)}

Task:
Generate a motivating, actionable diagnostic feedback report tailored to this student's learning profile.
- If proficiency tier is 'Advanced', focus on mastery, deeper inquiry, and tackling harder synthesis problems.
- If proficiency tier is 'Proficient', reinforce core concepts, address specific edge cases, and push toward mastery.
- If proficiency tier is 'Needs Intervention', break down fundamental concepts gently, diagnose misconceptions, and provide a clear recovery roadmap.

Return strictly a valid JSON object matching this schema:
{{
  "summary": "<2-3 sentence personalized diagnostic evaluation of the student's progress and potential>",
  "strengths": ["<specific strength 1>", "<specific strength 2>", "<specific strength 3>"],
  "weaknesses": ["<specific weakness or learning gap 1>", "<specific weakness or learning gap 2>"],
  "recommendations": ["<actionable learning recommendation 1>", "<actionable learning recommendation 2>", "<actionable learning recommendation 3>"],
  "study_plan": "<structured 1-to-2 week step-by-step study plan tailored to their needs>"
}}
""".strip()

    retry_correction: str | None = None
    parsed: dict[str, Any] | None = None

    for attempt_idx in range(MAX_COMPLETION_ATTEMPTS):
        active_prompt = prompt if not retry_correction else f"{prompt}\n\nCorrection required: {retry_correction}"
        raw_output = _send_feedback_completion(active_prompt)
        try:
            parsed = _extract_json_object(raw_output)
            break
        except (json.JSONDecodeError, ValueError) as exc:
            if attempt_idx + 1 == MAX_COMPLETION_ATTEMPTS:
                raise ValueError(f"Gemini returned invalid JSON for student feedback: {exc}") from exc
            retry_correction = "Return strictly a valid JSON object with summary, strengths, weaknesses, recommendations, and study_plan."

    if not isinstance(parsed, dict):
        raise ValueError("Model response could not be parsed into a dictionary")

    summary = str(parsed.get("summary", "")).strip() or (
        f"{student_name} currently exhibits {cluster_label} performance with an overall average of {avg_score}%."
    )
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
    recommendations = [
        str(r).strip()
        for r in parsed.get("recommendations", [])
        if isinstance(r, str) and r.strip()
    ]
    study_plan = str(parsed.get("study_plan", "")).strip() or "Review curriculum materials and practice relevant problem sets."

    return {
        "summary": summary,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "recommendations": recommendations,
        "study_plan": study_plan,
        "cluster_label": cluster_label,
    }


def generate_class_summary(
    class_analytics: dict[str, Any],  # From analytics.get_class_analytics()
    cluster_results: dict[str, Any],  # From analytics.cluster_students()
) -> dict[str, Any]:
    """Generate class-level summary insights for professor dashboard.
    Returns {
        'overall_assessment': str,
        'key_findings': list[str],
        'topic_recommendations': dict[str, str],
        'intervention_needed': list[str],  # student IDs needing help
        'class_strengths': list[str]
    }
    """
    total_students = int(class_analytics.get("total_students", 0))
    total_attempts = int(class_analytics.get("total_attempts", 0))
    avg_score_pct = float(class_analytics.get("avg_score_pct", 0.0))
    score_distribution = class_analytics.get("score_distribution", {})
    topic_performance = class_analytics.get("topic_performance", {})
    difficulty_breakdown = class_analytics.get("difficulty_breakdown", {})

    clusters = cluster_results.get("clusters", [])
    intervention_students_set: set[str] = set()
    cluster_counts: dict[str, int] = {}

    for c in clusters:
        if isinstance(c, dict):
            lbl = str(c.get("label", "")).strip()
            sid = str(c.get("student_id", "")).strip()
            cluster_counts[lbl] = cluster_counts.get(lbl, 0) + 1
            if lbl.lower() == "needs intervention" and sid:
                intervention_students_set.add(sid)

    prompt = f"""
You are an expert curriculum consultant analyzing class-wide educational analytics for a university professor's dashboard.

Class Performance Data:
- Total Enrolled Students: {total_students}
- Total Exam Submissions: {total_attempts}
- Class Mean Score: {avg_score_pct}%
- Score Distribution: {json.dumps(score_distribution, ensure_ascii=False)}
- Topic Performance (avg %): {json.dumps(topic_performance, ensure_ascii=False)}
- Difficulty Level Breakdown (avg %): {json.dumps(difficulty_breakdown, ensure_ascii=False)}
- Student Proficiency Clustering: {json.dumps(cluster_counts, ensure_ascii=False)}
- Students Identified for Intervention: {json.dumps(sorted(list(intervention_students_set)), ensure_ascii=False)}

Task:
Provide executive diagnostic insights and pedagogical guidance for the instructor.
1. Provide a succinct overall assessment of the cohort's learning progress.
2. Highlight 3-5 key findings explaining student trends and bottlenecks.
3. Provide targeted teaching recommendations mapped to specific curriculum topics.
4. Verify the student IDs who need early intervention.
5. Identify areas where the class demonstrated strong collective competency.

Return strictly a valid JSON object matching this schema:
{{
  "overall_assessment": "<executive summary paragraph for the professor>",
  "key_findings": ["<finding 1>", "<finding 2>", "<finding 3>"],
  "topic_recommendations": {{
    "<topic name>": "<recommended instructional strategy or remediation>"
  }},
  "intervention_needed": ["<student_id_1>", "<student_id_2>"],
  "class_strengths": ["<class strength 1>", "<class strength 2>"]
}}
""".strip()

    retry_correction: str | None = None
    parsed: dict[str, Any] | None = None

    for attempt_idx in range(MAX_COMPLETION_ATTEMPTS):
        active_prompt = prompt if not retry_correction else f"{prompt}\n\nCorrection required: {retry_correction}"
        raw_output = _send_feedback_completion(active_prompt)
        try:
            parsed = _extract_json_object(raw_output)
            break
        except (json.JSONDecodeError, ValueError) as exc:
            if attempt_idx + 1 == MAX_COMPLETION_ATTEMPTS:
                raise ValueError(f"Gemini returned invalid JSON for class summary: {exc}") from exc
            retry_correction = "Return strictly a valid JSON object with overall_assessment, key_findings, topic_recommendations, intervention_needed, and class_strengths."

    if not isinstance(parsed, dict):
        raise ValueError("Model response could not be parsed into a dictionary")

    overall_assessment = str(parsed.get("overall_assessment", "")).strip() or (
        f"The class shows an average performance of {avg_score_pct}% across {total_attempts} attempts."
    )
    key_findings = [
        str(f).strip()
        for f in parsed.get("key_findings", [])
        if isinstance(f, str) and f.strip()
    ]
    topic_recommendations_raw = parsed.get("topic_recommendations")
    topic_recommendations: dict[str, str] = {}
    if isinstance(topic_recommendations_raw, dict):
        for t, r in topic_recommendations_raw.items():
            if t and r:
                topic_recommendations[str(t).strip()] = str(r).strip()

    llm_intervention = [
        str(s).strip()
        for s in parsed.get("intervention_needed", [])
        if isinstance(s, str) and s.strip()
    ]
    # Ensure known intervention students from clustering are never dropped
    combined_intervention = sorted(list(intervention_students_set.union(set(llm_intervention))))

    class_strengths = [
        str(s).strip()
        for s in parsed.get("class_strengths", [])
        if isinstance(s, str) and s.strip()
    ]

    return {
        "overall_assessment": overall_assessment,
        "key_findings": key_findings,
        "topic_recommendations": topic_recommendations,
        "intervention_needed": combined_intervention,
        "class_strengths": class_strengths,
    }
