"""Phase 0: Fill missing summaries and build composite embed texts."""

import json
import time

import requests

from analysis.config import OLLAMA_CHAT_URL, OLLAMA_CHAT_MODEL
from analysis.db_schema import db_session, upsert_analysis_text


def _generate_summary(title: str, selftext: str) -> str:
    """Generate a summary via Qwen3-32B for posts missing one."""
    prompt = (
        "Summarize this Reddit post in 1-2 sentences. Focus on the main point "
        "about AI in K-12 education.\n\n"
        f"Title: {title}\n\nBody: {(selftext or '')[:2000]}"
    )
    resp = requests.post(OLLAMA_CHAT_URL, json={
        "model": OLLAMA_CHAT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 150,
    }, timeout=120)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    # Strip thinking tags if present (Qwen3 may include <think>...</think>)
    if "<think>" in content:
        parts = content.split("</think>")
        content = parts[-1].strip() if len(parts) > 1 else content
    return content.strip()


def _build_embed_text(summary: str, tags: str, category: str) -> str:
    """Build composite text for embedding."""
    parts = [f"search_document: {summary}"]
    if tags:
        try:
            tag_list = json.loads(tags) if isinstance(tags, str) else tags
            if tag_list:
                parts.append(f"Tags: {', '.join(tag_list)}")
        except (json.JSONDecodeError, TypeError):
            parts.append(f"Tags: {tags}")
    if category and category != "not_relevant":
        parts.append(f"Category: {category}")
    return ". ".join(parts)


def run_prepare(callback=None, skip_llm=False):
    """Build analysis_texts for all relevant classified posts."""
    log = callback or print

    with db_session() as conn:
        # Get all relevant posts with their classification data
        rows = conn.execute("""
            SELECT p.id, p.title, p.selftext,
                   c.summary, c.tags, c.category
            FROM posts p
            JOIN classifications c ON c.post_id = p.id
            WHERE c.relevant = 1
        """).fetchall()

        log(f"[prepare] Found {len(rows)} relevant posts")

        regenerated = 0
        for row in rows:
            post_id = row["id"]
            title = row["title"] or ""
            selftext = row["selftext"] or ""
            summary = row["summary"]
            tags = row["tags"]
            category = row["category"]

            # Check if already prepared
            existing = conn.execute(
                "SELECT 1 FROM analysis_texts WHERE post_id = ?", (post_id,)
            ).fetchone()
            if existing:
                continue

            # Determine summary source
            if summary and summary.strip():
                source = "classification"
            elif title.strip() and not skip_llm:
                # Try to regenerate via LLM
                try:
                    summary = _generate_summary(title, selftext)
                    source = "regenerated"
                    regenerated += 1
                    time.sleep(0.5)
                except Exception as e:
                    log(f"[prepare] LLM summary failed for {post_id}: {e}")
                    summary = title
                    source = "title_only"
            elif title.strip():
                # Use title + selftext snippet as summary
                snippet = (selftext[:200] + "...") if selftext else ""
                summary = f"{title}. {snippet}".strip()
                source = "title_only"
            else:
                summary = "Untitled post"
                source = "title_only"

            embed_text = _build_embed_text(summary, tags, category)
            upsert_analysis_text(conn, post_id, embed_text, source)

        conn.commit()
        total = conn.execute("SELECT COUNT(*) FROM analysis_texts").fetchone()[0]
        log(f"[prepare] Done. {total} texts ready ({regenerated} regenerated)")
        return total
