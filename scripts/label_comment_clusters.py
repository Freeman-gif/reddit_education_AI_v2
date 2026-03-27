"""Generate better labels for comment clusters using Qwen3-32B via Ollama."""

import json
import sqlite3
from pathlib import Path
import requests

DB_PATH = Path(__file__).parent.parent / "data" / "reddit_ai_k12.db"
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3:32b"

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

clusters = conn.execute("SELECT * FROM comment_clusters").fetchall()

for c in clusters:
    cid = c["cluster_id"]
    keywords = c["keywords"]
    count = c["count"]

    # Get top sample comments
    samples = conn.execute("""
        SELECT cm.body FROM comment_cluster_assignments cca
        JOIN comments cm ON cm.id = cca.comment_id
        WHERE cca.cluster_id = ? AND LENGTH(cm.body) > 20
        ORDER BY cm.score DESC LIMIT 5
    """, (cid,)).fetchall()

    sample_text = "\n".join(f"- {s['body'][:200]}" for s in samples)

    prompt = f"""I have a cluster of {count} Reddit comments about AI in K-12 education.
Here are the top TF-IDF keywords: {keywords}

Sample comments from this cluster:
{sample_text}

Give me a short, descriptive label (2-5 words) that captures the main theme of this cluster.
The label should be specific and meaningful, not generic.
Reply with ONLY the label, nothing else. No quotes, no explanation."""

    print(f"\nCluster {cid} (current: {c['label']}, {count} comments):")
    print(f"  Keywords: {keywords}")

    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3},
        }, timeout=300)
        resp.raise_for_status()
        new_label = resp.json()["response"].strip().strip('"').strip("'")
        # Remove any thinking tags if present
        if "</think>" in new_label:
            new_label = new_label.split("</think>")[-1].strip()
        print(f"  New label: {new_label}")

        conn.execute(
            "UPDATE comment_clusters SET label = ? WHERE cluster_id = ?",
            (new_label, cid),
        )
    except Exception as e:
        print(f"  Error: {e}")

conn.commit()
conn.close()
print("\nDone!")
