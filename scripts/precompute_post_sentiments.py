"""Pre-compute post-level emotional sentiment using GoEmotions NLP model.

Classifies each post's text (title + selftext) into one of 6 sentiment groups:
  sentiment_frustrated, sentiment_concerned, sentiment_sad,
  sentiment_optimistic, sentiment_curious, sentiment_neutral

Creates/populates `post_sentiments` table.

Run on Frame Desktop:
  ~/reddit_scrap/.venv/bin/python3 scripts/precompute_post_sentiments.py
"""

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "reddit_ai_k12.db"
GO_EMOTIONS_MODEL = "SamLowe/roberta-base-go_emotions"
BATCH_SIZE = 32

# GoEmotions 28 labels → 6 sentiment groups
EMOTION_TO_SENTIMENT = {
    "anger": "sentiment_frustrated",
    "annoyance": "sentiment_frustrated",
    "disapproval": "sentiment_frustrated",
    "disgust": "sentiment_frustrated",
    "fear": "sentiment_concerned",
    "nervousness": "sentiment_concerned",
    "caring": "sentiment_concerned",
    "confusion": "sentiment_concerned",
    "sadness": "sentiment_sad",
    "grief": "sentiment_sad",
    "disappointment": "sentiment_sad",
    "remorse": "sentiment_sad",
    "embarrassment": "sentiment_sad",
    "joy": "sentiment_optimistic",
    "optimism": "sentiment_optimistic",
    "excitement": "sentiment_optimistic",
    "pride": "sentiment_optimistic",
    "gratitude": "sentiment_optimistic",
    "admiration": "sentiment_optimistic",
    "approval": "sentiment_optimistic",
    "love": "sentiment_optimistic",
    "relief": "sentiment_optimistic",
    "amusement": "sentiment_optimistic",
    "curiosity": "sentiment_curious",
    "surprise": "sentiment_curious",
    "realization": "sentiment_curious",
    "desire": "sentiment_curious",
    "neutral": "sentiment_neutral",
}


def get_device():
    """Detect best available device (ROCm iGPU > CPU)."""
    import torch
    os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "11.0.0")
    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        return 0, name
    return -1, "CPU"


conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

# ── 1. Create table ──────────────────────────────────────────────────────

conn.execute("""CREATE TABLE IF NOT EXISTS post_sentiments (
    post_id TEXT PRIMARY KEY,
    emotions_json TEXT NOT NULL,
    dominant_emotion TEXT,
    sentiment_group TEXT,
    created_month TEXT
)""")
conn.execute("CREATE INDEX IF NOT EXISTS idx_ps_sentiment ON post_sentiments(sentiment_group)")
conn.execute("CREATE INDEX IF NOT EXISTS idx_ps_month ON post_sentiments(created_month)")
conn.commit()

# ── 2. Get posts to process ──────────────────────────────────────────────

existing = set(r[0] for r in conn.execute("SELECT post_id FROM post_sentiments").fetchall())

rows = conn.execute("""
    SELECT p.id as post_id, p.title, p.selftext, p.created_utc
    FROM posts p
    JOIN topic_assignments ta ON ta.post_id = p.id
    WHERE ta.level1_id IS NOT NULL
""").fetchall()

# Filter out already processed
to_process = [r for r in rows if r["post_id"] not in existing]
print(f"Total posts with topics: {len(rows)}")
print(f"Already processed: {len(existing)}")
print(f"To process: {len(to_process)}")

if not to_process:
    print("Nothing to do.")
    conn.close()
    exit(0)

# ── 3. Load model ────────────────────────────────────────────────────────

from transformers import pipeline as hf_pipeline

device, device_name = get_device()
print(f"Loading GoEmotions on {device_name}...")

classifier = hf_pipeline(
    "text-classification",
    model=GO_EMOTIONS_MODEL,
    top_k=None,
    truncation=True,
    max_length=512,
    device=device,
)
print("Model loaded.")

# ── 4. Classify in batches ───────────────────────────────────────────────

processed = 0
for i in range(0, len(to_process), BATCH_SIZE):
    batch = to_process[i:i + BATCH_SIZE]

    # Build input texts
    texts = []
    for r in batch:
        title = r["title"] or ""
        selftext = (r["selftext"] or "")[:500]
        # Skip [removed]/[deleted] body text
        if selftext in ("[removed]", "[deleted]"):
            selftext = ""
        text = f"{title}. {selftext}".strip() if selftext else title
        texts.append(text if text.strip() else "neutral")

    results = classifier(texts)

    for r, result in zip(batch, results):
        # Extract emotions with score > 0.05
        emotions = {item["label"]: round(item["score"], 4) for item in result if item["score"] > 0.05}
        if not emotions:
            emotions = {result[0]["label"]: round(result[0]["score"], 4)}

        dominant = max(emotions, key=emotions.get)
        sentiment_group = EMOTION_TO_SENTIMENT.get(dominant, "sentiment_neutral")

        # Compute created_month
        utc = r["created_utc"]
        if utc:
            created_month = datetime.utcfromtimestamp(float(utc)).strftime("%Y-%m")
        else:
            created_month = ""

        conn.execute(
            "INSERT OR REPLACE INTO post_sentiments VALUES (?, ?, ?, ?, ?)",
            (r["post_id"], json.dumps(emotions), dominant, sentiment_group, created_month),
        )

    processed += len(batch)
    conn.commit()
    print(f"  {processed}/{len(to_process)} posts processed")

# ── 5. Summary ───────────────────────────────────────────────────────────

print("\n=== Sentiment distribution ===")
dist = conn.execute("""
    SELECT sentiment_group, COUNT(*) as cnt
    FROM post_sentiments
    GROUP BY sentiment_group
    ORDER BY cnt DESC
""").fetchall()
for r in dist:
    print(f"  {r['sentiment_group']}: {r['cnt']}")

total = conn.execute("SELECT COUNT(*) FROM post_sentiments").fetchone()[0]
print(f"\nTotal: {total} posts with sentiments")
conn.close()
print("Done!")
