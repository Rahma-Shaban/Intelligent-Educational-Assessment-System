"""
Standalone, versioned supervised classification training pipeline for the Question Bank.

Phase 6 implementation:
  - Trains baseline classifiers for Difficulty and Bloom's Taxonomy ONLY on teacher-approved questions.
  - Requires a minimum dataset threshold to prevent overfitting on unrepresentative data.
  - Evaluates per-class precision, recall, macro-F1, and confusion matrix.
  - Saves artifacts in `outputs/` separately from application source code.
  - Maintains RAG/LLM as the active production pipeline when approved data is insufficient.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy.orm import Session

from app.database import Base, SessionLocal, engine
from app.models import QuestionBankItem
from scripts.config import OUTPUTS_DIR

Base.metadata.create_all(bind=engine)

logger = logging.getLogger(__name__)

MIN_TOTAL_SAMPLES = 100
MIN_PER_CLASS_SAMPLES = 25
MODEL_VERSION = "v1.0.0"


def inspect_dataset(session: Session) -> dict[str, Any]:
    """Inspects approved question bank records and reports class distributions."""
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
        "total_approved": total,
        "is_sufficient": is_sufficient,
        "difficulty_distribution": diff_counts,
        "bloom_distribution": bloom_counts,
        "min_required_total": MIN_TOTAL_SAMPLES,
        "min_required_per_class": MIN_PER_CLASS_SAMPLES,
    }


def train_classifier(
    target: str = "difficulty",
    test_size: float = 0.25,
    random_state: int = 42,
) -> dict[str, Any]:
    """
    Executes versioned supervised classifier training if approved data is sufficient.
    Otherwise reports data requirements and preserves RAG/LLM as active method.
    """
    with SessionLocal() as session:
        stats = inspect_dataset(session)

    if not stats["is_sufficient"]:
        msg = (
            f"Insufficient labeled approved dataset for supervised training: "
            f"{stats['total_approved']}/{MIN_TOTAL_SAMPLES} samples. "
            f"Difficulty distribution: {stats['difficulty_distribution']}. "
            f"RAG/LLM classification remains the active method."
        )
        logger.info(msg)
        print(msg)
        return {
            "status": "insufficient_data",
            "message": msg,
            "dataset_stats": stats,
            "active_method": "rag_llm",
        }

    # If data is sufficient, train TF-IDF + LogisticRegression / LinearSVC
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import classification_report, confusion_matrix
    from sklearn.model_selection import train_test_split
    from sklearn.pipeline import Pipeline
    import joblib

    with SessionLocal() as session:
        items = (
            session.query(QuestionBankItem)
            .filter(QuestionBankItem.classification_status == "approved")
            .all()
        )

        texts = [it.question_text for it in items]
        if target == "difficulty":
            labels = [str(it.difficulty).capitalize() for it in items]
        else:
            labels = [str(it.bloom_level).capitalize() for it in items]

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
    parser.add_argument("--inspect-only", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as db_session:
        data_stats = inspect_dataset(db_session)

    if args.inspect_only:
        print(json.dumps(data_stats, indent=2, ensure_ascii=False))
    else:
        train_classifier(target=args.target)
