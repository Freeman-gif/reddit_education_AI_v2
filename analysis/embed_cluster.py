"""Phase 1: Ollama embedding + BERTopic clustering."""

import struct

import numpy as np
import requests
from bertopic import BERTopic
from hdbscan import HDBSCAN
from sklearn.feature_extraction.text import CountVectorizer
from umap import UMAP

from analysis.config import (
    OLLAMA_EMBED_URL, OLLAMA_EMBED_MODEL, EMBEDDING_DIM,
    EMBED_BATCH_SIZE, BERTOPIC_DIR,
    UMAP_CLUSTER_PARAMS, UMAP_VIZ_PARAMS,
    HDBSCAN_PARAMS, VECTORIZER_PARAMS,
)
from analysis.db_schema import (
    db_session, get_analysis_texts, get_unembedded_posts,
    upsert_embedding, upsert_topic_assignment,
)


def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts via Ollama /api/embed endpoint."""
    resp = requests.post(OLLAMA_EMBED_URL, json={
        "model": OLLAMA_EMBED_MODEL,
        "input": texts,
    }, timeout=300)
    resp.raise_for_status()
    return resp.json()["embeddings"]


def _vector_to_blob(vec: list[float]) -> bytes:
    """Pack float32 vector as bytes."""
    return struct.pack(f"{len(vec)}f", *vec)


def _blob_to_vector(blob: bytes) -> np.ndarray:
    """Unpack bytes to float32 array."""
    n = len(blob) // 4
    return np.array(struct.unpack(f"{n}f", blob), dtype=np.float32)


def run_embed(callback=None):
    """Embed all analysis texts via Ollama."""
    log = callback or print

    with db_session() as conn:
        unembedded = get_unembedded_posts(conn)
        if not unembedded:
            total = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
            log(f"[embed] All {total} posts already embedded")
            return total

        log(f"[embed] Embedding {len(unembedded)} posts (batch={EMBED_BATCH_SIZE})")

        for i in range(0, len(unembedded), EMBED_BATCH_SIZE):
            batch = unembedded[i:i + EMBED_BATCH_SIZE]
            texts = [row["embed_text"] for row in batch]
            ids = [row["post_id"] for row in batch]

            vectors = _embed_batch(texts)

            for post_id, vec in zip(ids, vectors):
                upsert_embedding(conn, post_id, _vector_to_blob(vec), OLLAMA_EMBED_MODEL)

            conn.commit()
            done = min(i + EMBED_BATCH_SIZE, len(unembedded))
            log(f"[embed] {done}/{len(unembedded)} embedded")

        total = conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        log(f"[embed] Done. {total} embeddings stored")
        return total


def run_cluster(callback=None):
    """Run BERTopic clustering on pre-computed embeddings."""
    log = callback or print

    with db_session() as conn:
        # Load texts and embeddings in matching order
        texts_rows = get_analysis_texts(conn)
        embed_rows = conn.execute(
            "SELECT post_id, vector FROM embeddings ORDER BY post_id"
        ).fetchall()

        # Build aligned arrays
        embed_map = {row["post_id"]: row["vector"] for row in embed_rows}
        post_ids = []
        docs = []
        vectors = []
        for row in texts_rows:
            pid = row["post_id"]
            if pid in embed_map:
                post_ids.append(pid)
                docs.append(row["embed_text"])
                vectors.append(_blob_to_vector(embed_map[pid]))

        if not docs:
            log("[cluster] No documents to cluster")
            return

        matrix = np.vstack(vectors)
        log(f"[cluster] Clustering {len(docs)} documents ({matrix.shape})")

        # Build BERTopic
        umap_cluster = UMAP(**UMAP_CLUSTER_PARAMS)
        hdbscan_model = HDBSCAN(**HDBSCAN_PARAMS, prediction_data=True)
        vectorizer = CountVectorizer(**VECTORIZER_PARAMS)

        topic_model = BERTopic(
            umap_model=umap_cluster,
            hdbscan_model=hdbscan_model,
            vectorizer_model=vectorizer,
            calculate_probabilities=True,
        )
        topics, probs = topic_model.fit_transform(docs, embeddings=matrix)

        # 2D UMAP for visualization
        log("[cluster] Computing 2D UMAP for visualization...")
        umap_viz = UMAP(**UMAP_VIZ_PARAMS)
        coords_2d = umap_viz.fit_transform(matrix)

        # Save model
        BERTOPIC_DIR.mkdir(parents=True, exist_ok=True)
        topic_model.save(str(BERTOPIC_DIR), serialization="safetensors",
                         save_ctfidf=True, save_embedding_model=False)
        log(f"[cluster] Model saved to {BERTOPIC_DIR}")

        # Store assignments
        for i, pid in enumerate(post_ids):
            prob = float(probs[i].max()) if probs is not None and len(probs) > i else None
            upsert_topic_assignment(
                conn, pid, int(topics[i]), prob,
                float(coords_2d[i, 0]), float(coords_2d[i, 1])
            )
        conn.commit()

        # Summary
        n_topics = len(set(topics)) - (1 if -1 in topics else 0)
        n_outliers = sum(1 for t in topics if t == -1)
        outlier_pct = n_outliers / len(topics) * 100 if topics else 0
        log(f"[cluster] Done. {n_topics} topics found, "
            f"{n_outliers} outliers ({outlier_pct:.1f}%)")

        return topic_model
