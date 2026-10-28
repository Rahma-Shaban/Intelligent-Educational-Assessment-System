"""
Evaluation and Observability Module for RAG Assessment.

Provides functions to:
1. Validate environment and credentials safely without exposing secrets.
2. Load and validate evaluation datasets (e.g. data/evaluation/rag_test_set.json).
3. Execute the existing RAG pipeline with separate retrieval and generation latency tracking.
4. Instrument RAG workflows with LangSmith tracing (@traceable).
5. Evaluate results with Ragas across 4 core metrics:
   - Context Precision
   - Context Recall
   - Faithfulness
   - Answer Relevancy
6. Aggregate scores and save artifacts to outputs/evaluation/.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from dotenv import load_dotenv

from scripts.config import (
    BASE_DIR,
    DATA_DIR,
    ENV_FILE,
    GROQ_API_KEY,
    GROQ_MODEL_NAME,
    HF_EMBEDDING_MODEL_NAME,
    LLM_PROVIDER,
    OUTPUTS_DIR,
    VECTOR_DB_PATH,
)

logger = logging.getLogger(__name__)

# Ensure .env is loaded
if ENV_FILE.exists():
    load_dotenv(dotenv_path=str(ENV_FILE), override=False)


# ==============================================================================
# 1. Environment & Credentials Validation (No Secret Leaks)
# ==============================================================================

def mask_credential(val: Optional[str], show_last: int = 4) -> str:
    """Mask a secret key, displaying only its presence and last few characters."""
    if not val:
        return "[NOT SET]"
    if len(val) <= show_last:
        return "[CONFIGURED]"
    return f"{'*' * (len(val) - show_last)}{val[-show_last:]}"


def validate_eval_environment() -> dict[str, Any]:
    """
    Validate environment configuration for RAG evaluation and LangSmith tracing.
    Guarantees secrets are never printed or returned.
    """
    langsmith_tracing = os.getenv("LANGSMITH_TRACING", "false").strip().lower() in ("true", "1", "yes")
    langsmith_key = os.getenv("LANGSMITH_API_KEY", "")
    langsmith_project = os.getenv("LANGSMITH_PROJECT", "educational-assessment")
    
    provider = os.getenv("LLM_PROVIDER", LLM_PROVIDER).strip().lower()
    groq_key = os.getenv("GROQ_API_KEY", GROQ_API_KEY or "")
    gemini_key = os.getenv("GEMINI_API_KEY", "")

    vector_db = VECTOR_DB_PATH
    test_set_path = DATA_DIR / "evaluation" / "rag_test_set.json"

    # Dependency versions
    import importlib.metadata as md
    def get_ver(pkg_name: str) -> str:
        try:
            return md.version(pkg_name)
        except Exception:
            return "not installed"

    versions = {
        "python": sys.version.split()[0],
        "ragas": get_ver("ragas"),
        "langsmith": get_ver("langsmith"),
        "langchain-core": get_ver("langchain-core"),
        "chromadb": get_ver("chromadb"),
        "pandas": get_ver("pandas"),
    }

    status = {
        "env_file_exists": ENV_FILE.exists(),
        "llm_provider": provider,
        "primary_provider_configured": bool(groq_key) if provider == "groq" else bool(gemini_key),
        "groq_api_key_masked": mask_credential(groq_key),
        "gemini_api_key_masked": mask_credential(gemini_key),
        "langsmith_tracing_enabled": langsmith_tracing,
        "langsmith_api_key_configured": bool(langsmith_key),
        "langsmith_api_key_masked": mask_credential(langsmith_key),
        "langsmith_project": langsmith_project,
        "vector_db_exists": vector_db.exists(),
        "vector_db_path": str(vector_db),
        "test_set_exists": test_set_path.exists(),
        "test_set_path": str(test_set_path),
        "dependency_versions": versions,
    }
    return status


# ==============================================================================
# 2. Dataset Loading & Validation
# ==============================================================================

def load_and_validate_dataset(
    path: str | Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Loads and validates the RAG evaluation dataset from disk.
    
    Returns:
        valid_cases: list of normalized valid test cases.
        invalid_cases: list of excluded items with reason for exclusion.
    """
    dataset_path = Path(path) if path else (DATA_DIR / "evaluation" / "rag_test_set.json")
    if not dataset_path.exists():
        raise FileNotFoundError(f"Evaluation dataset not found at: {dataset_path}")

    try:
        with open(dataset_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in evaluation dataset {dataset_path}: {exc}") from exc

    if not isinstance(raw_data, list):
        raise ValueError(f"Dataset root must be a list of test cases, got {type(raw_data).__name__}")

    valid_cases: list[dict[str, Any]] = []
    invalid_cases: list[dict[str, Any]] = []
    seen_questions: set[str] = set()

    for idx, item in enumerate(raw_data):
        if not isinstance(item, dict):
            invalid_cases.append({
                "raw_item": item,
                "index": idx,
                "exclusion_reason": "Item is not a dictionary",
            })
            continue

        item_id = str(item.get("id") or f"q_{idx+1}").strip()
        question = str(item.get("question") or "").strip()
        reference = str(item.get("reference_answer") or item.get("reference") or "").strip()

        if not question:
            invalid_cases.append({
                "id": item_id,
                "index": idx,
                "exclusion_reason": "Missing or empty question",
            })
            continue

        if not reference:
            invalid_cases.append({
                "id": item_id,
                "question": question,
                "index": idx,
                "exclusion_reason": "Missing or empty reference answer",
            })
            continue

        # Check duplicates
        norm_q = question.lower()
        if norm_q in seen_questions:
            invalid_cases.append({
                "id": item_id,
                "question": question,
                "index": idx,
                "exclusion_reason": "Duplicate question text detected",
            })
            continue
        seen_questions.add(norm_q)

        # Build normalized test case
        case = {
            "id": item_id,
            "question": question,
            "reference_answer": reference,
            "source_chapter": str(item.get("source_chapter") or ""),
            "source_page": str(item.get("source_page") or ""),
            "question_type": str(item.get("question_type") or "direct"),
            "expected_chunk_content": str(item.get("expected_chunk_content") or ""),
            "answerability": str(item.get("answerability") or "answerable"),
        }
        valid_cases.append(case)

    return valid_cases, invalid_cases


# ==============================================================================
# 3. RAG Pipeline Execution & Tracing
# ==============================================================================

# LangSmith optional decorator
try:
    from langsmith import traceable
    from langsmith.run_helpers import get_current_run_tree
    from langsmith import Client as LangSmithClient
    _LANGSMITH_AVAILABLE = True
except ImportError:
    _LANGSMITH_AVAILABLE = False
    def traceable(*args, **kwargs):
        def decorator(f):
            return f
        return decorator
    def get_current_run_tree():
        return None
    LangSmithClient = None


@traceable(name="curriculum_retrieval", run_type="retriever")
def retrieve_contexts(
    query: str,
    k: int = 4,
    store: Any = None,
) -> tuple[list[str], list[dict[str, Any]], float]:
    """
    Retrieves curriculum chunks using the existing similarity search.
    Measures retrieval latency in seconds.
    """
    from scripts.generation import retrieve_curriculum_context
    start_time = time.perf_counter()
    try:
        docs = retrieve_curriculum_context(topic=query, k=k)
        retrieval_latency = time.perf_counter() - start_time
        context_texts = [doc.page_content for doc in docs]
        metadata_list = [getattr(doc, "metadata", {}) or {} for doc in docs]
        return context_texts, metadata_list, retrieval_latency
    except Exception as exc:
        retrieval_latency = time.perf_counter() - start_time
        logger.warning("Retrieval failed for query '%s': %s", query, exc)
        return [], [], retrieval_latency


@traceable(name="curriculum_generation", run_type="llm")
def generate_grounded_answer(
    question: str,
    retrieved_contexts: list[str],
) -> tuple[str, float]:
    """
    Generates a concise answer strictly grounded in the retrieved curriculum chunks.
    Reuses the existing _send_completion function from scripts/generation.py.
    Measures generation latency in seconds.
    """
    from scripts.generation import _send_completion

    if not retrieved_contexts:
        return "Context unavailable to answer this question.", 0.0

    joined_context = "\n\n".join(
        f"[Passage {i+1}]: {c}" for i, c in enumerate(retrieved_contexts)
    )
    prompt = (
        "You are an educational assessment assistant. Answer the user question concisely and factually "
        "based strictly on the provided curriculum passages. Do not extrapolate beyond the text.\n\n"
        f"Curriculum Passages:\n{joined_context}\n\n"
        f"Question: {question}\n\n"
        'Return your response strictly as a JSON object with this key: {"answer": "<your concise answer>"}'
    )

    start_time = time.perf_counter()
    try:
        raw_output = _send_completion(prompt, max_tokens=1024)
        gen_latency = time.perf_counter() - start_time

        # Extract answer from JSON
        clean_text = raw_output.strip()
        if clean_text.startswith("```"):
            lines = clean_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            clean_text = "\n".join(lines).strip()
        try:
            data = json.loads(clean_text)
            answer = str(data.get("answer", "")).strip()
            if not answer:
                answer = clean_text
        except Exception:
            answer = clean_text
        return answer, gen_latency
    except Exception as exc:
        gen_latency = time.perf_counter() - start_time
        logger.error("Generation error for question '%s': %s", question, exc)
        return f"[Generation Error: {exc}]", gen_latency


@traceable(name="curriculum_rag_pipeline", run_type="chain")
def run_rag_pipeline_for_case(
    case: dict[str, Any],
    k: int = 4,
    langsmith_client: Any = None,
) -> dict[str, Any]:
    """
    Runs the full RAG pipeline (retrieval + generation) for a single test case.
    Captures individual latencies, chunk IDs, and LangSmith trace run metadata.
    """
    start_total = time.perf_counter()
    run_tree = get_current_run_tree()
    run_id = str(run_tree.id) if run_tree else None

    question = case["question"]
    contexts, metadatas, ret_latency = retrieve_contexts(question, k=k)
    chunk_ids = [str(m.get("chunk_id", "")) for m in metadatas if m.get("chunk_id")]

    answer, gen_latency = generate_grounded_answer(question, contexts)
    total_latency = time.perf_counter() - start_total

    # Determine trace URL if LangSmith client is available
    trace_url = None
    if run_id and langsmith_client:
        try:
            run_obj = langsmith_client.read_run(run_id)
            trace_url = langsmith_client.get_run_url(run=run_obj)
        except Exception:
            # Fallback URL schema
            project = os.getenv("LANGSMITH_PROJECT", "educational-assessment")
            trace_url = f"https://smith.langchain.com (Run ID: {run_id})"

    status = "success"
    error_msg = None
    if not contexts:
        status = "empty_retrieval"
        error_msg = "No curriculum chunks retrieved"
    elif answer.startswith("[Generation Error:"):
        status = "generation_error"
        error_msg = answer

    return {
        "id": case.get("id", ""),
        "question": question,
        "reference": case.get("reference_answer", ""),
        "response": answer,
        "retrieved_contexts": contexts,
        "chunk_ids": chunk_ids,
        "num_retrieved_chunks": len(contexts),
        "retrieval_latency": round(ret_latency, 3),
        "generation_latency": round(gen_latency, 3),
        "total_latency": round(total_latency, 3),
        "run_id": run_id,
        "trace_url": trace_url,
        "status": status,
        "error": error_msg,
    }


def run_rag_batch(
    test_cases: list[dict[str, Any]],
    k: int = 4,
    max_cases: int | None = None,
    langsmith_client: Any = None,
    progress_callback: Any = None,
) -> list[dict[str, Any]]:
    """
    Executes the RAG pipeline over a batch of test cases without terminating on errors.
    Supports a max_cases limit for smoke testing.
    """
    subset = test_cases[:max_cases] if max_cases is not None else test_cases
    results = []
    total = len(subset)
    for idx, case in enumerate(subset, start=1):
        if progress_callback:
            progress_callback(idx, total, case["question"])
        res = run_rag_pipeline_for_case(case, k=k, langsmith_client=langsmith_client)
        results.append(res)
    return results


# ==============================================================================
# 4. Ragas Evaluation
# ==============================================================================

def setup_ragas_evaluators() -> tuple[Any, Any]:
    """
    Sets up the evaluator LLM and evaluator Embeddings.
    Reuses existing Groq credentials for evaluator LLM with bypass_n=True for Groq API compatibility.
    Reuses local HuggingFace sentence-transformers embeddings.
    """
    from langchain_openai import ChatOpenAI
    from langchain_huggingface import HuggingFaceEmbeddings
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import answer_relevancy

    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        raise ValueError("GROQ_API_KEY is required in .env for evaluator LLM")

    model_name = os.getenv("GROQ_MODEL_NAME", "openai/gpt-oss-20b")
    chat_llm = ChatOpenAI(
        model=model_name,
        api_key=groq_key,
        base_url="https://api.groq.com/openai/v1",
        temperature=0.0,
    )
    # Groq API limits n=1 per request. LangchainLLMWrapper(bypass_n=True) ensures
    # multiple completions are requested as individual n=1 prompts instead of n>1 payload.
    evaluator_llm = LangchainLLMWrapper(chat_llm, bypass_n=True)
    evaluator_emb = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )
    # Ensure answer_relevancy generates 1 statement at a time for Groq
    answer_relevancy.strictness = 1

    return evaluator_llm, evaluator_emb


