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
│   ├── precompute_galaxy.py # HDBSCAN clustering on UMAP 10D comment embeddings + LLM labels
│   ├── compute_bundles.py   # Hierarchical edge bundling between comment clusters
│   └── refresh_clusters.sh  # Cron script: runs all above in sequence
└── .venv/                   # Python venv (fastapi, uvicorn, scikit-learn, umap-learn, etc.)
```

---
