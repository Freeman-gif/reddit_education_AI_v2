"""Generate embeddings for all comments using Ollama nomic-embed-text on Frame Desktop."""

import json
import sqlite3
import struct
from pathlib import Path
import requests

DB_PATH = Path(__file__).parent.parent / "data" / "reddit_ai_k12.db"
OLLAMA_URL = "http://192.168.1.146:11434/api/embeddings"
MODEL = "nomic-embed-text"

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

# Create table
conn.execute("""
    CREATE TABLE IF NOT EXISTS comment_embeddings (
        comment_id TEXT PRIMARY KEY REFERENCES comments(id),
        vector BLOB NOT NULL,
        model_name TEXT NOT NULL
    )
""")
conn.commit()

# Get comments that don't have embeddings yet
rows = conn.execute("""
    SELECT c.id, c.body FROM comments c
    WHERE c.id NOT IN (SELECT comment_id FROM comment_embeddings)
""").fetchall()

print(f"Embedding {len(rows)} comments via Ollama {MODEL}...")

for i, r in enumerate(rows):
    text = (r["body"] or "").strip()
    if not text:
        text = "empty"

    try:
        resp = requests.post(OLLAMA_URL, json={"model": MODEL, "prompt": text}, timeout=30)
        resp.raise_for_status()
        embedding = resp.json()["embedding"]

        blob = struct.pack(f"{len(embedding)}f", *embedding)
        conn.execute(
            "INSERT OR REPLACE INTO comment_embeddings (comment_id, vector, model_name) VALUES (?, ?, ?)",
            (r["id"], blob, MODEL),
        )

        if (i + 1) % 50 == 0:
            conn.commit()
            print(f"  {i + 1}/{len(rows)}")
    except Exception as e:
        print(f"  Error on {r['id']}: {e}")

conn.commit()
total = conn.execute("SELECT COUNT(*) FROM comment_embeddings").fetchone()[0]
print(f"Done! {total} comment embeddings stored.")
conn.close()
