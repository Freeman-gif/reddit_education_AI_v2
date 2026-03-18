"""Generate embeddings for posts missing them, using local Ollama nomic-embed-text."""

import sqlite3
import struct
from pathlib import Path
import requests

DB_PATH = Path(__file__).parent.parent / "data" / "reddit_ai_k12.db"
OLLAMA_URL = "http://localhost:11434/api/embeddings"
MODEL = "nomic-embed-text"

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT p.id, p.title, p.selftext, c.summary, c.category, c.tags
    FROM posts p
    JOIN classifications c ON c.post_id = p.id
    WHERE c.relevant = 1
      AND p.id NOT IN (SELECT post_id FROM embeddings)
""").fetchall()

print(f"Embedding {len(rows)} new posts via Ollama {MODEL}...")

for i, r in enumerate(rows):
    text = f"search_document: {r['summary'] or r['title'] or ''}. Tags: {r['tags'] or ''}. Category: {r['category'] or ''}"
    text = text.strip()[:500]
    if not text:
        text = "empty"

    try:
        resp = requests.post(OLLAMA_URL, json={"model": MODEL, "prompt": text}, timeout=30)
        resp.raise_for_status()
        embedding = resp.json()["embedding"]
        blob = struct.pack(f"{len(embedding)}f", *embedding)
        conn.execute(
            "INSERT OR REPLACE INTO embeddings (post_id, vector, model_name) VALUES (?, ?, ?)",
            (r["id"], blob, MODEL),
        )
        if (i + 1) % 50 == 0:
            conn.commit()
            print(f"  {i + 1}/{len(rows)}")
    except Exception as e:
        print(f"  Error on {r['id']}: {e}")

conn.commit()
total = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
print(f"Done! {total} total post embeddings.")
conn.close()
