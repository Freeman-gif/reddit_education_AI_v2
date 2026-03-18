"""Re-cluster posts using K-Means on 768D embeddings + new UMAP 2D projection."""

import json
import sqlite3
import struct
from pathlib import Path

import numpy as np
import umap
from sklearn.cluster import KMeans
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.neighbors import NearestNeighbors

DB_PATH = Path(__file__).parent.parent / "data" / "reddit_ai_k12.db"

# ── 1. Load embeddings ──────────────────────────────────────────────────

print("Loading embeddings from DB...")
conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT e.post_id, e.vector, p.title, p.selftext, c.summary, c.category
    FROM embeddings e
    JOIN posts p ON p.id = e.post_id
    LEFT JOIN classifications c ON c.post_id = e.post_id
    WHERE c.relevant = 1
""").fetchall()

post_ids, vectors, titles, texts, categories = [], [], [], [], []

for r in rows:
    post_ids.append(r["post_id"])
    blob = r["vector"]
    dim = len(blob) // 4
    vectors.append(np.array(struct.unpack(f"{dim}f", blob), dtype=np.float32))
    titles.append(r["title"] or "")
    texts.append(f"{r['title'] or ''} {r['summary'] or ''} {r['selftext'] or ''}"[:500])
    categories.append(r["category"] or "")

X = np.vstack(vectors)
print(f"Loaded {X.shape[0]} posts with {X.shape[1]}D embeddings")

# ── 2. K-Means with silhouette score to pick optimal k ──────────────────

print("\nFinding optimal k via silhouette score on 768D embeddings...")
scores = {}
for k in range(5, 13):
    km = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels_k = km.fit_predict(X)
    s = silhouette_score(X, labels_k, sample_size=min(200, len(X)))
    scores[k] = s
    print(f"  k={k}: silhouette={s:.4f}")

best_k = max(scores, key=scores.get)
print(f"\nBest k={best_k} (silhouette={scores[best_k]:.4f})")

km = KMeans(n_clusters=best_k, random_state=42, n_init=10)
labels = km.fit_predict(X)

# ── 3. UMAP reduction to 2D (fresh projection) ──────────────────────────

print("\nRunning UMAP...")
reducer = umap.UMAP(
    n_components=2,
    n_neighbors=15,
    min_dist=0.15,
    metric="cosine",
    random_state=42,
)
X_2d = reducer.fit_transform(X)
print(f"UMAP range: x=[{X_2d[:,0].min():.1f}, {X_2d[:,0].max():.1f}] "
      f"y=[{X_2d[:,1].min():.1f}, {X_2d[:,1].max():.1f}]")

# Print cluster distribution
for c in range(best_k):
    cnt = (labels == c).sum()
    print(f"  Cluster {c}: {cnt} posts")

# ── 4. Generate keywords per cluster via TF-IDF ─────────────────────────

print("\nGenerating keywords per cluster...")
tfidf = TfidfVectorizer(max_features=5000, stop_words="english", max_df=0.8, min_df=2)
tfidf_matrix = tfidf.fit_transform(texts)
feature_names = tfidf.get_feature_names_out()

cluster_keywords = {}
cluster_top_categories = {}

for c in range(best_k):
    mask = labels == c
    cluster_tfidf = tfidf_matrix[mask].mean(axis=0).A1
    top_indices = cluster_tfidf.argsort()[-10:][::-1]
    cluster_keywords[c] = [feature_names[i] for i in top_indices]

    # Dominant existing categories
    cat_counts = {}
    for i in range(len(labels)):
        if labels[i] == c and categories[i]:
            cat_counts[categories[i]] = cat_counts.get(categories[i], 0) + 1
    if cat_counts:
        cluster_top_categories[c] = sorted(cat_counts.items(), key=lambda x: -x[1])

    sample = [titles[i] for i in range(len(labels)) if labels[i] == c][:3]
    print(f"\nCluster {c} ({mask.sum()} posts):")
    print(f"  Keywords: {', '.join(cluster_keywords[c][:6])}")
    print(f"  Categories: {cluster_top_categories.get(c, [])[:3]}")
    for t in sample:
        print(f"    - {t[:80]}")

# ── 5. Generate labels ──────────────────────────────────────────────────

cluster_labels = {}
cluster_descriptions = {}

for c in range(best_k):
    cats = cluster_top_categories.get(c, [])
    kws = cluster_keywords[c]
    if cats:
        primary = cats[0][0].replace("_", " ").title()
    else:
        primary = ", ".join(kws[:3]).title()
    cluster_labels[c] = primary
    cluster_descriptions[c] = (
        f"Posts about {', '.join(kws[:5])}. "
        f"Primary category: {cats[0][0] if cats else 'mixed'}"
    )

# De-duplicate labels
label_counts = {}
for lbl in cluster_labels.values():
    label_counts[lbl] = label_counts.get(lbl, 0) + 1
seen = {}
for c in sorted(cluster_labels.keys()):
    lbl = cluster_labels[c]
    if label_counts[lbl] > 1:
        kws = cluster_keywords[c]
        idx = seen.get(lbl, 0)
        suffix = kws[idx] if idx < len(kws) else str(c)
        cluster_labels[c] = f"{lbl}: {suffix.title()}"
        seen[lbl] = idx + 1

print("\n\nFinal cluster labels:")
for c in range(best_k):
    print(f"  {c}: {cluster_labels[c]} ({(labels == c).sum()} posts)")

# ── 6. Topic edges (cosine similarity between embedding centroids) ──────

print("\nComputing topic edges...")
centroids = np.vstack([X[labels == c].mean(axis=0) for c in range(best_k)])
sim_matrix = cosine_similarity(centroids)

topic_edges = []
for i in range(best_k):
    for j in range(i + 1, best_k):
        sim = float(sim_matrix[i, j])
        if sim > 0.5:
            topic_edges.append((i, j, sim))

print(f"Created {len(topic_edges)} topic edges (similarity > 0.5)")

# ── 7. Post KNN edges in UMAP space ─────────────────────────────────────

print("Computing post KNN edges...")
knn = NearestNeighbors(n_neighbors=5, metric="euclidean")
knn.fit(X_2d)
distances, indices = knn.kneighbors(X_2d)

post_edges_set = set()
for i in range(len(post_ids)):
    for j_idx in range(1, 5):
        j = indices[i, j_idx]
        dist = distances[i, j_idx]
        weight = max(0.0, 1.0 - dist / distances[:, -1].mean())
        if weight > 0.2:
            pair = tuple(sorted([post_ids[i], post_ids[j]]))
            post_edges_set.add((*pair, round(weight, 4)))

post_edges = list(post_edges_set)
print(f"Created {len(post_edges)} post KNN edges")

# ── 8. Update database ──────────────────────────────────────────────────

print("\nUpdating database...")

# Backup (skip if table doesn't exist)
for tbl in ["topics", "topic_assignments", "topic_edges", "post_edges"]:
    conn.execute(f"DROP TABLE IF EXISTS {tbl}_backup")
    exists = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?", (tbl,)
    ).fetchone()[0]
    if exists:
        conn.execute(f"CREATE TABLE {tbl}_backup AS SELECT * FROM {tbl}")
        conn.execute(f"DELETE FROM {tbl}")

# Create tables if they don't exist
conn.execute("""CREATE TABLE IF NOT EXISTS topic_edges (
    source_id INTEGER NOT NULL, target_id INTEGER NOT NULL,
    weight REAL NOT NULL, PRIMARY KEY (source_id, target_id))""")
conn.execute("""CREATE TABLE IF NOT EXISTS post_edges (
    source_id TEXT NOT NULL, target_id TEXT NOT NULL,
    weight REAL NOT NULL, PRIMARY KEY (source_id, target_id))""")

# Insert new L1 topics
for c in range(best_k):
    tid = 1000 + c
    count = int((labels == c).sum())
    kws_json = json.dumps(cluster_keywords[c])
    auto = ", ".join(cluster_keywords[c][:5])
    conn.execute(
        "INSERT INTO topics (topic_id, level, parent_id, count, keywords, auto_label, llm_label, llm_description) "
        "VALUES (?, 1, NULL, ?, ?, ?, ?, ?)",
        (tid, count, kws_json, auto, cluster_labels[c], cluster_descriptions[c]),
    )

# Insert topic assignments
for i in range(len(post_ids)):
    c = int(labels[i])
    tid = 1000 + c
    conn.execute(
        "INSERT OR REPLACE INTO topic_assignments "
        "(post_id, topic_id, probability, umap_x, umap_y, level1_id, level2_id) "
        "VALUES (?, ?, 1.0, ?, ?, ?, ?)",
        (post_ids[i], tid, float(X_2d[i, 0]), float(X_2d[i, 1]), tid, tid),
    )

# Insert topic edges
for src, tgt, weight in topic_edges:
    conn.execute(
        "INSERT INTO topic_edges (source_id, target_id, weight) VALUES (?, ?, ?)",
        (1000 + src, 1000 + tgt, weight),
    )

# Insert post edges
for src, tgt, weight in post_edges:
    conn.execute(
        "INSERT INTO post_edges (source_id, target_id, weight) VALUES (?, ?, ?)",
        (src, tgt, weight),
    )

conn.commit()

# Verify
for label, q in [
    ("Topics (L1)", "SELECT COUNT(*) FROM topics WHERE level=1"),
    ("Assignments", "SELECT COUNT(*) FROM topic_assignments"),
    ("Topic edges", "SELECT COUNT(*) FROM topic_edges"),
    ("Post edges", "SELECT COUNT(*) FROM post_edges"),
]:
    print(f"  {label}: {conn.execute(q).fetchone()[0]}")

conn.close()
print("\nDone!")
