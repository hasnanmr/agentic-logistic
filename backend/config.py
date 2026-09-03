"""Application configuration loaded from environment variables."""

import os

from dotenv import load_dotenv

load_dotenv()

# Auth
APP_USERNAME = os.getenv("APP_USERNAME", "reviewer")
APP_PASSWORD = os.getenv("APP_PASSWORD", "change-me")
SESSION_SECRET = os.getenv("SESSION_SECRET", "replace-with-a-random-secret")

# LLM
LLM_BASE_URL = os.getenv("LLM_BASE_URL")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-5.6-luna")

# Data
DATA_CSV_PATH = os.getenv("DATA_CSV_PATH", "mock_logistics_data.csv")
