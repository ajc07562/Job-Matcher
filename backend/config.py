import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

JOBS_FILE = DATA_DIR / "jobs.json"
SAMPLE_JOBS_FILE = DATA_DIR / "sample_jobs.json"
SKILLS_TAXONOMY_FILE = DATA_DIR / "skills_taxonomy.json"
DB_FILE = ROOT_DIR / "job_matcher.db"

# Session token signing secret. Falls back to a per-process random secret so the
# app runs out of the box; set SESSION_SECRET in .env for a persistent secret
# (required if you want sessions to survive a server restart).
SECRET_KEY = os.getenv("SESSION_SECRET", "").strip() or __import__("secrets").token_hex(32)
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days

# Hybrid ranking weights — see eval/evaluate.py for how these were chosen
WEIGHT_EMBEDDING = 0.6
WEIGHT_SKILL_OVERLAP = 0.3
WEIGHT_SENIORITY = 0.1

# Seniority levels, ordered low -> high, used for seniority-fit scoring
SENIORITY_LEVELS = ["intern", "entry", "mid", "senior", "staff", "principal"]
