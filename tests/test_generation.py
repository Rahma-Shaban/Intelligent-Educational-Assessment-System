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


def distinct_questions_for_type():
    call_count = 0

    def create(**kwargs):
        nonlocal call_count
        call_count += 1
        question = question_for_type(**kwargs)
        question["question"] = f"Explain concept {call_count} term{call_count}"
        return question

    return create


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

        question = sample_question()
        question["correct_answer"] = "2"
        question["reference_answer"] = "2: Unrelated option one"
        generation._validate_question(question)
        self.assertEqual(question["correct_answer"], "B")

    def test_rejects_invalid_mcq_answer_keys(self):
        for answer in ("", "BC", "5"):
            question = sample_question()
            question["correct_answer"] = answer
            with self.subTest(answer=answer), self.assertRaisesRegex(
                ValueError, "Correct answer must be one of"
            ):
                generation._validate_question(question)

    def test_duplicate_detection_uses_question_and_answer_tokens(self):
        original = {
            "question": "Which process transforms raw data into useful information?",
            "reference_answer": "Data analysis reveals patterns.",
        }
        near_duplicate = {
            "question": "Which process turns raw data into useful information?",
            "reference_answer": "Data analysis reveals patterns.",
        }
        different = {
            "question": "What are the three stages of a curriculum review?",
            "reference_answer": "Planning, review, and revision.",
        }

        self.assertTrue(generation._is_duplicate_question(near_duplicate, [original]))
        self.assertTrue(generation._is_duplicate_question(original, [original]))
        self.assertFalse(generation._is_duplicate_question(different, [original]))

    def test_prompt_requires_focus_chunk_and_has_consistent_mcq_grounding(self):
        prompt = generation._build_prompt(
            "mcq",
            "Lesson One",
            "medium",
            "apply",
            [sample_document()],
            focus_chunk_id="1-1-001",
        )

        self.assertIn(
            "The question MUST test the facts in the chunk with this chunk_id: 1-1-001.",
            prompt,
        )
        self.assertIn("The first listed context chunk is that chunk.", prompt)
        self.assertIn(generation.MCQ_GROUNDING_RULE, prompt)
        self.assertNotIn("less-obvious scenario", prompt)

    def test_invalid_source_references_are_rejected_without_sentence_fallback(self):
        for reference in (
            {"chunk_id": "1-1-001"},
            {"chunk_id": "1-1-001", "evidence_quote": "short"},
            {"chunk_id": "missing", "evidence_quote": "Artificial intelligence supports data analysis."},
        ):
            with self.subTest(reference=reference), self.assertRaises(
                generation.InvalidSourceRefError
            ):
                generation._canonicalize_source_refs([reference], [sample_document()])
        self.assertFalse(hasattr(generation, "_find_first_sentence"))

    def test_verbatim_quote_salvage_requires_eight_words_and_forty_characters(self):
        document = SimpleNamespace(
            page_content=(
                "Learning assessment frameworks can improve instructional decisions "
                "through careful curriculum planning and evidence-based decision making."
            ),
            metadata={"chunk_id": "1-1-001", "source": "curriculum.pdf"},
        )
        short_subquote = (
            "This unrelated wording contains learning assessment frameworks."
        )
        with self.assertRaisesRegex(
            generation.InvalidEvidenceQuoteError,
            "not present in its curriculum chunk",
        ):
            generation._canonicalize_source_refs(
                [{"chunk_id": "1-1-001", "evidence_quote": short_subquote}],
                [document],
            )
        canonical = generation._canonicalize_source_refs(
            [{
                "chunk_id": "1-1-001",
                "evidence_quote": (
                    "A learning assessment frameworks can improve instructional decisions "
                    "through careful curriculum planning and evidence-based decision making."
                ),
            }],
            [document],
        )
        self.assertEqual(
            canonical[0]["evidence_quote"],
            document.page_content,
        )

    def test_verifier_uses_only_question_options_and_context(self):
        question = sample_question()
        question["explanation"] = "Do not include this private explanation."
        with patch.object(
            generation,
            "_send_completion",
            return_value=json.dumps({"answer": "B", "supported": True}),
        ) as send_completion:
            self.assertFalse(generation._verify_mcq_answer(question, [sample_document()]))

        prompt = send_completion.call_args.args[0]
        self.assertNotIn(question["explanation"], prompt)
        self.assertNotIn("correct_answer", prompt)
        self.assertNotIn('"reference_answer"', prompt)
        self.assertEqual(send_completion.call_args.kwargs["temperature"], 0)

        with patch.object(
            generation,
            "_send_completion",
            return_value=json.dumps({"answer": "A", "supported": True}),
        ):
            self.assertTrue(generation._verify_mcq_answer(question, [sample_document()]))

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
        self.assertEqual(call["config"].temperature, generation.GENERATION_TEMPERATURE)
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

    def test_gemini_max_tokens_retries_with_larger_output_budget(self):
        client = unittest.mock.MagicMock()
        client.models.generate_content.side_effect = [
            SimpleNamespace(
                text="",
                candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")],
            ),
            SimpleNamespace(text='{"ready":true}', candidates=[]),
        ]
        with (
            patch.object(generation, "LLM_PROVIDER", "gemini"),
            patch.object(generation, "GEMINI_API_KEY", "test-api-key"),
            patch("google.genai.Client", return_value=client),
        ):
            response = generation._send_completion("test", max_tokens=8)

        self.assertEqual(response, '{"ready":true}')
        configs = [call.kwargs["config"] for call in client.models.generate_content.call_args_list]
        self.assertEqual(configs[0].max_output_tokens, 8)
        self.assertEqual(configs[1].max_output_tokens, generation.RETRY_COMPLETION_TOKENS)

    def test_ollama_receives_temperature_and_num_predict(self):
        fake_ollama = SimpleNamespace(
            ChatOllama=unittest.mock.MagicMock(
                return_value=SimpleNamespace(content=None, invoke=lambda prompt: SimpleNamespace(content='{"ready":true}'))
            )
        )
        with patch.dict("sys.modules", {"langchain_ollama": fake_ollama}):
            response = generation._send_ollama_completion("test", max_tokens=123)

        self.assertEqual(response, '{"ready":true}')
        call = fake_ollama.ChatOllama.call_args.kwargs
        self.assertEqual(call["temperature"], generation.GENERATION_TEMPERATURE)
        self.assertEqual(call["num_predict"], 123)

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

    def test_invalid_source_ref_is_retried_by_single_question_generation(self):
        invalid = sample_question()
        invalid["source_refs"][0]["chunk_id"] = "not-provided"
        valid = sample_question()
        with patch.object(
            generation,
            "_send_completion",
            side_effect=[json.dumps(invalid), json.dumps(valid)],
        ) as send_completion:
            generation.generate_single_question(
                topic="Lesson One",
                question_type="mcq",
                context_docs=[sample_document()],
            )

        self.assertEqual(send_completion.call_count, 2)
        self.assertIn("invalid source reference", send_completion.call_args.args[0])

    def test_focus_chunk_must_be_cited_and_is_retried(self):
        focus_doc = sample_document()
        other_doc = sample_document()
        other_doc.metadata["chunk_id"] = "1-1-002"
        invalid = sample_question()
        invalid["source_refs"][0]["chunk_id"] = "1-1-002"
        valid = sample_question()
        with patch.object(
            generation,
            "_send_completion",
            side_effect=[json.dumps(invalid), json.dumps(valid)],
        ) as send_completion:
            question = generation.generate_single_question(
                topic="Lesson One",
                question_type="mcq",
                context_docs=[focus_doc, other_doc],
                focus_chunk_id="1-1-001",
            )

        self.assertEqual(question["source_refs"][0]["chunk_id"], "1-1-001")
        self.assertEqual(send_completion.call_count, 2)
        self.assertIn("must cite its focus chunk", send_completion.call_args.args[0])

    def test_retrieval_caps_k_to_unique_available_lesson_chunks(self):
        metadatas = [
            {"chunk_id": "1-1-001"},
            {"chunk_id": "1-1-001"},
            {"chunk_id": "1-1-002"},
        ]
        store = SimpleNamespace(
            _collection=SimpleNamespace(
                get=lambda where, include: {"metadatas": metadatas}
            )
        )
        with (
            patch.object(generation, "load_curriculum_store", return_value=store),
            patch.object(generation, "retrieve", return_value=[sample_document()]) as retrieve_mock,
        ):
            generation.retrieve_curriculum_context(
                "Lesson One",
                lesson_id="1-1",
                k=20,
            )

        retrieve_mock.assert_called_once_with(store, query="Lesson One", k=2, lesson_id="1-1")

    def test_generate_exam_assigns_unique_focus_chunks(self):
        docs = []
        for index in range(4):
            doc = sample_document()
            doc.metadata["chunk_id"] = f"1-1-{index + 1:03d}"
            docs.append(doc)
        calls = []

        def create_question(**kwargs):
            calls.append(kwargs)
            question = question_for_type(**kwargs)
            question["question"] = f"Explain concept {len(calls)} term{len(calls)}"
            return question

        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch.object(generation, "validate_configuration", return_value=(True, [], "test-model")),
                patch.object(generation, "generate_single_question", side_effect=create_question),
            ):
                generation.generate_exam(
                    "Lesson One",
                    number_of_questions=4,
                    lesson_id="1-1",
                    context_docs=docs,
                    output_dir=temporary_directory,
                    verify_answers=False,
                )

        self.assertEqual(
            [call["focus_chunk_id"] for call in calls],
            ["1-1-001", "1-1-002", "1-1-003", "1-1-004"],
        )
        self.assertEqual(
            [call["context_docs"][0].metadata["chunk_id"] for call in calls],
            [call["focus_chunk_id"] for call in calls],
        )
        self.assertTrue(all(len(call["context_docs"]) <= 4 for call in calls))

    def test_generate_exam_retries_duplicate_with_correction_and_higher_temperature(self):
        call_count = 0

        def create_question(**kwargs):
            nonlocal call_count
            call_count += 1
            question = question_for_type(**kwargs)
            question["question"] = (
                "Explain curriculum principle alpha."
                if call_count < 3
                else "Compare the three stages used in curriculum planning."
            )
            return question

        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch.object(generation, "validate_configuration", return_value=(True, [], "test-model")),
                patch.object(generation, "generate_single_question", side_effect=create_question) as generate,
            ):
                exam, _ = generation.generate_exam(
                    "Lesson One",
                    question_types=["short_answer"],
                    number_of_questions=2,
                    lesson_id="1-1",
                    context_docs=[sample_document()],
                    output_dir=temporary_directory,
                    verify_answers=False,
                )

        self.assertEqual(exam["question_count"], 2)
        self.assertEqual(generate.call_count, 3)
        self.assertIn("Explain curriculum principle alpha.", generate.call_args.kwargs["correction_message"])
        self.assertEqual(generate.call_args.kwargs["temperature"], generation.GENERATION_TEMPERATURE + 0.2)

    def test_generate_exam_fails_after_three_attempts_or_skips_when_partial_allowed(self):
        def one_success_then_failures():
            call_count = 0

            def create_question(**kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    question = question_for_type(**kwargs)
                    question["question"] = "Describe the first distinct curriculum principle."
                    return question
                raise ValueError("invalid mock response")

            return create_question

        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch.object(generation, "validate_configuration", return_value=(True, [], "test-model")),
                patch.object(generation, "generate_single_question", side_effect=ValueError("invalid mock response")) as generate,
                self.assertRaisesRegex(ValueError, "Q01 failed after 3 attempts"),
            ):
                generation.generate_exam(
                    "Lesson One",
                    question_types=["short_answer"],
                    number_of_questions=1,
                    lesson_id="1-1",
                    context_docs=[sample_document()],
                    output_dir=temporary_directory,
                    verify_answers=False,
                )
            self.assertEqual(generate.call_count, 3)

            with (
                patch.object(generation, "validate_configuration", return_value=(True, [], "test-model")),
                patch.object(
                    generation,
                    "generate_single_question",
                    side_effect=one_success_then_failures(),
                ),
            ):
                exam, _ = generation.generate_exam(
                    "Lesson One",
                    question_types=["short_answer"],
                    number_of_questions=2,
                    lesson_id="1-1",
                    context_docs=[sample_document()],
                    output_dir=temporary_directory,
                    allow_partial=True,
                    verify_answers=False,
                )

        self.assertEqual(exam["question_count"], 1)
        self.assertEqual(exam["questions"][0]["question_id"], "Q01")
        self.assertTrue(any("Q02 was skipped" in warning for warning in exam["warnings"]))

    def test_provider_error_is_not_retried_by_question_loop(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch.object(generation, "validate_configuration", return_value=(True, [], "test-model")),
                patch.object(
                    generation,
                    "generate_single_question",
                    side_effect=generation.LLMProviderError("Gemini quota or rate limit exceeded"),
                ) as generate,
                self.assertRaisesRegex(generation.LLMProviderError, "quota or rate limit"),
            ):
                generation.generate_exam(
                    "Lesson One",
                    number_of_questions=1,
                    lesson_id="1-1",
                    context_docs=[sample_document()],
                    output_dir=temporary_directory,
                    verify_answers=False,
                )

        self.assertEqual(generate.call_count, 1)

    def test_failed_mcq_verification_retries_and_marks_accepted_question(self):
        first = sample_question()
        second = sample_question()
        second["question"] = "Which curriculum process supports evidence-based planning?"
        with tempfile.TemporaryDirectory() as temporary_directory:
            with (
                patch.object(generation, "validate_configuration", return_value=(True, [], "test-model")),
                patch.object(generation, "generate_single_question", side_effect=[first, second]) as generate,
                patch.object(generation, "_verify_mcq_answer", side_effect=[False, True]) as verify,
            ):
                exam, _ = generation.generate_exam(
                    "Lesson One",
                    question_types=["mcq"],
                    number_of_questions=1,
                    lesson_id="1-1",
                    context_docs=[sample_document()],
                    output_dir=temporary_directory,
                )

        self.assertEqual(generate.call_count, 2)
        self.assertEqual(verify.call_count, 2)
        self.assertTrue(exam["questions"][0]["verified"])

    def test_generation_saves_unique_validated_exams(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_dir = Path(temporary_directory)
            with (
                patch.object(generation, "validate_configuration", return_value=(True, [], "test-model")),
                patch.object(generation, "retrieve_curriculum_context", return_value=[sample_document()]),
                patch.object(generation, "generate_single_question", side_effect=distinct_questions_for_type()),
            ):
                _, first_path = generation.generate_exam(
                    "artificial intelligence", lesson_id="1-1", output_dir=output_dir,
                    verify_answers=False,
                )
                _, second_path = generation.generate_exam(
                    "artificial intelligence", lesson_id="1-1", output_dir=output_dir,
                    verify_answers=False,
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
                patch.object(generation, "generate_single_question", side_effect=distinct_questions_for_type()),
            ):
                exam, _ = generation.generate_exam(
                    topic="Lesson One",
                    number_of_questions=10,
                    lesson_id="1-1",
                    context_docs=docs,
                    output_dir=temporary_directory,
                    verify_answers=False,
                )

        self.assertEqual(exam["lesson_id"], "1-1")
        self.assertEqual(exam["lesson_title"], "Lesson One")
        self.assertEqual(exam["question_count"], 10)
        self.assertEqual(exam["total_points"], 10)
        self.assertEqual(
            {kind: sum(q["question_type"] == kind for q in exam["questions"]) for kind in generation.VALID_QUESTION_TYPES},
            {"mcq": 4, "short_answer": 3, "essay": 3},
        )
        self.assertEqual(len(exam["warnings"]), 1)
        self.assertIn("Only 1 unique curriculum chunks", exam["warnings"][0])

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
                patch.object(generation, "generate_single_question", side_effect=distinct_questions_for_type()),
            ):
                exam, _ = generation.generate_exam(
                    topic="Lesson One",
                    number_of_questions=11,
                    lesson_id="1-1",
                    context_docs=[sample_document()],
                    output_dir=temporary_directory,
                    verify_answers=False,
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
