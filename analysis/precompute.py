"""Phase 4: Pre-aggregate data for the dashboard."""

import json
from collections import Counter, defaultdict
from datetime import datetime

import numpy as np
from bertopic import BERTopic

from analysis.config import BERTOPIC_DIR, TIME_BINS
from analysis.db_schema import (
    db_session, get_analysis_texts,
    upsert_topic_emotion_agg, upsert_topic_over_time,
)


def run_aggregate(callback=None):
    """Aggregate emotion/stance scores per topic level."""
    log = callback or print

    with db_session() as conn:
        # ── Emotion aggregation per topic ────────────────────────────────
        log("[aggregate] Computing emotion distributions per topic...")

        for level_col, level_val in [("level1_id", 1), ("level2_id", 2)]:
            rows = conn.execute(f"""
                SELECT ta.{level_col} as topic_id,
                       ce.emotions, cs.agree_score, cs.disagree_score, cs.neutral_score
                FROM topic_assignments ta
                JOIN comments c ON c.post_id = ta.post_id
                JOIN comment_emotions ce ON ce.comment_id = c.id
                LEFT JOIN comment_stance cs ON cs.comment_id = c.id
                WHERE ta.{level_col} IS NOT NULL
            """).fetchall()

            # Group by topic
            by_topic = defaultdict(list)
            for r in rows:
                by_topic[r["topic_id"]].append(r)

            for tid, topic_rows in by_topic.items():
                # Aggregate emotions
                emotion_sums = Counter()
                for r in topic_rows:
                    emotions = json.loads(r["emotions"])
                    for emo, score in emotions.items():
                        emotion_sums[emo] += score

                n = len(topic_rows)
                emotion_dist = {k: round(v / n, 4) for k, v in emotion_sums.most_common(28)}
                dominant = emotion_sums.most_common(1)[0][0] if emotion_sums else "neutral"

                # Aggregate stance
                agree_scores = [r["agree_score"] for r in topic_rows if r["agree_score"] is not None]
                disagree_scores = [r["disagree_score"] for r in topic_rows if r["disagree_score"] is not None]
                neutral_scores = [r["neutral_score"] for r in topic_rows if r["neutral_score"] is not None]

                agree_pct = np.mean(agree_scores) * 100 if agree_scores else 33.3
                disagree_pct = np.mean(disagree_scores) * 100 if disagree_scores else 33.3
                neutral_pct = np.mean(neutral_scores) * 100 if neutral_scores else 33.3

                upsert_topic_emotion_agg(
                    conn, tid, level_val, n, emotion_dist, dominant,
                    round(agree_pct, 2), round(disagree_pct, 2), round(neutral_pct, 2)
                )

            log(f"[aggregate] Level {level_val}: {len(by_topic)} topics aggregated")

        conn.commit()

        # ── Topics over time ─────────────────────────────────────────────
        log("[aggregate] Computing topics over time...")

        try:
            topic_model = BERTopic.load(str(BERTOPIC_DIR))
            texts_rows = get_analysis_texts(conn)
            embed_map_rows = conn.execute(
                "SELECT post_id, vector FROM embeddings ORDER BY post_id"
            ).fetchall()
            embed_set = {r["post_id"] for r in embed_map_rows}

            post_ids = []
            docs = []
            for row in texts_rows:
                if row["post_id"] in embed_set:
                    post_ids.append(row["post_id"])
                    docs.append(row["embed_text"])

            # Get timestamps
            timestamps = []
            for pid in post_ids:
                ts_row = conn.execute(
                    "SELECT created_utc FROM posts WHERE id = ?", (pid,)
                ).fetchone()
                if ts_row and ts_row["created_utc"]:
                    timestamps.append(datetime.fromtimestamp(ts_row["created_utc"]))
                else:
                    timestamps.append(datetime(2024, 1, 1))

            topics_over_time = topic_model.topics_over_time(
                docs, timestamps, nr_bins=TIME_BINS
            )

            for _, row in topics_over_time.iterrows():
                upsert_topic_over_time(
                    conn,
                    int(row["Topic"]),
                    str(row["Timestamp"]),
                    int(row["Frequency"]),
                    json.dumps(row["Words"].split(", ") if isinstance(row["Words"], str) else [])
                )

            conn.commit()
            log(f"[aggregate] Topics over time: {len(topics_over_time)} entries")
        except Exception as e:
            log(f"[aggregate] Topics over time failed: {e}")

        log("[aggregate] Done")
