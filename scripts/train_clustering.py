"""
Unsupervised Student Clustering Pipeline Trainer with MLflow Tracking.

Fits a StandardScaler and KMeans (k=3) clustering pipeline on historical student
performance metrics, logs metrics/params to MLflow, and saves the artifact
to outputs/student_cluster_pipeline.pkl.
Unified cluster labels: "Needs Intervention", "Proficient", "Advanced".
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from typing import Any
import joblib
import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score, davies_bouldin_score, calinski_harabasz_score
from sklearn.preprocessing import StandardScaler

from scripts.config import OUTPUTS_DIR, PROCESSED_DATA_DIR

DEFAULT_DATASET = PROCESSED_DATA_DIR / "students_for_clustering (1).csv"
TARGET_MODEL_PATH = OUTPUTS_DIR / "student_cluster_pipeline1.pkl"

FEATURES = [
    "avg_percentage",
    "max_percentage",
    "min_percentage",
    "exams_taken",
    "std_percentage",
]

LEVEL_LABELS = {
    0: "Needs Intervention",
    1: "Proficient",
    2: "Advanced",
}


def find_dataset(custom_path: str | Path | None = None) -> Path:
    """Locate the student clustering CSV file."""
    if custom_path and Path(custom_path).exists():
        return Path(custom_path)

    if DEFAULT_DATASET.exists():
        return DEFAULT_DATASET

    candidates = list(PROCESSED_DATA_DIR.glob("students_for_clustering*.csv"))
    if candidates:
        return candidates[0]

    raise FileNotFoundError(
        f"Could not locate student clustering dataset at {DEFAULT_DATASET} "
        f"or in {PROCESSED_DATA_DIR}"
    )


def train_clustering_pipeline(
    data_path: str | Path | None = None,
    output_path: str | Path | None = None,
    n_clusters: int = 3,
    avg_weight: float = 1.5,
    random_state: int = 42,
) -> dict[str, Any]:
    """
    Train StandardScaler + KMeans(k=3), log metrics to MLflow, and save artifact bundle.
    """
    dataset_file = find_dataset(data_path)
    save_path = Path(output_path) if output_path else TARGET_MODEL_PATH
    save_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Loading clustering dataset from: {dataset_file}")
    df = pd.read_csv(dataset_file)

    missing = [f for f in FEATURES if f not in df.columns]
    if missing:
        raise ValueError(f"Dataset is missing required feature columns: {missing}")

    X = df[FEATURES].fillna(0).copy()
    print(f"Dataset shape: {X.shape[0]} students with {X.shape[1]} features")

    # إعداد تجربة MLflow
    mlflow.set_experiment("Student_Proficiency_Clustering")

    with mlflow.start_run(run_name="KMeans_Fair_Weight_V1"):
        # تسجيل المعاملات الأساسية
        mlflow.log_params({
            "n_clusters": n_clusters,
            "avg_weight": avg_weight,
            "random_state": random_state,
            "n_init": 10,
        })
        mlflow.log_param("features_list", FEATURES)
        mlflow.log_param("num_students", len(df))

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        # تطبيق الوزن على متوسط الدرجات (feature 0)
        X_scaled[:, 0] *= avg_weight

        kmeans = KMeans(
            n_clusters=n_clusters,
            random_state=random_state,
            n_init=10,
        )
        raw_clusters = kmeans.fit_predict(X_scaled)
        df["raw_cluster"] = raw_clusters

        # حساب وتسجيل المقاييس الإحصائية لجودة المجموعات
        inertia = float(kmeans.inertia_)
        sil_score = float(silhouette_score(X_scaled, raw_clusters))
        db_score = float(davies_bouldin_score(X_scaled, raw_clusters))
        ch_score = float(calinski_harabasz_score(X_scaled, raw_clusters))

        mlflow.log_metrics({
            "inertia": inertia,
            "silhouette_score": sil_score,
            "davies_bouldin_score": db_score,
            "calinski_harabasz_score": ch_score,
        })

        # ترتيب الكلاسترز تصاعدياً حسب متوسط الدرجات
        cluster_means = df.groupby("raw_cluster")["avg_percentage"].mean().sort_values(ascending=True)
        cluster_order = cluster_means.index.tolist()

        numeric_mapping: dict[int, int] = {
            int(raw_c): rank for rank, raw_c in enumerate(cluster_order)
        }

        df["level_code"] = df["raw_cluster"].map(numeric_mapping)
        df["student_level"] = df["level_code"].map(LEVEL_LABELS)

        print("\n--- Training Cluster Statistics ---")
        for code, label in LEVEL_LABELS.items():
            sub = df[df["level_code"] == code]
            avg_pct = sub["avg_percentage"].mean() if len(sub) > 0 else 0.0
            min_pct = sub["avg_percentage"].min() if len(sub) > 0 else 0.0
            max_pct = sub["avg_percentage"].max() if len(sub) > 0 else 0.0
            print(f"  Level {code} [{label}]: {len(sub)} students | Avg: {avg_pct:.1f}% (Range: {min_pct:.1f}% - {max_pct:.1f}%)")

        bundle = {
            "scaler": scaler,
            "model": kmeans,
            "features": FEATURES,
            "avg_weight": avg_weight,
            "numeric_mapping": numeric_mapping,
            "level_labels": LEVEL_LABELS,
        }

        # حفظ الملف في outputs
        joblib.dump(bundle, save_path)
        print(f"\nPipeline artifact successfully saved to: {save_path}")

        # تسجيل الـ Artifact والموديل في MLflow
        mlflow.log_artifact(str(save_path), artifact_path="model_bundle")
        mlflow.sklearn.log_model(
            sk_model=kmeans,
            name="kmeans_model",
            registered_model_name="StudentProficiencyKMeans",
        )

    return bundle


def main():
    parser = argparse.ArgumentParser(description="Train student clustering ML pipeline with MLflow tracking")
    parser.add_argument("--data", type=str, default=None, help="Path to input CSV")
    parser.add_argument("--output", type=str, default=None, help="Path to save PKL model")
    args = parser.parse_args()

    train_clustering_pipeline(data_path=args.data, output_path=args.output)


if __name__ == "__main__":
    main()
