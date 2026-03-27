"""Pre-compute UMAP 2D coords + HDBSCAN clusters for Comment Galaxy scatterplot.

Creates `comment_galaxy_coords` table with pre-computed x/y positions.
Updates `comment_clusters` with TF-IDF keywords and LLM-generated labels.

Pipeline:
  1. Load & filter comments (drop deleted/short)
  2. UMAP 768D → 10D (for clustering)
  3. HDBSCAN on 10D (density-based, natural cluster count)
  4. UMAP 768D → 2D (for visualization)
  5. TF-IDF keywords with domain stopwords
  6. LLM labeling via qwen3:32b chat API
  7. Write to DB

Run on Frame Desktop:
  ~/reddit_scrap/.venv/bin/python3 scripts/precompute_galaxy.py
"""

import json
import sqlite3
import struct
import time
from pathlib import Path

import hdbscan
import numpy as np
import requests
import umap
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

DB_PATH = Path(__file__).parent.parent / "data" / "reddit_ai_k12.db"
OLLAMA_URL = "http://localhost:11434/api/chat"
LLM_MODEL = "qwen3:32b"

# Domain-specific stopwords that appear across all clusters
DOMAIN_STOPWORDS = {
    "ai", "use", "using", "used", "chatgpt", "gpt", "don", "just",
    "like", "know", "think", "really", "would", "could", "also",
    "even", "much", "well", "get", "got", "one", "thing", "way",
    "make", "going", "want", "said", "say", "lot", "sure", "right",
    "need", "see", "go", "time", "people", "good", "ve", "ll", "re",
}

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

# ── 1. Load & filter embeddings ─────────────────────────────────────────

print("Loading comment embeddings (filtering short/deleted)...")
rows = conn.execute("""
    SELECT ce.comment_id, ce.vector, c.body, c.score, p.title AS post_title
    FROM comment_embeddings ce
    JOIN comments c ON c.id = ce.comment_id
    JOIN posts p ON p.id = c.post_id
    WHERE c.body NOT IN ('[deleted]', '[removed]')
      AND length(c.body) >= 30
""").fetchall()

comment_ids, vectors, texts, scores, post_titles = [], [], [], [], []
for r in rows:
    comment_ids.append(r["comment_id"])
    blob = r["vector"]
    dim = len(blob) // 4
    vectors.append(np.array(struct.unpack(f"{dim}f", blob), dtype=np.float32))
    texts.append((r["body"] or "")[:500])
    scores.append(r["score"] or 0)
    post_titles.append(r["post_title"] or "")

X = np.vstack(vectors)
n = X.shape[0]
scores = np.array(scores)
print(f"Loaded {n} comments with {X.shape[1]}D embeddings (after filtering)")

# ── 2. UMAP 768D → 10D (for clustering) ─────────────────────────────────

print("\nRunning UMAP 768D → 10D for clustering...")
t0 = time.time()
reducer_10d = umap.UMAP(
    n_components=10,
    n_neighbors=30,
    min_dist=0.0,
    metric="cosine",
    random_state=42,
)
X_10d = reducer_10d.fit_transform(X)
print(f"  Done in {time.time() - t0:.0f}s")

# ── 3. HDBSCAN clustering ───────────────────────────────────────────────

print("\nRunning HDBSCAN...")
t0 = time.time()
clusterer = hdbscan.HDBSCAN(
    min_cluster_size=1500,
    min_samples=50,
    cluster_selection_method="leaf",
    metric="euclidean",
)
labels = clusterer.fit_predict(X_10d)

n_clusters = labels.max() + 1
n_noise = (labels == -1).sum()
print(f"  Found {n_clusters} clusters, {n_noise} noise points ({n_noise*100/n:.1f}%)")
print(f"  Done in {time.time() - t0:.0f}s")

for c in range(n_clusters):
    print(f"  Cluster {c}: {(labels == c).sum()} comments")

# Assign noise points to nearest cluster centroid in 10D space
if n_noise > 0:
    print(f"\nReassigning {n_noise} noise points to nearest cluster...")
    centroids_10d = np.zeros((n_clusters, X_10d.shape[1]))
    for c in range(n_clusters):
        centroids_10d[c] = X_10d[labels == c].mean(axis=0)

    noise_mask = labels == -1
    noise_indices = np.where(noise_mask)[0]
    noise_points = X_10d[noise_indices]

    # Compute distances from noise points to each centroid
    from scipy.spatial.distance import cdist
    dists = cdist(noise_points, centroids_10d, metric="euclidean")
    nearest = dists.argmin(axis=1)

    for i, idx in enumerate(noise_indices):
        labels[idx] = nearest[i]

    print("  Cluster sizes after reassignment:")
    for c in range(n_clusters):
        print(f"    Cluster {c}: {(labels == c).sum()} comments")

# ── 4. UMAP 768D → 2D (for visualization) ───────────────────────────────

print("\nRunning UMAP 768D → 2D for visualization...")
t0 = time.time()
reducer_2d = umap.UMAP(
    n_components=2,
    n_neighbors=15,
    min_dist=0.15,
    metric="cosine",
    random_state=42,
)
X_2d = reducer_2d.fit_transform(X)
print(f"  UMAP range: x=[{X_2d[:,0].min():.2f}, {X_2d[:,0].max():.2f}] "
      f"y=[{X_2d[:,1].min():.2f}, {X_2d[:,1].max():.2f}]")
print(f"  Done in {time.time() - t0:.0f}s")

# ── 5. TF-IDF keywords ──────────────────────────────────────────────────

print("\nGenerating keywords...")
combined_stops = list(set(ENGLISH_STOP_WORDS) | DOMAIN_STOPWORDS)

