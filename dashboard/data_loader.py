"""Load analysis data from SQLite for the dashboard."""

import json

import pandas as pd

from analysis.db_schema import get_connection


def get_semantic_map_data() -> pd.DataFrame:
    """Load UMAP coordinates with topic labels for scatter plot."""
    conn = get_connection()
    try:
        df = pd.read_sql_query("""
            SELECT ta.post_id, ta.umap_x, ta.umap_y, ta.topic_id,
                   ta.level1_id, ta.level2_id, ta.probability,
                   at.embed_text,
                   t1.llm_label as l1_label, t1.auto_label as l1_auto,
                   t2.llm_label as l2_label, t2.auto_label as l2_auto,
                   p.title, p.subreddit, p.score, p.num_comments,
                   c.category, c.tags
            FROM topic_assignments ta
            JOIN analysis_texts at ON at.post_id = ta.post_id
            JOIN posts p ON p.id = ta.post_id
            LEFT JOIN classifications c ON c.post_id = ta.post_id
            LEFT JOIN topics t1 ON t1.topic_id = ta.level1_id
            LEFT JOIN topics t2 ON t2.topic_id = ta.level2_id
        """, conn)
        df["l1_label"] = df["l1_label"].fillna(df["l1_auto"]).fillna("Unassigned")
        df["l2_label"] = df["l2_label"].fillna(df["l2_auto"]).fillna("Unassigned")
        return df
    finally:
        conn.close()


def get_topics(level: int = None) -> pd.DataFrame:
    """Load topic metadata."""
    conn = get_connection()
    try:
        query = "SELECT * FROM topics"
        params = []
        if level is not None:
            query += " WHERE level = ?"
            params.append(level)
        query += " ORDER BY count DESC"
        return pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()


def get_topics_over_time() -> pd.DataFrame:
    """Load temporal topic data."""
    conn = get_connection()
    try:
        df = pd.read_sql_query("""
            SELECT tot.topic_id, tot.time_bin, tot.frequency, tot.keywords,
                   t.llm_label, t.auto_label
            FROM topics_over_time tot
            LEFT JOIN topics t ON t.topic_id = tot.topic_id
            ORDER BY tot.time_bin
        """, conn)
        df["label"] = df["llm_label"].fillna(df["auto_label"]).fillna("Topic " + df["topic_id"].astype(str))
        df["time_bin"] = pd.to_datetime(df["time_bin"])
        return df
    finally:
        conn.close()


def get_emotion_heatmap_data() -> pd.DataFrame:
    """Load topic emotion aggregations for heatmap."""
    conn = get_connection()
    try:
        df = pd.read_sql_query("""
            SELECT tea.topic_id, tea.level, tea.num_comments,
                   tea.emotion_distribution, tea.dominant_emotion,
                   tea.agree_pct, tea.disagree_pct, tea.neutral_pct,
                   t.llm_label, t.auto_label
            FROM topic_emotion_agg tea
            LEFT JOIN topics t ON t.topic_id = tea.topic_id
            ORDER BY tea.level, tea.num_comments DESC
        """, conn)
        df["label"] = df["llm_label"].fillna(df["auto_label"]).fillna("Topic " + df["topic_id"].astype(str))
        return df
    finally:
        conn.close()


def get_explorer_data(topic_id: int = None, search: str = None,
                      category: str = None, limit: int = 100) -> pd.DataFrame:
    """Load posts with filters for the explorer tab."""
    conn = get_connection()
    try:
        query = """
            SELECT p.id, p.title, p.subreddit, p.score, p.num_comments,
                   p.created_utc, p.permalink, p.selftext,
                   c.category, c.tags, c.summary, c.confidence,
                   ta.topic_id, ta.level1_id, ta.level2_id,
                   t1.llm_label as l1_label, t2.llm_label as l2_label
            FROM posts p
            JOIN classifications c ON c.post_id = p.id
            LEFT JOIN topic_assignments ta ON ta.post_id = p.id
            LEFT JOIN topics t1 ON t1.topic_id = ta.level1_id
            LEFT JOIN topics t2 ON t2.topic_id = ta.level2_id
            WHERE c.relevant = 1
        """
        params = []
        if topic_id is not None:
            query += " AND (ta.level1_id = ? OR ta.level2_id = ?)"
            params.extend([topic_id, topic_id])
        if category:
            query += " AND c.category = ?"
            params.append(category)
        if search:
            query += " AND (p.title LIKE ? OR c.summary LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])
        query += " ORDER BY p.score DESC LIMIT ?"
        params.append(limit)
        return pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()


def get_post_comments(post_id: str) -> pd.DataFrame:
    """Load comments for a specific post with emotion annotations."""
    conn = get_connection()
    try:
        return pd.read_sql_query("""
            SELECT c.id, c.body, c.author, c.score, c.depth, c.created_utc,
                   ce.emotions, ce.dominant_emotion, ce.sentiment,
                   cs.agree_score, cs.disagree_score, cs.stance
            FROM comments c
            LEFT JOIN comment_emotions ce ON ce.comment_id = c.id
            LEFT JOIN comment_stance cs ON cs.comment_id = c.id
            WHERE c.post_id = ?
            ORDER BY c.depth, c.score DESC
        """, conn, params=[post_id])
    finally:
        conn.close()


def get_dashboard_stats() -> dict:
    """Get summary stats for the dashboard header."""
    conn = get_connection()
    try:
        stats = {}
        stats["total_posts"] = conn.execute(
            "SELECT COUNT(*) FROM classifications WHERE relevant = 1"
        ).fetchone()[0]
        stats["total_comments"] = conn.execute(
            "SELECT COUNT(*) FROM comments"
        ).fetchone()[0]
        stats["topics_l1"] = conn.execute(
            "SELECT COUNT(*) FROM topics WHERE level = 1"
        ).fetchone()[0]
        stats["topics_l2"] = conn.execute(
            "SELECT COUNT(*) FROM topics WHERE level = 2"
        ).fetchone()[0]
        stats["comments_with_emotions"] = conn.execute(
            "SELECT COUNT(*) FROM comment_emotions"
        ).fetchone()[0]
        stats["subreddits"] = conn.execute("""
            SELECT COUNT(DISTINCT p.subreddit) FROM posts p
            JOIN classifications c ON c.post_id = p.id WHERE c.relevant = 1
        """).fetchone()[0]
        return stats
    finally:
        conn.close()
