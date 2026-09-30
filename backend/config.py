"""Settings loaded from the .env file in the project root."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# Smart model: planning, comparing, writing. Fast model: reading each source.
MODEL_SMART = os.getenv("MODEL_SMART", "gemini-3.8-flash")
MODEL_FAST = os.getenv("MODEL_FAST", "gemini-3.5-flash-lite")

# Free-tier pacing
GEMINI_RPM = int(os.getenv("GEMINI_RPM", "8"))                  # requests/minute per model
GEMINI_CONCURRENCY = int(os.getenv("GEMINI_CONCURRENCY", "2"))  # requests in flight

FRONTEND_DIR = ROOT / "frontend"
MAX_CHARS_PER_SOURCE = 12_000  # roughly 3k tokens of page text per source

# How much research each depth setting does
DEPTHS = {
    "quick":    {"queries": 3, "per_query": 4, "max_sources": 5},
    "standard": {"queries": 5, "per_query": 5, "max_sources": 8},
    "deep":     {"queries": 7, "per_query": 6, "max_sources": 12},
}
