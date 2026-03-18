"""Analysis DB tables and CRUD operations."""

import json
import sqlite3
from contextlib import contextmanager

from analysis.config import DB_PATH, DATA_DIR


def get_connection() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
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


def init_analysis_tables():
    """Create analysis-specific tables."""
    with db_session() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS analysis_texts (
                post_id TEXT PRIMARY KEY REFERENCES posts(id),
                embed_text TEXT NOT NULL,
                summary_source TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS embeddings (
                post_id TEXT PRIMARY KEY REFERENCES posts(id),
                vector BLOB NOT NULL,
                model_name TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS topic_assignments (
                post_id TEXT PRIMARY KEY REFERENCES posts(id),
                topic_id INTEGER NOT NULL,
                probability REAL,
                umap_x REAL,
                umap_y REAL,
                level1_id INTEGER,
                level2_id INTEGER
            );

            CREATE TABLE IF NOT EXISTS topics (
                topic_id INTEGER PRIMARY KEY,
                level INTEGER NOT NULL,
                parent_id INTEGER,
                count INTEGER,
                keywords TEXT,
                auto_label TEXT,
                llm_label TEXT,
                llm_description TEXT
            );

            CREATE TABLE IF NOT EXISTS comment_emotions (
                comment_id TEXT PRIMARY KEY REFERENCES comments(id),
                emotions TEXT NOT NULL,
                dominant_emotion TEXT,
                sentiment TEXT
            );

            CREATE TABLE IF NOT EXISTS comment_stance (
                comment_id TEXT PRIMARY KEY REFERENCES comments(id),
                agree_score REAL,
                disagree_score REAL,
                neutral_score REAL,
                stance TEXT
            );

            CREATE TABLE IF NOT EXISTS topic_emotion_agg (
                topic_id INTEGER,
                level INTEGER,
                num_comments INTEGER,
                emotion_distribution TEXT,
                dominant_emotion TEXT,
                agree_pct REAL,
                disagree_pct REAL,
                neutral_pct REAL,
                PRIMARY KEY (topic_id, level)
            );

            CREATE TABLE IF NOT EXISTS topics_over_time (
                topic_id INTEGER,
                time_bin TEXT,
                frequency INTEGER,
                keywords TEXT,
                PRIMARY KEY (topic_id, time_bin)
            );

            CREATE TABLE IF NOT EXISTS post_edges (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                weight REAL NOT NULL,
                PRIMARY KEY (source_id, target_id)
            );
            CREATE TABLE IF NOT EXISTS topic_edges (
                source_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                weight REAL NOT NULL,
                PRIMARY KEY (source_id, target_id)
            );

            CREATE INDEX IF NOT EXISTS idx_ta_topic ON topic_assignments(topic_id);
            CREATE INDEX IF NOT EXISTS idx_ta_l1 ON topic_assignments(level1_id);
            CREATE INDEX IF NOT EXISTS idx_ta_l2 ON topic_assignments(level2_id);
            CREATE INDEX IF NOT EXISTS idx_ce_sentiment ON comment_emotions(sentiment);
            CREATE INDEX IF NOT EXISTS idx_cs_stance ON comment_stance(stance);
            CREATE INDEX IF NOT EXISTS idx_pe_source ON post_edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_pe_target ON post_edges(target_id);
        """)


# ── Analysis Texts ───────────────────────────────────────────────────────────

def upsert_analysis_text(conn, post_id: str, embed_text: str, summary_source: str):
    conn.execute("""
        INSERT INTO analysis_texts (post_id, embed_text, summary_source)
        VALUES (?, ?, ?)
        ON CONFLICT(post_id) DO UPDATE SET
            embed_text=excluded.embed_text, summary_source=excluded.summary_source
    """, (post_id, embed_text, summary_source))


def get_analysis_texts(conn) -> list:
    return conn.execute(
        "SELECT post_id, embed_text FROM analysis_texts ORDER BY post_id"
    ).fetchall()


# ── Embeddings ───────────────────────────────────────────────────────────────

def upsert_embedding(conn, post_id: str, vector: bytes, model_name: str):
    conn.execute("""
        INSERT INTO embeddings (post_id, vector, model_name)
        VALUES (?, ?, ?)
        ON CONFLICT(post_id) DO UPDATE SET
            vector=excluded.vector, model_name=excluded.model_name
    """, (post_id, vector, model_name))


def get_all_embeddings(conn) -> list:
    return conn.execute(
        "SELECT post_id, vector FROM embeddings ORDER BY post_id"
    ).fetchall()


def get_unembedded_posts(conn) -> list:
    return conn.execute("""
        SELECT at.post_id, at.embed_text FROM analysis_texts at
        WHERE NOT EXISTS (SELECT 1 FROM embeddings e WHERE e.post_id = at.post_id)
        ORDER BY at.post_id
    """).fetchall()


# ── Topic Assignments ────────────────────────────────────────────────────────

def upsert_topic_assignment(conn, post_id: str, topic_id: int,
                            probability: float, umap_x: float, umap_y: float):
    conn.execute("""
        INSERT INTO topic_assignments (post_id, topic_id, probability, umap_x, umap_y)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(post_id) DO UPDATE SET
            topic_id=excluded.topic_id, probability=excluded.probability,
            umap_x=excluded.umap_x, umap_y=excluded.umap_y
    """, (post_id, topic_id, probability, umap_x, umap_y))


def update_topic_levels(conn, post_id: str, level1_id: int, level2_id: int):
    conn.execute("""
        UPDATE topic_assignments SET level1_id=?, level2_id=? WHERE post_id=?
    """, (level1_id, level2_id, post_id))


# ── Topics ───────────────────────────────────────────────────────────────────

def upsert_topic(conn, topic_id: int, level: int, parent_id: int,
                 count: int, keywords: str, auto_label: str,
                 llm_label: str = None, llm_description: str = None):
    conn.execute("""
        INSERT INTO topics (topic_id, level, parent_id, count, keywords,
                           auto_label, llm_label, llm_description)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(topic_id) DO UPDATE SET
            level=excluded.level, parent_id=excluded.parent_id,
            count=excluded.count, keywords=excluded.keywords,
            auto_label=excluded.auto_label, llm_label=excluded.llm_label,
            llm_description=excluded.llm_description
    """, (topic_id, level, parent_id, count, keywords, auto_label,
          llm_label, llm_description))


def update_topic_llm_label(conn, topic_id: int, llm_label: str, llm_description: str):
    conn.execute("""
        UPDATE topics SET llm_label=?, llm_description=? WHERE topic_id=?
    """, (llm_label, llm_description, topic_id))


# ── Comment Emotions ─────────────────────────────────────────────────────────

def upsert_comment_emotion(conn, comment_id: str, emotions: dict,
                           dominant_emotion: str, sentiment: str):
    conn.execute("""
        INSERT INTO comment_emotions (comment_id, emotions, dominant_emotion, sentiment)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(comment_id) DO UPDATE SET
            emotions=excluded.emotions, dominant_emotion=excluded.dominant_emotion,
            sentiment=excluded.sentiment
    """, (comment_id, json.dumps(emotions), dominant_emotion, sentiment))


def get_unprocessed_comments(conn) -> list:
    return conn.execute("""
        SELECT c.id, c.body, c.post_id, c.depth FROM comments c
        WHERE NOT EXISTS (SELECT 1 FROM comment_emotions ce WHERE ce.comment_id = c.id)
        ORDER BY c.depth ASC, c.id
    """).fetchall()


# ── Comment Stance ───────────────────────────────────────────────────────────

def upsert_comment_stance(conn, comment_id: str, agree: float,
                          disagree: float, neutral: float, stance: str):
    conn.execute("""
        INSERT INTO comment_stance (comment_id, agree_score, disagree_score,
                                    neutral_score, stance)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(comment_id) DO UPDATE SET
            agree_score=excluded.agree_score, disagree_score=excluded.disagree_score,
            neutral_score=excluded.neutral_score, stance=excluded.stance
    """, (comment_id, agree, disagree, neutral, stance))


def get_comments_without_stance(conn) -> list:
    return conn.execute("""
        SELECT c.id, c.body, c.post_id FROM comments c
        WHERE NOT EXISTS (SELECT 1 FROM comment_stance cs WHERE cs.comment_id = c.id)
        ORDER BY c.id
    """).fetchall()


# ── Aggregations ─────────────────────────────────────────────────────────────

def upsert_post_edge(conn, source_id: str, target_id: str, weight: float):
    conn.execute("""
        INSERT INTO post_edges (source_id, target_id, weight)
        VALUES (?, ?, ?)
        ON CONFLICT(source_id, target_id) DO UPDATE SET weight=excluded.weight
    """, (source_id, target_id, weight))


def upsert_topic_edge(conn, source_id: int, target_id: int, weight: float):
    conn.execute("""
        INSERT INTO topic_edges (source_id, target_id, weight)
        VALUES (?, ?, ?)
        ON CONFLICT(source_id, target_id) DO UPDATE SET weight=excluded.weight
    """, (source_id, target_id, weight))


# ── Aggregations ─────────────────────────────────────────────────────────

def upsert_topic_emotion_agg(conn, topic_id: int, level: int, num_comments: int,
                             emotion_distribution: dict, dominant_emotion: str,
                             agree_pct: float, disagree_pct: float, neutral_pct: float):
    conn.execute("""
        INSERT INTO topic_emotion_agg (topic_id, level, num_comments,
            emotion_distribution, dominant_emotion, agree_pct, disagree_pct, neutral_pct)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(topic_id, level) DO UPDATE SET
            num_comments=excluded.num_comments,
            emotion_distribution=excluded.emotion_distribution,
            dominant_emotion=excluded.dominant_emotion,
            agree_pct=excluded.agree_pct, disagree_pct=excluded.disagree_pct,
            neutral_pct=excluded.neutral_pct
    """, (topic_id, level, num_comments, json.dumps(emotion_distribution),
          dominant_emotion, agree_pct, disagree_pct, neutral_pct))


def upsert_topic_over_time(conn, topic_id: int, time_bin: str,
                           frequency: int, keywords: str):
    conn.execute("""
        INSERT INTO topics_over_time (topic_id, time_bin, frequency, keywords)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(topic_id, time_bin) DO UPDATE SET
            frequency=excluded.frequency, keywords=excluded.keywords
    """, (topic_id, time_bin, frequency, keywords))
