"""Export all graph API data as static JSON files for GitHub Pages deployment."""

import json
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "reddit_ai_k12.db"
OUT_DIR = Path(__file__).parent.parent / "frontend" / "public" / "data"
OUT_DIR.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row


def safe_row(row):
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, bytes):
            d[k] = v.decode("utf-8", errors="replace")
    return d


def export(name, data):
    path = OUT_DIR / f"{name}.json"
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    size = path.stat().st_size
    print(f"  {name}.json ({size:,} bytes)")


print("Exporting static JSON files...")

# stats
r = {}
r["total_posts"] = conn.execute("SELECT COUNT(*) FROM classifications WHERE relevant = 1").fetchone()[0]
r["total_comments"] = conn.execute("SELECT COUNT(*) FROM comments WHERE body NOT IN ('[deleted]','[removed]')").fetchone()[0]
r["topics_l1"] = conn.execute("SELECT COUNT(*) FROM topics WHERE level = 1").fetchone()[0]
r["topics_l2"] = 0
r["subreddits"] = conn.execute(
    "SELECT COUNT(DISTINCT p.subreddit) FROM posts p "
    "JOIN classifications c ON c.post_id = p.id WHERE c.relevant = 1"
).fetchone()[0]
r["post_edges"] = conn.execute("SELECT COUNT(*) FROM post_edges").fetchone()[0]
export("stats", r)

# years
post_years = [r[0] for r in conn.execute("""
    SELECT DISTINCT CAST(strftime('%Y', datetime(p.created_utc, 'unixepoch')) AS TEXT) as year
    FROM posts p JOIN topic_assignments ta ON ta.post_id = p.id ORDER BY year
""").fetchall()]
comment_years = [r[0] for r in conn.execute("""
    SELECT DISTINCT CAST(strftime('%Y', datetime(created_utc, 'unixepoch')) AS TEXT) as year
    FROM comments ORDER BY year
""").fetchall()]
export("years", {"post_years": post_years, "comment_years": comment_years})

