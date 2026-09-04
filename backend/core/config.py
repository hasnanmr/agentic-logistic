"""Application configuration loaded from environment variables."""

import os

from dotenv import load_dotenv

load_dotenv()

# Auth is deliberately absent here. ``backend.api.auth`` reads APP_USERNAME and
# APP_PASSWORD from os.environ itself and returns 503 when either is unset, so
# a deployment that forgets them is locked rather than open. A constant with a
# fallback would hand any future caller a working credential pair and quietly
# undo that, so credentials are never mirrored into module state.

# LLM
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or "https://openrouter.ai/api/v1"
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL") or "openai/gpt-5.6-luna"

# Data
DATA_CSV_PATH = os.getenv("DATA_CSV_PATH", "mock_logistics_data.csv")
