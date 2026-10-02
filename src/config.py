"""Project paths and local configuration; no database initialization."""
import os
from pathlib import Path
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "templates"


def settings() -> dict:
    file_values = dotenv_values(ROOT / ".env")
    return {k: os.environ.get(k, file_values.get(k) or "") for k in ("OPENAI_API_KEY", "OPENAI_MODEL")}


def supabase_settings() -> dict:
    file_values = dotenv_values(ROOT / ".env")
    names = ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SECRET_KEY")
    return {k: (os.environ.get(k, file_values.get(k) or "")).strip() for k in names}
