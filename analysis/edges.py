"""Compute KNN edges between posts and pairwise topic edges."""

import struct

import numpy as np
from sklearn.neighbors import NearestNeighbors
from sklearn.metrics.pairwise import cosine_similarity

from analysis.db_schema import (
    db_session, get_all_embeddings, upsert_post_edge, upsert_topic_edge,
)


def _blob_to_vector(blob: bytes) -> np.ndarray:
    n = len(blob) // 4
    return np.array(struct.unpack(f"{n}f", blob), dtype=np.float32)


def run_edges(k=5, threshold=0.3, callback=None):
    """Build post KNN edges and topic centroid edges."""
    log = callback or print

    with db_session() as conn:
        rows = get_all_embeddings(conn)
        if not rows:
            log("[edges] No embeddings found")
            return

        post_ids = [r["post_id"] for r in rows]
        matrix = np.vstack([_blob_to_vector(r["vector"]) for r in rows])
        log(f"[edges] Loaded {len(post_ids)} embeddings ({matrix.shape})")

        # KNN on posts
        nn = NearestNeighbors(n_neighbors=min(k + 1, len(post_ids)),
                              metric="cosine", algorithm="brute")
        nn.fit(matrix)
        distances, indices = nn.kneighbors(matrix)

        edge_count = 0
        conn.execute("DELETE FROM post_edges")
        for i in range(len(post_ids)):
            for j_idx in range(1, distances.shape[1]):  # skip self at 0
                neighbor = indices[i, j_idx]
                weight = 1.0 - distances[i, j_idx]
                if weight > threshold:
                    upsert_post_edge(conn, post_ids[i], post_ids[neighbor], weight)
                    edge_count += 1

        conn.commit()
        log(f"[edges] Stored {edge_count} post edges (k={k}, threshold={threshold})")

        # Topic centroid edges
        topic_rows = conn.execute("""
            SELECT ta.level1_id as topic_id, e.vector
            FROM topic_assignments ta
            JOIN embeddings e ON e.post_id = ta.post_id
            WHERE ta.level1_id IS NOT NULL
        """).fetchall()

        if not topic_rows:
            log("[edges] No topic assignments found, skipping topic edges")
            return

        # Group by topic
        topic_vecs = {}
        for r in topic_rows:
            tid = r["topic_id"]
            if tid not in topic_vecs:
                topic_vecs[tid] = []
            topic_vecs[tid].append(_blob_to_vector(r["vector"]))

        topic_ids = sorted(topic_vecs.keys())
        centroids = np.vstack([np.mean(topic_vecs[tid], axis=0) for tid in topic_ids])

        conn.execute("DELETE FROM topic_edges")
        sim_matrix = cosine_similarity(centroids)
        te_count = 0
        for i in range(len(topic_ids)):
            for j in range(i + 1, len(topic_ids)):
                w = float(sim_matrix[i, j])
                if w > 0.0:
                    upsert_topic_edge(conn, topic_ids[i], topic_ids[j], w)
                    te_count += 1

        conn.commit()
        log(f"[edges] Stored {te_count} topic edges")
