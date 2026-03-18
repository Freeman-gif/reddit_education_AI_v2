"""Export classified data to CSV and JSON for analysis."""

import csv
import json
from pathlib import Path

from config import DATA_DIR
from db import db_session


def export_csv(output_path: Path | None = None) -> Path:
    """Export relevant posts to CSV. Original post data + classification side-by-side."""
    if output_path is None:
        output_path = DATA_DIR / "relevant_posts.csv"

    with db_session() as conn:
        posts = conn.execute("""
            SELECT p.id, p.subreddit, p.author, p.title, p.selftext, p.url, p.score,
                   p.num_comments, p.created_utc, p.permalink, p.source,
                   c.confidence, c.category, c.tags, c.summary, c.reasoning
            FROM posts p
            JOIN classifications c ON c.post_id = p.id
            WHERE c.relevant = 1
            ORDER BY p.created_utc
        """).fetchall()

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id", "subreddit", "author", "title", "selftext", "url", "score",
            "num_comments", "created_utc", "permalink", "source",
            "confidence", "category", "tags", "summary", "reasoning",
        ])
        for post in posts:
            writer.writerow(list(post))

    print(f"Exported {len(posts)} posts to {output_path}")
    return output_path


def export_json(output_path: Path | None = None) -> Path:
    """Export relevant posts with classification + nested comment trees to JSON."""
    if output_path is None:
        output_path = DATA_DIR / "relevant_posts_with_comments.json"

    with db_session() as conn:
        posts = conn.execute("""
            SELECT p.*, c.relevant as cls_relevant, c.confidence, c.category,
                   c.tags, c.summary, c.reasoning
            FROM posts p
            JOIN classifications c ON c.post_id = p.id
            WHERE c.relevant = 1
            ORDER BY p.created_utc
        """).fetchall()

        result = []
        for post in posts:
            post_dict = dict(post)

            # Parse tags JSON
            if post_dict.get("tags"):
                try:
                    post_dict["tags"] = json.loads(post_dict["tags"])
                except json.JSONDecodeError:
                    pass

            comments = conn.execute(
                "SELECT * FROM comments WHERE post_id = ? ORDER BY created_utc",
                (post["id"],)
            ).fetchall()

            post_dict["comments"] = _build_comment_tree(
                [dict(c) for c in comments]
            )
            result.append(post_dict)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False, default=str)

    print(f"Exported {len(result)} posts (with comments) to {output_path}")
    return output_path


def _build_comment_tree(comments: list[dict]) -> list[dict]:
    """Build nested comment tree from flat list."""
    by_id = {c["id"]: {**c, "replies": []} for c in comments}
    roots = []

    for c in comments:
        node = by_id[c["id"]]
        parent = c.get("parent_id")
        if parent and parent in by_id:
            by_id[parent]["replies"].append(node)
        else:
            roots.append(node)

    return roots


def export_stats(output_path: Path | None = None) -> Path:
    """Export summary statistics to JSON."""
    if output_path is None:
        output_path = DATA_DIR / "stats.json"

    with db_session() as conn:
        stats = {}

        stats["total_posts"] = conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        stats["keyword_matched"] = conn.execute(
            "SELECT COUNT(*) FROM posts WHERE keyword_match = 1"
        ).fetchone()[0]
        stats["classified"] = conn.execute(
            "SELECT COUNT(*) FROM classifications"
        ).fetchone()[0]
        stats["llm_relevant"] = conn.execute(
            "SELECT COUNT(*) FROM classifications WHERE relevant = 1"
        ).fetchone()[0]
        stats["total_comments"] = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]

        # By subreddit
        stats["by_subreddit"] = {
            row[0]: row[1] for row in conn.execute("""
                SELECT p.subreddit, COUNT(*) FROM posts p
                JOIN classifications c ON c.post_id = p.id
                WHERE c.relevant = 1 GROUP BY p.subreddit
            """).fetchall()
        }

        # By category
        stats["by_category"] = {
            row[0]: row[1] for row in conn.execute(
                "SELECT category, COUNT(*) FROM classifications WHERE relevant=1 GROUP BY category"
            ).fetchall()
        }

        # By month
        stats["by_month"] = {
            row[0]: row[1] for row in conn.execute("""
                SELECT strftime('%Y-%m', p.created_utc, 'unixepoch') as month, COUNT(*)
                FROM posts p JOIN classifications c ON c.post_id = p.id
                WHERE c.relevant = 1
                GROUP BY month ORDER BY month
            """).fetchall()
        }

        # Top tags
        stats["top_tags"] = {}
        rows = conn.execute(
            "SELECT tags FROM classifications WHERE relevant = 1 AND tags IS NOT NULL"
        ).fetchall()
        for row in rows:
            try:
                for tag in json.loads(row[0]):
                    stats["top_tags"][tag] = stats["top_tags"].get(tag, 0) + 1
            except (json.JSONDecodeError, TypeError):
                pass
        # Sort by count
        stats["top_tags"] = dict(sorted(stats["top_tags"].items(), key=lambda x: -x[1]))

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    print(f"Exported stats to {output_path}")
    return output_path
