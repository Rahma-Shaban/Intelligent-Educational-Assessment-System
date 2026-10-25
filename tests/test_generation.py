import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import generation
from scripts.ingestion import build_vectorstore, load_vectorstore


def sample_document():
    return SimpleNamespace(
        page_content="Artificial intelligence supports data analysis.",
        metadata={
            "source": "curriculum.pdf",
            "chapter_id": 1,
            "chapter_title": "Artificial Intelligence",
            "lesson_id": "1-1",
            "lesson_title": "Lesson One",
            "chunk_id": "1-1-001",
            "content_type": "text",
        },
    )


def sample_question():
    return {
        "question": "Which use is described?",
        "question_id": "Q01",
        "lesson_id": "1-1",
        "question_type": "mcq",
        "difficulty": "medium",
        "bloom_level": "apply",
        "bloom_rationale": "Transfers the lesson concept to a short scenario.",
        "options": [
            "Data analysis",
            "Unrelated option one",
            "Unrelated option two",
            "Unrelated option three",
        ],
        "correct_answer": "A",
        "reference_answer": "A",
        "explanation": "The curriculum passage describes this use.",
        "max_score": 1,
        "rubric": [{"criterion": "Correct response", "points": 1, "description": "Identifies the use."}],
        "source_refs": [{
            "source": "curriculum.pdf",
            "chunk_id": "1-1-001",
            "evidence_quote": "Artificial intelligence supports data analysis.",
        }],
    }


def question_for_type(**kwargs):
    question_type = kwargs["question_type"]
    question = sample_question()
    question["question_type"] = question_type
    if question_type != "mcq":
        question["options"] = []
        question["correct_answer"] = ""
    return question


