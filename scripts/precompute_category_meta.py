"""Pre-compute enriched category metadata for the Topic Network drill-down.

Creates:
  - topic_category_meta: tags, subreddits, LLM paragraph summary per L1 topic
  - topic_overlap_edges: cross-category KNN edge counts + shared tags

Run on Frame Desktop:
  ~/reddit_scrap/.venv/bin/python3 scripts/precompute_category_meta.py
"""

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import requests

DB_PATH = Path(__file__).parent.parent / "data" / "reddit_ai_k12.db"
OLLAMA_URL = "http://localhost:11434/api/chat"
LLM_MODEL = "qwen3:32b"

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

# ── 1. Build post → topic map ────────────────────────────────────────────

print("Building post → topic map...")
topic_map = {}
rows = conn.execute("SELECT post_id, level1_id FROM topic_assignments WHERE level1_id IS NOT NULL").fetchall()
for r in rows:
    topic_map[r["post_id"]] = r["level1_id"]
print(f"  {len(topic_map)} posts mapped to L1 topics")

# ── 2. Tag distribution per topic ────────────────────────────────────────

print("\nComputing tag distributions...")
tag_counts = defaultdict(Counter)  # topic_id → Counter({tag: count})

rows = conn.execute("""
    SELECT c.post_id, c.tags
    FROM classifications c
    WHERE c.relevant = 1 AND c.tags IS NOT NULL
""").fetchall()

for r in rows:
    pid = r["post_id"]
    tid = topic_map.get(pid)
    if tid is None:
        continue
    try:
        tags = json.loads(r["tags"])
        if isinstance(tags, list):
            for tag in tags:
                tag_counts[tid][tag] += 1
    except (json.JSONDecodeError, TypeError):
        pass

for tid, counter in tag_counts.items():
    top = counter.most_common(10)
    print(f"  Topic {tid}: {top[:5]}")

# ── 3. Subreddit distribution per topic ──────────────────────────────────

print("\nComputing subreddit distributions...")
sub_counts = defaultdict(Counter)  # topic_id → Counter({subreddit: count})

rows = conn.execute("""
    SELECT p.id as post_id, p.subreddit
    FROM posts p
    JOIN topic_assignments ta ON ta.post_id = p.id
    WHERE ta.level1_id IS NOT NULL
""").fetchall()

for r in rows:
    tid = topic_map.get(r["post_id"])
    if tid is not None:
        sub_counts[tid][r["subreddit"]] += 1

for tid, counter in sub_counts.items():
    print(f"  Topic {tid}: {counter.most_common(5)}")

# ── 4. Cross-category overlap edges ─────────────────────────────────────

print("\nComputing cross-category overlap edges...")
overlap_counts = Counter()
edges = conn.execute("SELECT source_id, target_id FROM post_edges").fetchall()

for e in edges:
    src_topic = topic_map.get(e["source_id"])
    tgt_topic = topic_map.get(e["target_id"])
    if src_topic and tgt_topic and src_topic != tgt_topic:
        pair = tuple(sorted([src_topic, tgt_topic]))
        overlap_counts[pair] += 1

print(f"  {len(overlap_counts)} cross-category pairs found")
for pair, count in overlap_counts.most_common():
    print(f"    {pair[0]} ↔ {pair[1]}: {count} edges")

# Shared tags between overlapping topic pairs
overlap_shared_tags = {}
for (t1, t2), _ in overlap_counts.items():
    tags1 = set(tag_counts[t1].keys())
    tags2 = set(tag_counts[t2].keys())
    shared = tags1 & tags2
    overlap_shared_tags[(t1, t2)] = sorted(shared)[:10]

# ── 5. LLM paragraph summaries ──────────────────────────────────────────

print("\nGenerating LLM paragraph summaries...")
topics = conn.execute("""
    SELECT topic_id, llm_label, keywords FROM topics WHERE level = 1
""").fetchall()

topic_summaries = {}
for t in topics:
    tid = t["topic_id"]
    label = t["llm_label"] or f"Topic {tid}"
    keywords = []
    try:
        keywords = json.loads(t["keywords"] or "[]")
    except (json.JSONDecodeError, TypeError):
        pass

    # Get top 10 post titles for this topic
    top_posts = conn.execute("""
        SELECT p.title FROM topic_assignments ta
        JOIN posts p ON p.id = ta.post_id
        WHERE ta.level1_id = ?
        ORDER BY p.score DESC LIMIT 10
    """, (tid,)).fetchall()
    titles = [r["title"] for r in top_posts]

    top_tags = [tag for tag, _ in tag_counts[tid].most_common(8)]

    prompt = (
        f"Topic: {label}\n"
        f"Keywords: {', '.join(keywords[:10])}\n"
        f"Common tags: {', '.join(top_tags)}\n"
        f"Top post titles:\n" + "\n".join(f"- {t}" for t in titles) + "\n\n"
        f"Write a 2-3 sentence paragraph summarizing what this topic cluster is about. "
        f"Focus on the main themes and concerns expressed by educators. Be concise."
    )

    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.3, "num_predict": 200},
        }, timeout=120)
        text = resp.json().get("message", {}).get("content", "")
        topic_summaries[tid] = text.strip()
        print(f"  Topic {tid} ({label}): {text.strip()[:80]}...")
    except Exception as e:
        print(f"  Topic {tid}: LLM failed ({e})")
        topic_summaries[tid] = f"Posts about {label.lower()} in K-12 education."

# ── 6. Write to DB ───────────────────────────────────────────────────────

print("\nWriting to database...")

conn.execute("""CREATE TABLE IF NOT EXISTS topic_category_meta (
    topic_id INTEGER PRIMARY KEY,
    tags_json TEXT,
    subreddits_json TEXT,
    paragraph_summary TEXT
)""")
conn.execute("DELETE FROM topic_category_meta")

for tid in set(topic_map.values()):
    tags_list = [{"tag": tag, "count": count} for tag, count in tag_counts[tid].most_common(10)]
    subs_list = [{"subreddit": sub, "count": count} for sub, count in sub_counts[tid].most_common()]
    conn.execute(
        "INSERT INTO topic_category_meta VALUES (?, ?, ?, ?)",
        (tid, json.dumps(tags_list), json.dumps(subs_list), topic_summaries.get(tid, "")),
    )

conn.execute("""CREATE TABLE IF NOT EXISTS topic_overlap_edges (
    source_id INTEGER,
    target_id INTEGER,
    overlap_count INTEGER,
    shared_tags_json TEXT,
    PRIMARY KEY (source_id, target_id)
)""")
conn.execute("DELETE FROM topic_overlap_edges")

for (t1, t2), count in overlap_counts.items():
    conn.execute(
        "INSERT INTO topic_overlap_edges VALUES (?, ?, ?, ?)",
        (t1, t2, count, json.dumps(overlap_shared_tags.get((t1, t2), []))),
    )

conn.commit()
print(f"  topic_category_meta: {conn.execute('SELECT COUNT(*) FROM topic_category_meta').fetchone()[0]} rows")
print(f"  topic_overlap_edges: {conn.execute('SELECT COUNT(*) FROM topic_overlap_edges').fetchone()[0]} rows")
conn.close()
print("Done!")
