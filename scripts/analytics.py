"""
Student performance analytics and clustering module.

Provides feature matrix extraction, class-wide statistical aggregation,
and production-ready ML inference using the trained student clustering pipeline.
"""

from __future__ import annotations

import os
from typing import Any
import warnings
import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

# تجاهل تحذيرات أسماء الخصائص عند تمرير البيانات للـ Scaler
warnings.filterwarnings("ignore", category=UserWarning)

# تحديد مسارات المشروع والنموذج المدرب
try:
    from scripts.config import OUTPUTS_DIR
except ImportError:
    OUTPUTS_DIR = os.path.join(os.path.dirname(__file__), "..", "outputs")

MODEL_PATH = os.path.join(OUTPUTS_DIR, "student_cluster_pipeline1.pkl")


# ==========================================
# 1. محرك الذكاء الاصطناعي (Trained ML Engine)
# ==========================================
class StudentAnalyticsEngine:
    """Production inference engine using the pre-trained clustering pipeline."""

    def __init__(self, model_path: str = MODEL_PATH):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Pipeline model not found at: {model_path}")

        bundle = joblib.load(model_path)
        self.scaler = bundle["scaler"]
        self.model = bundle["model"]
        self.avg_weight = bundle.get("avg_weight", 1.5)
        self.numeric_mapping = bundle["numeric_mapping"]
        self.level_labels = bundle["level_labels"]
        self.features = bundle.get(
            "features",
            ["avg_percentage", "max_percentage", "min_percentage", "exams_taken", "std_percentage"],
        )

    def predict_student(self, scores: list[float]) -> dict[str, Any]:
        """توقع وتحديث مستوى طالب فردي لحظياً فور إنهاء اختباره."""
        if len(scores) < 2:
            return {
                "level_code": -1,
                "student_level": "Under Evaluation",
                "is_evaluated": False,
            }

        avg_val = float(np.mean(scores))
        max_val = float(np.max(scores))
        min_val = float(np.min(scores))
        exams_count = len(scores)

        # حساب الانحراف المعياري مع التأمين ضد الـ NaN
        std_val = float(np.std(scores, ddof=1)) if len(scores) > 1 else 0.0
        if np.isnan(std_val):
            std_val = 0.0

        features_df = pd.DataFrame(
            [[avg_val, max_val, min_val, exams_count, std_val]],
            columns=self.features,
        )
        features_scaled = self.scaler.transform(features_df)
        features_scaled[:, 0] *= self.avg_weight

        raw_cluster = self.model.predict(features_scaled)[0]
        code = int(self.numeric_mapping[raw_cluster])
        label = self.level_labels[code]

        return {
            "level_code": code,
            "student_level": label,
            "is_evaluated": True,
        }

    def classify_students_dataframe(self, df_features: pd.DataFrame) -> pd.DataFrame:
        """تصنيف دفعة كاملة من الطلاب دفعة واحدة (Batch Re-classification)."""
        df = df_features.copy()

        # التأكد من ملء أي قيم مفقودة وترتيب الأعمدة بدقة
        X = df[self.features].fillna(0)
        X_scaled = self.scaler.transform(X)
        X_scaled[:, 0] *= self.avg_weight

        raw_clusters = self.model.predict(X_scaled)
        df["level_code"] = [self.numeric_mapping[c] for c in raw_clusters]
        df["student_level"] = df["level_code"].map(self.level_labels)

        return df


# ==========================================
# 2. دوال استخراج البيانات وإحصائيات الداشبورد
# ==========================================
def _extract_attempt_score_pct(attempt: dict[str, Any]) -> float:
    """Extract or calculate the percentage score from an attempt record."""
    if "percentage" in attempt and attempt["percentage"] is not None:
        return float(attempt["percentage"])
    if "total_score" in attempt and "max_possible_score" in attempt:
        max_possible = float(attempt["max_possible_score"])
        if max_possible > 0:
            return (float(attempt["total_score"]) / max_possible) * 100.0
    if "score" in attempt and "max_score" in attempt:
        max_score = float(attempt["max_score"])
        if max_score > 0:
            return (float(attempt["score"]) / max_score) * 100.0
    return float(attempt.get("score", 0.0))


