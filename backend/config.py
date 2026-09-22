# backend/config.py — Centralized Configuration & Environment Settings
import os
import sys
import secrets
import logging
from pathlib import Path
from typing import Any

# Base paths
BACKEND_DIR = Path(__file__).resolve().parent
BASE_DIR = BACKEND_DIR.parent
FRONTEND_DIR = BASE_DIR / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"


def _load_env():
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env()

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Data directories
UPLOAD_FOLDER = BASE_DIR / "uploads"
VECTOR_FOLDER = BASE_DIR / "vectorstore"
TRACE_LOG_PATH = os.environ.get("TRACE_LOG_PATH", str(BASE_DIR / "traces" / "traces.jsonl"))
ORPHAN_LOG_PATH = Path(os.environ.get("ORPHAN_LOG_PATH", str(BASE_DIR / "vectorstore" / "orphaned_docs.jsonl")))

UPLOAD_FOLDER.mkdir(exist_ok=True)
VECTOR_FOLDER.mkdir(exist_ok=True)
Path(TRACE_LOG_PATH).parent.mkdir(exist_ok=True)
Path(ORPHAN_LOG_PATH).parent.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {"pdf", "txt", "md"}

# Backend selectors
EMBED_BACKEND = os.environ.get("EMBED_BACKEND", "ollama").lower()
VISION_BACKEND = os.environ.get("VISION_BACKEND", "ollama").lower()
CHAT_BACKEND = os.environ.get("CHAT_BACKEND", "ollama").lower()
VECTOR_BACKEND = os.environ.get("VECTOR_BACKEND", "memory")

# Local Ollama configuration
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "llava")
OLLAMA_CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "llama3.1:8b")

# Google Gemini configuration
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"
EMBED_MODEL = os.environ.get("EMBED_MODEL", "gemini-embedding-001")
GEMINI_VISION_MODEL = os.environ.get("GEMINI_VISION_MODEL", "gemini-3.7-flash")

# xAI Grok configuration
XAI_API_KEY = os.environ.get("XAI_API_KEY", "")
XAI_URL = os.environ.get("XAI_URL", "https://api.x.ai/v1")
XAI_MODEL = os.environ.get("XAI_MODEL", "grok-4.3")
LLM_MODEL = OLLAMA_CHAT_MODEL if CHAT_BACKEND == "ollama" else XAI_MODEL

# Qdrant configuration
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY") or None
QDRANT_TIMEOUT = float(os.environ.get("QDRANT_TIMEOUT", "10"))
QDRANT_CANDIDATE_POOL = int(os.environ.get("QDRANT_CANDIDATE_POOL", "30"))
QDRANT_SCROLL_LIMIT = int(os.environ.get("QDRANT_SCROLL_LIMIT", "5000"))

# Retrieval hyperparameters
EMBED_MIN_SCORE = float(os.environ.get("EMBED_MIN_SCORE", "0.55"))
SAFETY_MIN_SCORE = float(os.environ.get("SAFETY_MIN_SCORE", "0.40"))
TFIDF_MIN_SCORE = float(os.environ.get("TFIDF_MIN_SCORE", "0.15"))
RETRIEVAL_MODE = os.environ.get("RETRIEVAL_MODE", "hybrid")
HYBRID_ALPHA = float(os.environ.get("HYBRID_ALPHA", "0.6"))
RRF_K = int(os.environ.get("RRF_K", "10"))
BM25_K1 = float(os.environ.get("BM25_K1", "1.5"))
BM25_B = float(os.environ.get("BM25_B", "0.75"))
TOP_K = int(os.environ.get("TOP_K", "5"))
MAX_CONTEXT_TOKENS = int(os.environ.get("MAX_CONTEXT_TOKENS", "6000"))
DEFAULT_CHUNK_MODE = os.environ.get("DEFAULT_CHUNK_MODE", "structured")
DEFAULT_CHUNK_SIZE = int(os.environ.get("DEFAULT_CHUNK_SIZE", "512"))
EMBED_BATCH = int(os.environ.get("EMBED_BATCH", "32"))

# Reranking & Query Rewriting
RERANK_ENABLED = os.environ.get("RERANK_ENABLED", "false").lower() in ("1", "true", "yes")
RERANK_TOP_N = int(os.environ.get("RERANK_TOP_N", "8"))
RERANK_MIN_RELEVANCE = float(os.environ.get("RERANK_MIN_RELEVANCE", "5"))
QUERY_REWRITE_ENABLED = os.environ.get("QUERY_REWRITE_ENABLED", "false").lower() in ("1", "true", "yes")

# Security and Server settings
MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50 MB
SESSION_COOKIE_MAX_AGE = 14 * 24 * 60 * 60  # 14 days
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "").lower() in ("1", "true", "yes")
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")
PORT = int(os.environ.get("PORT", 5000))
HOST = os.environ.get("HOST", "127.0.0.1")
APP_DEBUG = os.environ.get("APP_DEBUG", "").lower() in ("1", "true", "yes")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Logging setup
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)-7s [%(name)s:%(filename)s:%(lineno)d] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ask_my_docs")

# Session secret key
_raw_secret = os.environ.get("SECRET_KEY", "").strip()
_is_prod = os.environ.get("APP_ENV", os.environ.get("ENV", "")).lower() == "production"

if _raw_secret:
    SECRET_KEY = _raw_secret
elif _is_prod:
    logger.critical("SECRET_KEY is required in production! Aborting startup.")
    raise SystemExit("CRITICAL: SECRET_KEY environment variable is missing in production.")
else:
    SECRET_KEY = secrets.token_hex(32)
    logger.warning("SECRET_KEY not set — using ephemeral per-process key.")


def get_app_symbol(name: str, default: Any = None) -> Any:
    """Dynamically resolve symbol from app facade if imported/mocked, else return default."""
    app_mod = sys.modules.get("app")
    if app_mod is not None and hasattr(app_mod, name):
        return getattr(app_mod, name)
    return default

