"""Fast local keyword pre-filter: AI term AND education term must both appear."""

import re

from config import AI_TERMS, EDUCATION_TERMS
from db import db_session, get_unfiltered_posts, update_keyword_match


def _normalize(text: str) -> str:
    return text.lower()


def _has_match(text: str, terms: set) -> bool:
    text_lower = _normalize(text)
    for term in terms:
        # Use word boundary for short terms to avoid false positives
        if len(term) <= 3:
            if re.search(r'\b' + re.escape(term) + r'\b', text_lower):
                return True
        else:
            if term in text_lower:
                return True
    return False


def keyword_matches(title: str, body: str) -> bool:
    """Check if text contains at least 1 AI term AND 1 education term."""
    combined = f"{title} {body}"
    return _has_match(combined, AI_TERMS) and _has_match(combined, EDUCATION_TERMS)


def run_keyword_filter(callback=None) -> tuple[int, int]:
    """Filter all unchecked posts. Returns (matched, total_checked)."""
    with db_session() as conn:
        posts = get_unfiltered_posts(conn)

    matched = 0
    total = len(posts)

    with db_session() as conn:
        for post in posts:
            is_match = keyword_matches(post["title"] or "", post["selftext"] or "")
            update_keyword_match(conn, post["id"], is_match)
            if is_match:
                matched += 1

    if callback:
        callback(f"  Keyword filter: {matched}/{total} matched")

    return matched, total
