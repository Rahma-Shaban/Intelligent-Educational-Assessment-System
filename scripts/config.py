"""
Configuration module for the Intelligent Educational Assessment System.
Defines project-level paths using pathlib and loads environment variables from .env.
"""

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

# Environment configurations (loaded safely without hardcoded secrets)
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "gemini-2.5-flash-lite")

# The retrieval pipeline uses local Hugging Face sentence-transformers embeddings,
# not the OpenAI-compatible embedding IDs used for an external API client.
HF_EMBEDDING_MODEL_NAME = os.getenv(
    "HF_EMBEDDING_MODEL_NAME",
    "sentence-transformers/all-MiniLM-L6-v2",
)

# Backward-compatible alias kept for older configs; retrieval should prefer the
# Hugging Face name above and not an OpenAI-style embedding ID.
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", HF_EMBEDDING_MODEL_NAME)
_vector_db_path = Path(
    os.getenv("VECTOR_DB_PATH", str(PROCESSED_DATA_DIR / "curriculum_rag_store"))
)
VECTOR_DB_PATH = (
    _vector_db_path if _vector_db_path.is_absolute() else BASE_DIR / _vector_db_path
).resolve()
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Ollama configuration (for local LLM provider)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL_NAME = os.getenv("OLLAMA_MODEL_NAME", "llama3")
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