def evaluate_rag_results(
    rag_results: list[dict[str, Any]],
    evaluator_llm: Any = None,
    evaluator_emb: Any = None,
) -> pd.DataFrame:
    """
    Evaluates RAG pipeline results using Ragas across 4 core metrics:
    - Context Precision
    - Context Recall
    - Faithfulness
    - Answer Relevancy
    
    Returns a unified per-question results DataFrame.
    """
    from ragas import EvaluationDataset, SingleTurnSample, evaluate
    from ragas.metrics import (
        answer_relevancy,
        context_precision,
        context_recall,
        faithfulness,
    )

    if evaluator_llm is None or evaluator_emb is None:
        evaluator_llm, evaluator_emb = setup_ragas_evaluators()

    # Filter cases that can be evaluated (must have non-empty response & context)
    samples: list[SingleTurnSample] = []
    eval_indices: list[int] = []

    for idx, res in enumerate(rag_results):
        contexts = res.get("retrieved_contexts") or []
        response = res.get("response") or ""
        question = res.get("question") or ""
        reference = res.get("reference") or ""

        # Only evaluate valid non-empty results
        if contexts and response and not response.startswith("[Generation Error:"):
            samples.append(
                SingleTurnSample(
                    user_input=question,
                    response=response,
                    reference=reference,
                    retrieved_contexts=contexts,
                )
            )
            eval_indices.append(idx)

    # Initialize results container
    df_rows = []
    for res in rag_results:
        row = {
            "id": res["id"],
            "question": res["question"],
            "reference": res["reference"],
            "response": res["response"],
            "num_chunks": res["num_retrieved_chunks"],
            "retrieval_latency": res["retrieval_latency"],
            "generation_latency": res["generation_latency"],
            "total_latency": res["total_latency"],
            "context_precision": None,
            "context_recall": None,
            "faithfulness": None,
            "answer_relevancy": None,
            "status": res["status"],
            "error": res["error"],
            "run_id": res.get("run_id"),
            "trace_url": res.get("trace_url"),
        }
        df_rows.append(row)

    if samples:
        from ragas.run_config import RunConfig
        dataset = EvaluationDataset(samples=samples)
        metrics = [context_precision, context_recall, faithfulness, answer_relevancy]
        run_config = RunConfig(timeout=180, max_workers=2, max_retries=5)
        try:
            eval_output = evaluate(
                dataset=dataset,
                metrics=metrics,
                llm=evaluator_llm,
                embeddings=evaluator_emb,
                run_config=run_config,
            )
            scores_df = eval_output.to_pandas()
            for eval_idx, (_, score_row) in zip(eval_indices, scores_df.iterrows()):
                df_rows[eval_idx]["context_precision"] = score_row.get("context_precision")
                df_rows[eval_idx]["context_recall"] = score_row.get("context_recall")
                df_rows[eval_idx]["faithfulness"] = score_row.get("faithfulness")
                df_rows[eval_idx]["answer_relevancy"] = score_row.get("answer_relevancy")
                df_rows[eval_idx]["status"] = "evaluated"
        except Exception as exc:
            logger.error("Ragas evaluation batch failed: %s", exc)
            for eval_idx in eval_indices:
                df_rows[eval_idx]["status"] = "evaluation_failed"
                df_rows[eval_idx]["error"] = str(exc)

    return pd.DataFrame(df_rows)


