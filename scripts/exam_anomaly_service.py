"""
Exam Anomaly Detection Service (Inference Layer).
Loads the trained pipeline artifact and inspects submitted exam attempts.
"""

import logging
import sys
from pathlib import Path
from typing import Any, Dict
import joblib
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin


# ---------------------------------------------------------------------
# كلاس هندسة الخصائص لضمان فك تسلسل النموذج بدون مشاكل استيراد
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


if "__main__" in sys.modules and not hasattr(sys.modules["__main__"], "ExamFeatureEngineer"):
    setattr(sys.modules["__main__"], "ExamFeatureEngineer", ExamFeatureEngineer)


# ---------------------------------------------------------------------
# كلاس خدمة فحص المحاولات
# ---------------------------------------------------------------------
class ExamAnomalyService:

    def __init__(self, model_path: str = None):
        if model_path is None:
            project_root = Path(__file__).resolve().parent.parent
            model_path = project_root / "outputs" / "exam_anomaly_pipeline.pkl"
        else:
            model_path = Path(model_path)

        if not model_path.exists():
            raise FileNotFoundError(
                f"لم يتم العثور على ملف النموذج في: {model_path}"
            )

        main_mod = sys.modules.get("__main__")
        if main_mod is not None and not hasattr(main_mod, "ExamFeatureEngineer"):
            setattr(main_mod, "ExamFeatureEngineer", ExamFeatureEngineer)
        self.pipeline = joblib.load(model_path)
        logging.getLogger(__name__).info("Exam anomaly pipeline loaded from: %s", model_path)

    def inspect_attempt(
        self,
        mcq_count: int,
        essay_count: int,
        duration_seconds: float,
        score_percentage: float,
    ) -> Dict[str, Any]:
        """فحص محاولة اختبار وتحديد ما إذا كانت طبيعية أم مشبوهة مع بيان السبب."""
        input_df = pd.DataFrame(
            [
                {
                    "mcq_count": int(mcq_count),
                    "essay_count": int(essay_count),
                    "duration_seconds": float(duration_seconds),
                    "score_percentage": float(score_percentage),
                }
            ]
        )

        # 1 = طبيعي, -1 = شاذ / مشبوه
        raw_pred = self.pipeline.predict(input_df)[0]
        is_anomaly = bool(raw_pred == -1)

        # حساب درجة الشذوذ (Decision Score)
        iso_forest = self.pipeline.named_steps["isolation_forest"]
        scaled_features = self.pipeline.named_steps["scaler"].transform(
            self.pipeline.named_steps["feature_engineering"].transform(input_df)
        )
        decision_score = float(iso_forest.decision_function(scaled_features)[0])

        # تحليل سبب التنبيه لتسهيل المراجعة على المعلم
        flag_reason = "محاولة طبيعية متناسقة"
        if is_anomaly:
            total_q = max(mcq_count + essay_count, 1)
            sec_per_q = duration_seconds / total_q

            # استبعاد الإنذارات الخاطئة: قضاء وقت طبيعي مع درجات غير مرتفعة ليس اشتباهاً بغش
            if sec_per_q >= 15.0 and score_percentage <= 80.0:
                is_anomaly = False
                flag_reason = "محاولة طبيعية متناسقة"
            elif essay_count > 0 and (duration_seconds / total_q) < 15.0:
                flag_reason = "سرعة حل غير واقعية لأسئلة مقالية (اشتباه قوي)"
            elif sec_per_q < 5.0 and score_percentage < 40.0:
                flag_reason = "تخمين عشوائي وسريع بدون قراءة الأسئلة"
            elif score_percentage > 85.0 and sec_per_q < 10.0:
                flag_reason = (
                    "درجة مرتفعة مع زمن قراءة مستحيل (اشتباه غش/تسريب)"
                )
            else:
                flag_reason = (
                    "سلوك شاذ إحصائياً مقارنة بمتوسط التوزيع العام للطلاب"
                )

        return {
            "is_anomaly": is_anomaly,
            "status": "Suspicious / Flagged" if is_anomaly else "Normal",
            "decision_score": round(decision_score, 4),
            "flag_reason": flag_reason,
            "summary": {
                "duration_min": round(duration_seconds / 60.0, 2),
                "avg_sec_per_question": round(
                    duration_seconds / max(mcq_count + essay_count, 1), 1
                ),
                "score_pct": score_percentage,
            },
        }


# ---------------------------------------------------------------------
# تجربة عملية على سيناريوهين واقعيين
# ---------------------------------------------------------------------
if __name__ == "__main__":
    service = ExamAnomalyService()

    print("\n--- 1. محاولة طبيعية لطالب ---")
    normal_case = service.inspect_attempt(
        mcq_count=16,
        essay_count=3,
        duration_seconds=1020.0,  # 17 دقيقة
        score_percentage=72.0,
    )
    print(normal_case)

    print("\n--- 2. محاولة مشبوهة (سرعة غير منطقية) ---")
    suspicious_case = service.inspect_attempt(
        mcq_count=16,
        essay_count=3,
        duration_seconds=180.0,  # 3 دقائق فقط لنفس الامتحان وبدرجة عالية
        score_percentage=94.0,
    )
    print(suspicious_case)
