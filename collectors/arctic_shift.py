"""Arctic Shift API collector for historical Reddit data (2023-2026)."""

import time
import requests
from datetime import datetime

from config import (
    SUBREDDITS, SEARCH_QUERIES, DATE_START, DATE_END, ARCTIC_SHIFT_DELAY,
)
from db import (
    db_session, upsert_post, upsert_comment,
    get_or_create_job, update_job, get_relevant_posts_without_comments,
)


API_URL = "https://arctic-shift.photon-reddit.com/api/posts/search"
COMMENTS_API_URL = "https://arctic-shift.photon-reddit.com/api/comments/search"


def _to_epoch(date_str: str) -> int:
    return int(datetime.strptime(date_str, "%Y-%m-%d").timestamp())


def _fetch_page(subreddit: str, query: str | None, after: int, before: int,
                limit: int = 100) -> list[dict]:
    params = {
        "subreddit": subreddit,
        "after": after,
        "before": before,
        "sort": "asc",
        "sort_type": "created_utc",
        "limit": limit,
    }
    if query:
        params["title"] = query

    resp = requests.get(API_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", [])


def _post_to_row(post: dict, source_query: str | None) -> dict:
    return {
        "id": post.get("id", ""),
        "subreddit": post.get("subreddit", ""),
        "author": post.get("author", "[deleted]"),
        "title": post.get("title", ""),
        "selftext": post.get("selftext", ""),
        "url": post.get("url", ""),
        "score": post.get("score", 0),
        "num_comments": post.get("num_comments", 0),
        "created_utc": post.get("created_utc", 0),
        "permalink": post.get("permalink", ""),
        "source": "arctic_shift",
        "search_query": source_query,
    }


def collect_subreddit_query(subreddit: str, query: str | None,
                            callback=None) -> int:
    """Collect all posts for a subreddit+query combo. Returns post count."""
    with db_session() as conn:
        job = get_or_create_job(conn, "arctic_shift", subreddit, query)

        if job["status"] == "completed":
            if callback:
                callback(f"  [skip] {subreddit}/{query or 'broad'} already completed")
            return job["posts_collected"]

        after = int(job["last_timestamp"] or _to_epoch(DATE_START))
        before = _to_epoch(DATE_END)
        total = job["posts_collected"] or 0

        update_job(conn, job["id"], status="running",
                   started_at=datetime.now().isoformat())
        conn.commit()

    while True:
        try:
            posts = _fetch_page(subreddit, query, after, before)
        except requests.RequestException as e:
            if callback:
                callback(f"  [error] {subreddit}/{query}: {e}")
            time.sleep(5)
            continue

        if not posts:
            break

        with db_session() as conn:
            for p in posts:
                upsert_post(conn, _post_to_row(p, query))
            total += len(posts)
            after = int(posts[-1]["created_utc"])
            update_job(conn, job["id"], last_timestamp=after, posts_collected=total)

        if callback:
            callback(f"  {subreddit}/{query or 'broad'}: +{len(posts)} (total: {total})")

        if len(posts) < 100:
            break

        time.sleep(ARCTIC_SHIFT_DELAY)

    with db_session() as conn:
        update_job(conn, job["id"], status="completed", posts_collected=total)

    return total


# Large subs where broad sweep would pull too many irrelevant posts
SKIP_BROAD_SWEEP = {"ChatGPT"}


def collect_all(callback=None) -> int:
    """Run Arctic Shift collection for all subreddits × queries + broad sweeps."""
    grand_total = 0

    for sub in SUBREDDITS:
        # Targeted queries
        for query in SEARCH_QUERIES:
            count = collect_subreddit_query(sub, query, callback)
            grand_total += count

        # Broad sweep (skip for massive non-education subs)
        if sub not in SKIP_BROAD_SWEEP:
            count = collect_subreddit_query(sub, None, callback)
            grand_total += count
        elif callback:
            callback(f"  [skip] {sub}/broad — large sub, targeted queries only")

    return grand_total


# ── Comment Collection ───────────────────────────────────────────────────────

def _fetch_comments(post_id: str, limit: int = 100) -> list[dict]:
    """Fetch all comments for a post via Arctic Shift."""
    all_comments = []
    after = None

    while True:
        params = {
            "link_id": post_id,
            "limit": limit,
            "sort": "asc",
            "sort_type": "created_utc",
        }
        if after is not None:
            params["after"] = after

        resp = requests.get(COMMENTS_API_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", [])

        if not data:
            break

        all_comments.extend(data)
        if len(data) < limit:
            break

        after = int(data[-1]["created_utc"])
        time.sleep(ARCTIC_SHIFT_DELAY)

    return all_comments


def _comment_to_row(comment: dict, post_id: str) -> dict:
    parent = comment.get("parent_id", "")
    # parent_id is "t1_xxx" for comment replies, "t3_xxx" for top-level
    parent_comment_id = parent[3:] if parent.startswith("t1_") else None

    return {
        "id": comment.get("id", ""),
        "post_id": post_id,
        "parent_id": parent_comment_id,
        "author": comment.get("author", "[deleted]"),
        "body": comment.get("body", ""),
        "score": comment.get("score", 0),
        "created_utc": comment.get("created_utc", 0),
        "depth": comment.get("depth", 0),
    }


def collect_comments(callback=None) -> int:
    """Fetch comments for all LLM-relevant posts that lack comments."""
    with db_session() as conn:
        posts = get_relevant_posts_without_comments(conn)

    if callback:
        callback(f"  Fetching comments for {len(posts)} relevant posts via Arctic Shift...")

    total = 0
    for i, post_row in enumerate(posts):
        post_id = post_row["id"]
        try:
            comments = _fetch_comments(post_id)
            with db_session() as conn:
                for c in comments:
                    upsert_comment(conn, _comment_to_row(c, post_id))
            total += len(comments)
            if callback and (i + 1) % 10 == 0:
                callback(f"  Comments progress: {i+1}/{len(posts)} posts, {total} comments")
        except requests.RequestException as e:
            if callback:
                callback(f"  [error] Comments {post_id}: {e}")
            time.sleep(5)

        time.sleep(ARCTIC_SHIFT_DELAY)

    if callback:
        callback(f"  Comments done: {total} comments from {len(posts)} posts")

    return total