# categories (L1 topics enriched with metadata)
cat_rows = conn.execute("""
    SELECT t.topic_id, t.llm_label, t.auto_label, t.count,
           t.llm_description, t.keywords,
           AVG(ta.umap_x) as cx, AVG(ta.umap_y) as cy,
           m.tags_json, m.subreddits_json, m.paragraph_summary
    FROM topics t
    JOIN topic_assignments ta ON ta.level1_id = t.topic_id
    LEFT JOIN topic_category_meta m ON m.topic_id = t.topic_id
    WHERE t.level = 1
    GROUP BY t.topic_id
""").fetchall()
cats_out = []
for r in cat_rows:
    d = safe_row(r)
    for field in ("tags_json", "subreddits_json"):
        try:
            d[field] = json.loads(d.get(field) or "[]")
        except (json.JSONDecodeError, TypeError):
            d[field] = []
    try:
        d["keywords"] = json.loads(d.get("keywords") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["keywords"] = []
    cats_out.append(d)
export("categories", cats_out)

# category edges (topic overlap)
try:
    overlap_rows = conn.execute("SELECT * FROM topic_overlap_edges").fetchall()
    overlap_out = []
    for r in overlap_rows:
        d = safe_row(r)
        try:
            d["shared_tags_json"] = json.loads(d.get("shared_tags_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["shared_tags_json"] = []
        overlap_out.append(d)
    export("categories_edges", overlap_out)
except Exception as e:
    print(f"  Skipping categories_edges: {e}")

# timeline (monthly post counts + sentiment per topic)
tl_rows = conn.execute("""
    SELECT strftime('%Y-%m', datetime(p.created_utc, 'unixepoch')) as month,
           ta.level1_id as topic_id,
           COUNT(*) as cnt
    FROM posts p
    JOIN topic_assignments ta ON ta.post_id = p.id
    GROUP BY month, ta.level1_id
    ORDER BY month
""").fetchall()

months_dict = {}
for r in tl_rows:
    m = r["month"]
    if m not in months_dict:
        months_dict[m] = {"month": m, "total": 0, "by_topic": {}, "sentiment_by_topic": {}}
    months_dict[m]["total"] += r["cnt"]
    months_dict[m]["by_topic"][str(r["topic_id"])] = r["cnt"]

try:
    sent_rows = conn.execute("""
        SELECT ps.created_month as month,
               ta.level1_id as topic_id,
               ps.sentiment_group,
               COUNT(*) as cnt
        FROM post_sentiments ps
        JOIN topic_assignments ta ON ta.post_id = ps.post_id
        GROUP BY ps.created_month, ta.level1_id, ps.sentiment_group
        ORDER BY ps.created_month
    """).fetchall()
    for r in sent_rows:
        m = r["month"]
        if m not in months_dict:
            continue
        tid = str(r["topic_id"])
        sg = r["sentiment_group"] or "sentiment_neutral"
        if tid not in months_dict[m]["sentiment_by_topic"]:
            months_dict[m]["sentiment_by_topic"][tid] = {}
        sd = months_dict[m]["sentiment_by_topic"][tid]
        sd[sg] = sd.get(sg, 0) + r["cnt"]
except Exception as e:
    print(f"  Skipping sentiment_by_topic: {e}")

export("timeline", {"months": list(months_dict.values())})

# hubs
rows = conn.execute("""
    SELECT t.topic_id, t.llm_label, t.auto_label, t.count,
           t.llm_description, t.keywords,
           AVG(ta.umap_x) as cx, AVG(ta.umap_y) as cy
    FROM topics t
    JOIN topic_assignments ta ON ta.level1_id = t.topic_id
    WHERE t.level = 1
    GROUP BY t.topic_id
""").fetchall()
export("hubs", [safe_row(r) for r in rows])

# hub edges
rows = conn.execute("SELECT * FROM topic_edges").fetchall()
export("hubs_edges", [safe_row(r) for r in rows])

# all posts
posts = conn.execute("""
    SELECT p.id as post_id, p.title, p.score, p.num_comments,
           p.subreddit, c.summary, c.category,
           ta.umap_x, ta.umap_y, ta.level1_id as topic_id,
           CAST(strftime('%Y', datetime(p.created_utc, 'unixepoch')) AS TEXT) as year
    FROM topic_assignments ta
    JOIN posts p ON p.id = ta.post_id
    LEFT JOIN classifications c ON c.post_id = p.id
""").fetchall()

# dominant emotion per post
post_ids = [p["post_id"] for p in posts]
emotions = {}
if post_ids:
    placeholders = ",".join("?" * len(post_ids))
    emo_rows = conn.execute(f"""
        SELECT cm.post_id, ce.dominant_emotion, COUNT(*) as cnt
        FROM comments cm
        JOIN comment_emotions ce ON ce.comment_id = cm.id
        WHERE cm.post_id IN ({placeholders})
        GROUP BY cm.post_id, ce.dominant_emotion
        ORDER BY cnt DESC
    """, post_ids).fetchall()
    for r in emo_rows:
        pid = r["post_id"]
        if pid not in emotions:
            emotions[pid] = r["dominant_emotion"]

posts_out = []
for p in posts:
    d = safe_row(p)
    d["dominant_emotion"] = emotions.get(d["post_id"], "neutral")
    posts_out.append(d)

edges = conn.execute("SELECT source_id, target_id, weight FROM post_edges").fetchall()
export("posts_all", {"posts": posts_out, "edges": [safe_row(e) for e in edges]})

# per-topic drilldown data (posts + intra-topic edges + sentiments)
all_edges = [safe_row(e) for e in edges]
# Build post sentiments lookup
post_sentiments = {}
try:
    ps_rows = conn.execute(
        "SELECT post_id, dominant_emotion, sentiment_group FROM post_sentiments"
    ).fetchall()
    for r in ps_rows:
        post_sentiments[r["post_id"]] = {
            "dominant_emotion": r["dominant_emotion"],
            "sentiment_group": r["sentiment_group"],
        }
except Exception:
    pass

for topic in conn.execute("SELECT topic_id FROM topics WHERE level = 1").fetchall():
    tid = topic["topic_id"]
    topic_posts = [p for p in posts_out if p.get("topic_id") == tid]
    topic_post_ids = set(p["post_id"] for p in topic_posts)
    topic_edges = [e for e in all_edges if e["source_id"] in topic_post_ids and e["target_id"] in topic_post_ids]

    # Enrich with sentiment + created_month
    tp_out = []
    for p in topic_posts:
        d = dict(p)
        s = post_sentiments.get(d["post_id"], {})
        d["dominant_emotion"] = s.get("dominant_emotion", d.get("dominant_emotion", "neutral"))
        d["sentiment_group"] = s.get("sentiment_group", "sentiment_neutral")
        # Add created_month from created_utc via DB
        tp_out.append(d)

    # Get created_month for time filtering
    if topic_post_ids:
        placeholders = ",".join("?" * len(topic_post_ids))
        month_rows = conn.execute(f"""
            SELECT p.id as post_id,
                   strftime('%Y-%m', datetime(p.created_utc, 'unixepoch')) as created_month
            FROM posts p WHERE p.id IN ({placeholders})
        """, list(topic_post_ids)).fetchall()
        month_map = {r["post_id"]: r["created_month"] for r in month_rows}
        for d in tp_out:
            d["created_month"] = month_map.get(d["post_id"], "")

    export(f"posts_topic_{tid}", {"posts": tp_out, "edges": topic_edges})

# hub detail for each topic
for topic in conn.execute("SELECT topic_id FROM topics WHERE level = 1").fetchall():
    tid = topic["topic_id"]
    t = safe_row(conn.execute(
        "SELECT topic_id, llm_label, auto_label, count, keywords, llm_description FROM topics WHERE topic_id = ?",
        (tid,)
    ).fetchone())
    try:
        t["keywords"] = json.loads(t.get("keywords") or "[]")
    except (json.JSONDecodeError, TypeError):
        t["keywords"] = []

    top_posts = conn.execute("""
        SELECT p.id as post_id, p.title, p.subreddit, p.score
        FROM topic_assignments ta JOIN posts p ON p.id = ta.post_id
        WHERE ta.level1_id = ? ORDER BY p.score DESC LIMIT 5
    """, (tid,)).fetchall()
    t["top_posts"] = [safe_row(r) for r in top_posts]

    emos = conn.execute("""
        SELECT ce.dominant_emotion, COUNT(*) as cnt
        FROM topic_assignments ta JOIN comments cm ON cm.post_id = ta.post_id
        JOIN comment_emotions ce ON ce.comment_id = cm.id
        WHERE ta.level1_id = ? GROUP BY ce.dominant_emotion ORDER BY cnt DESC
    """, (tid,)).fetchall()
    t["emotions"] = [safe_row(r) for r in emos]

    stance = conn.execute("""
        SELECT cs.stance, COUNT(*) as cnt
        FROM topic_assignments ta JOIN comments cm ON cm.post_id = ta.post_id
        JOIN comment_stance cs ON cs.comment_id = cm.id
        WHERE ta.level1_id = ? GROUP BY cs.stance
    """, (tid,)).fetchall()
    t["stance"] = {r["stance"]: r["cnt"] for r in stance}

    export(f"hub_{tid}", t)

# comment galaxy (columnar scatter format)
galaxy_rows = conn.execute("""
    SELECT gc.comment_id, gc.x, gc.y, gc.cluster_id,
           ce.sentiment, ce.dominant_emotion,
           CAST(strftime('%Y', datetime(cm.created_utc, 'unixepoch')) AS TEXT) as year
    FROM comment_galaxy_coords gc
    JOIN comments cm ON cm.id = gc.comment_id
    JOIN comment_emotions ce ON ce.comment_id = cm.id
    WHERE cm.body NOT IN ('[deleted]', '[removed]')
""").fetchall()

galaxy_data = []
for r in galaxy_rows:
    galaxy_data.append([
        r["comment_id"],
        round(r["x"], 4),
        round(r["y"], 4),
        r["cluster_id"],
        r["sentiment"] or "neutral",
        r["dominant_emotion"] or "neutral",
        r["year"] or "",
    ])

galaxy_clusters = conn.execute(
    "SELECT cluster_id, label, count, keywords FROM comment_clusters ORDER BY cluster_id"
).fetchall()
galaxy_clusters_out = []
for c in galaxy_clusters:
    galaxy_clusters_out.append({
        "cluster_id": c["cluster_id"],
        "label": c["label"] or f"Cluster {c['cluster_id']}",
        "count": c["count"],
        "keywords": c["keywords"] or "[]",
    })

export("comments_galaxy_scatter", {
    "columns": ["comment_id", "x", "y", "cluster_id", "sentiment", "dominant_emotion", "year"],
    "data": galaxy_data,
    "clusters": galaxy_clusters_out,
})

# cluster bundles (HEB paths)
try:
    bundle_rows = conn.execute(
        "SELECT source_id, target_id, weight, path FROM comment_cluster_bundles"
    ).fetchall()
    bundles_out = []
    for r in bundle_rows:
        bundles_out.append({
            "source": r["source_id"],
            "target": r["target_id"],
            "weight": r["weight"],
            "path": json.loads(r["path"]),
        })
    export("cluster_bundles", {"bundles": bundles_out})
except Exception as e:
    print(f"  Skipping cluster_bundles (table may not exist): {e}")

# comment cluster details
for cl in conn.execute("SELECT * FROM comment_clusters").fetchall():
    cid = cl["cluster_id"]
    d = safe_row(cl)
    try:
        d["keywords"] = json.loads(d.get("keywords") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["keywords"] = []

    top_c = conn.execute("""
        SELECT cm.id, cm.body, cm.author, cm.score, cm.post_id,
               ce.dominant_emotion, ce.sentiment, cs.stance, p.title as post_title
        FROM comment_cluster_assignments cca
        JOIN comments cm ON cm.id = cca.comment_id
        JOIN comment_emotions ce ON ce.comment_id = cm.id
        LEFT JOIN comment_stance cs ON cs.comment_id = cm.id
        JOIN posts p ON p.id = cm.post_id
        WHERE cca.cluster_id = ? AND cm.body NOT IN ('[deleted]','[removed]')
        ORDER BY cm.score DESC LIMIT 10
    """, (cid,)).fetchall()
    d["top_comments"] = [safe_row(c) for c in top_c]

    emos = conn.execute("""
        SELECT ce.dominant_emotion, COUNT(*) as cnt
        FROM comment_cluster_assignments cca
        JOIN comment_emotions ce ON ce.comment_id = cca.comment_id
        JOIN comments cm ON cm.id = cca.comment_id
        WHERE cca.cluster_id = ? AND cm.body NOT IN ('[deleted]','[removed]')
        GROUP BY ce.dominant_emotion ORDER BY cnt DESC
    """, (cid,)).fetchall()
    d["emotions"] = [safe_row(e) for e in emos]

    sent = conn.execute("""
        SELECT ce.sentiment, COUNT(*) as cnt
        FROM comment_cluster_assignments cca
        JOIN comment_emotions ce ON ce.comment_id = cca.comment_id
        JOIN comments cm ON cm.id = cca.comment_id
        WHERE cca.cluster_id = ? AND cm.body NOT IN ('[deleted]','[removed]')
        GROUP BY ce.sentiment
    """, (cid,)).fetchall()
    d["sentiment"] = {r["sentiment"]: r["cnt"] for r in sent}

    export(f"comment_cluster_{cid}", d)

# post details for ALL posts in the graph
for post in conn.execute("""
    SELECT DISTINCT ta.post_id FROM topic_assignments ta
""").fetchall():
    pid = post["post_id"]
    p = conn.execute("""
        SELECT p.*, c.summary, c.category, c.tags,
               t1.llm_label as l1_label
        FROM posts p
        LEFT JOIN classifications c ON c.post_id = p.id
        LEFT JOIN topic_assignments ta ON ta.post_id = p.id
        LEFT JOIN topics t1 ON t1.topic_id = ta.level1_id
        WHERE p.id = ?
    """, (pid,)).fetchone()
    if not p:
        continue

    cmts = conn.execute("""
        SELECT c.id, c.body, c.author, c.score, c.depth,
               ce.dominant_emotion, ce.sentiment, cs.stance
        FROM comments c
        LEFT JOIN comment_emotions ce ON ce.comment_id = c.id
        LEFT JOIN comment_stance cs ON cs.comment_id = c.id
        WHERE c.post_id = ? AND c.body NOT IN ('[deleted]','[removed]')
        ORDER BY c.depth, c.score DESC
    """, (pid,)).fetchall()

    export(f"post_{pid}", {"post": safe_row(p), "comments": [safe_row(c) for c in cmts]})

conn.close()
print(f"\nDone! Files in {OUT_DIR}")
