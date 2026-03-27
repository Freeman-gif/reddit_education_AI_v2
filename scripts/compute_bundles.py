"""Compute Hierarchical Edge Bundling paths between K-Means clusters.

Pre-computes curved bundle paths so the browser never touches spline math.
Stores results in DB + exports JSON for deck.gl PathLayer.

Algorithm:
  1. Compute 768D cluster centroids → cosine similarity → threshold → macro-edges
  2. Ward hierarchical clustering on 2D centroids → tree structure
  3. For each macro-edge, route through LCA in the hierarchy → control points
  4. Beta-blend control points (bundling strength), then B-spline interpolate
  5. Export smooth [x,y] curves ready for deck.gl PathLayer

Run on Frame Desktop:
  ~/reddit_scrap/.venv/bin/python3 scripts/compute_bundles.py
"""

import json
import sqlite3
import struct
from pathlib import Path

import numpy as np
from scipy.cluster.hierarchy import linkage, to_tree
from scipy.interpolate import splprep, splev
from sklearn.metrics.pairwise import cosine_similarity

DB_PATH = Path(__file__).parent.parent / "data" / "reddit_ai_k12.db"
OUT_PATH = Path(__file__).parent.parent / "frontend" / "public" / "data" / "cluster_bundles.json"

# ── Config ──────────────────────────────────────────────────────────────
SIMILARITY_PERCENTILE = 70   # keep top 30% of cluster-pair similarities
BUNDLE_BETA = 0.85           # bundling strength (0 = straight, 1 = fully bundled)
SPLINE_SAMPLES = 64          # points per bundled curve
EMBEDDING_SAMPLE = 2000      # max embeddings per cluster for centroid calc

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

# ── 1. Cluster centroids ────────────────────────────────────────────────

print("Computing cluster centroids...")
clusters = conn.execute(
    "SELECT cluster_id, label FROM comment_clusters ORDER BY cluster_id"
).fetchall()
cluster_ids = [c["cluster_id"] for c in clusters]
cluster_labels = {c["cluster_id"]: c["label"] for c in clusters}
n = len(cluster_ids)
print(f"  {n} clusters")

# 2D centroids (UMAP space — for rendering positions + hierarchy)
centroids_2d = np.zeros((n, 2))
for i, cid in enumerate(cluster_ids):
    row = conn.execute(
        "SELECT AVG(x) as cx, AVG(y) as cy FROM comment_galaxy_coords WHERE cluster_id = ?",
        (cid,),
    ).fetchone()
    centroids_2d[i] = [row["cx"], row["cy"]]

# 768D centroids (embedding space — for semantic similarity)
print("Loading embeddings for centroid computation...")
centroids_hd = []
for i, cid in enumerate(cluster_ids):
    rows = conn.execute(f"""
        SELECT ce.vector FROM comment_embeddings ce
        JOIN comment_galaxy_coords gc ON gc.comment_id = ce.comment_id
        WHERE gc.cluster_id = ?
        ORDER BY RANDOM() LIMIT {EMBEDDING_SAMPLE}
    """, (cid,)).fetchall()
    vecs = []
    for r in rows:
        blob = r["vector"]
        dim = len(blob) // 4
        vecs.append(np.array(struct.unpack(f"{dim}f", blob), dtype=np.float32))
    centroids_hd.append(np.mean(vecs, axis=0))
    print(f"  Cluster {cid} ({cluster_labels[cid]}): {len(vecs)} embeddings sampled")

X_hd = np.vstack(centroids_hd)

# ── 2. Macro-edges via cosine similarity ────────────────────────────────

print("\nComputing cluster similarities...")
sim = cosine_similarity(X_hd)

mask = np.ones_like(sim, dtype=bool)
np.fill_diagonal(mask, False)
threshold = np.percentile(sim[mask], SIMILARITY_PERCENTILE)

edges = []
for i in range(n):
    for j in range(i + 1, n):
        if sim[i, j] >= threshold:
            edges.append((i, j, float(sim[i, j])))

print(f"  {len(edges)} edges above {SIMILARITY_PERCENTILE}th percentile (threshold={threshold:.4f})")
for s, t, w in edges:
    print(f"    {cluster_labels[cluster_ids[s]]} <-> {cluster_labels[cluster_ids[t]]} (sim={w:.3f})")

# ── 3. Hierarchical clustering for bundling tree ────────────────────────

print("\nBuilding hierarchy (Ward linkage on 2D centroids)...")
Z = linkage(centroids_2d, method="ward")
root = to_tree(Z)

# Compute positions for internal nodes (weighted centroid of children)
node_pos = {}
for i in range(n):
    node_pos[i] = centroids_2d[i].copy()


