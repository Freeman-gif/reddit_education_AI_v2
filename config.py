"""Configuration for Reddit AI-in-K12 education data collection."""

import os
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).parent
DATA_DIR = PROJECT_DIR / "data"
DB_PATH = DATA_DIR / "reddit_ai_k12.db"

# ── Reddit API (PRAW) ───────────────────────────────────────────────────────
# Create a "script" app at https://www.reddit.com/prefs/apps/
REDDIT_CLIENT_ID = os.environ.get("REDDIT_CLIENT_ID", "YOUR_CLIENT_ID")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "YOUR_CLIENT_SECRET")
REDDIT_USER_AGENT = "python:ai_k12_research:v1.0 (by /u/YOUR_USERNAME)"

# ── Subreddits ───────────────────────────────────────────────────────────────
SUBREDDITS = [
    "education",
    "edtech",
    "StudentTeaching",
    "Teachers",
    "teaching",
    "ELATeachers",
    "CSEducation",
    "ChatGPT",
    "matheducation",
    "ScienceTeachers",
    "historyteachers",
]

# ── Date Range ───────────────────────────────────────────────────────────────
DATE_START = "2023-01-01"
DATE_END = "2026-03-17"

# ── Search Queries (for Arctic Shift title search & PRAW search) ─────────────
SEARCH_QUERIES = [
    "AI in classroom",
    "AI in education",
    "AI in school",
    "AI in teaching",
    "AI lesson plan",
    "AI cheating",
    "AI detection",
    "AI grading",
    "AI homework",
    "AI tutoring",
    "AI writing",
    "ChatGPT school",
    "ChatGPT students",
    "ChatGPT teacher",
    "ChatGPT classroom",
    "GPT students",
    "generative AI education",
    "artificial intelligence school",
    "AI tools teaching",
    "AI policy school",
]

# ── Keyword Sets for Pre-Filter ──────────────────────────────────────────────
AI_TERMS = {
    "ai", "a.i.", "artificial intelligence", "chatgpt", "chat gpt", "gpt",
    "gpt-4", "gpt-3", "gpt4", "gpt3", "copilot", "gemini", "claude",
    "llm", "large language model", "generative ai", "genai", "gen ai",
    "openai", "open ai", "deepseek", "machine learning", "ml model",
    "neural network", "chatbot", "ai tutor", "ai tool", "ai-powered",
    "ai powered", "dall-e", "midjourney", "stable diffusion", "perplexity",
    "grammarly ai", "turnitin ai", "gptzero", "ai detector", "ai detection",
    "natural language processing", "nlp", "transformer model",
}

EDUCATION_TERMS = {
    "student", "students", "teacher", "teachers", "teaching", "classroom",
    "school", "schools", "lesson", "lessons", "homework", "grading",
    "grade", "grades", "k-12", "k12", "elementary", "middle school",
    "high school", "curriculum", "assignment", "assignments", "essay",
    "essays", "exam", "exams", "test", "education", "educator", "educators",
    "instruction", "instructional", "pedagogy", "academic", "academics",
    "cheating", "plagiarism", "integrity", "district", "principal",
    "superintendent", "ib", "ap class", "ap classes", "semester",
    "syllabus", "rubric", "tutoring", "learning", "lecture",
}

# ── Ollama (Frame Desktop) ──────────────────────────────────────────────────
OLLAMA_BASE_URL = "http://192.168.1.146:11434/v1"
OLLAMA_MODEL = "qwen3:32b"

# ── LLM Classification Categories ───────────────────────────────────────────
LLM_CATEGORIES = [
    "teacher_use",
    "student_cheating",
    "policy",
    "attitude",
    "ai_detection",
    "professional_development",
    "ai_tools",
    "personalized_learning",
    "general_discussion",
    "not_relevant",
]

# ── Rate Limiting ────────────────────────────────────────────────────────────
ARCTIC_SHIFT_DELAY = 1.0  # seconds between requests (volunteer infrastructure)
LLM_BATCH_SIZE = 5        # posts per LLM call
