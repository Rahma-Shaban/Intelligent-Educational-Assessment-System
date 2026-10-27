"""
Model training and experiment tracking module using MLflow.
Trains the student proficiency clustering pipeline, logs metrics, and registers artifacts.
"""

import os
import joblib
import mlflow
import mlflow.sklearn
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score, davies_bouldin_score, calinski_harabasz_score
from sklearn.preprocessing import StandardScaler

# تحديد المسارات الديناميكية لمجلدات المشروع
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(BASE_DIR, "data", "processed", "students_for_clustering.csv")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def train_and_track():
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(f"Data file not found at: {DATA_PATH}")

    # 1. إعداد اسم التجربة في MLflow
    mlflow.set_experiment("Student_Proficiency_Clustering")

    # 2. تحميل البيانات وتحديد الخصائص الأساسية
    df = pd.read_csv(DATA_PATH)
    features = [
        "avg_percentage",
        "max_percentage",
        "min_percentage",
        "exams_taken",
        "std_percentage",
    ]
    X = df[features].copy()

    params = {
        "n_clusters": 3,
        "avg_weight": 1.5,
        "random_state": 42,
        "n_init": 10,
    }

    # 3. بدء تتبع التجربة
    with mlflow.start_run(run_name="KMeans_Fair_Weight_V1"):
        # تسجيل المعاملات
        mlflow.log_params(params)
        mlflow.log_param("features_list", features)
        mlflow.log_param("num_students", len(df))

        # معالجة وتحجيم البيانات مع تطبيق وزن 1.5x على المتوسط
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        X_scaled[:, 0] *= params["avg_weight"]

        # تدريب خوارزمية KMeans
        kmeans = KMeans(
            n_clusters=params["n_clusters"],
            random_state=params["random_state"],
            n_init=params["n_init"],
        )
        cluster_labels = kmeans.fit_predict(X_scaled)

        # حساب المقاييس الإحصائية لجودة المجموعات
        inertia = float(kmeans.inertia_)
        sil_score = float(silhouette_score(X_scaled, cluster_labels))
        db_score = float(davies_bouldin_score(X_scaled, cluster_labels))
        ch_score = float(calinski_harabasz_score(X_scaled, cluster_labels))

        # تسجيل المقاييس في MLflow
        mlflow.log_metrics({
            "inertia": inertia,
            "silhouette_score": sil_score,
            "davies_bouldin_score": db_score,
            "calinski_harabasz_score": ch_score,
        })

        # ترتيب المجموعات منطقياً وتعيين المسميات الأكاديمية
        cluster_means = [
            float(X.loc[cluster_labels == i, "avg_percentage"].mean())
            for i in range(params["n_clusters"])
        ]
        sorted_clusters = np.argsort(cluster_means)

        numeric_mapping = {
            int(cluster_id): int(rank) for rank, cluster_id in enumerate(sorted_clusters)
        }
        level_labels = {0: "Needs Support", 1: "Intermediate", 2: "Advanced"}

        # تجميع حزمة الإنتاج (Pipeline Bundle)
        pipeline_bundle = {
            "scaler": scaler,
            "model": kmeans,
            "avg_weight": params["avg_weight"],
            "numeric_mapping": numeric_mapping,
            "level_labels": level_labels,
            "features": features,
        }

        # حفظ الحزمة في مجلد outputs
        bundle_path = os.path.join(OUTPUT_DIR, "student_cluster_pipeline.pkl")
        joblib.dump(pipeline_bundle, bundle_path)

        # تسجيل الحزمة والموديل داخل MLflow
        mlflow.log_artifact(bundle_path, artifact_path="model_bundle")
        mlflow.sklearn.log_model(
            sk_model=kmeans,
            name="kmeans_model",
            registered_model_name="StudentProficiencyKMeans",
        )

        print("Training & MLflow logging completed successfully!")
        print(f"Silhouette Score: {sil_score:.4f} | Inertia: {inertia:.4f}")
        print(f"Pipeline saved to: {bundle_path}")


if __name__ == "__main__":
    train_and_track()