def _extract_attempt_duration(attempt: dict[str, Any]) -> float:
    """Extract duration in seconds from an attempt record."""
    for key in ("duration", "duration_seconds", "time_spent", "duration_minutes"):
        if key in attempt and attempt[key] is not None:
            val = float(attempt[key])
            if key == "duration_minutes":
                val *= 60.0
            return val
    return 0.0


def _extract_attempt_topic_scores(
    attempt: dict[str, Any],
    fallback_pct: float,
) -> dict[str, list[float]]:
    """Extract topic scores map from attempt-level or answer-level records."""
    topic_map: dict[str, list[float]] = {}

    if "topic_scores" in attempt and isinstance(attempt["topic_scores"], dict):
        for topic, score in attempt["topic_scores"].items():
            if isinstance(score, (int, float)):
                topic_map.setdefault(str(topic), []).append(float(score))
    elif "topic_performance" in attempt and isinstance(attempt["topic_performance"], dict):
        for topic, score in attempt["topic_performance"].items():
            if isinstance(score, (int, float)):
                topic_map.setdefault(str(topic), []).append(float(score))
    elif "graded_answers" in attempt and isinstance(attempt["graded_answers"], list):
        question_topic_scores: dict[str, list[tuple[float, float]]] = {}
        for ans in attempt["graded_answers"]:
            if isinstance(ans, dict) and ans.get("topic"):
                t_name = str(ans["topic"]).strip()
                s = float(ans.get("score", 0.0))
                m = float(ans.get("max_score", 1.0))
                question_topic_scores.setdefault(t_name, []).append((s, m))
        for t_name, pairs in question_topic_scores.items():
            total_earned = sum(p[0] for p in pairs)
            total_possible = sum(p[1] for p in pairs)
            pct = (total_earned / total_possible * 100.0) if total_possible > 0 else 0.0
            topic_map.setdefault(t_name, []).append(pct)
    elif attempt.get("topic"):
        topic_map.setdefault(str(attempt["topic"]).strip(), []).append(fallback_pct)

    return topic_map


def build_feature_matrix(
    student_attempts: list[dict[str, Any]],
) -> tuple[np.ndarray, list[str], list[str]]:
    """Build feature matrix from student attempt records."""
    if not student_attempts:
        default_names = ["avg_score_pct", "avg_duration", "attempt_count"]
        return np.empty((0, 3), dtype=float), [], default_names

    student_records: dict[str, dict[str, Any]] = {}
    discovered_topics: set[str] = set()

    for attempt in student_attempts:
        if not isinstance(attempt, dict):
            continue

        raw_id = (
            attempt.get("student_phone")
            or attempt.get("phone")
            or attempt.get("student_id")
            or attempt.get("student_name")
            or attempt.get("user_id")
            or "unknown"
        )
        sid = str(raw_id).strip()
        score_pct = max(0.0, min(100.0, _extract_attempt_score_pct(attempt)))
        duration = max(0.0, _extract_attempt_duration(attempt))
        topics_in_attempt = _extract_attempt_topic_scores(attempt, score_pct)

        if sid not in student_records:
            student_records[sid] = {
                "scores": [],
                "durations": [],
                "topics": {},
                "attempt_count": 0,
            }

        rec = student_records[sid]
        rec["scores"].append(score_pct)
        rec["durations"].append(duration)
        rec["attempt_count"] += 1

        for topic, pcts in topics_in_attempt.items():
            discovered_topics.add(topic)
            rec["topics"].setdefault(topic, []).extend(pcts)

    if not student_records:
        default_names = ["avg_score_pct", "avg_duration", "attempt_count"]
        return np.empty((0, 3), dtype=float), [], default_names

    sorted_topics = sorted(discovered_topics)
    feature_names = ["avg_score_pct", "avg_duration", "attempt_count"] + [
        f"topic_{t}" for t in sorted_topics
    ]
    student_ids = sorted(student_records.keys())

    rows: list[list[float]] = []
    for sid in student_ids:
        rec = student_records[sid]
        avg_score = float(np.mean(rec["scores"])) if rec["scores"] else 0.0
        avg_duration = float(np.mean(rec["durations"])) if rec["durations"] else 0.0
        attempt_count = float(rec["attempt_count"])

        row = [round(avg_score, 2), round(avg_duration, 2), round(attempt_count, 2)]
        for topic in sorted_topics:
            if topic in rec["topics"] and rec["topics"][topic]:
                t_score = float(np.mean(rec["topics"][topic]))
            else:
                t_score = avg_score
            row.append(round(t_score, 2))
        rows.append(row)

    feature_matrix = np.array(rows, dtype=float)
    return feature_matrix, student_ids, feature_names


