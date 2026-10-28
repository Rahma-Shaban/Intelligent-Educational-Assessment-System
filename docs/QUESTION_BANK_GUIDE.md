# Question Bank Architecture & Operations Guide

## Overview

The **Question Bank System** provides a safe, grounded, and intelligent assessment repository for the Intelligent Educational Assessment System. It bridges curriculum materials and teacher review, enabling multi-source question ingestion, curriculum grounding via Chroma vector retrieval, psychometric classification (Bloom's Taxonomy and cognitive difficulty), an interactive professor review interface, and safe incremental learning from teacher-approved classifications.

---

## 1. System Architecture & Ingestion Pipeline

The Question Bank operates in four decoupled stages:

```
[Question Source]
  ├── PDF / DOCX / XLSX / CSV / JSON
  └── Manual Entry
         │
         ▼
[Stage 1: Ingestion & Validation] (scripts/question_processing.py)
  ├── Extract question stem, options (A-D), model answer, explanation
  ├── Filter prohibited distractors ("all of the above", "both a and b")
  ├── Check option count & duplicate distractors
  └── Exact & normalized duplicate detection
         │
         ▼
[Stage 2: Evidence Retrieval & Grounding] (scripts/curriculum_mapping.py & question_bank_service.py)
  ├── Sentence-Transformers embeddings (all-MiniLM-L6-v2)
  ├── Top-k retrieval against Chroma collection ("curriculum" or professor collection)
  ├── Real Chunk ID validation (e.g. "1-1-001", "1-1-002")
  └── In-context learning: similar teacher-approved exemplar retrieval (leakage-safe)
         │
         ▼
[Stage 3: Psychometric Inference & Confidence] (scripts/question_analysis.py)
  ├── Bloom's Revised Taxonomy (Remember, Understand, Apply, Analyze, Evaluate, Create)
  ├── Cognitive Difficulty (Easy, Medium, Hard, Unknown) evaluated independently
  ├── Grounding validation: hallucinated chunk IDs are strictly stripped
  └── Composite heuristic confidence calculation (retrieval similarity + LLM score + grounding)
         │
         ▼
[Stage 4: Persistence & Isolated Chroma Sync] (scripts/question_bank_service.py)
  ├── SQLite table: `question_bank_items`
  ├── Dedicated Chroma collection: `question_bank` (isolated from `curriculum`)
  └── Review status: `pending_review` | `needs_review` | `approved` | `rejected`
```

---

## 2. Configuration & Providers

### A. LLM Provider (`.env` or environment variables)
- `LLM_PROVIDER`: `"gemini"` (default), `"groq"`, or `"ollama"`.
- `GEMINI_MODEL_NAME`: e.g. `"gemini-2.5-flash"` or `"gemini-1.5-flash"`.
- `GROQ_MODEL_NAME`: e.g. `"openai/gpt-oss-20b"`.
- `OLLAMA_BASE_URL`: e.g. `"http://localhost:11434"`.
- `LLM_FALLBACK_PROVIDERS`: comma-separated fallback chain, e.g. `"groq,ollama"`.

### B. Embedding & Vector Database
- Local HuggingFace sentence transformer: `sentence-transformers/all-MiniLM-L6-v2`.
- `VECTOR_DB_PATH`: points to the persistent Chroma directory (e.g., `data/processed/curriculum_rag_store`).
- Collections:
  - `curriculum`: read-only curriculum text chunks ingested from official textbooks.
  - `question_bank`: dedicated collection storing question embeddings (`"<stem> [OPTIONS: ...] [ANSWER: ...]"`). Never mutates or overwrites `curriculum`.

---

## 3. Curriculum Evidence & Grounding Rules

1. **Strict Evidence Requirement**: The LLM must derive `subject`, `unit`, `lesson`, and `page_number` solely from retrieved chunks.
2. **Chunk ID Citation Verification**: Every returned `supporting_chunk_ids` entry is verified against the actual retrieved chunks. Hallucinated or invented chunk IDs are discarded before persistence.
3. **Missing or Low-Relevance Evidence**:
   - If no relevant chunks are found or top similarity is below threshold, curriculum fields are set to `"Unknown"` or `null`.
   - The question is automatically assigned `classification_status = "needs_review"`.
   - Explicit `review_reasons` are recorded (e.g., `"No supporting curriculum chunks retrieved for question."`).

---

## 4. Confidence Calculation & `needs_review` Lifecycle

Confidence is explicitly documented as a **calibrated heuristic score** rather than an uncalibrated LLM probability.

$$\text{Confidence} = 0.45 \times \text{RetrievalSimilarity} + 0.35 \times \text{LLMConfidence} + 0.20 \times \text{GroundingFactor}$$

Where:
- $\text{RetrievalSimilarity} \in [0.0, 1.0]$: normalized cosine similarity from Chroma.
- $\text{LLMConfidence} \in [0.0, 1.0]$: model self-assessed confidence.
- $\text{GroundingFactor}$: $1.0$ if verifiable supporting chunks exist; $0.40$ if ungrounded.

### Status Assignment:
- `pending_review`: Evidence is grounded and composite confidence $\ge 0.70$. Ready for instructor review.
- `needs_review`: Flagged for instructor attention if confidence $< 0.70$, ingestion warnings exist, or curriculum evidence is insufficient.
- `approved`: Formally approved by an instructor. Final label recorded with reviewer identity, timestamp, and corrections diff.
- `rejected`: Explicitly rejected with instructor rationale.

---

## 5. Teacher Review & Incremental Learning

### How the System Learns from Approvals (Safe In-Context Learning):
1. **Teacher Corrections Diff**: When an instructor edits Bloom level, difficulty, lesson, or answers and approves a question, the full diff is persisted in `teacher_corrections_json`.
2. **Exemplar Retrieval**: During future classifications, `retrieve_approved_exemplars()` retrieves top similar **approved** questions (`classification_status == "approved"`).
3. **Zero Data Leakage**: Exemplar search excludes the active question ID so that an item can never retrieve its own record during evaluation.
4. **No Untested Model Retraining**: Storing examples is never falsely described as "training a model". LLM in-context few-shot guidance provides immediate improvement without dangerous weight mutations.

### Supervised Classifier (`scripts/train_question_classifier.py`):
- Standalone, versioned training pipeline (`MODEL_VERSION = "v1.0.0"`).
- **Threshold**: Requires at least $100$ approved questions overall and $\ge 25$ approved questions per difficulty/Bloom class.
- When samples are below threshold, it reports class frequencies and maintains RAG/LLM as the active method.
- When ready: performs train/test split, trains a TF-IDF + Classifier pipeline, measures precision, recall, macro-F1, and confusion matrix, and saves artifacts in `outputs/question_bank_models/` separately from application code.

---

## 6. Question Bank REST API

All endpoints enforce authentication and professor role restrictions (`role == 'professor'`). Students are strictly forbidden.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/question-bank/import` | Upload file (PDF, DOCX, XLSX, CSV, JSON) with validation & staging |
| `POST` | `/api/question-bank/classify` | On-demand RAG classification for manual questions (with optional persist) |
| `GET` | `/api/question-bank` | List/search questions with filters (status, difficulty, bloom, lesson) & pagination |
| `GET` | `/api/question-bank/summary` | Statistics: counts by status, difficulty distribution, bloom distribution |
| `GET` | `/api/question-bank/learning-stats` | Approved dataset metrics and supervised classifier training readiness |
| `GET` | `/api/question-bank/{question_id}` | Detailed question entity, supporting chunks, citations, and corrections |
| `PATCH`| `/api/question-bank/{question_id}` | Instructor edits (invalidates/refreshes Chroma embedding on stem/option change) |
| `POST` | `/api/question-bank/{question_id}/approve` | Approve question, save corrections diff and reviewer identity |
| `POST` | `/api/question-bank/{question_id}/reject` | Reject question with feedback notes |
| `POST` | `/api/question-bank/reconcile-embeddings` | Reconcile pending or failed Chroma vector embeddings |

---

## 7. Supported & Unsupported File Formats

- **Supported Formats**:
  - `PDF`: Parsed via `pymupdf` (`fitz`) or `pypdf`. Extracts numbered question stems, options A-D, answers, and explanations.
  - `DOCX`: Parsed via `python-docx` or standard XML element tree (`word/document.xml`).
  - `XLSX / XLS`: Excel spreadsheet (looks for standard question columns or `All_Questions` sheet).
  - `CSV`: Comma-separated question records.
  - `JSON`: Single question or array of question objects.
- **Unsupported Formats**:
  - Binary executables, images, PPTX, or unformatted text without recognizable question structure.
  - Uploading unsupported formats returns HTTP 400 with a user-friendly error listing supported formats.

---

## 8. Verification & Running Tests

```bash
# Run question bank persistence & embedding tests (57 tests)
python -m pytest tests/test_question_bank.py -v

# Run Question Bank API, auth & classification tests (13 tests)
python -m pytest tests/test_question_bank_api.py -v

# Run full question processing, analysis, and curriculum mapping test suite
python -m pytest tests/test_question_processing.py tests/test_question_analysis.py tests/test_curriculum_mapping.py -v

# Inspect learning dataset readiness
python scripts/train_question_classifier.py --inspect-only
```

