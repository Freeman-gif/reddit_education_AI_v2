# Deployment: Interactive Graph Dashboard on Frame Desktop

## Overview

The interactive force-directed graph dashboard is deployed on Frame Desktop, accessible from anywhere via Tailscale VPN.

| | URL |
|---|---|
| **LAN** | http://192.168.1.146:3000 |
| **Tailscale** | http://100.70.226.16:3000 |

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Frame Desktop (AMD Ryzen AI Max+ 395, 128GB)   │
│                                                  │
│  ┌──────────────────────────────────────┐        │
│  │  FastAPI (uvicorn, port 3000)        │        │
│  │  - /api/*  → REST endpoints          │        │
│  │  - /*      → React SPA (static dist) │        │
│  └──────────┬───────────────────────────┘        │
│             │                                    │
│  ┌──────────▼───────────────────────────┐        │
│  │  SQLite DB                            │        │
│  │  ~/reddit_scrap/data/reddit_ai_k12.db │        │
│  └──────────────────────────────────────┘        │
│                                                  │
│  ┌──────────────────────────────────────┐        │
│  │  Ollama (port 11434)                  │        │
│  │  - qwen/qwen3-32b (classification)   │        │
│  │  - nomic-embed-text (embeddings)      │        │
│  └──────────────────────────────────────┘        │
│                                                  │
│  Screen sessions:                                │
│  - webgraph  → FastAPI web server                │
│  - classify  → Stage 2 LLM classification        │
│                                                  │
│  Cron:                                           │
│  - Every 3 hours → refresh_clusters.sh           │
└─────────────────────────────────────────────────┘
```

---

## File Layout on Frame Desktop

```
~/reddit_scrap/
├── backend/
│   └── main.py              # FastAPI app (API + static file serving)
├── frontend/
│   └── dist/                # Production React build (Vite output)
│       ├── index.html
│       └── assets/
├── data/
│   └── reddit_ai_k12.db    # SQLite database (shared with classification pipeline)
├── scripts/
│   ├── embed_posts.py       # Embed new posts via Ollama nomic-embed-text
│   ├── embed_comments.py    # Embed new comments via Ollama nomic-embed-text
│   ├── recluster_topics.py  # K-Means clustering on post embeddings
│   ├── cluster_comments.py  # K-Means clustering on comment embeddings
│   └── refresh_clusters.sh  # Cron script: runs all 4 above in sequence
└── .venv/                   # Python venv (fastapi, uvicorn, scikit-learn, umap-learn, etc.)
```

---

## Running Services

### Web Server

Runs in a screen session called `webgraph`:

```bash
# Start
screen -dmS webgraph bash -c "cd ~/reddit_scrap && ~/reddit_scrap/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 3000; exec bash"

# Attach to check logs
screen -r webgraph

# Restart
screen -X -S webgraph quit
# then start again
```

### Stage 2 Classification

Runs in a screen session called `classify`:

```bash
# Check progress
tail -1 /tmp/classify.log

# Attach
screen -r classify
```

### Auto-Refresh Cron

Every 3 hours, `refresh_clusters.sh` re-runs the full clustering pipeline:

1. `embed_posts.py` — embeds any new posts that lack embeddings
2. `recluster_topics.py` — K-Means on all post embeddings, updates topics/topic_assignments/topic_edges/post_edges
3. `embed_comments.py` — embeds any new comments that lack embeddings
4. `cluster_comments.py` — K-Means on all comment embeddings, updates comment_clusters/comment_cluster_assignments/comment_edges

```bash
# View cron
crontab -l
# Output: 0 */3 * * * /home/freeman/reddit_scrap/scripts/refresh_clusters.sh

# Check last refresh log
cat /tmp/refresh_clusters.log
```

---

## Updating the Frontend

When frontend code changes on the development machine (MacBook):

```bash
# 1. Build on MacBook
cd ~/reddit_scrap/frontend
npm run build

# 2. Sync to Frame Desktop
sshpass -p 'Zhiyuan#115' scp -o StrictHostKeyChecking=no -r dist freeman@192.168.1.146:~/reddit_scrap/frontend/

# 3. Restart web server (uvicorn doesn't hot-reload static files)
sshpass -p 'Zhiyuan#115' ssh -o StrictHostKeyChecking=no freeman@192.168.1.146 '
screen -X -S webgraph quit
screen -dmS webgraph bash -c "cd ~/reddit_scrap && ~/reddit_scrap/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 3000; exec bash"
'
```

## Updating the Backend

```bash
# 1. Sync backend code
sshpass -p 'Zhiyuan#115' scp -o StrictHostKeyChecking=no backend/main.py freeman@192.168.1.146:~/reddit_scrap/backend/

# 2. Restart web server
sshpass -p 'Zhiyuan#115' ssh -o StrictHostKeyChecking=no freeman@192.168.1.146 '
screen -X -S webgraph quit
screen -dmS webgraph bash -c "cd ~/reddit_scrap && ~/reddit_scrap/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 3000; exec bash"
'
```

---

## Python Virtual Environment

The `.venv` on Frame Desktop contains all dependencies:

```bash
# Recreate if needed
python3 -m venv ~/reddit_scrap/.venv
~/reddit_scrap/.venv/bin/pip install fastapi uvicorn umap-learn scikit-learn hdbscan numpy requests
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Web server not responding | `screen -r webgraph` to check logs, or restart |
| `sqlite3.OperationalError: database is locked` | Classification + clustering writing at the same time; clustering uses timeout=10 which usually handles this |
| Frontend shows stale data | Cron runs every 3 hours; manually trigger: `~/reddit_scrap/scripts/refresh_clusters.sh` |
| New deps needed | `~/reddit_scrap/.venv/bin/pip install <package>` |
| Port 3000 in use | `lsof -ti:3000 \| xargs kill -9` then restart screen |
| Cron not running | `crontab -l` to verify; check `/tmp/refresh_clusters.log` for errors |
