"""SQLite database schema and CRUD operations."""

import sqlite3
from contextlib import contextmanager
from typing import Optional

from config import DB_PATH, DATA_DIR


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_session():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """Create tables and indexes."""
    with db_session() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS posts (
                id TEXT PRIMARY KEY,
                subreddit TEXT NOT NULL,
                author TEXT,
                title TEXT,
                selftext TEXT,
                url TEXT,
                score INTEGER DEFAULT 0,
                num_comments INTEGER DEFAULT 0,
                created_utc REAL,
                permalink TEXT,
                source TEXT,  -- 'arctic_shift' or 'praw'
                search_query TEXT,
                keyword_match INTEGER DEFAULT NULL,  -- NULL=unchecked, 0=no, 1=yes
                llm_relevant INTEGER DEFAULT NULL,   -- NULL=unchecked, 0=no, 1=yes
                llm_confidence REAL DEFAULT NULL,
                llm_category TEXT DEFAULT NULL,
                llm_reasoning TEXT DEFAULT NULL,
                collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS comments (
                id TEXT PRIMARY KEY,
                post_id TEXT NOT NULL,
                parent_id TEXT,
                author TEXT,
                body TEXT,
                score INTEGER DEFAULT 0,
                created_utc REAL,
                depth INTEGER DEFAULT 0,
                collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (post_id) REFERENCES posts(id)
            );

            CREATE TABLE IF NOT EXISTS collection_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,       -- 'arctic_shift' or 'praw'
                subreddit TEXT NOT NULL,
                query TEXT,                 -- search query or NULL for broad sweep
                last_timestamp REAL,        -- for resume cursor
                status TEXT DEFAULT 'pending',  -- pending, running, completed, failed
                posts_collected INTEGER DEFAULT 0,
                started_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source, subreddit, query)
            );

            CREATE TABLE IF NOT EXISTS classifications (
                post_id TEXT PRIMARY KEY,
                relevant INTEGER NOT NULL,       -- 0=no, 1=yes
                confidence REAL,
                category TEXT,
                tags TEXT,                        -- JSON array of tags
                summary TEXT,                     -- LLM-generated summary
                reasoning TEXT,
                classified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (post_id) REFERENCES posts(id)
            );

            CREATE INDEX IF NOT EXISTS idx_posts_subreddit ON posts(subreddit);
            CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_utc);
            CREATE INDEX IF NOT EXISTS idx_posts_keyword ON posts(keyword_match);
            CREATE INDEX IF NOT EXISTS idx_cls_relevant ON classifications(relevant);
            CREATE INDEX IF NOT EXISTS idx_cls_category ON classifications(category);
            CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON collection_jobs(status);
        """)


# ── Post CRUD ────────────────────────────────────────────────────────────────

def upsert_post(conn: sqlite3.Connection, post: dict):
    """Insert or update a post."""
    conn.execute("""
        INSERT INTO posts (id, subreddit, author, title, selftext, url, score,
                          num_comments, created_utc, permalink, source, search_query)
        VALUES (:id, :subreddit, :author, :title, :selftext, :url, :score,
                :num_comments, :created_utc, :permalink, :source, :search_query)
        ON CONFLICT(id) DO UPDATE SET
            score = MAX(posts.score, excluded.score),
            num_comments = MAX(posts.num_comments, excluded.num_comments)
    """, post)


def post_exists(conn: sqlite3.Connection, post_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM posts WHERE id = ?", (post_id,)).fetchone()
    return row is not None


def get_unfiltered_posts(conn: sqlite3.Connection) -> list:
    """Posts that haven't been keyword-filtered yet."""
    return conn.execute(
        "SELECT id, title, selftext FROM posts WHERE keyword_match IS NULL"
    ).fetchall()


def get_keyword_matched_unclassified(conn: sqlite3.Connection) -> list:
    """Posts that passed keyword filter but haven't been LLM-classified."""
    return conn.execute(
        "SELECT p.id, p.subreddit, p.title, p.selftext FROM posts p "
        "WHERE p.keyword_match = 1 "
        "AND NOT EXISTS (SELECT 1 FROM classifications c WHERE c.post_id = p.id)"
    ).fetchall()


def get_relevant_posts_without_comments(conn: sqlite3.Connection) -> list:
    """LLM-relevant posts that don't have comments collected yet."""
    return conn.execute("""
        SELECT p.id, p.permalink FROM posts p
        JOIN classifications c ON c.post_id = p.id
        WHERE c.relevant = 1
        AND NOT EXISTS (SELECT 1 FROM comments cm WHERE cm.post_id = p.id)
    """).fetchall()


def update_keyword_match(conn: sqlite3.Connection, post_id: str, match: bool):
    conn.execute(
        "UPDATE posts SET keyword_match = ? WHERE id = ?",
        (1 if match else 0, post_id)
    )


def upsert_classification(conn: sqlite3.Connection, post_id: str,
                          relevant: bool, confidence: float,
                          category: str, tags: str,
                          summary: str, reasoning: str):
    """Insert or replace classification in separate table (never modifies posts)."""
    conn.execute("""
        INSERT INTO classifications (post_id, relevant, confidence, category, tags, summary, reasoning)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(post_id) DO UPDATE SET
            relevant=excluded.relevant, confidence=excluded.confidence,
            category=excluded.category, tags=excluded.tags,
            summary=excluded.summary, reasoning=excluded.reasoning,
            classified_at=CURRENT_TIMESTAMP
    """, (post_id, 1 if relevant else 0, confidence, category, tags, summary, reasoning))


# ── Comment CRUD ─────────────────────────────────────────────────────────────

def upsert_comment(conn: sqlite3.Connection, comment: dict):
    conn.execute("""
        INSERT INTO comments (id, post_id, parent_id, author, body, score, created_utc, depth)
        VALUES (:id, :post_id, :parent_id, :author, :body, :score, :created_utc, :depth)
        ON CONFLICT(id) DO UPDATE SET
            score = MAX(comments.score, excluded.score)
    """, comment)


# ── Job Tracking ─────────────────────────────────────────────────────────────

def get_or_create_job(conn: sqlite3.Connection, source: str, subreddit: str,
                      query: Optional[str] = None) -> dict:
    row = conn.execute(
        "SELECT * FROM collection_jobs WHERE source=? AND subreddit=? AND query IS ?",
        (source, subreddit, query)
    ).fetchone()
    if row:
        return dict(row)
    conn.execute(
        "INSERT INTO collection_jobs (source, subreddit, query, status) VALUES (?, ?, ?, 'pending')",
        (source, subreddit, query)
    )
    conn.commit()
    return dict(conn.execute(
        "SELECT * FROM collection_jobs WHERE source=? AND subreddit=? AND query IS ?",
        (source, subreddit, query)
    ).fetchone())


def update_job(conn: sqlite3.Connection, job_id: int, **kwargs):
    sets = ", ".join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [job_id]
    conn.execute(
        f"UPDATE collection_jobs SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        vals
    )


# ── Stats ────────────────────────────────────────────────────────────────────

def get_stats(conn: sqlite3.Connection) -> dict:
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
    stats["by_subreddit"] = {
        row["subreddit"]: row["cnt"]
        for row in conn.execute(
            "SELECT subreddit, COUNT(*) as cnt FROM posts GROUP BY subreddit"
        ).fetchall()
    }
    stats["by_category"] = {
        row["category"]: row["cnt"]
        for row in conn.execute(
            "SELECT category, COUNT(*) as cnt FROM classifications "
            "WHERE relevant = 1 GROUP BY category"
        ).fetchall()
    }
    return stats
