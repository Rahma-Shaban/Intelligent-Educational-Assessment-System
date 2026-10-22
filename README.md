# Intelligent Educational Assessment System

An AI-powered system that helps teachers generate curriculum-based exams, grade open-ended answers semantically, and give students clear feedback on their performance.

> **Status:** In development. Only the project skeleton exists so far; all modules are planned.

## Architecture

```mermaid
flowchart LR
    T([Teacher]) -->|uploads PDF| M1["1. Curriculum Ingestion"]
    M1 --> VS[(Vector Store)]
    VS --> M2["2. Exam Generation (RAG)"]
    T -->|picks lesson, difficulty| M2
    M2 -->|teacher approves| S([Student])
    S -->|answers| M3["3. Semantic Grading"]
    M3 --> M4["4. Student Analytics"]
    M3 --> M5["5. Feedback & Dashboard"]
    M4 --> M5
    M5 --> S
    M5 --> T
```

## Modules

| # | Module | What it does | Status |
|---|---|---|---|
| 1 | Curriculum Ingestion | Extracts text from PDFs, splits it into lessons and chunks, indexes it | Planned |
| 2 | Exam Generation | Generates questions, model answers, and rubrics grounded in the curriculum | Planned |
| 3 | Essay Grading | Grades answers by meaning against rubrics, with partial credit | Planned |
| 4 | Student Analytics | Predicts at-risk students and groups students by proficiency | Planned |
| 5 | Feedback & Dashboard | Student reports and a teacher dashboard | Planned |

## Project Structure

```text
├── data/
│   ├── raw/          # original PDFs and datasets
│   └── processed/    # cleaned and chunked data
├── outputs/          # generated exams, results, reports
├── scripts/          # reusable Python code (one file per module + config.py)
├── notebooks/        # experiments (one notebook per module)
├── .env.example
├── requirements.txt
└── README.md
```

## Getting Started

```bash
git clone <repository-url>
cd Intelligent-Educational-Assessment-System

python -m venv venv
# Windows: .\venv\Scripts\Activate.ps1
# macOS/Linux: source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env    # Windows: Copy-Item .env.example .env
```

Then add your own keys to `.env` (never commit this file) and run `jupyter notebook`.

## Workflow

We work notebook-first: experiment in `notebooks/`, then move stable code into `scripts/` and import it back into the notebooks.