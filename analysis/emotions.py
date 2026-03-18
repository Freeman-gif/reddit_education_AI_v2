"""Phase 3: go_emotions classification + NLI stance on comments."""

import json
import os

from analysis.config import (
    GO_EMOTIONS_MODEL, NLI_MODEL,
    EMOTION_BATCH_SIZE, NLI_BATCH_SIZE,
    EMOTION_CHECKPOINT_INTERVAL,
    POSITIVE_EMOTIONS, NEGATIVE_EMOTIONS,
)
from analysis.db_schema import (
    db_session, get_unprocessed_comments, get_comments_without_stance,
    upsert_comment_emotion, upsert_comment_stance,
)


def _get_device():
    """Detect best available device (ROCm iGPU > CPU)."""
    import torch
    # Ensure HSA override is set for Strix Halo (gfx1151 → gfx1100)
    os.environ.setdefault("HSA_OVERRIDE_GFX_VERSION", "11.0.0")
    if torch.cuda.is_available():
        name = torch.cuda.get_device_name(0)
        return 0, name  # device index, name
    return -1, "CPU"


def _classify_sentiment(emotions: dict) -> str:
    """Derive sentiment from emotion labels."""
    pos = sum(v for k, v in emotions.items() if k in POSITIVE_EMOTIONS)
    neg = sum(v for k, v in emotions.items() if k in NEGATIVE_EMOTIONS)
    if pos > neg * 1.2:
        return "positive"
    elif neg > pos * 1.2:
        return "negative"
    return "neutral"


def run_emotions(callback=None):
    """Run go_emotions on all unprocessed comments."""
    log = callback or print

    # Lazy import to avoid loading torch at module level
    from transformers import pipeline as hf_pipeline

    with db_session() as conn:
        comments = get_unprocessed_comments(conn)
        if not comments:
            total = conn.execute("SELECT COUNT(*) FROM comment_emotions").fetchone()[0]
            log(f"[emotions] All comments processed ({total} total)")
            return

        device, device_name = _get_device()
        log(f"[emotions] Processing {len(comments)} comments with go_emotions on {device_name}...")

        classifier = hf_pipeline(
            "text-classification", model=GO_EMOTIONS_MODEL,
            top_k=None, truncation=True, max_length=512,
            device=device,
        )
        log(f"[emotions] go_emotions loaded on device={device}")

        processed = 0
        for i in range(0, len(comments), EMOTION_BATCH_SIZE):
            batch = comments[i:i + EMOTION_BATCH_SIZE]
            texts = [row["body"][:512] if row["body"] else "" for row in batch]

            # Filter empty
            valid_indices = [j for j, t in enumerate(texts) if t.strip()]
            if not valid_indices:
                continue

            valid_texts = [texts[j] for j in valid_indices]
            results = classifier(valid_texts)

            for idx, result in zip(valid_indices, results):
                row = batch[idx]
                # result is list of {label, score}
                emotions = {r["label"]: round(r["score"], 4) for r in result if r["score"] > 0.05}
                if not emotions:
                    emotions = {result[0]["label"]: round(result[0]["score"], 4)}
                dominant = max(emotions, key=emotions.get)
                sentiment = _classify_sentiment(emotions)
                upsert_comment_emotion(conn, row["id"], emotions, dominant, sentiment)

            processed += len(valid_indices)
            if processed % EMOTION_CHECKPOINT_INTERVAL == 0 or i + EMOTION_BATCH_SIZE >= len(comments):
                conn.commit()
                log(f"[emotions] {processed}/{len(comments)} comments processed")

        conn.commit()
        log(f"[emotions] Done. {processed} comments classified")


def run_stance(callback=None):
    """Run NLI stance detection on comments."""
    log = callback or print

    from transformers import pipeline as hf_pipeline

    with db_session() as conn:
        comments = get_comments_without_stance(conn)
        if not comments:
            total = conn.execute("SELECT COUNT(*) FROM comment_stance").fetchone()[0]
            log(f"[stance] All comments processed ({total} total)")
            return

        device, device_name = _get_device()
        log(f"[stance] Processing {len(comments)} comments with NLI on {device_name}...")

        nli = hf_pipeline(
            "zero-shot-classification", model=NLI_MODEL,
            truncation=True, max_length=512,
            device=device,
        )

        # Build post summary lookup
        post_ids = list(set(row["post_id"] for row in comments))
        summaries = {}
        for pid in post_ids:
            row = conn.execute(
                "SELECT embed_text FROM analysis_texts WHERE post_id = ?", (pid,)
            ).fetchone()
            summaries[pid] = row["embed_text"][:200] if row else ""

        processed = 0
        for i in range(0, len(comments), NLI_BATCH_SIZE):
            batch = comments[i:i + NLI_BATCH_SIZE]

            for row in batch:
                body = (row["body"] or "")[:512]
                if not body.strip():
                    upsert_comment_stance(conn, row["id"], 0.33, 0.33, 0.34, "neutral")
                    continue

                premise = summaries.get(row["post_id"], "")
                if not premise:
                    upsert_comment_stance(conn, row["id"], 0.33, 0.33, 0.34, "neutral")
                    continue

                try:
                    result = nli(body, candidate_labels=["agreement", "disagreement"],
                                 hypothesis_template="This comment expresses {}.")
                    scores = dict(zip(result["labels"], result["scores"]))
                    agree = scores.get("agreement", 0)
                    disagree = scores.get("disagreement", 0)
                    neutral_score = max(0, 1 - agree - disagree)

                    if agree > disagree and agree > 0.5:
                        stance = "agree"
                    elif disagree > agree and disagree > 0.5:
                        stance = "disagree"
                    else:
                        stance = "neutral"

                    upsert_comment_stance(conn, row["id"], agree, disagree,
                                          neutral_score, stance)
                except Exception as e:
                    log(f"[stance] Error on comment {row['id']}: {e}")
                    upsert_comment_stance(conn, row["id"], 0.33, 0.33, 0.34, "neutral")

            processed += len(batch)
            if processed % EMOTION_CHECKPOINT_INTERVAL == 0 or i + NLI_BATCH_SIZE >= len(comments):
                conn.commit()
                log(f"[stance] {processed}/{len(comments)} comments processed")

        conn.commit()
        log(f"[stance] Done. {processed} comments classified")