class GenerationValidationTests(unittest.TestCase):
    def test_extracts_plain_and_fenced_json(self):
        expected = {"question": "test"}
        self.assertEqual(generation._extract_json_object(json.dumps(expected)), expected)
        self.assertEqual(
            generation._extract_json_object(f"```json\n{json.dumps(expected)}\n```"),
            expected,
        )

    def test_rejects_malformed_or_non_object_json(self):
        for value in ("not json", "[1, 2]"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                generation._extract_json_object(value)

    def test_validates_mcq_shape_and_normalizes_correct_answer(self):
        question = sample_question()
        question["correct_answer"] = "1"
        generation._validate_question(question)
        self.assertEqual(question["correct_answer"], "A")

    def test_rejects_mcq_reference_answer_that_disagrees_with_key(self):
        question = sample_question()
        question["reference_answer"] = "B"
        with self.assertRaisesRegex(ValueError, "does not match correct_answer"):
            generation._validate_question(question)

    def test_rejects_mcq_reference_text_that_disagrees_with_selected_option(self):
        question = sample_question()
        question["reference_answer"] = "A: Unrelated option one"
        with self.assertRaisesRegex(ValueError, "text does not match the selected option"):
            generation._validate_question(question)

    def test_mcq_rubric_must_be_one_point_for_one_selected_answer(self):
        question = sample_question()
        question["rubric"] = [
            {"criterion": "Correct selection", "points": 1, "description": "Correct."},
            {"criterion": "Explanation", "points": 1, "description": "Explains."},
        ]
        with self.assertRaisesRegex(ValueError, "exactly 1 point"):
            generation._validate_question(question)

    def test_question_max_score_must_match_rubric_sum(self):
        question = sample_question()
        question["max_score"] = 5
        with self.assertRaisesRegex(ValueError, "max_score must equal"):
            generation._validate_question(question)

    def test_generation_keeps_only_unique_quoted_retrieved_sources(self):
        document = sample_document()
        generated_question = sample_question()
        generated_question["source_refs"] = [
            {"chunk_id": "1-1-001", "evidence_quote": "Artificial intelligence supports data analysis."},
            {"chunk_id": "1-1-001", "evidence_quote": "Artificial intelligence supports data analysis."},
        ]
        with patch.object(generation, "_send_completion", return_value=json.dumps(generated_question)):
            result = generation.generate_single_question(
                topic="Lesson One",
                question_type="mcq",
                context_docs=[document],
            )
        self.assertEqual(len(result["source_refs"]), 1)
        self.assertEqual(result["source_refs"][0]["chunk_id"], "1-1-001")
        self.assertEqual(result["source_refs"][0]["evidence_quote"], document.page_content)
        self.assertEqual(result["rubric"], [{
            "criterion": "Correct selected answer",
            "points": 1,
            "description": "Correct option = 1 point; incorrect or unanswered = 0 points.",
        }])
        self.assertEqual(result["max_score"], 1)

    def test_generation_retries_when_model_quote_is_not_verbatim(self):
        document = sample_document()
        invalid_question = sample_question()
        invalid_question["source_refs"][0]["evidence_quote"] = "AI helps analyze useful data."
        valid_question = sample_question()
        with patch.object(
            generation,
            "_send_completion",
            side_effect=[json.dumps(invalid_question), json.dumps(valid_question)],
        ) as send_completion:
            result = generation.generate_single_question(
                topic="Lesson One",
                question_type="mcq",
                context_docs=[document],
            )

        self.assertEqual(len(result["source_refs"]), 1)
        self.assertEqual(result["source_refs"][0]["evidence_quote"], document.page_content)
        self.assertEqual(send_completion.call_count, 2)
        self.assertIn("verbatim quote", send_completion.call_args.args[0])

    def test_generation_rejects_quote_that_remains_nonverbatim_after_retry(self):
        invalid_question = sample_question()
        invalid_question["source_refs"][0]["evidence_quote"] = "AI helps analyze useful data."
        with (
            patch.object(generation, "_send_completion", return_value=json.dumps(invalid_question)) as send_completion,
            self.assertRaisesRegex(ValueError, "not present in its curriculum chunk"),
        ):
            generation.generate_single_question(
                topic="Lesson One",
                question_type="mcq",
                context_docs=[sample_document()],
            )

        self.assertEqual(send_completion.call_count, 2)

    def test_generation_retries_malformed_json_and_returns_valid_question(self):
        with patch.object(
            generation,
            "_send_completion",
            side_effect=["{\"question\": \"unfinished\"", json.dumps(sample_question())],
        ) as send_completion:
            result = generation.generate_single_question(
                topic="Lesson One",
                question_type="mcq",
                context_docs=[sample_document()],
            )

        self.assertEqual(result["question"], sample_question()["question"])
        self.assertEqual(send_completion.call_count, 2)
        self.assertIn("not valid JSON", send_completion.call_args.args[0])
        self.assertIn("complete JSON object", send_completion.call_args.args[0])

    def test_persistent_malformed_json_has_actionable_error(self):
        with (
            patch.object(generation, "_send_completion", return_value="{\"question\":"),
            self.assertRaisesRegex(
                ValueError,
                r"invalid JSON twice \(last error at line 1, column",
            ),
        ):
            generation.generate_single_question(
                topic="Lesson One",
                question_type="mcq",
                context_docs=[sample_document()],
            )

    def test_rejects_source_quote_not_present_in_retrieved_chunk(self):
        with self.assertRaisesRegex(ValueError, "not present in its curriculum chunk"):
            generation._canonicalize_source_refs(
                [{
                    "chunk_id": "1-1-001",
                    "evidence_quote": "This sentence is not in the book.",
                }],
                [sample_document()],
            )

    def test_exam_total_points_must_match_question_rubrics(self):
        with self.assertRaisesRegex(ValueError, "total_points"):
            generation.validate_exam({
                "lesson_id": "1-1",
                "difficulty": "medium",
                "bloom_level": "apply",
                "question_count": 1,
                "total_points": 5,
                "questions": [sample_question()],
            })

    def test_rejects_duplicate_mcq_options(self):
        question = sample_question()
        question["options"][3] = question["options"][0]
        with self.assertRaisesRegex(ValueError, "distinct"):
            generation._validate_question(question)

    def test_rejects_missing_explanation(self):
        question = sample_question()
        del question["explanation"]
        with self.assertRaisesRegex(ValueError, "Missing required fields"):
            generation._validate_question(question)

    def test_rejects_incomplete_rubric_items(self):
        question = sample_question()
        question["question_type"] = "short_answer"
        question["options"] = []
        question["correct_answer"] = ""
        question["rubric"][0]["points"] = 0
        with self.assertRaisesRegex(ValueError, "positive point value"):
            generation._validate_question(question)

    def test_configuration_error_does_not_include_secret(self):
        with (
            patch.object(generation, "LLM_PROVIDER", "gemini"),
            patch.object(generation, "GEMINI_API_KEY", None),
        ):
            with self.assertRaisesRegex(ValueError, "GEMINI_API_KEY"):
                generation._send_completion("test")

    def test_gemini_configuration_requires_an_api_key(self):
        with (
            patch.object(generation, "LLM_PROVIDER", "gemini"),
            patch.object(generation, "GEMINI_API_KEY", None),
            patch.object(generation, "LLM_MODEL_NAME", "gemini-2.5-flash-lite"),
        ):
            self.assertEqual(
                generation.validate_configuration(),
                (False, ["GEMINI_API_KEY"], "gemini-2.5-flash-lite"),
            )

    def test_gemini_completion_uses_json_mode_and_configured_model(self):
        client = unittest.mock.MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(text='{"ready":true}')
        with (
            patch.object(generation, "LLM_PROVIDER", "gemini"),
            patch.object(generation, "GEMINI_API_KEY", "test-api-key"),
            patch.object(generation, "LLM_MODEL_NAME", "gemini-2.5-flash-lite"),
            patch("google.genai.Client", return_value=client) as client_factory,
        ):
            result = generation._send_completion("Make a JSON object")

        self.assertEqual(result, '{"ready":true}')
        client_factory.assert_called_once_with(api_key="test-api-key")
        client.models.generate_content.assert_called_once()
        call = client.models.generate_content.call_args.kwargs
        self.assertEqual(call["model"], "gemini-2.5-flash-lite")
        self.assertEqual(call["contents"], "Make a JSON object")
        self.assertEqual(call["config"].response_mime_type, "application/json")
        self.assertEqual(call["config"].max_output_tokens, generation.MAX_COMPLETION_TOKENS)
        client.close.assert_called_once()

    def test_gemini_authentication_error_is_actionable(self):
        from google.genai.errors import APIError

        client = unittest.mock.MagicMock()
        client.models.generate_content.side_effect = APIError(
            code=403, response_json={"error": {"message": "permission denied"}}
        )
        with (
            patch.object(generation, "LLM_PROVIDER", "gemini"),
            patch.object(generation, "GEMINI_API_KEY", "test-api-key"),
            patch("google.genai.Client", return_value=client),
            self.assertRaisesRegex(ValueError, "authentication or permission failed"),
        ):
            generation._send_completion("test")

    def test_gemini_quota_error_is_actionable(self):
        from google.genai.errors import APIError

        client = unittest.mock.MagicMock()
        client.models.generate_content.side_effect = APIError(
            code=429, response_json={"error": {"message": "quota exceeded"}}
        )
        with (
            patch.object(generation, "LLM_PROVIDER", "gemini"),
            patch.object(generation, "GEMINI_API_KEY", "test-api-key"),
            patch("google.genai.Client", return_value=client),
            self.assertRaisesRegex(ValueError, "quota or rate limit exceeded"),
        ):
            generation._send_completion("test")

    def test_gemini_connection_check_makes_one_minimal_request(self):
        client = unittest.mock.MagicMock()
        client.models.generate_content.return_value = SimpleNamespace(text='{"status":"READY"}')
        with (
            patch.object(generation, "LLM_PROVIDER", "gemini"),
            patch.object(generation, "GEMINI_API_KEY", "test-api-key"),
            patch.object(generation, "LLM_MODEL_NAME", "gemini-2.5-flash-lite"),
            patch("google.genai.Client", return_value=client),
        ):
            result = generation.test_gemini_connection()

        self.assertEqual(result["content"], '{"status":"READY"}')
        client.models.generate_content.assert_called_once()
        call = client.models.generate_content.call_args.kwargs
        self.assertEqual(call["config"].max_output_tokens, 16)

    def test_gemini_empty_response_retries_with_larger_output_budget(self):
        client = unittest.mock.MagicMock()
        client.models.generate_content.side_effect = [
            SimpleNamespace(text=""),
            SimpleNamespace(text='{"status":"READY"}'),
        ]
        with (
            patch.object(generation, "LLM_PROVIDER", "gemini"),
            patch.object(generation, "GEMINI_API_KEY", "test-api-key"),
            patch("google.genai.Client", return_value=client),
        ):
            result = generation._send_completion("test", max_tokens=8)

        self.assertEqual(result, '{"status":"READY"}')
        self.assertEqual(client.models.generate_content.call_count, 2)
        configs = [call.kwargs["config"] for call in client.models.generate_content.call_args_list]
        self.assertEqual(configs[0].max_output_tokens, 8)
        self.assertEqual(configs[1].max_output_tokens, generation.RETRY_COMPLETION_TOKENS)
        client.close.assert_called_once()

    def test_gemini_api_error_does_not_expose_api_key(self):
        from google.genai.errors import APIError

        secret = "test-private-api-key"
        client = unittest.mock.MagicMock()
        client.models.generate_content.side_effect = APIError(
            code=418, response_json={"error": {"message": secret}}
        )
        with (
            patch.object(generation, "LLM_PROVIDER", "gemini"),
            patch.object(generation, "GEMINI_API_KEY", secret),
            patch("google.genai.Client", return_value=client),
            self.assertRaises(ValueError) as raised,
        ):
            generation._send_completion("test")
        self.assertNotIn(secret, str(raised.exception))

    def test_generation_saves_unique_validated_exams(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            with (
                patch.object(generation, "validate_configuration", return_value=(True, [], "test-model")),
                patch.object(generation, "retrieve_curriculum_context", return_value=[sample_document()]),
                patch.object(generation, "generate_single_question", side_effect=lambda **kwargs: sample_question()),
            ):
                _, first_path = generation.generate_exam(
                    "artificial intelligence", lesson_id="1-1", output_dir=output_dir
                )
                _, second_path = generation.generate_exam(
                    "artificial intelligence", lesson_id="1-1", output_dir=output_dir
                )
            self.assertNotEqual(first_path, second_path)
            self.assertEqual(len(list(output_dir.glob("*.json"))), 2)
            self.assertEqual(json.loads(first_path.read_text(encoding="utf-8"))["question_count"], 10)

    def test_default_type_mix_includes_open_ended_questions(self):
        sequence = generation._build_question_type_sequence(None, 10)
        self.assertEqual(
            {question_type: sequence.count(question_type) for question_type in generation.VALID_QUESTION_TYPES},
            {"mcq": 4, "short_answer": 3, "essay": 3},
        )

    def test_lists_unique_lessons_and_counts_their_chunks(self):
        records = {
            "metadatas": [
                {"lesson_id": "1-1", "lesson_title": "Lesson One", "chapter_id": 1, "chapter_title": "Chapter", "chunk_id": "1-1-001"},
                {"lesson_id": "1-1", "lesson_title": "Lesson One", "chapter_id": 1, "chapter_title": "Chapter", "chunk_id": "1-1-002"},
                {"lesson_id": "1-2", "lesson_title": "Lesson Two", "chapter_id": 1, "chapter_title": "Chapter", "chunk_id": "1-2-001"},
            ]
        }
        store = SimpleNamespace(
            _collection=SimpleNamespace(
                get=lambda include: records if include == ["metadatas"] else {}
            )
        )
        lessons = generation.list_curriculum_lessons(store)
        self.assertEqual(
            [(lesson["lesson_id"], lesson["lesson_title"], lesson["chunk_count"]) for lesson in lessons],
            [("1-1", "Lesson One", 2), ("1-2", "Lesson Two", 1)],
        )

    def test_lesson_exam_is_scoped_and_mixes_types(self):
        docs = [sample_document() for _ in range(4)]
        for document in docs:
            document.metadata["lesson_title"] = "Lesson One"

        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch.object(generation, "validate_configuration", return_value=(True, [], "test-model")),
                patch.object(generation, "generate_single_question", side_effect=question_for_type),
            ):
                exam, _ = generation.generate_exam(
                    topic="Lesson One",
                    number_of_questions=10,
                    lesson_id="1-1",
                    context_docs=docs,
                    output_dir=temporary_directory,
                )

        self.assertEqual(exam["lesson_id"], "1-1")
        self.assertEqual(exam["lesson_title"], "Lesson One")
        self.assertEqual(exam["question_count"], 10)
        self.assertEqual(exam["total_points"], 10)
        self.assertEqual(
            {kind: sum(q["question_type"] == kind for q in exam["questions"]) for kind in generation.VALID_QUESTION_TYPES},
            {"mcq": 4, "short_answer": 3, "essay": 3},
        )

    def test_lesson_exam_rejects_context_from_another_lesson(self):
        with (
            patch.object(generation, "validate_configuration", return_value=(True, [], "test-model")),
            self.assertRaisesRegex(ValueError, "outside the selected lesson"),
        ):
            generation.generate_exam(
                topic="Lesson One",
                number_of_questions=1,
                lesson_id="1-2",
                context_docs=[sample_document()],
            )

    def test_question_count_must_be_positive(self):
        with (
            patch.object(generation, "validate_configuration", return_value=(True, [], "test-model")),
            self.assertRaisesRegex(ValueError, "positive integer"),
        ):
            generation.generate_exam(
                topic="Lesson One",
                number_of_questions=0,
                lesson_id="1-1",
                context_docs=[sample_document()],
            )

    def test_generation_accepts_more_than_ten_questions(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch.object(generation, "validate_configuration", return_value=(True, [], "test-model")),
                patch.object(generation, "generate_single_question", side_effect=question_for_type),
            ):
                exam, _ = generation.generate_exam(
                    topic="Lesson One",
                    number_of_questions=11,
                    lesson_id="1-1",
                    context_docs=[sample_document()],
                    output_dir=temporary_directory,
                )

        self.assertEqual(exam["question_count"], 11)
        self.assertEqual(len(exam["questions"]), 11)

    def test_retrieval_passes_selected_lesson_filter(self):
        store = object()
        with (
            patch.object(generation, "load_curriculum_store", return_value=store),
            patch.object(generation, "retrieve", return_value=[sample_document()]) as retrieve_mock,
        ):
            generation.retrieve_curriculum_context("Lesson One", lesson_id="1-1")
        retrieve_mock.assert_called_once_with(store, query="Lesson One", k=8, lesson_id="1-1")

    def test_save_never_overwrites_an_existing_exam(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            fixed_random = b"\x00\x01\x02\x03"
            with patch.object(generation.os, "urandom", return_value=fixed_random):
                path = generation.save_exam(
                    {
                        "lesson_id": "1-1",
                        "difficulty": "medium",
                        "bloom_level": "apply",
                        "question_count": 1,
                        "total_points": 1,
                        "questions": [sample_question()],
                    },
                    output_dir,
                )
                original_content = path.read_text(encoding="utf-8")
                with self.assertRaises(FileExistsError):
                    generation.save_exam(
                        {
                            "lesson_id": "1-1",
                            "difficulty": "medium",
                            "bloom_level": "apply",
                            "question_count": 1,
                            "total_points": 1,
                            "questions": [sample_question()],
                        },
                        output_dir,
                    )
            self.assertEqual(path.read_text(encoding="utf-8"), original_content)

    def test_vector_store_helpers_preserve_existing_or_missing_collections(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            existing_client = SimpleNamespace(
                list_collections=lambda: [SimpleNamespace(name="preserved")]
            )
            with (
                patch("scripts.ingestion.chromadb.PersistentClient", return_value=existing_client),
                patch("scripts.ingestion.Chroma") as chroma_constructor,
                self.assertRaises(FileExistsError),
            ):
                build_vectorstore(
                    [],
                    embeddings=None,
                    persist_dir=temporary_directory,
                    collection_name="preserved",
                )
            chroma_constructor.assert_not_called()

            missing_client = SimpleNamespace(list_collections=lambda: [])
            with (
                patch("scripts.ingestion.chromadb.PersistentClient", return_value=missing_client),
                patch("scripts.ingestion.Chroma") as chroma_constructor,
                self.assertRaises(FileNotFoundError),
            ):
                load_vectorstore(
                    embeddings=None,
                    persist_dir=temporary_directory,
                    collection_name="missing",
                )
            chroma_constructor.assert_not_called()

    def test_loading_missing_store_does_not_create_a_directory(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            missing_path = Path(temporary_directory) / "missing"
            with (
                patch("scripts.ingestion.chromadb.PersistentClient") as client_constructor,
                self.assertRaises(FileNotFoundError),
            ):
                load_vectorstore(embeddings=None, persist_dir=missing_path)
            client_constructor.assert_not_called()
            self.assertFalse(missing_path.exists())


if __name__ == "__main__":
    unittest.main()
