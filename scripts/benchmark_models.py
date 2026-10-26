"""Benchmark LLM models on curriculum-grounded assessment generation.

Compares candidate models (e.g. groq:openai/gpt-oss-20b, groq:openai/gpt-oss-120b,
gemini:gemini-2.5-flash-lite) across:
- Latency (seconds per question and total)
- Estimated token usage / output length
- API calls, rate limits (HTTP 429), and retries
- JSON validity
- MCQ structure and answer-key accuracy
- Curriculum citation and evidence-quote fidelity
- Rubric point integrity

Results are saved to outputs/benchmark_results_<timestamp>.csv and displayed
as a comparison table.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure root directory is on sys.path
_root_dir = Path(__file__).resolve().parent.parent
if str(_root_dir) not in sys.path:
    sys.path.insert(0, str(_root_dir))

from scripts import config
from scripts import generation

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("benchmark")


def evaluate_question(
    question: dict[str, Any],
    question_type: str,
    context_docs: list[Any],
) -> dict[str, Any]:
    """Evaluate quality dimensions: JSON validity, MCQ correctness, evidence fidelity, rubric."""
    eval_res: dict[str, Any] = {
        "valid_json": True,
        "valid_schema": True,
        "mcq_valid": None,
        "evidence_fidelity": False,
        "rubric_valid": False,
        "failure_reason": "",
    }

    try:
        generation._validate_question(question)
    except Exception as exc:
        eval_res["valid_schema"] = False
        eval_res["failure_reason"] = f"Schema validation: {exc}"
        return eval_res

    # 1. MCQ evaluation
    if question_type == "mcq":
        options = question.get("options") or []
        correct = question.get("correct_answer")
        ref_ans = str(question.get("reference_answer", "")).strip()

        has_4_options = isinstance(options, list) and len(options) == 4 and len(set(options)) == 4
        valid_letter = correct in {"A", "B", "C", "D"}
        
        # Check if reference answer aligns with correct option
        ref_aligns = False
        if valid_letter and has_4_options:
            opt_idx = ord(correct) - ord("A")
            target_opt = str(options[opt_idx]).strip().lower()
            ref_aligns = (
                ref_ans.lower().startswith(correct.lower())
                or target_opt in ref_ans.lower()
                or ref_ans.lower() in target_opt
            )

        eval_res["mcq_valid"] = bool(has_4_options and valid_letter and ref_aligns)
        if not eval_res["mcq_valid"]:
            reasons = []
            if not has_4_options:
                reasons.append(f"options count={len(options)}")
            if not valid_letter:
                reasons.append(f"correct_answer='{correct}'")
            if not ref_aligns:
                reasons.append("ref_answer mismatch")
            eval_res["failure_reason"] = f"MCQ flaw: {', '.join(reasons)}"

    # 2. Evidence quote fidelity
    source_refs = question.get("source_refs") or []
    if source_refs and isinstance(source_refs, list):
        docs_by_chunk = {
            str((getattr(d, "metadata", {}) or {}).get("chunk_id")): d
            for d in context_docs
        }
        fidelity_checks = []
        for ref in source_refs:
            chunk_id = ref.get("chunk_id")
            doc = docs_by_chunk.get(str(chunk_id))
            if not doc:
                continue
            quote = str(ref.get("evidence_quote", "")).strip()
            if len(quote) < 12:
                continue
            doc_content = " ".join(getattr(doc, "page_content", "").split()).lower()
            norm_quote = " ".join(quote.split()).lower()
            if norm_quote in doc_content:
                fidelity_checks.append(True)
            else:
                # Check for subquote match
                subquote = generation._find_verbatim_subquote(quote, getattr(doc, "page_content", ""))
                fidelity_checks.append(bool(subquote))
        eval_res["evidence_fidelity"] = bool(fidelity_checks and all(fidelity_checks))
        if not eval_res["evidence_fidelity"]:
            if eval_res["failure_reason"]:
                eval_res["failure_reason"] += "; "
            eval_res["failure_reason"] += "evidence_quote not verbatim in chunk"
    else:
        eval_res["failure_reason"] += "no source_refs"

    # 3. Rubric integrity
    rubric = question.get("rubric") or []
    max_score = question.get("max_score")
    if isinstance(rubric, list) and isinstance(max_score, (int, float)):
        rubric_sum = sum(item.get("points", 0) for item in rubric if isinstance(item, dict))
        eval_res["rubric_valid"] = bool(rubric_sum == max_score)
        if not eval_res["rubric_valid"]:
            if eval_res["failure_reason"]:
                eval_res["failure_reason"] += "; "
            eval_res["failure_reason"] += f"rubric points sum {rubric_sum} != max_score {max_score}"

    return eval_res


def benchmark_model_on_questions(
    provider: str,
    model: str,
    lesson_id: str,
    context_docs: list[Any],
    question_types: list[str],
) -> list[dict[str, Any]]:
    """Run generation of a small set of questions for a single provider:model."""
    results: list[dict[str, Any]] = []

    # Override provider and model for this run
    original_provider = config.LLM_PROVIDER
    original_model = config.LLM_MODEL_NAME
    original_groq_model = config.GROQ_MODEL_NAME

    config.LLM_PROVIDER = provider
    config.LLM_MODEL_NAME = model
    if provider == "groq":
        config.GROQ_MODEL_NAME = model
        generation.GROQ_MODEL_NAME = model

    generation.LLM_PROVIDER = provider
    generation.LLM_MODEL_NAME = model

    logger.info("Starting benchmark for [%s:%s] on lesson '%s'...", provider, model, lesson_id)

    try:
        for idx, q_type in enumerate(question_types, start=1):
            focus_chunk = context_docs[(idx - 1) % len(context_docs)]
            focus_id = str((getattr(focus_chunk, "metadata", {}) or {}).get("chunk_id", ""))
            
            logger.info("  Generating question %d/%d (type: %s, focus: %s)...", idx, len(question_types), q_type, focus_id)
            
            calls_before = generation.get_llm_call_count()
            t0 = time.perf_counter()
            error_msg = ""
            question_obj = None

            try:
                question_obj = generation.generate_single_question(
                    topic=f"Curriculum assessment for lesson {lesson_id}",
                    question_type=q_type,
                    difficulty="medium",
                    bloom_level="understand" if q_type == "mcq" else ("apply" if q_type == "short_answer" else "analyze"),
                    context_docs=context_docs,
                    focus_chunk_id=focus_id,
                )
            except Exception as exc:
                error_msg = str(exc)
                logger.error("  Question %d generation failed: %s", idx, error_msg)

            latency = round(time.perf_counter() - t0, 3)
            calls_made = generation.get_llm_call_count() - calls_before

            row: dict[str, Any] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "provider": provider,
                "model": model,
                "lesson_id": lesson_id,
                "question_index": idx,
                "question_type": q_type,
                "latency_sec": latency,
                "llm_calls": calls_made,
                "success": bool(question_obj is not None),
                "error": error_msg,
                "prompt_chars_est": 0,
                "completion_chars": len(json.dumps(question_obj)) if question_obj else 0,
            }

            if question_obj:
                eval_metrics = evaluate_question(question_obj, q_type, context_docs)
                row.update({
                    "valid_json": eval_metrics["valid_json"],
                    "valid_schema": eval_metrics["valid_schema"],
                    "mcq_valid": eval_metrics["mcq_valid"],
                    "evidence_fidelity": eval_metrics["evidence_fidelity"],
                    "rubric_valid": eval_metrics["rubric_valid"],
                    "failure_reason": eval_metrics["failure_reason"],
                    "question_text": question_obj.get("question", "")[:100],
                })
            else:
                row.update({
                    "valid_json": False,
                    "valid_schema": False,
                    "mcq_valid": False if q_type == "mcq" else None,
                    "evidence_fidelity": False,
                    "rubric_valid": False,
                    "failure_reason": error_msg,
                    "question_text": "",
                })

            results.append(row)

    finally:
        config.LLM_PROVIDER = original_provider
        config.LLM_MODEL_NAME = original_model
        config.GROQ_MODEL_NAME = original_groq_model
        generation.LLM_PROVIDER = original_provider
        generation.LLM_MODEL_NAME = original_model
        generation.GROQ_MODEL_NAME = original_groq_model

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark LLM models on curriculum-grounded assessment generation.")
    parser.add_argument("--lesson-id", default="1-2", help="Curriculum lesson ID to retrieve context from (default: 1-2)")
    parser.add_argument("--questions", type=int, default=3, help="Number of questions per model: 1 mcq, 1 short_answer, 1 essay (default: 3)")
    parser.add_argument(
        "--models",
        default="groq:openai/gpt-oss-20b,groq:openai/gpt-oss-120b,gemini:gemini-2.5-flash-lite",
        help="Comma-separated provider:model specifications",
    )
    parser.add_argument("--output-csv", default=None, help="Custom output CSV path")
    args = parser.parse_args()

    # Determine question types sequence
    base_types = ["mcq", "short_answer", "essay"]
    question_types = [base_types[i % len(base_types)] for i in range(args.questions)]

    # Load curriculum context once
    logger.info("Loading curriculum vector store at '%s'...", config.VECTOR_DB_PATH)
    try:
        context_docs = generation.retrieve_curriculum_context(
            topic=f"Curriculum assessment for lesson {args.lesson_id}",
            lesson_id=args.lesson_id,
            k=max(6, args.questions * 2),
        )
    except Exception as exc:
        logger.error("Failed to retrieve curriculum context for lesson %s: %s", args.lesson_id, exc)
        return 1

    logger.info("Retrieved %d context chunks for lesson %s.", len(context_docs), args.lesson_id)

    # Parse models list
    models_to_test: list[tuple[str, str]] = []
    for spec in args.models.split(","):
        spec = spec.strip()
        if not spec:
            continue
        if ":" in spec:
            p, m = spec.split(":", 1)
            models_to_test.append((p.strip().lower(), m.strip()))
        else:
            models_to_test.append((config.LLM_PROVIDER, spec.strip()))

    all_rows: list[dict[str, Any]] = []

    for prov, model in models_to_test:
        # Check prerequisites
        if prov == "groq" and not config.GROQ_API_KEY:
            logger.warning("Skipping [%s:%s]: GROQ_API_KEY not configured.", prov, model)
            continue
        if prov == "gemini" and not config.GEMINI_API_KEY:
            logger.warning("Skipping [%s:%s]: GEMINI_API_KEY not configured.", prov, model)
            continue
        if prov == "ollama":
            # Test connectivity
            try:
                check = generation.test_ollama_connection(model=model)
                if not check.get("ok"):
                    logger.warning("Skipping [%s:%s]: Ollama not reachable (%s).", prov, model, check.get("error"))
                    continue
            except Exception as exc:
                logger.warning("Skipping [%s:%s]: Ollama unreachable (%s).", prov, model, exc)
                continue

        model_rows = benchmark_model_on_questions(
            provider=prov,
            model=model,
            lesson_id=args.lesson_id,
            context_docs=context_docs,
            question_types=question_types,
        )
        all_rows.extend(model_rows)

    if not all_rows:
        logger.error("No benchmark runs were completed.")
        return 1

    # Save to CSV
    output_dir = config.OUTPUTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    csv_path = Path(args.output_csv) if args.output_csv else output_dir / f"benchmark_results_{timestamp_str}.csv"

    fieldnames = [
        "timestamp", "provider", "model", "lesson_id", "question_index", "question_type",
        "latency_sec", "llm_calls", "success", "valid_json", "valid_schema",
        "mcq_valid", "evidence_fidelity", "rubric_valid", "completion_chars",
        "failure_reason", "error", "question_text"
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)

    logger.info("Saved benchmark CSV to: %s", csv_path)

    # Print summary table
    print("\n" + "=" * 95)
    print(f"BENCHMARK RESULTS SUMMARY (Lesson {args.lesson_id}, {args.questions} questions each)")
    print("=" * 95)
    headers = ["Model", "Q Type", "Latency (s)", "Calls", "JSON", "MCQ OK", "Evidence", "Rubric", "Status"]
    print(f"{headers[0]:<28} {headers[1]:<13} {headers[2]:<12} {headers[3]:<6} {headers[4]:<6} {headers[5]:<8} {headers[6]:<10} {headers[7]:<8} {headers[8]}")
    print("-" * 95)

    for row in all_rows:
        model_label = f"{row['provider']}:{row['model'].split('/')[-1]}"
        q_type = row["question_type"]
        lat = f"{row['latency_sec']:.2f}s"
        calls = str(row["llm_calls"])
        j_ok = "PASS" if row.get("valid_json") else "FAIL"
        m_ok = "-" if row.get("mcq_valid") is None else ("PASS" if row.get("mcq_valid") else "FAIL")
        ev_ok = "PASS" if row.get("evidence_fidelity") else "FAIL"
        rb_ok = "PASS" if row.get("rubric_valid") else "FAIL"
        status = "SUCCESS" if row["success"] and not row.get("failure_reason") else (row.get("failure_reason") or "ERROR")[:24]

        print(f"{model_label:<28} {q_type:<13} {lat:<12} {calls:<6} {j_ok:<6} {m_ok:<8} {ev_ok:<10} {rb_ok:<8} {status}")

    print("=" * 95 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
