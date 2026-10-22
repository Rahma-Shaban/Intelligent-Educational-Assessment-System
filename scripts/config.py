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

# Load environment variables from .env file at project root
ENV_FILE = BASE_DIR / ".env"
load_dotenv(dotenv_path=ENV_FILE)

# Environment configurations (loaded safely without hardcoded secrets)
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "gpt-4o-mini")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "text-embedding-3-small")
VECTOR_DB_PATH = os.getenv("VECTOR_DB_PATH", str(PROCESSED_DATA_DIR / "chroma_db"))
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
