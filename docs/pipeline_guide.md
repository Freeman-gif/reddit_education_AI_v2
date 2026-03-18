# Pipeline Technical Guide

## Overview

This document covers the end-to-end technical setup, execution, and troubleshooting of the analysis pipeline. For research methodology and motivation, see [methodology.md](methodology.md).

---

## 1. Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Data Collection                             │
│  Arctic Shift API → 276K posts → Keyword Filter → 9.2K matched     │
│  Qwen3-32B (Ollama) → LLM Classification → ~4-7K relevant          │
│  Arctic Shift / PRAW → Comments for relevant posts                  │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                       Analysis Pipeline                             │
│                                                                     │
│  Phase 0: Prepare ─── fill missing summaries, build embed texts     │
│       │                                                             │
│  Phase 1: Embed ───── Ollama nomic-embed-text (768-dim)             │
│       │                BERTopic (UMAP + HDBSCAN + c-TF-IDF)        │
│       │                                                             │
│  Phase 2: Hierarchy ─ L1 (15 broad) + L2 (50 niche) topics         │
│       │                Qwen3-32B readable labels                    │
│       │                                                             │
│  Phase 3: Emotions ── GoEmotions (28 labels) on comments            │
│       │                NLI stance (agree/disagree) on comments       │
│       │                Both on ROCm iGPU                            │
│       │                                                             │
│  Phase 4: Aggregate ─ Pre-compute heatmaps, timelines, stats        │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────────┐
│                       Plotly Dash Dashboard                         │
│  Tab 1: Semantic Map (UMAP scatter)                                 │
│  Tab 2: Timeline (stacked area)                                     │
│  Tab 3: Emotion Heatmap + Stance bars                               │
│  Tab 4: Explorer (searchable table + comment detail)                │
│                                                                     │
│  Hosted on Frame Desktop at http://100.70.226.16:8050               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Infrastructure Setup

### 2.1 Frame Desktop Specs

| Component | Detail |
|-----------|--------|
| CPU | AMD Ryzen AI Max+ 395 (Strix Halo), 32C/64T |
| RAM | 128 GB unified (shared CPU/GPU) |
| GPU | Radeon 8060S iGPU (RDNA 3.5, 40 CUs) via ROCm |
| NPU | XDNA 2 (driver loaded, `/dev/accel0`) |
| Disk | 457 GB NVMe (~65 GB free) |
| OS | Ubuntu 24.04.3 LTS, kernel 6.17 |
| Access | SSH via LAN (192.168.1.146) or Tailscale (100.70.226.16) |

### 2.2 Software Dependencies

**Ollama models** (on Frame Desktop):
```
qwen3:32b           — LLM classification, summary generation, topic labeling
nomic-embed-text    — Document embedding (768-dim)
```

**Python packages** (installed globally with `--break-system-packages`):
```
# Core analysis
bertopic>=0.16.0        umap-learn>=0.5.5       hdbscan>=0.8.33
scikit-learn>=1.3.0     numpy>=1.24.0           pandas>=2.0.0

# ML inference
torch>=2.7 (ROCm 6.2.4 build)
transformers>=4.40.0    sentence-transformers>=3.0.0

# Dashboard
plotly>=5.18.0          dash>=2.17.0            dash-bootstrap-components>=1.5.0

# Utilities
openai>=1.0             requests>=2.31.0        safetensors>=0.4.0
joblib>=1.3.0
```

### 2.3 ROCm Setup (AMD Strix Halo iGPU)

The Frame Desktop uses an AMD Ryzen AI Max+ 395 with an integrated Radeon 8060S GPU (RDNA 3.5, gfx1151). Since gfx1151 is not yet a first-class ROCm target, we use a GFX version override to map it to the supported gfx1100 (RDNA 3):

**Installed components:**
- ROCm 6.4 userspace (`rocm-hip-runtime`, `rocminfo`, `comgr`, `hsa-rocr`)
- PyTorch 2.7.1+rocm6.2.4
- User `freeman` added to `render` and `video` groups

**Critical environment variable** (in `~/.bashrc`):
```bash
export HSA_OVERRIDE_GFX_VERSION=11.0.0
```

This maps gfx1151 → gfx1100, enabling PyTorch ROCm to use the iGPU. Without this, `torch.cuda.is_available()` returns `False`.

**Verification:**
```bash
# Check GPU recognized
sg render -c "HSA_OVERRIDE_GFX_VERSION=11.0.0 rocminfo" | grep -A5 "Agent 2"
# Expected: gfx1100, Radeon 8060S Graphics

# Check PyTorch GPU
sg render -c 'HSA_OVERRIDE_GFX_VERSION=11.0.0 python3 -c "
import torch
print(torch.cuda.is_available())       # True
print(torch.cuda.get_device_name(0))   # Radeon 8060S Graphics
"'
```

