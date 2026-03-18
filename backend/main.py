"""FastAPI backend serving network graph data from the analysis DB."""

import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

DB_PATH = Path(__file__).parent.parent / "data" / "reddit_ai_k12.db"
DIST_DIR = Path(__file__).parent.parent / "frontend" / "dist"

app = FastAPI(title="Reddit AI K-12 Graph API")


def safe_row(row) -> dict:
    """Convert a sqlite3.Row to dict, decoding bytes safely."""
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, bytes):
            d[k] = v.decode("utf-8", errors="replace")
    return d
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# ── Stats ────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def stats():
    conn = get_db()
    try:
        r = {}
        r["total_posts"] = conn.execute(
            "SELECT COUNT(*) FROM classifications WHERE relevant = 1"
        ).fetchone()[0]
        r["total_comments"] = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        r["topics_l1"] = conn.execute("SELECT COUNT(*) FROM topics WHERE level = 1").fetchone()[0]
        r["topics_l2"] = conn.execute("SELECT COUNT(*) FROM topics WHERE level = 2").fetchone()[0]
        r["subreddits"] = conn.execute(
            "SELECT COUNT(DISTINCT p.subreddit) FROM posts p "
            "JOIN classifications c ON c.post_id = p.id WHERE c.relevant = 1"
        ).fetchone()[0]
        r["post_edges"] = conn.execute("SELECT COUNT(*) FROM post_edges").fetchone()[0]
        return r
    finally:
        conn.close()


# ── Hub nodes (L1 topics) ───────────────────────────────────────────────

