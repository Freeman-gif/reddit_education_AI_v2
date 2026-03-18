"""Pipeline orchestration: collect → filter → classify → comments → stats."""

import time

from db import init_db, db_session, get_stats
from collectors.arctic_shift import collect_all as arctic_collect
from collectors.arctic_shift import collect_comments
from filters.keyword_filter import run_keyword_filter
from filters.llm_filter import run_llm_filter


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def run_full_pipeline(skip_llm=False):
    """Run the complete pipeline end-to-end."""
    init_db()

    # 1. Arctic Shift collection
    log("=== Stage 1: Arctic Shift Collection ===")
    total = arctic_collect(callback=log)
    log(f"Arctic Shift done: {total} posts collected")

    # 2. Keyword pre-filter
    log("=== Stage 2: Keyword Pre-Filter ===")
    matched, checked = run_keyword_filter(callback=log)
    log(f"Keyword filter: {matched}/{checked} posts matched")

    # 3. LLM classification
    if not skip_llm:
        log("=== Stage 3: LLM Classification ===")
        relevant, classified = run_llm_filter(callback=log)
        log(f"LLM filter: {relevant}/{classified} posts relevant")
    else:
        log("=== Stage 3: LLM skipped ===")

    # 4. Comment collection (Arctic Shift, relevant posts only)
    if not skip_llm:
        log("=== Stage 4: Comment Collection ===")
        total = collect_comments(callback=log)
        log(f"Comments collected: {total}")
    else:
        log("=== Stage 4: Comments skipped (need LLM first) ===")

    # 6. Summary
    log("=== Summary ===")
    with db_session() as conn:
        stats = get_stats(conn)
    log(f"  Total posts: {stats['total_posts']}")
    log(f"  Keyword matched: {stats['keyword_matched']}")
    log(f"  LLM relevant: {stats['llm_relevant']}")
    log(f"  Total comments: {stats['total_comments']}")
    log(f"  By subreddit: {stats['by_subreddit']}")
    log(f"  By category: {stats['by_category']}")


def run_arctic_only():
    """Just Arctic Shift collection + keyword filter."""
    init_db()
    log("=== Arctic Shift Collection ===")
    total = arctic_collect(callback=log)
    log(f"Done: {total} posts")

    log("=== Keyword Pre-Filter ===")
    matched, checked = run_keyword_filter(callback=log)
    log(f"Keyword filter: {matched}/{checked} matched")


def run_llm_only():
    """Just LLM classification on existing keyword-matched posts."""
    init_db()
    log("=== LLM Classification ===")
    relevant, classified = run_llm_filter(callback=log)
    log(f"LLM filter: {relevant}/{classified} relevant")


def run_comments_only():
    """Just comment collection on LLM-relevant posts."""
    init_db()
    log("=== Comment Collection ===")
    total = collect_comments(callback=log)
    log(f"Comments collected: {total}")
