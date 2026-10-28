"""
Standalone, versioned supervised classification training pipeline for the Question Bank.

Phase 6 / Integration implementation:
  - Can inspect & train baseline classifiers for Difficulty and Bloom's Taxonomy from:
    1. Cleaned dataset files (e.g., Question_Bank_Cleaned.xlsx via scripts.dataset_loader)
    2. Teacher-approved database records (QuestionBankItem table)
  - Enforces strict ground-truth requirements:
    * If ground-truth labels do NOT exist in the dataset, it DOES NOT fabricate labels.
    * Explicitly reports missing target labels and halts training.
    * Preserves RAG/LLM classification as the active production method.
  - Requires a minimum dataset threshold (MIN_TOTAL_SAMPLES, MIN_PER_CLASS_SAMPLES) to prevent overfitting.
  - Evaluates per-class precision, recall, macro-F1, and confusion matrix when trained.
  - Saves versioned artifacts in `outputs/question_bank_models/` separate from code.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from scripts.config import OUTPUTS_DIR
from scripts.dataset_loader import load_cleaned_dataset, resolve_cleaned_dataset_path

logger = logging.getLogger(__name__)

MIN_TOTAL_SAMPLES = 100
MIN_PER_CLASS_SAMPLES = 25
MODEL_VERSION = "v1.0.0"


def inspect_dataset_from_file(
    dataset_path: Optional[str | Path] = None,
    target: str = "difficulty",
) -> dict[str, Any]:
    """
    Inspects the cleaned dataset file for ground-truth classification labels.
    Does NOT invent or hallucinate missing labels.
    """
    try:
        resolved = resolve_cleaned_dataset_path(dataset_path)
    except FileNotFoundError as err:
        return {
            "source": "file",
            "status": "file_not_found",
            "message": str(err),
            "is_sufficient": False,
            "has_target_labels": False,
            "target": target,
        }

    dataset = load_cleaned_dataset(resolved)
    prov = dataset.provenance

    has_target = (
        prov.has_difficulty_labels if target == "difficulty" else prov.has_bloom_labels
    )
    col_name = (
        prov.difficulty_column if target == "difficulty" else prov.bloom_column
    )

    if not has_target or not col_name:
        return {
            "source": "file",
            "file_path": str(resolved),
            "sha256": prov.sha256_hash,
            "total_rows": prov.valid_rows,
            "target": target,
            "has_target_labels": False,
            "is_sufficient": False,
            "status": "missing_labels",
            "message": (
                f"Dataset at '{resolved.name}' contains {prov.valid_rows} valid questions "
                f"across {len(dataset.filters_available.get('chapters', []))} chapters, but DOES NOT "
                f"contain ground-truth labels for '{target}'. "
                f"Supervised training cannot proceed without real human-verified or curriculum ground-truth labels. "
                f"Synthetic labels will NOT be fabricated. RAG/LLM classification remains the active method."
            ),
            "active_method": "rag_llm",
            "available_columns": list(dataset.records[0].keys()) if dataset.records else [],
        }

    # If target column exists, inspect class distribution
    label_counts: dict[str, int] = {}
    valid_labeled_count = 0
    for r in dataset.records:
        val = r.get(target)
        if val:
            lbl = str(val).strip().capitalize()
            label_counts[lbl] = label_counts.get(lbl, 0) + 1
            valid_labeled_count += 1

    expected_classes = (
        ("Easy", "Medium", "Hard")
        if target == "difficulty"
        else ("Remember", "Understand", "Apply", "Analyze", "Evaluate", "Create")
    )

    is_sufficient = (
        valid_labeled_count >= MIN_TOTAL_SAMPLES
        and all(label_counts.get(c, 0) >= MIN_PER_CLASS_SAMPLES for c in expected_classes[:3])
    )

    return {
        "source": "file",
        "file_path": str(resolved),
        "sha256": prov.sha256_hash,
        "total_rows": prov.valid_rows,
        "valid_labeled_count": valid_labeled_count,
        "target": target,
        "has_target_labels": True,
        "is_sufficient": is_sufficient,
        "status": "ready" if is_sufficient else "insufficient_data",
        "class_distribution": label_counts,
        "min_required_total": MIN_TOTAL_SAMPLES,
        "min_required_per_class": MIN_PER_CLASS_SAMPLES,
        "active_method": "supervised" if is_sufficient else "rag_llm",
    }


def inspect_dataset_from_db(target: str = "difficulty") -> dict[str, Any]:
    """Inspects approved question bank records in the database."""
    from app.database import Base, SessionLocal, engine
    from app.models import QuestionBankItem

    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        approved_items = (
            session.query(QuestionBankItem)
            .filter(QuestionBankItem.classification_status == "approved")
            .all()
        )

        diff_counts: dict[str, int] = {}
        bloom_counts: dict[str, int] = {}

        for item in approved_items:
            d = str(item.difficulty or "Unknown").capitalize()
            b = str(item.bloom_level or "Unknown").capitalize()
            diff_counts[d] = diff_counts.get(d, 0) + 1
            bloom_counts[b] = bloom_counts.get(b, 0) + 1

        total = len(approved_items)
        is_sufficient = (
            total >= MIN_TOTAL_SAMPLES
            and all(diff_counts.get(c, 0) >= MIN_PER_CLASS_SAMPLES for c in ("Easy", "Medium", "Hard"))
        )

        return {
            "source": "db",
            "total_approved": total,
            "target": target,
            "has_target_labels": total > 0,
            "is_sufficient": is_sufficient,
            "status": "ready" if is_sufficient else "insufficient_data",
            "difficulty_distribution": diff_counts,
            "bloom_distribution": bloom_counts,
            "min_required_total": MIN_TOTAL_SAMPLES,
            "min_required_per_class": MIN_PER_CLASS_SAMPLES,
            "active_method": "supervised" if is_sufficient else "rag_llm",
        }


def inspect_dataset(
    source: str = "file",
    dataset_path: Optional[str | Path] = None,
    target: str = "difficulty",
) -> dict[str, Any]:
    """Unified inspection interface across file and database sources."""
    if source == "file":
        return inspect_dataset_from_file(dataset_path=dataset_path, target=target)
    elif source == "db":
        return inspect_dataset_from_db(target=target)
    else:
        raise ValueError(f"Unknown source '{source}'. Expected 'file' or 'db'.")


def train_classifier(
    target: str = "difficulty",
    source: str = "file",
    dataset_path: Optional[str | Path] = None,
    test_size: float = 0.25,
    random_state: int = 42,
) -> dict[str, Any]:
    """
    Executes versioned supervised classifier training if suitable ground-truth data exists.
    If ground truth is missing or insufficient, explicitly explains why and preserves RAG/LLM.
    """
    stats = inspect_dataset(source=source, dataset_path=dataset_path, target=target)

    # Case 1: Missing labels in dataset (do NOT fabricate!)
    if stats.get("status") == "missing_labels":
        msg = stats["message"]
        logger.warning(msg)
        print(f"\n[TRAINING HALTED] {msg}\n")
        return {
            "status": "missing_labels",
            "target": target,
            "source": source,
            "message": msg,
            "active_method": "rag_llm",
            "dataset_stats": stats,
        }

    # Case 2: Insufficient sample count for training
    if not stats.get("is_sufficient", False):
        labeled_count = stats.get("valid_labeled_count") or stats.get("total_approved", 0)
        msg = (
            f"Insufficient labeled samples for supervised training ({labeled_count}/{MIN_TOTAL_SAMPLES}). "
            f"Preserving RAG/LLM classification as active method."
        )
        logger.info(msg)
        print(f"\n[TRAINING HALTED] {msg}\n")
        return {
            "status": "insufficient_data",
            "target": target,
            "source": source,
            "message": msg,
            "dataset_stats": stats,
            "active_method": "rag_llm",
        }

    # Case 3: Suitable labels exist and threshold met -> Train classifier
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    import joblib

    texts: list[str] = []
    labels: list[str] = []

    if source == "file":
        resolved = resolve_cleaned_dataset_path(dataset_path)
        ds = load_cleaned_dataset(resolved)
        for r in ds.records:
            lbl = r.get(target)
            if lbl:
                texts.append(r["question_text"])
                labels.append(str(lbl).strip().capitalize())
    else:
        from app.database import SessionLocal
        from app.models import QuestionBankItem

        with SessionLocal() as session:
            items = (
                session.query(QuestionBankItem)
                .filter(QuestionBankItem.classification_status == "approved")
                .all()
            )
            for it in items:
                lbl = it.difficulty if target == "difficulty" else it.bloom_level
                if lbl:
                    texts.append(it.question_text)
                    labels.append(str(lbl).strip().capitalize())

    X_train, X_test, y_train, y_test = train_test_split(
        texts, labels, test_size=test_size, random_state=random_state, stratify=labels
    )

    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), max_features=5000)),
        ("clf", LogisticRegression(class_weight="balanced", max_iter=1000)),
    ])

    pipe.fit(X_train, y_train)
    y_pred = pipe.predict(X_test)

    report = classification_report(y_test, y_pred, output_dict=True)
    cm = confusion_matrix(y_test, y_pred).tolist()

    artifact_dir = OUTPUTS_DIR / "question_bank_models"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    model_path = artifact_dir / f"qb_{target}_classifier_{MODEL_VERSION}.pkl"
    joblib.dump(pipe, model_path)

    metadata = {
        "target": target,
        "source": source,
        "model_version": MODEL_VERSION,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "total_samples": len(texts),
        "train_samples": len(X_train),
        "test_samples": len(X_test),
        "classification_report": report,
        "confusion_matrix": cm,
        "artifact_path": str(model_path),
    }

    meta_path = artifact_dir / f"qb_{target}_metadata_{MODEL_VERSION}.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    print(f"Successfully trained {target} classifier {MODEL_VERSION}: {model_path}")
    return {
        "status": "success",
        "model_version": MODEL_VERSION,
        "report": report,
        "confusion_matrix": cm,
        "artifact_path": str(model_path),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Question Bank Supervised Classifier Training")
    parser.add_argument("--target", choices=["difficulty", "bloom_level"], default="difficulty")
    parser.add_argument("--source", choices=["file", "db"], default="file")
    parser.add_argument("--dataset-path", type=str, default=None, help="Path to cleaned dataset file")
    parser.add_argument("--inspect-only", action="store_true", help="Inspect and report dataset without training")
    args = parser.parse_args()

    stats = inspect_dataset(source=args.source, dataset_path=args.dataset_path, target=args.target)

    if args.inspect_only:
        print(json.dumps(stats, indent=2, ensure_ascii=False))
    else:
        train_classifier(
            target=args.target,
            source=args.source,
            dataset_path=args.dataset_path,
        )
