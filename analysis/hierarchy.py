"""Phase 2: Hierarchical topic slicing + LLM label generation."""

import json
import time

import numpy as np
import requests
from bertopic import BERTopic

from analysis.config import (
    BERTOPIC_DIR, L1_TOPICS, L2_TOPICS,
    OLLAMA_CHAT_URL, OLLAMA_CHAT_MODEL,
)
from analysis.db_schema import (
    db_session, get_analysis_texts, upsert_topic,
    update_topic_levels, update_topic_llm_label,
)
from analysis.embed_cluster import _blob_to_vector


def _generate_topic_label(keywords: list[str], representative_docs: list[str]) -> dict:
    """Ask Qwen3-32B to generate a readable label and description."""
    doc_samples = "\n".join(f"- {d[:200]}" for d in representative_docs[:5])
    prompt = (
        "You are labeling topics from a study of Reddit discussions about AI in K-12 education.\n\n"
        f"Top keywords: {', '.join(keywords[:10])}\n\n"
        f"Representative posts:\n{doc_samples}\n\n"
        "Respond with JSON only (no markdown):\n"
        '{"label": "3-6 word topic label", "description": "1 sentence description"}'
    )
    resp = requests.post(OLLAMA_CHAT_URL, json={
        "model": OLLAMA_CHAT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 150,
    }, timeout=120)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    # Strip thinking tags
    if "<think>" in content:
        parts = content.split("</think>")
        content = parts[-1].strip() if len(parts) > 1 else content
    # Extract JSON
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
    return json.loads(content)


def _store_topics_from_model(conn, topic_model: BERTopic, level: int,
                             topic_id_offset: int = 0):
    """Extract topic info from BERTopic model and store in DB."""
    topic_info = topic_model.get_topic_info()
    stored = []
    for _, row in topic_info.iterrows():
        tid = row["Topic"]
        if tid == -1:
            continue
        db_tid = tid + topic_id_offset
        words = topic_model.get_topic(tid)
        keywords = [w for w, _ in words[:10]] if words else []
        auto_label = " | ".join(keywords[:5])
        count = row["Count"]
        upsert_topic(conn, db_tid, level, parent_id=None, count=count,
                      keywords=json.dumps(keywords), auto_label=auto_label)
        stored.append((db_tid, keywords))
    return stored


def run_hierarchy(callback=None):
    """Build L1/L2 hierarchy and generate LLM labels."""
    log = callback or print

    # Load the saved base model
    log("[hierarchy] Loading BERTopic model...")
    topic_model = BERTopic.load(str(BERTOPIC_DIR))

    with db_session() as conn:
        # Load docs in same order as clustering
        texts_rows = get_analysis_texts(conn)
        embed_rows = conn.execute(
            "SELECT post_id, vector FROM embeddings ORDER BY post_id"
        ).fetchall()
        embed_map = {r["post_id"]: r["vector"] for r in embed_rows}

        post_ids = []
        docs = []
        for row in texts_rows:
            pid = row["post_id"]
            if pid in embed_map:
                post_ids.append(pid)
                docs.append(row["embed_text"])

        if not docs:
            log("[hierarchy] No documents found")
            return

        # Store leaf (level 0) topics
        log("[hierarchy] Storing leaf topics (level 0)...")
        _store_topics_from_model(conn, topic_model, level=0)
        conn.commit()

        # Scale topic counts based on dataset size
        n_leaf = len(set(topic_model.topics_)) - (1 if -1 in topic_model.topics_ else 0)
        l1_target = min(L1_TOPICS, max(5, n_leaf // 3))
        l2_target = min(L2_TOPICS, max(l1_target + 2, n_leaf))

        # ── L1: Broad themes ────────────────────────────────────────────
        log(f"[hierarchy] Reducing to {l1_target} L1 topics (from {n_leaf} leaf)...")
        l1_model = BERTopic.load(str(BERTOPIC_DIR))
        l1_model.reduce_topics(docs, nr_topics=l1_target)
        l1_topics = l1_model.topics_

        # Store L1 topics with offset to avoid collision
        l1_offset = 1000
        _store_topics_from_model(conn, l1_model, level=1, topic_id_offset=l1_offset)
        conn.commit()

        # ── L2: Niche topics ────────────────────────────────────────────
        log(f"[hierarchy] Reducing to {l2_target} L2 topics...")
        l2_model = BERTopic.load(str(BERTOPIC_DIR))
        l2_model.reduce_topics(docs, nr_topics=l2_target)
        l2_topics = l2_model.topics_

        l2_offset = 2000
        _store_topics_from_model(conn, l2_model, level=2, topic_id_offset=l2_offset)
        conn.commit()

        # ── Update assignments with L1/L2 IDs ───────────────────────────
        log("[hierarchy] Updating topic assignments with L1/L2 mappings...")
        for i, pid in enumerate(post_ids):
            l1_id = int(l1_topics[i]) + l1_offset if l1_topics[i] != -1 else None
            l2_id = int(l2_topics[i]) + l2_offset if l2_topics[i] != -1 else None
            update_topic_levels(conn, pid, l1_id, l2_id)
        conn.commit()

        # ── LLM Labels ──────────────────────────────────────────────────
        topics_to_label = conn.execute(
            "SELECT topic_id, keywords FROM topics WHERE llm_label IS NULL AND level > 0"
        ).fetchall()

        log(f"[hierarchy] Generating LLM labels for {len(topics_to_label)} topics...")
        for row in topics_to_label:
            tid = row["topic_id"]
            keywords = json.loads(row["keywords"]) if row["keywords"] else []

            # Get representative docs for this topic
            if tid >= l2_offset:
                orig_tid = tid - l2_offset
                model = l2_model
            else:
                orig_tid = tid - l1_offset
                model = l1_model

            try:
                rep_docs = model.get_representative_docs(orig_tid)
            except Exception:
                rep_docs = []

            if not rep_docs:
                rep_docs = keywords[:3]

            try:
                result = _generate_topic_label(keywords, rep_docs)
                update_topic_llm_label(conn, tid, result["label"], result["description"])
                log(f"  Topic {tid}: {result['label']}")
                time.sleep(0.5)
            except Exception as e:
                log(f"  Topic {tid}: LLM label failed ({e})")
                auto = " | ".join(keywords[:3]) if keywords else f"Topic {tid}"
                update_topic_llm_label(conn, tid, auto, "")

        conn.commit()

        n_l1 = conn.execute("SELECT COUNT(*) FROM topics WHERE level=1").fetchone()[0]
        n_l2 = conn.execute("SELECT COUNT(*) FROM topics WHERE level=2").fetchone()[0]
        log(f"[hierarchy] Done. L1={n_l1}, L2={n_l2} topics with labels")