def cluster_students(
    features: np.ndarray,
    student_ids: list[str],
    n_clusters: int = 3,
    feature_names: list[str] | None = None,
) -> dict[str, Any]:
    """Fallback runtime clustering for general cohort grouping."""
    n_students = len(student_ids)
    if (
        n_students == 0
        or features.size == 0
        or features.ndim != 2
        or features.shape[0] != n_students
    ):
        return {
            "clusters": [],
            "centroids": [],
            "labels": [],
            "inertia": 0.0,
        }

    k = max(1, min(int(n_clusters), n_students))

    if n_students > 1:
        scaler = StandardScaler()
        scaled_features = scaler.fit_transform(features)
    else:
        scaled_features = features.copy()

    kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
    cluster_assignments = kmeans.fit_predict(scaled_features)
    inertia = float(kmeans.inertia_)

    cluster_mean_scores: dict[int, float] = {}
    for c_id in range(k):
        mask = cluster_assignments == c_id
        cluster_mean_scores[c_id] = (
            float(np.mean(features[mask, 0])) if np.any(mask) else 0.0
        )

    ranked_clusters = sorted(
        range(k), key=lambda c: cluster_mean_scores[c], reverse=True
    )

    cluster_to_label: dict[int, str] = {}
    if k >= 3:
        cluster_to_label[ranked_clusters[0]] = "Advanced"
        for mid_cluster in ranked_clusters[1:-1]:
            cluster_to_label[mid_cluster] = "Proficient"
        cluster_to_label[ranked_clusters[-1]] = "Needs Intervention"
    elif k == 2:
        cluster_to_label[ranked_clusters[0]] = (
            "Advanced"
            if cluster_mean_scores[ranked_clusters[0]] >= 80.0
            else "Proficient"
        )
        cluster_to_label[ranked_clusters[1]] = "Needs Intervention"
    else:
        score = cluster_mean_scores[ranked_clusters[0]]
        cluster_to_label[ranked_clusters[0]] = (
            "Advanced"
            if score >= 80.0
            else ("Proficient" if score >= 60.0 else "Needs Intervention")
        )

    labels_list = [cluster_to_label[c_id] for c_id in range(k)]

    centroids: list[list[float]] = []
    for c_id in range(k):
        mask = cluster_assignments == c_id
        if np.any(mask):
            centroid = [round(float(v), 2) for v in features[mask].mean(axis=0)]
        else:
            centroid = [round(float(v), 2) for v in kmeans.cluster_centers_[c_id]]
        centroids.append(centroid)

    f_names = (
        feature_names
        if feature_names and len(feature_names) == features.shape[1]
        else [f"feature_{col}" for col in range(features.shape[1])]
    )

    clusters_output: list[dict[str, Any]] = []
    for idx, sid in enumerate(student_ids):
        c_id = int(cluster_assignments[idx])
        feat_dict = {
            f_names[col]: round(float(features[idx, col]), 2)
            for col in range(features.shape[1])
        }
        clusters_output.append({
            "student_id": sid,
            "cluster": c_id,
            "label": cluster_to_label[c_id],
            "features": feat_dict,
        })

    return {
        "clusters": clusters_output,
        "centroids": centroids,
        "labels": labels_list,
        "inertia": round(inertia, 4),
    }


