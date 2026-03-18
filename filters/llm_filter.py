"""LLM relevance classification using Qwen3-32B via Ollama on Frame Desktop."""

import json
import time
from openai import OpenAI

from config import OLLAMA_BASE_URL, OLLAMA_MODEL, LLM_BATCH_SIZE, LLM_CATEGORIES
from db import db_session, get_keyword_matched_unclassified, upsert_classification


client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")

SYSTEM_PROMPT = """You are a research assistant classifying Reddit posts for a study on AI in K-12 education.

For each post, determine if it is relevant to how AI/LLMs are discussed in K-12 education contexts (teachers, students, schools, classrooms, curriculum, etc.).

Classify each post and return a JSON array with one object per post:
```json
[
  {
    "post_id": "abc123",
    "relevant": true,
    "confidence": 0.85,
    "category": "student_cheating",
    "tags": ["ChatGPT", "essay_writing", "academic_integrity", "high_school"],
    "summary": "A high school English teacher reports widespread ChatGPT use on essay assignments and asks how other teachers are handling detection and policy changes.",
    "reasoning": "Teacher discusses students using ChatGPT on essays"
  }
]
```

Category (pick the single best fit):
- teacher_use: Teachers using AI tools in their practice
- student_cheating: Students using AI to cheat / academic integrity
- policy: School/district AI policies
- attitude: Opinions/attitudes about AI in education
- ai_detection: AI detection tools (Turnitin, GPTZero, etc.)
- professional_development: Teacher training on AI
- ai_tools: Specific AI tools for education
- personalized_learning: AI for differentiated/personalized instruction
- general_discussion: General AI + education discussion
- not_relevant: Not about AI in K-12 education

Tags: assign 2-6 descriptive tags from these dimensions:
- AI tool mentioned (ChatGPT, Gemini, Copilot, GPTZero, Turnitin, etc.)
- Grade level (elementary, middle_school, high_school, k12_general)
- Subject area (english, math, science, history, cs, art, etc.)
- Theme (academic_integrity, lesson_planning, grading, writing, assessment, equity, parent_concern, admin_policy, etc.)

Summary: 1-2 sentences capturing the post's key point and context. Be specific.

Rules:
- Higher education only (college/university) without K-12 relevance → not_relevant
- Must involve AI/LLM technology, not just "technology in education" broadly → not_relevant if no AI
- confidence: 0.0-1.0 reflecting how certain you are
- Return ONLY the JSON array, no other text. Do NOT wrap in markdown code blocks."""


def _build_user_prompt(posts: list[dict]) -> str:
    parts = []
    for p in posts:
        body = (p["selftext"] or "")[:1500]  # truncate long posts
        parts.append(
            f"--- Post ID: {p['id']} | r/{p['subreddit']} ---\n"
            f"Title: {p['title']}\n"
            f"Body: {body}\n"
        )
    return "\n".join(parts) + "\n\n/no_think"


def _parse_response(text: str, post_ids: list[str]) -> list[dict]:
    """Parse LLM JSON response. Returns list of classification dicts."""
    # Strip markdown code fences if present
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()

    results = json.loads(text)
    if isinstance(results, dict):
        results = [results]
    return results


def _default_result(post_id: str, reason: str = "Missing from LLM response") -> dict:
    return {
        "post_id": post_id,
        "relevant": False,
        "confidence": 0.0,
        "category": "not_relevant",
        "tags": [],
        "summary": "",
        "reasoning": reason,
    }


def _classify_batch(posts: list[dict]) -> list[dict]:
    """Send a batch of posts to the LLM for classification."""
    user_prompt = _build_user_prompt(posts)
    post_ids = [p["id"] for p in posts]

    resp = client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=4096,
    )

    text = resp.choices[0].message.content
    # Handle Qwen3 thinking tags
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()

    try:
        return _parse_response(text, post_ids)
    except (json.JSONDecodeError, KeyError, IndexError):
        # Retry with single posts on parse failure
        results = []
        for post in posts:
            try:
                single = _classify_single(post)
                results.append(single)
            except Exception:
                results.append(_default_result(post["id"], "LLM parse error — skipped"))
        return results


def _classify_single(post: dict) -> dict:
    """Classify a single post (fallback on batch parse failure)."""
    user_prompt = _build_user_prompt([post])

    resp = client.chat.completions.create(
        model=OLLAMA_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=1024,
    )

    text = resp.choices[0].message.content
    if "</think>" in text:
        text = text.split("</think>")[-1].strip()

    results = _parse_response(text, [post["id"]])
    return results[0]


def run_llm_filter(callback=None) -> tuple[int, int]:
    """Classify all keyword-matched but unclassified posts. Returns (relevant, total)."""
    with db_session() as conn:
        posts = get_keyword_matched_unclassified(conn)

    total = len(posts)
    if callback:
        callback(f"  LLM filter: {total} posts to classify")

    if total == 0:
        return 0, 0

    relevant_count = 0

    for i in range(0, total, LLM_BATCH_SIZE):
        batch = posts[i:i + LLM_BATCH_SIZE]
        batch_dicts = [dict(p) for p in batch]

        try:
            results = _classify_batch(batch_dicts)
        except Exception as e:
            if callback:
                callback(f"  [error] LLM batch {i}: {e}")
            time.sleep(5)
            continue

        # Map results by post_id
        result_map = {r["post_id"]: r for r in results}

        with db_session() as conn:
            for post in batch_dicts:
                r = result_map.get(post["id"], _default_result(post["id"]))
                is_relevant = bool(r.get("relevant", False))
                tags = r.get("tags", [])
                if isinstance(tags, list):
                    tags = json.dumps(tags)
                upsert_classification(
                    conn, post["id"],
                    relevant=is_relevant,
                    confidence=float(r.get("confidence", 0.0)),
                    category=r.get("category", "not_relevant"),
                    tags=tags,
                    summary=r.get("summary", ""),
                    reasoning=r.get("reasoning", ""),
                )
                if is_relevant:
                    relevant_count += 1

        if callback:
            callback(f"  LLM progress: {min(i + LLM_BATCH_SIZE, total)}/{total}")

    return relevant_count, total