**Note:** Ollama already uses the iGPU for LLM inference (100% GPU as shown by `ollama ps`). The ROCm setup is for PyTorch-based HuggingFace models (GoEmotions, NLI).

### 2.4 Ollama Configuration

Ollama's default idle timeout unloads models after a few minutes. For long-running classification jobs, we set a 24-hour keep-alive:

```bash
# /etc/systemd/system/ollama.service.d/keepalive.conf
[Service]
Environment="OLLAMA_KEEP_ALIVE=24h"
```

Applied via:
```bash
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

Verify: `ollama ps` should show `24 hours from now` in the UNTIL column.

---

## 3. Database Schema

All data lives in a single SQLite database at `data/reddit_ai_k12.db` (~300 MB). SQLite is configured with WAL mode for concurrent read/write and foreign keys enabled.

### 3.1 Collection Tables (existing)

| Table | Rows | Purpose |
|-------|------|---------|
| `posts` | ~276K | Raw Reddit posts from Arctic Shift/PRAW |
| `comments` | growing | Comment threads for relevant posts |
| `classifications` | growing | LLM classification results (separate from posts) |
| `collection_jobs` | ~231 | Resume tracking for collectors |

### 3.2 Analysis Tables (new)

| Table | Purpose |
|-------|---------|
| `analysis_texts` | Composite embed texts with summary source tracking |
| `embeddings` | 768-dim float32 vectors stored as BLOBs |
| `topic_assignments` | Post → topic mapping with UMAP coordinates and L1/L2 IDs |
| `topics` | Topic metadata: level, keywords, auto/LLM labels |
| `comment_emotions` | GoEmotions results (JSON of 28 scores per comment) |
| `comment_stance` | NLI agree/disagree/neutral scores per comment |
| `topic_emotion_agg` | Pre-aggregated emotion/stance per topic (for dashboard) |
| `topics_over_time` | Temporal topic frequencies (for timeline chart) |

---

## 4. Running the Pipeline

### 4.1 CLI Commands

```bash
PYTHON=python3  # On Frame Desktop

# Individual phases
$PYTHON run_analysis.py prepare      # Phase 0: build embed texts
$PYTHON run_analysis.py embed        # Phase 1: embed + cluster
$PYTHON run_analysis.py hierarchy    # Phase 2: L1/L2 + LLM labels
$PYTHON run_analysis.py emotions     # Phase 3: emotions + stance (long)
$PYTHON run_analysis.py aggregate    # Phase 4: pre-aggregate
$PYTHON run_analysis.py dashboard    # Launch Dash app on :8050

# Full pipeline
$PYTHON run_analysis.py all          # Phases 0-4 sequentially
```

### 4.2 Running on Frame Desktop

For long-running tasks, use `screen` for persistence:

```bash
# SSH into Frame Desktop
sshpass -p 'Zhiyuan#115' ssh -o PreferredAuthentications=password \
  -o PubkeyAuthentication=no freeman@192.168.1.146

# Start analysis in screen
screen -S analysis
cd ~/reddit_scrap
HSA_OVERRIDE_GFX_VERSION=11.0.0 python3 run_analysis.py all
# Ctrl+A, D to detach

# Check progress later
screen -r analysis
```

### 4.3 Phase-by-Phase Execution

**Phase 0 (Prepare):**
- Queries all posts with `classifications.relevant = 1`
- For posts missing a summary: regenerates via Qwen3-32B
- Builds composite text: `"search_document: {summary}. Tags: {tags}. Category: {category}"`
- Stores in `analysis_texts`
- Verify: `SELECT COUNT(*), summary_source FROM analysis_texts GROUP BY summary_source`

**Phase 1 (Embed + Cluster):**
- Embeds via Ollama `/api/embed` endpoint in batches of 64
- Stores 768-dim vectors as float32 BLOBs (~3 KB per post)
- Runs BERTopic with pre-computed embeddings
- Saves model to `data/bertopic_model/`
- Verify: Check topic count (expect 30-80), outlier rate (<15%)

**Phase 2 (Hierarchy):**
- Loads saved BERTopic model
- `reduce_topics(nr_topics=15)` → L1 (broad)
- `reduce_topics(nr_topics=50)` → L2 (niche)
- Generates LLM labels for each L1/L2 topic
- Verify: `SELECT level, COUNT(*), llm_label FROM topics GROUP BY level`

**Phase 3 (Emotions + Stance):**
- go_emotions on all comments (batch 32, GPU-accelerated)
- NLI stance on all comments (batch 16, GPU-accelerated)
- Checkpoints every 1,000 comments
- **This is the longest phase** (~1-3 hrs on GPU, ~3-7 hrs on CPU)
- Verify: Sample 10 comments and check emotion labels

**Phase 4 (Aggregate):**
- Joins topic assignments with emotion/stance data
- Computes per-topic averages
- Runs `topics_over_time()` for temporal analysis
- Verify: `SELECT COUNT(*) FROM topic_emotion_agg`

### 4.4 Dashboard

```bash
# Start dashboard
HSA_OVERRIDE_GFX_VERSION=11.0.0 python3 run_analysis.py dashboard