# ==============================================================================
# 5. Aggregation & Summarization
# ==============================================================================

def aggregate_evaluation_results(df: pd.DataFrame) -> dict[str, Any]:
    """
    Computes summary metrics, counts, and latency aggregates.
    Correctly accounts for valid denominators and ignores NaNs.
    """
    metric_cols = ["context_precision", "context_recall", "faithfulness", "answer_relevancy"]
    metrics_summary: dict[str, Any] = {}

    for m in metric_cols:
        if m in df.columns:
            series = pd.to_numeric(df[m], errors="coerce").dropna()
            count = int(series.count())
            mean_val = float(series.mean()) if count > 0 else None
            metrics_summary[m] = {
                "mean": round(mean_val, 4) if mean_val is not None else None,
                "valid_count": count,
                "missing_or_failed_count": int(len(df) - count),
            }

    latency_summary = {
        "mean_retrieval_latency": round(float(df["retrieval_latency"].mean()), 3) if "retrieval_latency" in df else 0.0,
        "mean_generation_latency": round(float(df["generation_latency"].mean()), 3) if "generation_latency" in df else 0.0,
        "mean_total_latency": round(float(df["total_latency"].mean()), 3) if "total_latency" in df else 0.0,
    }

    status_counts = df["status"].value_counts().to_dict() if "status" in df else {}

    return {
        "total_evaluated_cases": len(df),
        "status_distribution": status_counts,
        "metrics": metrics_summary,
        "latency_summary": latency_summary,
    }


