"""
MLflow Training Pipeline for Exam Anomaly Detection.
Tracks parameters, unsupervised evaluation metrics, and logs the pipeline artifact.
"""

from pathlib import Path
import joblib
import mlflow
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.ensemble import IsolationForest
from sklearn.metrics import davies_bouldin_score, silhouette_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


# ---------------------------------------------------------------------
# 1. محول استخراج الخصائص السلوكية
# ---------------------------------------------------------------------
class ExamFeatureEngineer(BaseEstimator, TransformerMixin):
    def fit(self, X, y=None):
        return self

    def transform(self, X):
        if not isinstance(X, pd.DataFrame):
            df = pd.DataFrame(
                X,
                columns=[
                    "mcq_count",
                    "essay_count",
                    "duration_seconds",
                    "score_percentage",
                ],
            )
        else:
            df = X.copy()

        total_questions = df["mcq_count"] + df["essay_count"]
        avg_sec_per_q = df["duration_seconds"] / np.maximum(total_questions, 1)
        essay_speed_ratio = (df["essay_count"] * 100.0) / np.maximum(
            df["duration_seconds"], 1.0
        )
        speed_accuracy_index = df["score_percentage"] / np.maximum(
            avg_sec_per_q, 1.0
        )

        features = pd.DataFrame(
            {
                "duration_seconds": df["duration_seconds"],
                "score_percentage": df["score_percentage"],
                "avg_sec_per_q": avg_sec_per_q,
                "essay_speed_ratio": essay_speed_ratio,
                "speed_accuracy_index": speed_accuracy_index,
            }
        )
        return features.values


# ---------------------------------------------------------------------
# 2. التدريب والتسجيل في MLflow
# ---------------------------------------------------------------------
def train_and_log_mlflow():
    # إعداد المسارات الديناميكية المطلقة
    project_root = Path(__file__).resolve().parent.parent
    dataset_path = (
        project_root
        / "data"
        / "processed"
        / "exam_attempts_anomaly_dataset.csv"
    )
    output_dir = project_root / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    local_model_path = output_dir / "exam_anomaly_pipeline.pkl"

    if not dataset_path.exists():
        raise FileNotFoundError(f"لم يتم العثور على الملف في: {dataset_path}")

    df = pd.read_csv(dataset_path)
    feature_cols = [
        "mcq_count",
        "essay_count",
        "duration_seconds",
        "score_percentage",
    ]
    X = df[feature_cols]

    # Hyperparameters
    params = {
        "n_estimators": 150,
        "contamination": 0.04,
        "random_state": 42,
        "n_jobs": -1,
    }

    # تحديد اسم التجربة في MLflow
    mlflow.set_experiment("Exam_Behavior_Anomaly_Detection")

    with mlflow.start_run(run_name="Isolation_Forest_Unsupervised_v1"):
        # تسجيل المعاملات
        mlflow.log_params(params)
        mlflow.log_param("dataset_samples_count", len(df))
        mlflow.log_param("features_list", feature_cols)

        # بناء الـ Pipeline
        pipeline = Pipeline(
            [
                ("feature_engineering", ExamFeatureEngineer()),
                ("scaler", StandardScaler()),
                (
                    "isolation_forest",
                    IsolationForest(
                        n_estimators=params["n_estimators"],
                        contamination=params["contamination"],
                        random_state=params["random_state"],
                        n_jobs=params["n_jobs"],
                    ),
                ),
            ]
        )

        print("جاري تدريب الـ Pipeline...")
        pipeline.fit(X)

        # حساب التوقعات والتقييم الرياضي
        raw_preds = pipeline.predict(X)
        cluster_labels = np.where(raw_preds == -1, 1, 0)

        transformed_X = pipeline.named_steps["scaler"].transform(
            pipeline.named_steps["feature_engineering"].transform(X)
        )

        sil_score = float(silhouette_score(transformed_X, cluster_labels))
        db_score = float(davies_bouldin_score(transformed_X, cluster_labels))
        anomaly_ratio = float((np.sum(cluster_labels == 1) / len(df)) * 100)

        # تسجيل الـ Metrics داخل MLflow
        mlflow.log_metric("silhouette_score", sil_score)
        mlflow.log_metric("davies_bouldin_index", db_score)
        mlflow.log_metric("detected_anomalies_pct", anomaly_ratio)
        mlflow.log_metric(
            "detected_anomalies_count", int(np.sum(cluster_labels == 1))
        )

        print("\n--- النتائج المسجلة في MLflow ---")
        print(f"Silhouette Score    : {sil_score:.4f}")
        print(f"Davies-Bouldin Index: {db_score:.4f}")
        print(f"Anomaly Ratio       : {anomaly_ratio:.2f}%")

        # 1. حفظ نسخة محلية عبر joblib
        joblib.dump(pipeline, local_model_path)
        print(f"\nتم حفظ الموديل محلياً في: {local_model_path}")

        # 2. رفع ملف الموديل كـ Artifact مباشر داخل MLflow
        mlflow.log_artifact(str(local_model_path), artifact_path="model")
        print("تم تسجيل الموديل كـ Artifact بنجاح في MLflow!")
        print("تم تسجيل Run بنجاح في MLflow!")


if __name__ == "__main__":
    train_and_log_mlflow()
