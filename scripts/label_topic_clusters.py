"""Generate better labels for topic clusters using Qwen3 via Ollama."""

import json
import sqlite3
from pathlib import Path
import requests

DB_PATH = Path(__file__).parent.parent / "data" / "reddit_ai_k12.db"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3:32b"

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

clusters = conn.execute("SELECT * FROM topics WHERE level = 1").fetchall()

for c in clusters:
    tid = c["topic_id"]
    keywords = c["keywords"]
    count = c["count"]
    current = c["llm_label"]

    samples = conn.execute("""
        SELECT p.title FROM topic_assignments ta
        JOIN posts p ON p.id = ta.post_id
        WHERE ta.level1_id = ? AND LENGTH(p.title) > 20
        ORDER BY p.score DESC LIMIT 5
    """, (tid,)).fetchall()

    sample_text = "\n".join(f"- {s['title'][:150]}" for s in samples)

    prompt = f"""I have a cluster of {count} Reddit posts about AI in K-12 education.
Top TF-IDF keywords: {keywords}

Sample post titles:
{sample_text}

Give me a short, descriptive label (2-5 words) that captures the unique theme of this cluster.
Be specific — avoid generic labels like "AI in Education". Focus on what makes this cluster different.
Reply with ONLY the label, nothing else. No quotes, no explanation."""

    print(f"\nTopic {tid} (current: {current}, {count} posts):")

    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3},
        }, timeout=300)
        resp.raise_for_status()
        new_label = resp.json()["response"].strip().strip('"').strip("'")
        if "</think>" in new_label:
            new_label = new_label.split("</think>")[-1].strip()
        print(f"  New label: {new_label}")

        conn.execute(
            "UPDATE topics SET llm_label = ? WHERE topic_id = ?",
            (new_label, tid),
        )
    except Exception as e:
        print(f"  Error: {e}")

conn.commit()
conn.close()
print("\nDone!")
