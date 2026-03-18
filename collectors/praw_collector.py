"""PRAW collector for recent Reddit posts and comment trees."""

import praw

from config import (
    REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT,
    SUBREDDITS, SEARCH_QUERIES,
)
from db import (
    db_session, upsert_post, upsert_comment, post_exists,
    get_relevant_posts_without_comments,
)


def _get_reddit() -> praw.Reddit:
    return praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )


def _submission_to_row(submission, query: str) -> dict:
    return {
        "id": submission.id,
        "subreddit": str(submission.subreddit),
        "author": str(submission.author) if submission.author else "[deleted]",
        "title": submission.title,
        "selftext": submission.selftext,
        "url": submission.url,
        "score": submission.score,
        "num_comments": submission.num_comments,
        "created_utc": submission.created_utc,
        "permalink": submission.permalink,
        "source": "praw",
        "search_query": query,
    }


def collect_recent(callback=None) -> int:
    """Search recent posts across all subreddits."""
    reddit = _get_reddit()
    total = 0

    for sub_name in SUBREDDITS:
        subreddit = reddit.subreddit(sub_name)
        for query in SEARCH_QUERIES:
            try:
                results = subreddit.search(query, sort="new", time_filter="month", limit=100)
                batch = 0
                with db_session() as conn:
                    for submission in results:
                        if not post_exists(conn, submission.id):
                            upsert_post(conn, _submission_to_row(submission, query))
                            batch += 1
                total += batch
                if callback and batch:
                    callback(f"  PRAW {sub_name}/{query}: +{batch}")
            except Exception as e:
                if callback:
                    callback(f"  [error] PRAW {sub_name}/{query}: {e}")

    return total


def collect_comments(callback=None) -> int:
    """Fetch comment trees for LLM-relevant posts that lack comments."""
    reddit = _get_reddit()
    total = 0

    with db_session() as conn:
        posts = get_relevant_posts_without_comments(conn)

    if callback:
        callback(f"  Fetching comments for {len(posts)} relevant posts...")

    for post_row in posts:
        post_id = post_row["id"]
        try:
            submission = reddit.submission(id=post_id)
            submission.comments.replace_more(limit=32)

            with db_session() as conn:
                count = _walk_comments(conn, submission.comments.list(), post_id)
            total += count
            if callback:
                callback(f"  Comments for {post_id}: +{count}")
        except Exception as e:
            if callback:
                callback(f"  [error] Comments {post_id}: {e}")

    return total


def _walk_comments(conn, comments, post_id: str) -> int:
    """Insert all comments for a post."""
    count = 0
    for comment in comments:
        if not hasattr(comment, "body"):
            continue
        upsert_comment(conn, {
            "id": comment.id,
            "post_id": post_id,
            "parent_id": _parent_id(comment),
            "author": str(comment.author) if comment.author else "[deleted]",
            "body": comment.body,
            "score": comment.score,
            "created_utc": comment.created_utc,
            "depth": comment.depth,
        })
        count += 1
    return count


def _parent_id(comment) -> str | None:
    """Extract parent comment ID (strip 't1_' prefix), or None if top-level."""
    pid = comment.parent_id
    if pid.startswith("t1_"):
        return pid[3:]
    return None