tfidf = TfidfVectorizer(
    max_features=5000,
    stop_words=combined_stops,
    max_df=0.4,
    min_df=10,
    ngram_range=(1, 2),
)
tfidf_matrix = tfidf.fit_transform(texts)
feature_names = tfidf.get_feature_names_out()

cluster_keywords = {}
for c in range(n_clusters):
    mask = labels == c
    cluster_tfidf = tfidf_matrix[mask].mean(axis=0).A1
    top_indices = cluster_tfidf.argsort()[-8:][::-1]
    cluster_keywords[c] = [feature_names[i] for i in top_indices]
    print(f"  Cluster {c} ({mask.sum()} comments): {', '.join(cluster_keywords[c][:5])}")

# ── 6. LLM-label clusters ───────────────────────────────────────────────

print("\nLabeling clusters with LLM...")
cluster_labels = {}
cluster_descriptions = {}

for c in range(n_clusters):
    kws = cluster_keywords[c]
    mask = labels == c
    cluster_indices = np.where(mask)[0]

    # Sample top-scored comments (highest upvote) for better representation
    cluster_scores = scores[cluster_indices]
    top_score_order = cluster_scores.argsort()[::-1]
    top_indices = cluster_indices[top_score_order[:10]]

    sample_texts = [texts[i][:200] for i in top_indices[:5]]
    sample_titles = list(set(post_titles[i] for i in top_indices[:10]))[:5]

    # Build context about other clusters for differentiation
    other_clusters = []
    for oc in range(n_clusters):
        if oc != c and oc in cluster_keywords:
            other_clusters.append(f"  - Cluster {oc}: {', '.join(cluster_keywords[oc][:4])}")
    existing_labels = [f"  - {cluster_labels[oc]}" for oc in cluster_labels]

    prompt = (
        f"These are comments from a Reddit discussion cluster about AI in K-12 education.\n\n"
        f"THIS CLUSTER's top keywords: {', '.join(kws)}\n\n"
        f"Parent post titles:\n" + "\n".join(f"- {t}" for t in sample_titles) + "\n\n"
        f"Top-voted sample comments:\n" + "\n".join(f"- {t}" for t in sample_texts) + "\n\n"
    )
    if other_clusters:
        prompt += "Other clusters (for contrast):\n" + "\n".join(other_clusters) + "\n\n"
    if existing_labels:
        prompt += "Labels already used (do NOT reuse):\n" + "\n".join(existing_labels) + "\n\n"
    prompt += (
        f"Give a short DISTINCTIVE label (3-5 words) that differentiates THIS cluster from the others above. "
        f"Do NOT use generic terms like 'AI in Education' or 'AI Discussion'. Do NOT repeat labels above.\n"
        f"Also give a one-sentence description.\n"
        f"Format exactly:\nLABEL: <label>\nDESCRIPTION: <description>"
    )

    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "options": {"temperature": 0.3, "num_predict": 100},
        }, timeout=120)
        text = resp.json().get("message", {}).get("content", "")
        # Remove thinking tags if present
        if "</think>" in text:
            text = text.split("</think>")[-1].strip()

        label = ""
        desc = ""
        for line in text.strip().split("\n"):
            line = line.strip()
            if line.upper().startswith("LABEL:"):
                label = line.split(":", 1)[1].strip().strip('"').strip("*")
            elif line.upper().startswith("DESCRIPTION:"):
                desc = line.split(":", 1)[1].strip().strip('"').strip("*")

        if not label:
            label = ", ".join(kws[:3]).title()
        if not desc:
            desc = f"Comments about {', '.join(kws[:5])}"

        cluster_labels[c] = label
        cluster_descriptions[c] = desc
        print(f"  Cluster {c}: {label}")
    except Exception as e:
        print(f"  Cluster {c}: LLM failed ({e}), using keywords")
        cluster_labels[c] = ", ".join(kws[:3]).title()
        cluster_descriptions[c] = f"Comments about {', '.join(kws[:5])}"

# ── 7. Write to DB ──────────────────────────────────────────────────────

print("\nUpdating database...")

conn.execute("""CREATE TABLE IF NOT EXISTS comment_galaxy_coords (
    comment_id TEXT PRIMARY KEY REFERENCES comments(id),
    x REAL NOT NULL,
    y REAL NOT NULL,
    cluster_id INTEGER NOT NULL
)""")

conn.execute("DELETE FROM comment_galaxy_coords")

# Only write non-noise points (cluster_id >= 0)
written = 0
for i in range(n):
    conn.execute(
        "INSERT INTO comment_galaxy_coords VALUES (?, ?, ?, ?)",
        (comment_ids[i], round(float(X_2d[i, 0]), 4), round(float(X_2d[i, 1]), 4), int(labels[i])),
    )
    written += 1

# Update comment_clusters table
conn.execute("""CREATE TABLE IF NOT EXISTS comment_clusters (
    cluster_id INTEGER PRIMARY KEY,
    count INTEGER,
    keywords TEXT,
    label TEXT,
    description TEXT
)""")
conn.execute("DELETE FROM comment_clusters")

for c in range(n_clusters):
    conn.execute(
        "INSERT INTO comment_clusters VALUES (?, ?, ?, ?, ?)",
        (c, int((labels == c).sum()), json.dumps(cluster_keywords[c]),
         cluster_labels[c], cluster_descriptions[c]),
    )


conn.commit()

print(f"  Galaxy coords: {conn.execute('SELECT COUNT(*) FROM comment_galaxy_coords').fetchone()[0]}")
print(f"  Clusters: {conn.execute('SELECT COUNT(*) FROM comment_clusters').fetchone()[0]}")
conn.close()
print("Done!")