def get_class_analytics(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute class-wide statistics for dashboards."""
    if not attempts:
        return {
            "total_students": 0,
            "total_attempts": 0,
            "avg_score_pct": 0.0,
            "score_distribution": {
                "0-20": 0,
                "21-40": 0,
                "41-60": 0,
                "61-80": 0,
                "81-100": 0,
            },
            "topic_performance": {},
            "difficulty_breakdown": {},
        }

    student_ids: set[str] = set()
    scores: list[float] = []
    topic_scores: dict[str, list[float]] = {}
    difficulty_scores: dict[str, list[float]] = {}

    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue

        raw_id = (
            attempt.get("student_phone")
            or attempt.get("phone")
            or attempt.get("student_id")
            or attempt.get("student_name")
            or attempt.get("user_id")
        )
        if raw_id:
            student_ids.add(str(raw_id).strip())

        score_pct = max(0.0, min(100.0, _extract_attempt_score_pct(attempt)))
        scores.append(score_pct)

        topics = _extract_attempt_topic_scores(attempt, score_pct)
        for topic, pcts in topics.items():
            topic_scores.setdefault(topic, []).extend(pcts)

        if "difficulty_breakdown" in attempt and isinstance(
            attempt["difficulty_breakdown"], dict
        ):
            for diff, val in attempt["difficulty_breakdown"].items():
                if isinstance(val, (int, float)):
                    difficulty_scores.setdefault(str(diff).lower(), []).append(float(val))
        elif "graded_answers" in attempt and isinstance(
            attempt["graded_answers"], list
        ):
            diff_question_map: dict[str, list[tuple[float, float]]] = {}
            for ans in attempt["graded_answers"]:
                if isinstance(ans, dict) and ans.get("difficulty"):
                    d = str(ans["difficulty"]).strip().lower()
                    s = float(ans.get("score", 0.0))
                    m = float(ans.get("max_score", 1.0))
                    diff_question_map.setdefault(d, []).append((s, m))
            for diff, pairs in diff_question_map.items():
                total_earned = sum(p[0] for p in pairs)
                total_possible = sum(p[1] for p in pairs)
                pct = (
                    (total_earned / total_possible * 100.0)
                    if total_possible > 0
                    else 0.0
                )
                difficulty_scores.setdefault(diff, []).append(pct)
        elif attempt.get("difficulty"):
            difficulty_scores.setdefault(
                str(attempt["difficulty"]).strip().lower(), []
            ).append(score_pct)

    score_distribution = {
        "0-20": 0,
        "21-40": 0,
        "41-60": 0,
        "61-80": 0,
        "81-100": 0,
    }
    for s in scores:
        if s <= 20.0:
            score_distribution["0-20"] += 1
        elif s <= 40.0:
            score_distribution["21-40"] += 1
        elif s <= 60.0:
            score_distribution["41-60"] += 1
        elif s <= 80.0:
            score_distribution["61-80"] += 1
        else:
            score_distribution["81-100"] += 1

    avg_score_pct = round(float(np.mean(scores)), 2) if scores else 0.0
    topic_performance = {
        topic: round(float(np.mean(vals)), 2)
        for topic, vals in sorted(topic_scores.items())
    }
    difficulty_breakdown = {
        diff: round(float(np.mean(vals)), 2)
        for diff, vals in sorted(difficulty_scores.items())
    }

    return {
        "total_students": len(student_ids),
        "total_attempts": len(scores),
        "avg_score_pct": avg_score_pct,
        "score_distribution": score_distribution,
        "topic_performance": topic_performance,
        "difficulty_breakdown": difficulty_breakdown,
    }


# ==========================================
# 3. اختبار ذاتي للملف (Smoke Test)
# ==========================================
if __name__ == "__main__":
    engine = StudentAnalyticsEngine()
    sample_scores = [85.0, 92.0, 78.0, 88.0]
    result = engine.predict_student(sample_scores)
    print("Pipeline Loaded Successfully!")
    print("Sample Student Prediction:", result)
