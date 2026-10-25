import unittest
import numpy as np
from scripts import analytics


class AnalyticsModuleTests(unittest.TestCase):
    def test_build_feature_matrix_empty(self):
        matrix, sids, fnames = analytics.build_feature_matrix([])
        self.assertEqual(matrix.shape, (0, 3))
        self.assertEqual(sids, [])
        self.assertEqual(fnames, ["avg_score_pct", "avg_duration", "attempt_count"])

    def test_build_feature_matrix_with_attempts(self):
        attempts = [
            {
                "student_id": "S1",
                "score": 80.0,
                "max_score": 100.0,
                "duration": 600,
                "topic": "Python",
            },
            {
                "student_id": "S1",
                "score": 90.0,
                "max_score": 100.0,
                "duration": 700,
                "topic": "Algorithms",
            },
            {
                "student_id": "S2",
                "score": 50.0,
                "max_score": 100.0,
                "duration": 1200,
                "topic": "Python",
            },
        ]
        matrix, sids, fnames = analytics.build_feature_matrix(attempts)

        self.assertEqual(sids, ["S1", "S2"])
        self.assertEqual(matrix.shape, (2, 5))
        self.assertIn("topic_Algorithms", fnames)
        self.assertIn("topic_Python", fnames)

        # S1 avg score is 85.0, avg duration is 650.0, attempt count is 2.0
        self.assertAlmostEqual(matrix[0, 0], 85.0)
        self.assertAlmostEqual(matrix[0, 1], 650.0)
        self.assertAlmostEqual(matrix[0, 2], 2.0)

        # S2 avg score is 50.0, avg duration is 1200.0, attempt count is 1.0
        self.assertAlmostEqual(matrix[1, 0], 50.0)
        self.assertAlmostEqual(matrix[1, 1], 1200.0)
        self.assertAlmostEqual(matrix[1, 2], 1.0)

    def test_cluster_students_labels_ranking(self):
        # 3 distinct proficiency groups
        # Advanced (high score, moderate duration)
        # Proficient (mid score)
        # Needs Intervention (low score)
        features = np.array([
            [95.0, 300.0, 3.0],
            [92.0, 320.0, 3.0],
            [75.0, 500.0, 2.0],
            [72.0, 510.0, 2.0],
            [40.0, 800.0, 1.0],
            [35.0, 850.0, 1.0],
        ])
        sids = ["S1", "S2", "S3", "S4", "S5", "S6"]
        fnames = ["avg_score_pct", "avg_duration", "attempt_count"]

        res = analytics.cluster_students(features, sids, n_clusters=3, feature_names=fnames)

        self.assertEqual(len(res["clusters"]), 6)
        self.assertEqual(len(res["centroids"]), 3)
        self.assertIn("Advanced", res["labels"])
        self.assertIn("Proficient", res["labels"])
        self.assertIn("Needs Intervention", res["labels"])

        # Check that highest scoring students receive 'Advanced'
        student_cluster_map = {c["student_id"]: c["label"] for c in res["clusters"]}
        self.assertEqual(student_cluster_map["S1"], "Advanced")
        self.assertEqual(student_cluster_map["S2"], "Advanced")
        self.assertEqual(student_cluster_map["S5"], "Needs Intervention")
        self.assertEqual(student_cluster_map["S6"], "Needs Intervention")

    def test_cluster_students_edge_cases(self):
        # Empty input
        empty_res = analytics.cluster_students(np.empty((0, 3)), [])
        self.assertEqual(empty_res["clusters"], [])
        self.assertEqual(empty_res["labels"], [])

        # Single student
        single_res = analytics.cluster_students(np.array([[90.0, 300.0, 1.0]]), ["S1"], n_clusters=3)
        self.assertEqual(len(single_res["clusters"]), 1)
        self.assertEqual(single_res["clusters"][0]["label"], "Advanced")

    def test_get_class_analytics(self):
        attempts = [
            {
                "student_id": "S1",
                "percentage": 95.0,
                "topic": "AI",
                "difficulty": "easy",
            },
            {
                "student_id": "S1",
                "percentage": 85.0,
                "topic": "ML",
                "difficulty": "medium",
            },
            {
                "student_id": "S2",
                "percentage": 45.0,
                "topic": "AI",
                "difficulty": "hard",
            },
        ]
        stats = analytics.get_class_analytics(attempts)

        self.assertEqual(stats["total_students"], 2)
        self.assertEqual(stats["total_attempts"], 3)
        self.assertAlmostEqual(stats["avg_score_pct"], 75.0, places=1)
        self.assertEqual(stats["score_distribution"]["81-100"], 2)
        self.assertEqual(stats["score_distribution"]["41-60"], 1)
        self.assertEqual(stats["topic_performance"]["AI"], 70.0)
        self.assertEqual(stats["topic_performance"]["ML"], 85.0)
        self.assertEqual(stats["difficulty_breakdown"]["easy"], 95.0)
        self.assertEqual(stats["difficulty_breakdown"]["hard"], 45.0)


if __name__ == "__main__":
    unittest.main()