@app.get("/api/hubs")
def hubs():
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT t.topic_id, t.llm_label, t.auto_label, t.count,
                   t.llm_description, t.keywords,
                   AVG(ta.umap_x) as cx, AVG(ta.umap_y) as cy
            FROM topics t
            JOIN topic_assignments ta ON ta.level1_id = t.topic_id
            WHERE t.level = 1
            GROUP BY t.topic_id
        """).fetchall()
        return [safe_row(r) for r in rows]
    finally:
        conn.close()


# ── Hub-to-hub edges ────────────────────────────────────────────────────

@app.get("/api/hubs/edges")
def hub_edges():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM topic_edges").fetchall()
        return [safe_row(r) for r in rows]
    finally:
        conn.close()


# ── All posts + KNN edges (full pool) ──────────────────────────────────

@app.get("/api/years")
def available_years():
    conn = get_db()
    try:
        post_years = conn.execute("""
            SELECT DISTINCT CAST(strftime('%Y', datetime(p.created_utc, 'unixepoch')) AS TEXT) as year
            FROM posts p JOIN topic_assignments ta ON ta.post_id = p.id
            ORDER BY year
        """).fetchall()
        comment_years = conn.execute("""
            SELECT DISTINCT CAST(strftime('%Y', datetime(created_utc, 'unixepoch')) AS TEXT) as year
            FROM comments ORDER BY year
        """).fetchall()
        return {
            "post_years": [r["year"] for r in post_years],
            "comment_years": [r["year"] for r in comment_years],
        }
    finally:
        conn.close()


@app.get("/api/posts/all")
def all_posts(years: str = Query(default=None)):
    conn = get_db()
    try:
        year_filter = ""
        params = []
        if years:
            year_list = [y.strip() for y in years.split(",")]
            placeholders = ",".join("?" * len(year_list))
            year_filter = f" AND CAST(strftime('%Y', datetime(p.created_utc, 'unixepoch')) AS TEXT) IN ({placeholders})"
            params = year_list

        posts = conn.execute(f"""
            SELECT p.id as post_id, p.title, p.score, p.num_comments,
                   p.subreddit, c.summary, c.category,
                   ta.umap_x, ta.umap_y, ta.level1_id as topic_id
            FROM topic_assignments ta
            JOIN posts p ON p.id = ta.post_id
            LEFT JOIN classifications c ON c.post_id = p.id
            WHERE 1=1 {year_filter}
        """, params).fetchall()

        post_id_set = {p["post_id"] for p in posts}
        all_edges = conn.execute(
            "SELECT source_id, target_id, weight FROM post_edges"
        ).fetchall()
        edges = [e for e in all_edges if e["source_id"] in post_id_set and e["target_id"] in post_id_set]

        # Dominant emotion per post
        post_ids = [p["post_id"] for p in posts]
        emotions = {}
        if post_ids:
            placeholders = ",".join("?" * len(post_ids))
            emo_rows = conn.execute(f"""
                SELECT cm.post_id, ce.dominant_emotion, COUNT(*) as cnt
                FROM comments cm
                JOIN comment_emotions ce ON ce.comment_id = cm.id
                WHERE cm.post_id IN ({placeholders})
                GROUP BY cm.post_id, ce.dominant_emotion
                ORDER BY cnt DESC
            """, post_ids).fetchall()
            for r in emo_rows:
                pid = r["post_id"]
                if pid not in emotions:
                    emotions[pid] = r["dominant_emotion"]

        posts_out = []
        for p in posts:
            d = safe_row(p)
            d["dominant_emotion"] = emotions.get(d["post_id"], "neutral")
            posts_out.append(d)

        return {
            "posts": posts_out,
            "edges": [safe_row(e) for e in edges],
        }
    finally:
        conn.close()


# ── Posts + KNN edges for a topic ────────────────────────────────────────

@app.get("/api/posts/{topic_id}")
def topic_posts(topic_id: int):
    conn = get_db()
    try:
        posts = conn.execute("""
            SELECT p.id as post_id, p.title, p.score, p.num_comments,
                   p.subreddit, c.summary, c.category,
                   ta.umap_x, ta.umap_y
            FROM topic_assignments ta
            JOIN posts p ON p.id = ta.post_id
            LEFT JOIN classifications c ON c.post_id = p.id
            WHERE ta.level1_id = ?
        """, (topic_id,)).fetchall()

        edges = conn.execute("""
            SELECT pe.source_id, pe.target_id, pe.weight
            FROM post_edges pe
            WHERE pe.source_id IN (SELECT post_id FROM topic_assignments WHERE level1_id = ?)
              AND pe.target_id IN (SELECT post_id FROM topic_assignments WHERE level1_id = ?)
        """, (topic_id, topic_id)).fetchall()

        # Dominant emotion per post (from its comments)
        post_ids = [p["post_id"] for p in posts]
        emotions = {}
        if post_ids:
            placeholders = ",".join("?" * len(post_ids))
            emo_rows = conn.execute(f"""
                SELECT cm.post_id, ce.dominant_emotion, COUNT(*) as cnt
                FROM comments cm
                JOIN comment_emotions ce ON ce.comment_id = cm.id
                WHERE cm.post_id IN ({placeholders})
                GROUP BY cm.post_id, ce.dominant_emotion
                ORDER BY cnt DESC
            """, post_ids).fetchall()
            for r in emo_rows:
                pid = r["post_id"]
                if pid not in emotions:
                    emotions[pid] = r["dominant_emotion"]

        posts_out = []
        for p in posts:
            d = safe_row(p)
            d["dominant_emotion"] = emotions.get(d["post_id"], "neutral")
            posts_out.append(d)

        return {
            "posts": posts_out,
            "edges": [safe_row(e) for e in edges],
        }
    finally:
        conn.close()


# ── Post detail + comments ──────────────────────────────────────────────

@app.get("/api/post/{post_id}")
def post_detail(post_id: str):
    conn = get_db()
    try:
        post = conn.execute("""
            SELECT p.*, c.summary, c.category, c.tags,
                   ta.level1_id, ta.level2_id,
                   t1.llm_label as l1_label, t2.llm_label as l2_label
            FROM posts p
            LEFT JOIN classifications c ON c.post_id = p.id
            LEFT JOIN topic_assignments ta ON ta.post_id = p.id
            LEFT JOIN topics t1 ON t1.topic_id = ta.level1_id
            LEFT JOIN topics t2 ON t2.topic_id = ta.level2_id
            WHERE p.id = ?
        """, (post_id,)).fetchone()
        if not post:
            return {"error": "not found"}

        comments = conn.execute("""
            SELECT c.id, c.body, c.author, c.score, c.depth,
                   ce.dominant_emotion, ce.sentiment,
                   cs.stance
            FROM comments c
            LEFT JOIN comment_emotions ce ON ce.comment_id = c.id
            LEFT JOIN comment_stance cs ON cs.comment_id = c.id
            WHERE c.post_id = ?
            ORDER BY c.depth, c.score DESC
        """, (post_id,)).fetchall()

        return {
            "post": safe_row(post),
            "comments": [safe_row(c) for c in comments],
        }
    finally:
        conn.close()


# ── Hub detail (enriched topic) ─────────────────────────────────────────

@app.get("/api/hub/{topic_id}")
def hub_detail(topic_id: int):
    conn = get_db()
    try:
        # Topic info
        topic = conn.execute("""
            SELECT topic_id, llm_label, auto_label, count, keywords,
                   llm_description
            FROM topics WHERE topic_id = ?
        """, (topic_id,)).fetchone()
        if not topic:
            return {"error": "not found"}
        t = safe_row(topic)
        # Parse keywords JSON
        try:
            t["keywords"] = json.loads(t.get("keywords") or "[]")
        except (json.JSONDecodeError, TypeError):
            t["keywords"] = []

        # Top 5 posts by score
        top_posts = conn.execute("""
            SELECT p.id as post_id, p.title, p.subreddit, p.score
            FROM topic_assignments ta
            JOIN posts p ON p.id = ta.post_id
            WHERE ta.level1_id = ?
            ORDER BY p.score DESC
            LIMIT 5
        """, (topic_id,)).fetchall()
        t["top_posts"] = [safe_row(r) for r in top_posts]

        # Emotion breakdown across all comments in topic
        emotions = conn.execute("""
            SELECT ce.dominant_emotion, COUNT(*) as cnt
            FROM topic_assignments ta
            JOIN comments cm ON cm.post_id = ta.post_id
            JOIN comment_emotions ce ON ce.comment_id = cm.id
            WHERE ta.level1_id = ?
            GROUP BY ce.dominant_emotion
            ORDER BY cnt DESC
        """, (topic_id,)).fetchall()
        t["emotions"] = [safe_row(r) for r in emotions]

        # Stance distribution
        stance = conn.execute("""
            SELECT cs.stance, COUNT(*) as cnt
            FROM topic_assignments ta
            JOIN comments cm ON cm.post_id = ta.post_id
            JOIN comment_stance cs ON cs.comment_id = cm.id
            WHERE ta.level1_id = ?
            GROUP BY cs.stance
        """, (topic_id,)).fetchall()
        t["stance"] = {r["stance"]: r["cnt"] for r in stance}

        return t
    finally:
        conn.close()


# ── Emotion detail ─────────────────────────────────────────────────────

@app.get("/api/emotion/{emotion}")
def emotion_detail(emotion: str):
    conn = get_db()
    try:
        # All comments with this dominant emotion
        comments = conn.execute("""
            SELECT cm.id, cm.body, cm.author, cm.score, cm.post_id,
                   ce.sentiment, cs.stance,
                   p.title as post_title, p.subreddit
            FROM comments cm
            JOIN comment_emotions ce ON ce.comment_id = cm.id
            LEFT JOIN comment_stance cs ON cs.comment_id = cm.id
            JOIN posts p ON p.id = cm.post_id
            WHERE ce.dominant_emotion = ?
            ORDER BY cm.score DESC
        """, (emotion,)).fetchall()

        # Sentiment breakdown
        sentiment = conn.execute("""
            SELECT ce.sentiment, COUNT(*) as cnt
            FROM comment_emotions ce
            WHERE ce.dominant_emotion = ?
            GROUP BY ce.sentiment
        """, (emotion,)).fetchall()

        # Top posts by comment count for this emotion
        top_posts = conn.execute("""
            SELECT p.id as post_id, p.title, p.subreddit,
                   COUNT(*) as comment_count
            FROM comments cm
            JOIN comment_emotions ce ON ce.comment_id = cm.id
            JOIN posts p ON p.id = cm.post_id
            WHERE ce.dominant_emotion = ?
            GROUP BY p.id
            ORDER BY comment_count DESC
            LIMIT 8
        """, (emotion,)).fetchall()

        return {
            "emotion": emotion,
            "total": len(comments),
            "comments": [safe_row(c) for c in comments[:20]],
            "sentiment": {r["sentiment"]: r["cnt"] for r in sentiment},
            "top_posts": [safe_row(r) for r in top_posts],
        }
    finally:
        conn.close()


# ── Comment galaxy data (cluster-based) ────────────────────────────────

@app.get("/api/comments/galaxy")
def comment_galaxy(years: str = Query(default=None)):
    conn = get_db()
    try:
        year_filter = ""
        params = []
        if years:
            year_list = [y.strip() for y in years.split(",")]
            placeholders = ",".join("?" * len(year_list))
            year_filter = f" AND CAST(strftime('%Y', datetime(cm.created_utc, 'unixepoch')) AS TEXT) IN ({placeholders})"
            params = year_list

        # Cluster hubs
        hubs = conn.execute(f"""
            SELECT cc.cluster_id, cc.count, cc.keywords, cc.label, cc.description,
                   AVG(cca.umap_x) as cx, AVG(cca.umap_y) as cy
            FROM comment_clusters cc
            JOIN comment_cluster_assignments cca ON cca.cluster_id = cc.cluster_id
            JOIN comments cm ON cm.id = cca.comment_id
            WHERE cm.body NOT IN ('[deleted]', '[removed]') {year_filter}
            GROUP BY cc.cluster_id
        """, params).fetchall()

        # Comment nodes
        comments = conn.execute(f"""
            SELECT cca.comment_id, cca.cluster_id, cca.umap_x, cca.umap_y,
                   cm.body, cm.score, cm.post_id, cm.author,
                   ce.dominant_emotion, ce.sentiment,
                   cs.stance,
                   p.title as post_title
            FROM comment_cluster_assignments cca
            JOIN comments cm ON cm.id = cca.comment_id
            JOIN comment_emotions ce ON ce.comment_id = cm.id
            LEFT JOIN comment_stance cs ON cs.comment_id = cm.id
            JOIN posts p ON p.id = cm.post_id
            WHERE cm.body NOT IN ('[deleted]', '[removed]') {year_filter}
        """, params).fetchall()

        # KNN edges (filtered to visible comments)
        comment_id_set = {c["comment_id"] for c in comments}
        all_edges = conn.execute(
            "SELECT source_id, target_id, weight FROM comment_edges"
        ).fetchall()
        edges = [safe_row(e) for e in all_edges
                 if e["source_id"] in comment_id_set and e["target_id"] in comment_id_set]

        return {
            "hubs": [safe_row(h) for h in hubs],
            "comments": [safe_row(c) for c in comments],
            "edges": edges,
        }
    finally:
        conn.close()


# ── Comment cluster detail ─────────────────────────────────────────────

@app.get("/api/comment-cluster/{cluster_id}")
def comment_cluster_detail(cluster_id: int):
    conn = get_db()
    try:
        cluster = conn.execute(
            "SELECT * FROM comment_clusters WHERE cluster_id = ?", (cluster_id,)
        ).fetchone()
        if not cluster:
            return {"error": "not found"}
        d = safe_row(cluster)
        try:
            d["keywords"] = json.loads(d.get("keywords") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["keywords"] = []

        # Top comments by score
        top_comments = conn.execute("""
            SELECT cm.id, cm.body, cm.author, cm.score, cm.post_id,
                   ce.dominant_emotion, ce.sentiment, cs.stance,
                   p.title as post_title
            FROM comment_cluster_assignments cca
            JOIN comments cm ON cm.id = cca.comment_id
            JOIN comment_emotions ce ON ce.comment_id = cm.id
            LEFT JOIN comment_stance cs ON cs.comment_id = cm.id
            JOIN posts p ON p.id = cm.post_id
            WHERE cca.cluster_id = ?
            ORDER BY cm.score DESC
            LIMIT 10
        """, (cluster_id,)).fetchall()
        d["top_comments"] = [safe_row(c) for c in top_comments]

        # Emotion breakdown
        emotions = conn.execute("""
            SELECT ce.dominant_emotion, COUNT(*) as cnt
            FROM comment_cluster_assignments cca
            JOIN comment_emotions ce ON ce.comment_id = cca.comment_id
            WHERE cca.cluster_id = ?
            GROUP BY ce.dominant_emotion ORDER BY cnt DESC
        """, (cluster_id,)).fetchall()
        d["emotions"] = [safe_row(e) for e in emotions]

        # Sentiment breakdown
        sentiment = conn.execute("""
            SELECT ce.sentiment, COUNT(*) as cnt
            FROM comment_cluster_assignments cca
            JOIN comment_emotions ce ON ce.comment_id = cca.comment_id
            WHERE cca.cluster_id = ?
            GROUP BY ce.sentiment
        """, (cluster_id,)).fetchall()
        d["sentiment"] = {r["sentiment"]: r["cnt"] for r in sentiment}

        return d
    finally:
        conn.close()


# ── Serve frontend static files ────────────────────────────────────────

if DIST_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        """Serve index.html for all non-API routes (SPA fallback)."""
        file_path = DIST_DIR / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(DIST_DIR / "index.html"))
