"""
Configuration module for the Intelligent Educational Assessment System.
Defines project-level paths using pathlib and loads environment variables from .env.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Base project directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Data directories
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"

# Outputs directory
OUTPUTS_DIR = BASE_DIR / "outputs"

# Notebooks and Scripts directories
NOTEBOOKS_DIR = BASE_DIR / "notebooks"
SCRIPTS_DIR = BASE_DIR / "scripts"

# Load environment variables from the root .env file explicitly.
# Do not overwrite runtime-provided values; prefer the process environment.
ENV_FILE = (BASE_DIR / ".env").resolve()
if ENV_FILE.exists():
    load_dotenv(dotenv_path=str(ENV_FILE), override=False)

# Environment configurations
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# Dedicated Gemini model so Gemini still gets a valid model name when it is used as a
# fallback behind another primary provider (LLM_MODEL_NAME then holds a Groq/Ollama ID).
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash")

# Ollama configuration (for local LLM provider)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL_NAME = os.getenv("OLLAMA_MODEL_NAME", "llama3.2")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))

# Groq configuration (cloud LLM provider with free-tier limits)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_MODEL_NAME = os.getenv("GROQ_MODEL_NAME", "openai/gpt-oss-20b")
CHATBOT_MODEL_NAME = os.getenv("CHATBOT_MODEL_NAME", "openai/gpt-oss-120b")

# Free-tier optimization & rate limiting settings
LLM_MIN_INTERVAL_SECONDS = float(os.getenv("LLM_MIN_INTERVAL_SECONDS", "1.0"))
VERIFY_MCQ_ANSWERS = os.getenv("VERIFY_MCQ_ANSWERS", "false").strip().lower() in ("true", "1", "yes")
MAX_PER_QUESTION_RETRIES = int(os.getenv("MAX_PER_QUESTION_RETRIES", "3"))
_fallback_str = os.getenv("LLM_FALLBACK_PROVIDERS", "")
LLM_FALLBACK_PROVIDERS = [p.strip().lower() for p in _fallback_str.split(",") if p.strip()]

# Resolve active LLM model name based on provider
if LLM_PROVIDER == "ollama":
    env_model = os.getenv("LLM_MODEL_NAME")
    if env_model and not env_model.lower().startswith("gemini"):
        LLM_MODEL_NAME = env_model
    else:
        LLM_MODEL_NAME = OLLAMA_MODEL_NAME
elif LLM_PROVIDER == "groq":
    env_model = os.getenv("LLM_MODEL_NAME")
    if env_model and not env_model.lower().startswith("gemini") and not env_model.lower().startswith("llama3.2"):
        LLM_MODEL_NAME = env_model
    else:
        LLM_MODEL_NAME = GROQ_MODEL_NAME
else:
    env_model = os.getenv("LLM_MODEL_NAME")
    if env_model and env_model.lower().startswith("gemini"):
        LLM_MODEL_NAME = env_model
    else:
        LLM_MODEL_NAME = GEMINI_MODEL_NAME

# The retrieval pipeline uses local Hugging Face sentence-transformers embeddings,
# not the OpenAI-compatible embedding IDs used for an external API client.
HF_EMBEDDING_MODEL_NAME = os.getenv(
    "HF_EMBEDDING_MODEL_NAME",
    "sentence-transformers/all-MiniLM-L6-v2",
)

# Backward-compatible alias kept for older configs; retrieval should prefer the
# Hugging Face name above and not an OpenAI-style embedding ID.
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", HF_EMBEDDING_MODEL_NAME)
_default_vdb = str(PROCESSED_DATA_DIR / "chroma_db")
_vector_db_path = Path(os.getenv("VECTOR_DB_PATH", _default_vdb))
VECTOR_DB_PATH = (
    _vector_db_path if _vector_db_path.is_absolute() else BASE_DIR / _vector_db_path
).resolve()

# Graceful fallback: if configured path does not exist but processed/chroma_db does, reuse it
if not VECTOR_DB_PATH.exists() and (PROCESSED_DATA_DIR / "chroma_db").exists():
    VECTOR_DB_PATH = (PROCESSED_DATA_DIR / "chroma_db").resolve()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
