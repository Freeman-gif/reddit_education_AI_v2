"""Cluster comments using K-Means on 768D embeddings + UMAP 2D projection."""

import json
import sqlite3
import struct
from pathlib import Path

import numpy as np
import umap
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.neighbors import NearestNeighbors

DB_PATH = Path(__file__).parent.parent / "data" / "reddit_ai_k12.db"

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

# ── 1. Load embeddings ──────────────────────────────────────────────────

print("Loading comment embeddings...")
rows = conn.execute("""
    SELECT ce2.comment_id, ce2.vector, c.body,
           ce.dominant_emotion, ce.sentiment, cs.stance
    FROM comment_embeddings ce2
    JOIN comments c ON c.id = ce2.comment_id
    JOIN comment_emotions ce ON ce.comment_id = c.id
    LEFT JOIN comment_stance cs ON cs.comment_id = c.id
    WHERE c.body NOT IN ('[deleted]', '[removed]')
""").fetchall()

comment_ids, vectors, texts = [], [], []
for r in rows:
    comment_ids.append(r["comment_id"])
    blob = r["vector"]
    dim = len(blob) // 4
    vectors.append(np.array(struct.unpack(f"{dim}f", blob), dtype=np.float32))
    texts.append((r["body"] or "")[:500])

X = np.vstack(vectors)
print(f"Loaded {X.shape[0]} comments with {X.shape[1]}D embeddings")

# ── 2. K-Means with silhouette ──────────────────────────────────────────

print("\nFinding optimal k...")
scores = {}
for k in range(3, 10):
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels_k = km.fit_predict(X)
    s = silhouette_score(X, labels_k, sample_size=min(200, len(X)))
    scores[k] = s
    print(f"  k={k}: silhouette={s:.4f}")

best_k = max(scores, key=scores.get)
print(f"\nBest k={best_k} (silhouette={scores[best_k]:.4f})")

km = KMeans(n_clusters=best_k, random_state=42, n_init=10)
labels = km.fit_predict(X)

# ── 3. UMAP 2D ──────────────────────────────────────────────────────────

print("\nRunning UMAP...")
reducer = umap.UMAP(n_components=2, n_neighbors=15, min_dist=0.15, metric="cosine", random_state=42)
X_2d = reducer.fit_transform(X)
print(f"UMAP range: x=[{X_2d[:,0].min():.1f}, {X_2d[:,0].max():.1f}] "
      f"y=[{X_2d[:,1].min():.1f}, {X_2d[:,1].max():.1f}]")

# ── 4. TF-IDF keywords ──────────────────────────────────────────────────

print("\nGenerating keywords...")
tfidf = TfidfVectorizer(max_features=3000, stop_words="english", max_df=0.8, min_df=2)
tfidf_matrix = tfidf.fit_transform(texts)
feature_names = tfidf.get_feature_names_out()

cluster_keywords = {}
for c in range(best_k):
    mask = labels == c
    cluster_tfidf = tfidf_matrix[mask].mean(axis=0).A1
    top_indices = cluster_tfidf.argsort()[-8:][::-1]
    cluster_keywords[c] = [feature_names[i] for i in top_indices]
    sample = [texts[i][:60] for i in range(len(labels)) if labels[i] == c][:2]
    print(f"\n  Cluster {c} ({mask.sum()} comments): {', '.join(cluster_keywords[c][:5])}")
    for s in sample:
        print(f"    - {s}...")

# ── 5. Generate labels ──────────────────────────────────────────────────

cluster_labels = {}
cluster_descriptions = {}
for c in range(best_k):
    kws = cluster_keywords[c]
    cluster_labels[c] = ", ".join(kws[:3]).title()
    cluster_descriptions[c] = f"Comments about {', '.join(kws[:5])}"

print("\n\nFinal cluster labels:")
for c in range(best_k):
    print(f"  {c}: {cluster_labels[c]} ({(labels == c).sum()} comments)")

# ── 6. KNN edges ────────────────────────────────────────────────────────

print("\nComputing KNN edges...")
knn = NearestNeighbors(n_neighbors=5, metric="euclidean")
knn.fit(X_2d)
distances, indices = knn.kneighbors(X_2d)

edges_set = set()
for i in range(len(comment_ids)):
    for j_idx in range(1, 5):
        j = indices[i, j_idx]
        dist = distances[i, j_idx]
        weight = max(0.0, 1.0 - dist / distances[:, -1].mean())
        if weight > 0.2:
            pair = tuple(sorted([comment_ids[i], comment_ids[j]]))
            edges_set.add((*pair, round(weight, 4)))

comment_edges = list(edges_set)
print(f"Created {len(comment_edges)} comment KNN edges")

# ── 7. Write to DB ──────────────────────────────────────────────────────

print("\nUpdating database...")

conn.execute("""CREATE TABLE IF NOT EXISTS comment_clusters (
    cluster_id INTEGER PRIMARY KEY,
    count INTEGER,
    keywords TEXT,
    label TEXT,
    description TEXT
)""")

conn.execute("""CREATE TABLE IF NOT EXISTS comment_cluster_assignments (
    comment_id TEXT PRIMARY KEY REFERENCES comments(id),
    cluster_id INTEGER NOT NULL,
    umap_x REAL,
    umap_y REAL
)""")

conn.execute("""CREATE TABLE IF NOT EXISTS comment_edges (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    weight REAL NOT NULL,
    PRIMARY KEY (source_id, target_id)
)""")

conn.execute("DELETE FROM comment_clusters")
conn.execute("DELETE FROM comment_cluster_assignments")
conn.execute("DELETE FROM comment_edges")

for c in range(best_k):
    conn.execute(
        "INSERT INTO comment_clusters VALUES (?, ?, ?, ?, ?)",
        (c, int((labels == c).sum()), json.dumps(cluster_keywords[c]),
         cluster_labels[c], cluster_descriptions[c]),
    )

for i in range(len(comment_ids)):
    conn.execute(
        "INSERT INTO comment_cluster_assignments VALUES (?, ?, ?, ?)",
        (comment_ids[i], int(labels[i]), float(X_2d[i, 0]), float(X_2d[i, 1])),
    )

for src, tgt, weight in comment_edges:
    conn.execute("INSERT INTO comment_edges VALUES (?, ?, ?)", (src, tgt, weight))

conn.commit()

print(f"  Clusters: {conn.execute('SELECT COUNT(*) FROM comment_clusters').fetchone()[0]}")
print(f"  Assignments: {conn.execute('SELECT COUNT(*) FROM comment_cluster_assignments').fetchone()[0]}")
print(f"  Edges: {conn.execute('SELECT COUNT(*) FROM comment_edges').fetchone()[0]}")
conn.close()
print("Done!")