def _compute_internal_pos(node):
    if node.is_leaf():
        return node_pos[node.id].copy()
    lp = _compute_internal_pos(node.get_left())
    rp = _compute_internal_pos(node.get_right())
    pos = (lp * node.get_left().count + rp * node.get_right().count) / node.count
    node_pos[node.id] = pos
    return pos


_compute_internal_pos(root)

# Root-to-leaf paths for LCA computation
def _root_to_leaf(node, path=None):
    if path is None:
        path = []
    cur = path + [node.id]
    if node.is_leaf():
        return {node.id: cur}
    out = {}
    out.update(_root_to_leaf(node.get_left(), cur))
    out.update(_root_to_leaf(node.get_right(), cur))
    return out


leaf_paths = _root_to_leaf(root)

# ── 4. Bundle each edge through the hierarchy ──────────────────────────


def lca_control_points(a_idx, b_idx):
    """Route an edge from leaf a to leaf b through their LCA in the hierarchy."""
    pa = leaf_paths[a_idx]  # root -> ... -> a
    pb = leaf_paths[b_idx]  # root -> ... -> b

    # Find deepest common ancestor
    lca_depth = 0
    for d in range(min(len(pa), len(pb))):
        if pa[d] == pb[d]:
            lca_depth = d
        else:
            break

    # Path: a -> ... -> LCA -> ... -> b
    a_to_lca = list(reversed(pa[lca_depth:]))
    lca_to_b = pb[lca_depth + 1:]
    path_ids = a_to_lca + lca_to_b

    return [node_pos[nid].tolist() for nid in path_ids]


def bundle_and_smooth(control_pts, beta=BUNDLE_BETA, num_samples=SPLINE_SAMPLES):
    """Apply beta-blending then B-spline interpolation."""
    pts = np.array(control_pts)
    n_pts = len(pts)

    if n_pts < 2:
        return control_pts

    # Beta-blending: interpolate between straight line and hierarchy path
    start, end = pts[0], pts[-1]
    blended = np.zeros_like(pts)
    for i in range(n_pts):
        t = i / max(n_pts - 1, 1)
        straight = start + t * (end - start)
        blended[i] = (1 - beta) * straight + beta * pts[i]

    if n_pts == 2:
        t_arr = np.linspace(0, 1, num_samples)
        return [
            [round(float(blended[0, 0] + ti * (blended[1, 0] - blended[0, 0])), 4),
             round(float(blended[0, 1] + ti * (blended[1, 1] - blended[0, 1])), 4)]
            for ti in t_arr
        ]

    # B-spline interpolation
    k = min(3, n_pts - 1)
    try:
        tck, _ = splprep([blended[:, 0], blended[:, 1]], k=k, s=0)
        u_new = np.linspace(0, 1, num_samples)
        xs, ys = splev(u_new, tck)
        return [[round(float(x), 4), round(float(y), 4)] for x, y in zip(xs, ys)]
    except Exception as e:
        print(f"    splprep failed ({e}), falling back to linear interp")
        t_arr = np.linspace(0, 1, num_samples)
        xs = np.interp(t_arr, np.linspace(0, 1, n_pts), blended[:, 0])
        ys = np.interp(t_arr, np.linspace(0, 1, n_pts), blended[:, 1])
        return [[round(float(x), 4), round(float(y), 4)] for x, y in zip(xs, ys)]


print("\nComputing bundled paths...")
bundles = []
for src_idx, tgt_idx, weight in edges:
    ctrl = lca_control_points(src_idx, tgt_idx)
    path = bundle_and_smooth(ctrl)
    bundles.append({
        "source": cluster_ids[src_idx],
        "target": cluster_ids[tgt_idx],
        "weight": round(weight, 4),
        "path": path,
    })
    print(f"  {cluster_labels[cluster_ids[src_idx]]:40s} -> "
          f"{cluster_labels[cluster_ids[tgt_idx]]:40s} "
          f"({len(ctrl)} ctrl pts -> {len(path)} curve pts, sim={weight:.3f})")

# ── 5. Store in DB ──────────────────────────────────────────────────────

print(f"\nSaving {len(bundles)} bundles to database...")
conn.execute("""CREATE TABLE IF NOT EXISTS comment_cluster_bundles (
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    weight REAL NOT NULL,
    path TEXT NOT NULL,
    PRIMARY KEY (source_id, target_id)
)""")
conn.execute("DELETE FROM comment_cluster_bundles")

for b in bundles:
    conn.execute(
        "INSERT INTO comment_cluster_bundles VALUES (?, ?, ?, ?)",
        (b["source"], b["target"], b["weight"], json.dumps(b["path"])),
    )
conn.commit()

# ── 6. Export static JSON ───────────────────────────────────────────────

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
with open(OUT_PATH, "w") as f:
    json.dump({"bundles": bundles}, f, separators=(",", ":"))

size = OUT_PATH.stat().st_size
print(f"  Exported {OUT_PATH.name} ({size:,} bytes)")

conn.close()
print("Done!")
