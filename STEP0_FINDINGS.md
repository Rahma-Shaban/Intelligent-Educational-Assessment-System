# Step 0: Exam Generation Diagnosis

Line numbers below refer to the pre-change Step 0 snapshot.

## Retrieval behavior

`scripts/ingestion.py:462-487` calls `store.similarity_search(query=query, k=k, filter=filter_dict)`. It does not de-duplicate results, use MMR, or apply a score threshold. Chroma may return fewer than `k` matches when fewer eligible chunks are available. `lesson_id` is converted to a string and applied as an exact metadata equality filter; if both chapter and lesson are supplied, the filters are combined with `$and`.

## UI generation path

- The UI is `frontend/src/pages/professor/GenerateExam.jsx`.
- Its numeric input allows 1–20 questions (`GenerateExam.jsx:245-252`); there is no additional count cap in its submit handler (`:82-108`).
- The handler sends `num_questions` (`:103`), but `app/schemas.py:89-103` defines `number_of_questions` with a default of 5. The endpoint reads `payload.number_of_questions` (`app/routers/exam_router.py:46-62`). As a result, the requested count is ignored by request validation and the backend receives 5.
- The UI does not retrieve context itself. It calls `generateExam` (`frontend/src/api/client.js:79-81`), which posts to `/exams/generate`; `app/routers/exam_router.py:56-63` calls `generate_exam`, and `scripts/generation.py:923-931` retrieves for the topic with `k=8` and the selected lesson filter.
- The UI makes one API call, not a loop over `generate_single_question`. The backend generator loops over questions (`scripts/generation.py:948-962`).
- Generation errors are caught by the UI and shown in its error alert (`GenerateExam.jsx:109-119`); the API converts generation exceptions to HTTP errors with details (`app/routers/exam_router.py:64-77`). It does not intentionally turn failures into a successful partial list.
- No generation-result cache/session reuse was found in this path. The UI renders all received questions with `generatedExam.questions.map` (`GenerateExam.jsx:364`) and does not slice or paginate that list.
- The API limit is 25 (`app/schemas.py:103`), so the UI's 20-question limit is lower than the backend's accepted maximum.

## Why the report was “5 distinct out of 20”

The count mismatch deterministically explains why a request for 20 reaches the generator as 5. Repetition is a separate issue: `generate_exam` gives every question the same retrieved documents (`scripts/generation.py:948-957`), and provider calls use temperature 0 (`scripts/generation.py:474`, `:545`). Existing duplicate avoidance only sends prior question strings (`:948-962`) and does not detect duplicates itself. These conditions can produce near-identical questions within the five the backend actually generated.

The notebook is a separate caller, not the failing UI path. It currently retrieves once with `RETRIEVAL_COUNT = 8` (`notebooks/02_exam_generation.ipynb`, source cell 6), passes those `context_docs` to `generate_exam` (source cell 10), and requests one question in its current configuration.

## Mock reproduction and baseline

A direct API-route mock could not be run before changes because the active `.venv` is missing FastAPI. A request-schema import also encounters the missing `email-validator` dependency. The static field/default/endpoint trace above identifies the exact conversion to 5; no live Gemini or Ollama request was made.

Baseline `python -m unittest discover -v`: 58 tests ran; the suite ended with one import error because `tests.test_api_endpoints` could not import the missing `fastapi` package. Baseline `python -m pytest` could not start because `pytest` is not installed. No source changes had been made when these commands ran.
