# Intelligent Educational Assessment System

An AI-powered system that helps teachers generate curriculum-based exams, grade open-ended answers semantically, and give students clear feedback on their performance.

> **Status:** Production-Ready Graduation Project. All five core modules (Ingestion, RAG Generation, Semantic Grading, Unsupervised ML Analytics, and Interactive Role-Based Dashboards) are implemented, hardened, and verified end-to-end.

## Architecture

```mermaid
flowchart LR
    T([Professor]) -->|uploads PDF| M1["1. Curriculum Ingestion"]
    M1 --> VS[(Chroma Vector DB)]
    VS --> M2["2. Exam Generation (RAG)"]
    T -->|configures lesson, Bloom, types| M2
    M2 -->|publishes exam| S([Student])
    S -->|submits responses| M3["3. Semantic Grading"]
    M3 --> M4["4. Student Analytics (KMeans)"]
    M3 --> M5["5. Feedback & Dashboards"]
    M4 --> M5
    M5 --> S
    M5 --> T
```

## Modules

| # | Module | What it does | Status |
|---|---|---|---|
| 1 | Curriculum Ingestion | Extracts text from PDFs, splits into lessons and chunks, generates embeddings, indexes in Chroma DB (`data/processed/chroma_db`) | Implemented |
| 2 | Exam Generation | Generates questions, model answers, and rubrics grounded in curriculum context with verbatim source citations across Bloom's cognitive taxonomy | Implemented |
| 3 | Semantic Grading | Deterministic MCQ verification + LLM rubric-based criterion grading for open-ended answers with partial credit, strengths, and weaknesses | Implemented |
| 4 | Student Analytics | Unsupervised KMeans clustering (`outputs/student_cluster_pipeline.pkl`) grouping students into "Needs Intervention", "Proficient", and "Advanced" | Implemented |
| 5 | Feedback & Dashboards | Complete FastAPI REST API (`app/`) paired with modern React + Vite frontend (`frontend/`) featuring student and professor portals | Implemented |
| 6 | RAG Evaluation & Observability | Evaluates curriculum RAG with Ragas (4 metrics) and traces retrieval/generation execution paths in LangSmith | Implemented |

## Project Structure

```text
├── app/                  # FastAPI web application (routers, auth, database, schemas)
│   ├── routers/          # auth, curriculum, exam, attempt, analytics routers
│   ├── auth.py           # JWT bearer authentication and role-based access control
│   ├── database.py       # SQLAlchemy engine and session dependency
│   ├── models.py         # User, Curriculum, Exam, ExamAttempt, StudentCluster models
│   └── schemas.py        # Pydantic v2 validation schemas
├── frontend/             # Modern React + Vite frontend with Tailwind CSS
│   ├── src/pages/        # Student & Professor portals, exam taking, analytics dashboards
│   └── src/components/   # Reusable UI component library (Card, Badge, Button, Alert)
├── data/
│   ├── raw/              # Curriculum textbook PDFs
│   ├── processed/        # Chroma DB store (240 chunks across 14 ML lessons)
│   └── evaluation/       # Evaluation dataset (rag_test_set.json)
├── notebooks/            # Educational workflows (01_ingestion, 02_generation ... 06_rag_evaluation)
├── outputs/              # Benchmark comparisons, generated exams, evaluation results
│   └── evaluation/       # ragas_results.csv, ragas_summary.json, run_manifest.jsonl, plots
├── scripts/              # Core modules (config, ingestion, generation, grading, analytics, evaluation)
├── tests/                # Unit and integration test suite (including test_evaluation.py)
├── .env.example          # Environment configuration template
├── requirements.txt      # Python dependencies
└── README.md
```

## Getting Started

### 1. Backend Setup

```bash
git clone <repository-url>
cd Intelligent-Educational-Assessment-System

python -m venv .venv
# Windows: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env    # Windows: Copy-Item .env.example .env
```

### 2. Supported LLM Providers (`LLM_PROVIDER` in `.env`)

- **Groq (Recommended for fast inference):** Set `LLM_PROVIDER=groq`, `GROQ_API_KEY=your_key`. Default model: `openai/gpt-oss-20b` (or `openai/gpt-oss-120b`). Handled via direct `httpx` with exponential backoff on HTTP 429 rate limits and client throttling.
- **Gemini:** Set `LLM_PROVIDER=gemini`, `GEMINI_API_KEY=your_key`. Default active model: `gemini-2.5-flash`.
- **Ollama:** Set `LLM_PROVIDER=ollama`, `OLLAMA_BASE_URL=http://localhost:11434`. Default model: `llama3.2`.