# ==============================================================================
# 6. Artifact Saving
# ==============================================================================

def save_evaluation_outputs(
    results_df: pd.DataFrame,
    summary: dict[str, Any],
    detailed_records: list[dict[str, Any]],
    output_dir: str | Path | None = None,
) -> dict[str, Path]:
    """
    Saves evaluation artifacts to outputs/evaluation/.
    Produces:
      - ragas_results.csv
      - ragas_summary.json
      - ragas_results.json
      - run_manifest.jsonl
    """
    out_path = Path(output_dir) if output_dir else (OUTPUTS_DIR / "evaluation")
    out_path.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).isoformat()
    meta_summary = {
        "execution_timestamp": timestamp,
        "dataset": "rag_test_set.json",
        "ragas_version": "0.4.3",
        "summary": summary,
    }

    # 1. ragas_results.csv
    csv_file = out_path / "ragas_results.csv"
    results_df.to_csv(csv_file, index=False)

    # 2. ragas_summary.json
    summary_file = out_path / "ragas_summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(meta_summary, f, indent=2)

    # 3. ragas_results.json
    results_json_file = out_path / "ragas_results.json"
    with open(results_json_file, "w", encoding="utf-8") as f:
        json.dump(results_df.to_dict(orient="records"), f, indent=2)

    # 4. run_manifest.jsonl
    manifest_file = out_path / "run_manifest.jsonl"
    with open(manifest_file, "w", encoding="utf-8") as f:
        for rec in detailed_records:
            # Mask any internal sensitive keys if present
            safe_rec = {k: v for k, v in rec.items() if not k.lower().endswith("key")}
            f.write(json.dumps(safe_rec, ensure_ascii=False) + "\n")

    return {
        "csv": csv_file,
        "summary_json": summary_file,
        "results_json": results_json_file,
        "manifest_jsonl": manifest_file,
    }