# Access via:
# LAN:       http://192.168.1.146:8050
# Tailscale: http://100.70.226.16:8050
```

---

## 5. Deployment (GitHub Actions)

### 5.1 Workflow

On push to `main`, the GitHub Actions workflow (`.github/workflows/deploy.yml`):

1. Runs `ruff` linting on `analysis/`, `dashboard/`, `run_analysis.py`
2. SSHs into Frame Desktop via Tailscale IP
3. `git pull origin main`
4. `pip install -r requirements-analysis.txt`
5. Restarts the dashboard systemd service

### 5.2 Required Secrets

| Secret | Value |
|--------|-------|
| `FRAME_TAILSCALE_IP` | `100.70.226.16` |
| `FRAME_SSH_PASS` | Frame Desktop SSH password |

### 5.3 Systemd Service (Optional)

To run the dashboard as a persistent service:

```ini
# /etc/systemd/system/reddit-dashboard.service
[Unit]
Description=Reddit AI K-12 Dashboard
After=network.target

[Service]
User=freeman
WorkingDirectory=/home/freeman/reddit_scrap
Environment="HSA_OVERRIDE_GFX_VERSION=11.0.0"
ExecStart=/usr/bin/python3 run_analysis.py dashboard
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable reddit-dashboard
sudo systemctl start reddit-dashboard
```

---

## 6. File Structure

```
reddit_scrap/
├── config.py                    # Collection config (subreddits, queries, Ollama)
├── db.py                        # Collection DB schema + CRUD
├── run.py                       # Collection CLI
├── pipeline.py                  # Collection pipeline orchestration
├── export.py                    # CSV/JSON export
├── collectors/
│   ├── arctic_shift.py          # Arctic Shift API collector
│   └── praw_collector.py        # Reddit API collector
├── filters/
│   ├── keyword_filter.py        # Regex pre-filter
│   └── llm_filter.py           # Qwen3-32B classification
├── analysis/
│   ├── config.py                # Analysis-specific config
│   ├── db_schema.py             # Analysis DB tables + CRUD
│   ├── prepare.py               # Phase 0: embed text preparation
│   ├── embed_cluster.py         # Phase 1: embedding + BERTopic
│   ├── hierarchy.py             # Phase 2: L1/L2 + LLM labels
│   ├── emotions.py              # Phase 3: GoEmotions + NLI stance
│   └── precompute.py            # Phase 4: aggregation
├── dashboard/
│   ├── app.py                   # Dash entry point
│   ├── layouts.py               # Page layouts (4 tabs)
│   ├── callbacks.py             # Interactivity logic
│   └── data_loader.py           # SQLite → DataFrame queries
├── run_analysis.py              # Analysis CLI
├── data/
│   ├── reddit_ai_k12.db         # SQLite database (~300 MB)
│   └── bertopic_model/          # Saved BERTopic model
├── docs/
│   ├── methodology.md           # Research methodology & motivation
│   └── pipeline_guide.md        # This file
├── .github/workflows/
│   └── deploy.yml               # CI/CD to Frame Desktop
├── requirements.txt             # Collection dependencies
└── requirements-analysis.txt    # Analysis dependencies
```

---

## 7. Troubleshooting

### Ollama model unloading during classification
**Symptom:** Classification hangs, `ollama ps` shows "Stopping..."
**Fix:** Set `OLLAMA_KEEP_ALIVE=24h` via systemd override (see Section 2.4)

### PyTorch doesn't see AMD GPU
**Symptom:** `torch.cuda.is_available()` returns `False`
**Fix:** Ensure `HSA_OVERRIDE_GFX_VERSION=11.0.0` is set AND user is in `render` group:
```bash
export HSA_OVERRIDE_GFX_VERSION=11.0.0
sg render -c "python3 -c 'import torch; print(torch.cuda.is_available())'"
```

### BERTopic "not enough documents" error
**Symptom:** HDBSCAN finds 0 clusters
**Fix:** Reduce `min_cluster_size` in `analysis/config.py` (try 10 or even 5 for small datasets)

### ROCm "Permission denied" on /dev/kfd
**Symptom:** `rocminfo` fails with permission error
**Fix:** `sudo usermod -aG render,video freeman` then start a new SSH session

### Dashboard shows "No data available"
**Symptom:** All charts empty
**Fix:** Ensure phases 0-4 have run. Check: `SELECT COUNT(*) FROM topic_assignments`

### Classification log not updating
**Symptom:** `/tmp/classify.log` stays empty
**Fix:** Use `PYTHONUNBUFFERED=1` when launching:
```bash
PYTHONUNBUFFERED=1 python3 run.py filter llm 2>&1 | tee /tmp/classify.log
```