Test LLM connectivity at any time:
```bash
python -c "from scripts.generation import test_llm_connection; print(test_llm_connection())"
```

### 3. Run the Backend API

```bash
python -m uvicorn app.main:app --reload --port 8000
```
Interactive API documentation available at `http://127.0.0.1:8000/docs`.

### 4. Run the React Frontend

```bash
cd frontend
npm install
npm run dev
```
Access the application at `http://localhost:5173`.

### 5. Running Tests & Benchmarks

Run the test suite:
```bash
python -m unittest discover -v
```

Run model latency and accuracy benchmarks:
```bash
python scripts/benchmark_models.py --models groq:openai/gpt-oss-20b groq:openai/gpt-oss-120b gemini:gemini-2.5-flash
```

Retrain the unsupervised clustering model:
```bash
python scripts/train_clusters.py
```

---

## 6. RAG Evaluation & Observability (Ragas + LangSmith)

Module 6 provides ground-truth curriculum evaluation and production observability.

### Purpose
- **Evaluates the actual RAG pipeline** against 30 expert-curated curriculum test cases in `data/evaluation/rag_test_set.json`.
- **Measures 4 core Ragas metrics**:
  1. **Context Precision**: Signal-to-noise ratio of retrieved chunks (did relevant chunks place at the top ranks?).
  2. **Context Recall**: Ground-truth coverage (did retrieved chunks contain all facts from the reference answer?).
  3. **Faithfulness**: Hallucination check (are claims in the generated response grounded in context?).
  4. **Answer Relevancy**: Query alignment (does the generated answer address the original question directly?).
- **Instruments full-stack tracing via LangSmith**: Captures hierarchical execution runs (`curriculum_retrieval` $\rightarrow$ `curriculum_generation` $\rightarrow$ `curriculum_rag_pipeline`), latencies, chunk IDs, and run IDs.

### Configuration (`.env`)
Add the following optional LangSmith variables:
```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=your_langsmith_api_key_here
LANGSMITH_PROJECT=educational-assessment
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```
*Note: If `LANGSMITH_TRACING=false` is set or API keys are missing, tracing is automatically disabled and the RAG pipeline continues operating normally without interruption.*

### Dataset Schema (`data/evaluation/rag_test_set.json`)
The dataset contains 30 curriculum questions with:
- `id`: Question identifier (e.g. `q01`).
- `question`: User query.
- `reference_answer`: Ground truth factual reference.
- `source_chapter`, `source_page`: Curriculum textbook source location.
- `question_type`, `expected_chunk_content`, `answerability`.

### Running Evaluation

1. **Run Unit Tests (Offline, No External API Calls Required):**
```bash
python -m unittest tests.test_evaluation -v
```

2. **Open the Evaluation Notebook:**
```bash
jupyter notebook notebooks/06_rag_evaluation.ipynb
# or: notebooks/0_6rag_evaluation.ipynb
```

3. **Smoke Test vs Full Evaluation:**
- In Section C of the notebook, `RUN_FULL_EVALUATION = False` runs a quick 3-question smoke test.
- Change `RUN_FULL_EVALUATION = True` to evaluate the entire 30-question dataset.

4. **Saved Artifacts (`outputs/evaluation/`):**
- `ragas_results.csv`: Per-question results table with latencies, chunk counts, and all 4 metric scores.
- `ragas_summary.json`: Aggregate metrics summary (mean scores, valid denominators, execution timestamp).
- `ragas_results.json`: Complete detailed records with per-case status.
- `run_manifest.jsonl`: Sanitized trace run log with trace URLs.
- `ragas_metrics_plot.png`: Aggregate metrics comparison bar chart and latency breakdown plot.

### Inspecting LangSmith Traces
1. Log in to [LangSmith](https://smith.langchain.com).
2. Select the `educational-assessment` project.
3. Inspect parent runs (`curriculum_rag_pipeline`) and drill down into child retrieval (`curriculum_retrieval`) and generation (`curriculum_generation`) steps to view latency waterfalls, chunk metadata, and token usage.

### Privacy & Security
- API keys and tokens are never printed or logged in notebook cells or output files.
- Traces and evaluation artifacts contain curriculum text and educational questions only; no student personally identifiable information (PII) is processed or sent externally.