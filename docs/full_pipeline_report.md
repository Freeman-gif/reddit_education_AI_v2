# Full Pipeline Report: AI in K-12 Education — Reddit Analysis

This report documents every stage of the data pipeline, from raw Reddit post collection through NLP/LLM classification, embedding, clustering, sentiment analysis, and interactive visualization. Each section explains *what* is computed, *how* it is computed, *which models and parameters* are used, and *where* the results are stored.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Stage 1: Data Collection](#2-stage-1-data-collection)
3. [Stage 2: Keyword Pre-Filtering](#3-stage-2-keyword-pre-filtering)
4. [Stage 3: LLM Relevance Classification](#4-stage-3-llm-relevance-classification)
5. [Stage 4: Comment Collection](#5-stage-4-comment-collection)
6. [Stage 5: Post Embeddings](#6-stage-5-post-embeddings)
7. [Stage 6: Topic Modeling (BERTopic)](#7-stage-6-topic-modeling-bertopic)
8. [Stage 7: Hierarchical Topic Labels](#8-stage-7-hierarchical-topic-labels)
9. [Stage 8: KNN Post Edges](#9-stage-8-knn-post-edges)
10. [Stage 9: Comment Emotion Analysis](#10-stage-9-comment-emotion-analysis)
11. [Stage 10: Post-Level Sentiment (GoEmotions)](#11-stage-10-post-level-sentiment-goemotions)
12. [Stage 11: Topic Emotion Aggregation](#12-stage-11-topic-emotion-aggregation)
13. [Stage 12: Category Metadata Enrichment](#13-stage-12-category-metadata-enrichment)
14. [Stage 13: Comment Clustering & Galaxy](#14-stage-13-comment-clustering--galaxy)
15. [Stage 14: Hierarchical Edge Bundling](#15-stage-14-hierarchical-edge-bundling)
16. [Stage 15: Backend API](#16-stage-15-backend-api)
17. [Stage 16: Frontend Visualization](#17-stage-16-frontend-visualization)
18. [Database Schema Reference](#18-database-schema-reference)
19. [Models & Parameters Reference](#19-models--parameters-reference)

---

## 1. Architecture Overview

```
Reddit (11 subreddits)
    │
    ▼
┌─────────────────────┐
│  Arctic Shift API    │  ~276K posts collected
│  (Historical scrape) │
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  Keyword Pre-Filter  │  AI term + Education term regex
│  → ~9.2K matched     │
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  LLM Classification  │  Qwen3-32B via Ollama
│  → ~5.3K relevant    │  category, tags, summary
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│  Comment Collection  │  Arctic Shift API
│  → ~30K+ comments    │  for relevant posts only
└─────────┬───────────┘
          ▼
┌─────────────────────────────────────────────────┐
│                ANALYSIS PIPELINE                 │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐ │
│  │ Embeddings│→│ BERTopic │→│ Topic Hierarchy│ │
│  │ (768-dim) │  │ (HDBSCAN)│  │ (L1=5, L2=50)│ │
│  └──────────┘  └──────────┘  └───────────────┘ │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐ │
│  │ KNN Edges│  │GoEmotions│  │Post Sentiment │ │
│  │ (k=5)    │  │(comments)│  │ (6 groups)    │ │
│  └──────────┘  └──────────┘  └───────────────┘ │
│  ┌──────────┐  ┌──────────┐  ┌───────────────┐ │
│  │ Comment  │  │ Edge     │  │ Category Meta │ │
│  │ Galaxy   │  │ Bundling │  │ (LLM summary) │ │
│  └──────────┘  └──────────┘  └───────────────┘ │
└─────────────────────┬───────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────┐
│  FastAPI Backend (port 3000, Frame Desktop)      │
│  → 20 REST endpoints serving from SQLite         │
│  → Serves React SPA from frontend/dist/          │
└─────────────────────┬───────────────────────────┘
                      ▼
┌─────────────────────────────────────────────────┐
│  React Frontend (2 tabs)                         │
│  Tab 1: Topic Network (force graph + timeline)   │
│  Tab 2: Comment Galaxy (deck.gl + edge bundles)  │
└─────────────────────────────────────────────────┘
```

**Hardware:** Frame Desktop — AMD Ryzen AI Max+ 395, 128GB RAM, ROCm iGPU, Ubuntu 24.04

**Database:** Single SQLite file at `data/reddit_ai_k12.db` (~300 MB)

---

## 2. Stage 1: Data Collection

**Script:** `collectors/arctic_shift.py`

**Source:** Arctic Shift API (`https://arctic-shift.photon-reddit.com/api/posts/search`)

**11 Subreddits:**
Teachers, education, edtech, ChatGPT, teaching, ELATeachers, historyteachers, ScienceTeachers, matheducation, CSEducation, StudentTeaching

**20 Search Queries:** e.g., "AI in classroom", "ChatGPT teacher", "AI homework", "LLM education", "generative AI school"

**Process:**
1. For each (subreddit, query) pair, create a `collection_job` record
2. Paginate through the API using `after` timestamp (100 posts per request)
3. Deduplicate by Reddit post `id` (UPSERT into `posts` table)
4. Rate-limit: 1 second delay between API calls
5. Job status tracked as `running` → `completed` / `failed` (enables resume)

**Output Table:** `posts`
| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | Reddit post ID (e.g., "1abc2de") |
| subreddit | TEXT | Source subreddit name |
| author | TEXT | Reddit username |
| title | TEXT | Post title |
| selftext | TEXT | Post body text |
| url | TEXT | Post URL |
| score | INTEGER | Reddit upvotes |
| num_comments | INTEGER | Comment count |
| created_utc | REAL | Unix timestamp |
| source | TEXT | "arctic_shift" or "praw" |

**Volume:** ~276,000 posts collected across all subreddits and queries.

---

## 3. Stage 2: Keyword Pre-Filtering

**Script:** `filters/keyword_filter.py`

**Purpose:** Reduce 276K posts to a manageable set using fast regex matching, before expensive LLM classification.

**Algorithm:** A post passes if its (title + selftext) contains BOTH:
- At least one **AI term** (38 terms): `ai`, `chatgpt`, `gpt-4`, `copilot`, `gemini`, `llm`, `artificial intelligence`, `machine learning`, `claude`, `midjourney`, `openai`, `bard`, `perplexity`, etc.
- At least one **Education term** (42 terms): `student`, `teacher`, `classroom`, `school`, `homework`, `essay`, `grade`, `curriculum`, `lesson`, `lecture`, `assignment`, `exam`, `university`, `k-12`, etc.

**Word boundary handling:** Terms ≤ 3 characters (like "ai") use `\b` word boundaries to avoid false positives (e.g., "wait" would match "ai" without boundaries).

**Result:** ~276K → ~9,200 posts matched. Field `posts.keyword_match` set to 1.

---

## 4. Stage 3: LLM Relevance Classification

**Script:** `filters/llm_filter.py`

**Model:** Qwen3-32B via Ollama on Frame Desktop
- Endpoint: `http://192.168.1.146:11434/v1/chat/completions`
- Temperature: 0.1 (near-deterministic)
- Max tokens: 4096

**Batch size:** 5 posts per LLM request

**System prompt (condensed):** Classify each Reddit post about AI's impact on K-12 education. Return JSON with: relevant (boolean), confidence (0-1), category, tags, summary, reasoning.

**10 Classification Categories:**
| Category | Description |
|----------|-------------|
| `teacher_use` | Teachers using AI tools in classroom |
| `student_cheating` | Students using AI to cheat |
| `policy` | School/district AI policies |
| `attitude` | Opinions about AI in education |
| `ai_detection` | AI plagiarism detection tools |
| `professional_development` | Teacher training on AI |
| `ai_tools` | Specific AI tools for education |
| `personalized_learning` | AI for adaptive/personalized learning |
| `general_discussion` | Broad discussion about AI + education |
| `not_relevant` | Not about K-12 AI education |

**Output per post (stored in `classifications` table):**
| Field | Example |
|-------|---------|
| relevant | 1 |
| confidence | 0.95 |
| category | "student_cheating" |
| tags | `["ChatGPT", "essay_writing", "high_school"]` |
| summary | "Teacher describes students using ChatGPT for essay assignments" |
| reasoning | "Directly about AI cheating in high school" |

**Processing time:** ~15-20 hours for 9.2K posts at ~0.5 sec/post.

**Result:** ~5,275 posts classified as `relevant = 1`.

---

## 5. Stage 4: Comment Collection

**Script:** `collectors/arctic_shift.py::collect_comments()`

**Trigger:** Only collects for posts where `classifications.relevant = 1`.

**Process:**
1. Query all relevant post IDs lacking comments
2. For each post, paginate through Arctic Shift comment API
3. Extract: comment ID, body, author, score, parent_id, depth, created_utc
4. Rate-limit: 1 second per API call

**Output Table:** `comments`
| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PK | Reddit comment ID |
| post_id | TEXT FK | Parent post ID |
| parent_id | TEXT | Parent comment ID (for threading) |
| author | TEXT | Reddit username |
| body | TEXT | Comment text |
| score | INTEGER | Upvotes |
| created_utc | REAL | Unix timestamp |
| depth | INTEGER | Nesting depth (0 = top-level) |

---

## 6. Stage 5: Post Embeddings

**Script:** `analysis/embed_cluster.py` (Phase 1, embedding portion)

**Pre-step — Text Preparation** (`analysis/prepare.py`):
For each relevant post, build a composite embedding text:
```
search_document: {summary}. Tags: {tags}. Category: {category}
```
Stored in `analysis_texts.embed_text`.

**Embedding Model:** `nomic-embed-text` v1.5 (768 dimensions)
- Served via Ollama: `http://localhost:11434/api/embed`
- Batch size: 64 texts per API call
- Storage: float32 BLOBs (~3,072 bytes per vector)

**How the embedding is computed:**
1. Load composite text from `analysis_texts`
2. Send batch of 64 texts to Ollama's embedding endpoint
3. Receive 768-dimensional float vectors
4. Pack each vector as `struct.pack('768f', *vector)` → BLOB
5. Store in `embeddings` table

**Output Table:** `embeddings`
| Column | Type | Description |
|--------|------|-------------|
| post_id | TEXT PK | Post ID |
| vector | BLOB | 768 × float32 = 3,072 bytes |
| model_name | TEXT | "nomic-embed-text" |

---

## 7. Stage 6: Topic Modeling (BERTopic)

**Script:** `analysis/embed_cluster.py` (Phase 1, clustering portion)

**Pipeline:**
1. Load all 768D embeddings from `embeddings` table
2. **UMAP dimensionality reduction** (for clustering, not visualization):
   - n_neighbors=15, n_components=5, min_dist=0.0, metric="cosine", random_state=42
   - Reduces 768D → 5D (preserves global structure)
3. **HDBSCAN density clustering:**
   - min_cluster_size=10, min_samples=3, cluster_selection_method="eom"
   - Produces 30-80 leaf-level clusters (topic_id = 0, 1, 2, ...)
   - ~10-15% outliers assigned topic_id = -1
4. **c-TF-IDF keyword extraction:**
   - stop_words="english", ngram_range=(1,2), min_df=2
   - Top 10 keywords per topic
5. **UMAP 2D projection** (for visualization):
   - n_neighbors=15, n_components=2, min_dist=0.1, metric="cosine", random_state=42
   - Produces (umap_x, umap_y) coordinates for every post
6. **Save BERTopic model** to `data/bertopic_model/` (safetensors format)

**Output Tables:**

`topics` (leaf level):
| Column | Description |
|--------|-------------|
| topic_id | 0, 1, 2, ... (leaf topics) |
| level | 0 |
| count | Number of posts |
| keywords | JSON: top 10 (word, weight) pairs |
| auto_label | Auto-generated from keywords |

`topic_assignments`:
| Column | Description |
|--------|-------------|
| post_id | Post ID |
| topic_id | Leaf topic (L0) |
| probability | Assignment confidence |
| umap_x, umap_y | 2D coordinates for visualization |

---

## 8. Stage 7: Hierarchical Topic Labels

**Script:** `analysis/hierarchy.py`

**Purpose:** Reduce 30-80 leaf topics into 2 human-readable levels: L1 (broad themes, ~5 topics) and L2 (niche subtopics, ~50 topics).

**Process:**

### L1 Topic Reduction
1. Load saved BERTopic model from Stage 6
2. Call `topic_model.reduce_topics(docs, nr_topics=L1_TARGET)`
   - Uses agglomerative clustering on c-TF-IDF topic vectors
   - Merges similar leaf topics until target count reached
3. Topic IDs: 1000, 1001, 1003, 1004, 1005

### L2 Topic Reduction
1. Load fresh BERTopic model
2. Call `topic_model.reduce_topics(docs, nr_topics=L2_TARGET)`
3. Topic IDs: 2000-2049

### LLM Labeling (for both L1 and L2)
For each topic, send to Qwen3-32B:
```
Given these keywords for a Reddit discussion topic about AI in K-12 education:
Keywords: {top 10 keywords}
Representative posts: {5 sample titles}

Respond with JSON: {"label": "3-6 word label", "description": "1 sentence description"}
```

**Final L1 Topics (after merge of topic 1002 into 1001):**
| ID | Label | Count |
|----|-------|-------|
| 1000 | Professional Development | 766 |
| 1001 | General Discussion: Education | 1,051 |
| 1003 | Student Cheating | 1,467 |
| 1004 | AI Detection | 601 |
| 1005 | AI Tools | 1,390 |

**Database updates:**
- `topics` table: L1 and L2 rows with `llm_label` and `llm_description`
- `topic_assignments.level1_id` and `level2_id` populated for all posts

---

## 9. Stage 8: KNN Post Edges

**Script:** `analysis/edges.py`

**Purpose:** Create similarity edges between posts for the network graph.

### Post-to-Post KNN
1. Load all 768D embeddings
2. Fit `sklearn.neighbors.NearestNeighbors(n_neighbors=5, metric="cosine")`
3. For each post, find 5 nearest neighbors
4. Compute weight = 1 - cosine_distance
5. Filter: keep edges with weight > 0.3
6. Store in `post_edges` (source_id, target_id, weight)

**Result:** ~7,337 post edges.

### Topic-to-Topic Centroid Edges
1. Compute centroid per L1 topic (mean of all 768D vectors in that topic)
2. Pairwise cosine similarity between centroids
3. All pairs stored in `topic_edges`

**Result:** Fully connected graph between 5 topics.

---

## 10. Stage 9: Comment Emotion Analysis

**Script:** `analysis/emotions.py`

**Model:** `SamLowe/roberta-base-go_emotions` (HuggingFace)
- 28 fine-grained emotion labels
- Runs on Frame Desktop ROCm iGPU (with `HSA_OVERRIDE_GFX_VERSION=11.0.0`)
- Batch size: 32 comments
- Input: comment body text, truncated to 512 tokens

**How emotion scores are computed:**
1. Load the `text-classification` pipeline with `top_k=None` (returns all 28 scores)
2. For each comment, get `[{label: "joy", score: 0.82}, {label: "neutral", score: 0.12}, ...]`
3. Filter: keep emotions with score > 0.05
4. Select `dominant_emotion` = emotion with highest score
5. Derive `sentiment`:
   - Sum all positive emotion scores (admiration, joy, optimism, etc. — 13 emotions)
   - Sum all negative emotion scores (anger, sadness, fear, etc. — 11 emotions)
   - If positive > negative × 1.2 → "positive"
   - If negative > positive × 1.2 → "negative"
   - Otherwise → "neutral"

**Output Table:** `comment_emotions`
| Column | Example |
|--------|---------|
| comment_id | "abc123" |
| emotions | `{"joy": 0.82, "neutral": 0.12}` |
| dominant_emotion | "joy" |
| sentiment | "positive" |

### Stance Detection (same script)
**Model:** `roberta-large-mnli` (zero-shot NLI)
- Batch size: 16 comments
- For each comment, test entailment against post summary:
  - "This comment expresses agreement"
  - "This comment expresses disagreement"
- Returns agree_score, disagree_score, neutral_score
- Decision: if agree > disagree AND agree > 0.5 → "agree", etc.

**Output Table:** `comment_stance`
| Column | Example |
|--------|---------|
| agree_score | 0.78 |
| disagree_score | 0.15 |
| neutral_score | 0.07 |
| stance | "agree" |

---

## 11. Stage 10: Post-Level Sentiment (GoEmotions)

**Script:** `scripts/precompute_post_sentiments.py`

**Purpose:** Classify each post's emotional sentiment directly from its text (independent of comments). Used for the "Community | Sentiment" toggle in the Topic Network.

**Model:** Same `SamLowe/roberta-base-go_emotions` as comment emotions.

**Input:** `title + ". " + selftext[:500]` (truncated; [removed]/[deleted] body skipped)

**GoEmotions 28 labels → 6 Sentiment Groups:**

| Sentiment Group | Color | GoEmotions Labels |
|----------------|-------|-------------------|
| `sentiment_frustrated` | #ef4444 (Red) | anger, annoyance, disapproval, disgust |
| `sentiment_concerned` | #f97316 (Orange) | fear, nervousness, caring, confusion |
| `sentiment_sad` | #a855f7 (Purple) | sadness, grief, disappointment, remorse, embarrassment |
| `sentiment_optimistic` | #22c55e (Green) | joy, optimism, excitement, pride, gratitude, admiration, approval, love, relief, amusement |
| `sentiment_curious` | #3b82f6 (Blue) | curiosity, surprise, realization, desire |
| `sentiment_neutral` | #64748b (Gray) | neutral |

**How it works:**
1. Load GoEmotions model on Frame Desktop (CPU or ROCm iGPU)
2. Batch classify at 32 posts/batch
3. For each post: extract emotions (score > 0.05), pick dominant, map to group
4. Store with `created_month` (for timeline aggregation)

**Processing time:** ~5 minutes for 5,275 posts on CPU.

**Output Table:** `post_sentiments`
| Column | Example |
|--------|---------|
| post_id | "1abc2de" |
| emotions_json | `{"curiosity": 0.71, "neutral": 0.35}` |
| dominant_emotion | "curiosity" |
| sentiment_group | "sentiment_curious" |
| created_month | "2024-06" |

**Distribution across 5,275 posts:**
| Group | Count | % |
|-------|-------|---|
| sentiment_neutral | 2,352 | 44.6% |
| sentiment_curious | 1,617 | 30.7% |
| sentiment_optimistic | 703 | 13.3% |
| sentiment_concerned | 250 | 4.7% |
| sentiment_sad | 193 | 3.7% |
| sentiment_frustrated | 160 | 3.0% |

---

## 12. Stage 11: Topic Emotion Aggregation

**Script:** `analysis/precompute.py`

**Purpose:** Pre-aggregate comment-level emotions and stance at the topic level to avoid expensive joins at query time.

**How it's computed:**
1. For each L1 and L2 topic:
   - Join `topic_assignments` → `comments` → `comment_emotions`
   - Sum all raw emotion scores across all comments in that topic
   - Normalize by number of comments → `emotion_distribution` (JSON dict)
   - Pick `dominant_emotion` = highest summed score
2. For stance:
   - Average agree/disagree/neutral scores across all comments
   - Store as `agree_pct`, `disagree_pct`, `neutral_pct`

**Output Table:** `topic_emotion_agg`
| Column | Description |
|--------|-------------|
| topic_id | L1 or L2 topic ID |
| level | 1 or 2 |
| num_comments | Total comments in topic |
| emotion_distribution | JSON: {emotion: avg_score, ...} |
| dominant_emotion | Most prevalent emotion |
| agree_pct / disagree_pct / neutral_pct | Stance percentages |

---

## 13. Stage 12: Category Metadata Enrichment

**Script:** `scripts/precompute_category_meta.py`

**Purpose:** Enrich each L1 topic with aggregate metadata for the category overview visualization.

### 13.1 Tag Distribution
- Parse `classifications.tags` (JSON arrays) for all posts in each L1 topic
- Count frequency of each tag → top 10 stored
- Example: Topic 1003 (Student Cheating): `[{tag: "academic_integrity", count: 1197}, ...]`

### 13.2 Subreddit Distribution
- Count posts per subreddit within each L1 topic
- Example: Topic 1003: `[{subreddit: "Teachers", count: 865}, {subreddit: "ChatGPT", count: 303}, ...]`

### 13.3 Cross-Category Overlap Edges
- For each edge in `post_edges`, check if source and target belong to different L1 topics
- Count overlaps per topic pair → shows which categories share semantically similar posts
- Example: Topics 1000 ↔ 1001: 214 cross-boundary KNN edges

### 13.4 LLM Paragraph Summary
- For each L1 topic, send to Qwen3-32B:
  - Topic label, keywords, top 10 post titles
  - Prompt: "Write a 2-3 sentence paragraph summarizing what this topic cluster is about"
- Uses Ollama chat API with `think: false` (disable reasoning tokens)

**Output Tables:**

`topic_category_meta`:
| Column | Example |
|--------|---------|
| topic_id | 1003 |
| tags_json | `[{"tag": "academic_integrity", "count": 1197}, ...]` |
| subreddits_json | `[{"subreddit": "Teachers", "count": 865}, ...]` |
| paragraph_summary | "This topic centers on growing concerns among educators..." |

`topic_overlap_edges`:
| Column | Example |
|--------|---------|
| source_id | 1000 |
| target_id | 1001 |
| overlap_count | 214 |
| shared_tags_json | `["AI", "high_school", "ChatGPT", ...]` |

---

## 14. Stage 13: Comment Clustering & Galaxy

### 14.1 Comment Embeddings

**Script:** `scripts/embed_comments.py` (uses same nomic-embed-text model as post embeddings)

Embeds all comments using Ollama (768-dim vectors). Stored in `comment_embeddings` table.

### 14.2 Comment Clustering + 2D Layout

**Script:** `scripts/precompute_galaxy.py`

**Pipeline:**
1. **Load & filter** 768D comment embeddings — exclude `[deleted]`/`[removed]` and comments shorter than 30 characters (~128K comments retained from ~138K)
2. **UMAP 768D → 10D** (for clustering):
   - n_components=10, n_neighbors=30, min_dist=0.0, metric="cosine", random_state=42
   - Reduces dimensionality to remove curse-of-dimensionality noise before clustering
3. **HDBSCAN** density-based clustering on 10D UMAP output:
   - min_cluster_size=1500, min_samples=50, cluster_selection_method="leaf", metric="euclidean"
   - Discovers natural cluster count (14 clusters found)
   - Noise points reassigned to nearest cluster centroid in 10D space (0% final noise)
4. **UMAP 768D → 2D** (for visualization):
   - n_components=2, n_neighbors=15, min_dist=0.15, metric="cosine", random_state=42
   - Produces (x, y) scatter coordinates
5. **TF-IDF keywords** per cluster with domain stopwords:
   - max_features=5000, max_df=0.4, min_df=10, ngram_range=(1,2)
   - Domain stopwords filter out ubiquitous terms: "ai", "use", "chatgpt", "gpt", "just", "like", etc.
   - Top 8 terms per cluster
6. **LLM cluster labels** (Qwen3-32B via Ollama chat API):
   - Input: cluster keywords + top-voted sample comments + parent post titles + other cluster keywords for differentiation
   - `think: false` to disable reasoning tokens, temperature=0.3
   - Output: "LABEL: ..." and "DESCRIPTION: ..."
   - Fallback: top 3 keywords if LLM fails

**Current clusters (14):**
| Cluster | Count | Label | Top Keywords |
|---------|-------|-------|-------------|
| 13 | 15,305 | AI Skepticism and Satire | post, thank, thanks, comment |
| 9 | 14,640 | AI in Classroom Practice | students, lesson, teachers, tool |
| 12 | 14,005 | AI Job Anxiety in Education | technology, tech, work, kids |
| 11 | 13,972 | Teacher-Centric AI Resistance | teachers, teacher, school, education |
| 6 | 13,491 | AI Essay Accountability Measures | writing, write, essay, paper |
| 10 | 10,316 | Parental Involvement and AI Pushback | kids, parents, school, kid |
| 8 | 9,252 | AI Grading and Student Accountability | grade, class, homework, students |
| 4 | 8,656 | AI Writing Misuse and Consequences | sources, information, google, wrong |
| 5 | 7,504 | AI Academic Dishonesty Fallout | cheating, cheat, students, student |
| 7 | 7,129 | AI Detection Skepticism | plagiarism, detectors, work, detector |
| 0 | 3,913 | AI Writing Detection in Schools | chat, bot, write, https |
| 1 | 3,776 | AI and Math Pedagogy | math, calculator, calculators, students |
| 2 | 3,442 | AI Detection Controversies | https, generative, students, work |
| 3 | 3,436 | AI Text Bypass Tactics | history, google, copy, docs |

**Output Tables:**

`comment_galaxy_coords`:
| Column | Description |
|--------|-------------|
| comment_id | Comment ID |
| x, y | UMAP 2D coordinates |
| cluster_id | HDBSCAN cluster assignment (0-13) |

`comment_clusters`:
| Column | Description |
|--------|-------------|
| cluster_id | 0, 1, 2, ... 13 |
| count | Number of comments |
| keywords | JSON: top 8 TF-IDF terms |
| label | LLM-generated short label |
| description | LLM-generated description |

### 14.3 Comment KNN Edges

**Script:** `scripts/cluster_comments.py`

1. Build KNN graph on 2D UMAP coordinates (k=5)
2. Weight = 1 - (distance / avg_distance)
3. Filter: keep edges with weight > 0.2

**Output Table:** `comment_edges` (source_id, target_id, weight)

---

## 15. Stage 14: Hierarchical Edge Bundling

**Script:** `scripts/compute_bundles.py`

**Purpose:** Pre-compute smooth curved paths between comment clusters for the Comment Galaxy visualization (deck.gl PathLayer).

**Algorithm:**
1. **Cluster centroids:** Sample up to 2,000 embeddings per cluster, compute mean 768D vector → then take mean 2D UMAP position
2. **Edge selection:** Cosine similarity between all cluster centroids → keep top 30% (above 70th percentile threshold)
3. **Hierarchical tree:** Ward linkage agglomerative clustering on 2D centroids → binary tree
4. **Path routing:** For each edge (cluster A → cluster B):
   - Find Lowest Common Ancestor (LCA) in hierarchy tree
   - Route through control points: root → A → LCA → B → leaf
5. **Beta blending:** 85% bundled path + 15% straight line
6. **B-spline interpolation:** Smooth each path to 64 sample points

**Output Table:** `comment_cluster_bundles`
| Column | Description |
|--------|-------------|
| source_id | Cluster A |
| target_id | Cluster B |
| weight | Cosine similarity |
| path | JSON: [[x1,y1], [x2,y2], ..., [x64,y64]] |

---

## 16. Stage 15: Backend API

**File:** `backend/main.py`

**Framework:** FastAPI + uvicorn on port 3000

**20 REST endpoints:**

### Stats & Metadata
| Endpoint | Returns |
|----------|---------|
| `GET /api/stats` | total_posts, total_comments, topics_l1, subreddits, post_edges |
| `GET /api/years` | Available post/comment years for filtering |
| `GET /api/timeline` | Monthly post counts per topic + sentiment_by_topic breakdown |

### Category Overview (L1 Topics)
| Endpoint | Returns |
|----------|---------|
| `GET /api/categories` | 5 L1 topics with tags, subreddits, paragraph_summary, UMAP centroid |
| `GET /api/categories/edges` | Cross-category overlap edges |

### Posts
| Endpoint | Returns |
|----------|---------|
| `GET /api/posts/all?years=...` | All posts with KNN edges, optional year filter |
| `GET /api/posts/{topic_id}` | Posts within a topic + edges + sentiment_group |
| `GET /api/post/{post_id}` | Full post detail with comments, emotions, stance |

### Topic Details
| Endpoint | Returns |
|----------|---------|
| `GET /api/hub/{topic_id}` | Keywords, top posts, emotion breakdown, stance distribution |

### Comment Galaxy
| Endpoint | Returns |
|----------|---------|
| `GET /api/comments/galaxy` | Columnar scatterplot data + cluster metadata |
| `GET /api/comments/bundles` | Pre-computed edge bundling paths |
| `GET /api/comment/{id}` | Single comment detail |
| `GET /api/comment-cluster/{id}` | Cluster with top comments, emotion/sentiment breakdown |

### Emotion Drill-Down
| Endpoint | Returns |
|----------|---------|
| `GET /api/emotion/{emotion}` | All comments with that emotion, top posts, sentiment breakdown |

**Key computation in API layer:**
- The `/api/timeline` endpoint aggregates `post_sentiments.sentiment_group` per month per topic — this powers the stacked timeline bar chart and the time-filtered sentiment toggle.
- The `/api/posts/{topic_id}` endpoint joins `post_sentiments` to return `sentiment_group` per post — this powers the drilldown view's sentiment coloring.

---

## 17. Stage 16: Frontend Visualization

**Tech stack:** React 18, Vite, react-force-graph-2d, deck.gl, D3-force

### Tab 1: Topic Network

**Two-level interactive experience:**

#### Category Overview (default)
- 5 large macro-nodes positioned by UMAP centroid (mean of all posts' UMAP coords × 80 scale)
- Node size: `20 + sqrt(count) * 1.2` (range 25-50px)
- Overlap edges between categories (width proportional to cross-boundary KNN edge count)
- **Hover tooltip:** paragraph summary, tag distribution, subreddit distribution, sentiment bar
- **Click:** drills down into that category

#### Post Drill-Down
- All posts within the selected category rendered as individual nodes
- Posts positioned by UMAP (x, y) coordinates × 80 scale
- KNN edges between posts (width/opacity proportional to weight)
- **Back button** returns to category overview

#### Color Toggle: Community | Sentiment
- **Community mode:** Category nodes use fixed HUB_COLORS; posts colored by subreddit
- **Sentiment mode:** All nodes colored by dominant emotional sentiment:
  - Category nodes: dominant sentiment computed from `sentiment_by_topic` in timeline data, reactive to selected time range
  - Post nodes: colored by `sentiment_group` from API
- Legend dynamically updates to show either subreddit or sentiment groups

#### Timeline Bar
- Horizontal stacked bar chart at bottom (one bar per month, 39 months total)
- Bars stacked by topic (community mode) or by sentiment group (sentiment mode)
- **Drag to select** time range → filters category counts and drilldown posts
- **Double-click** to clear selection

### Tab 2: Comment Galaxy

- **deck.gl OrthographicView** scatterplot of all comments (UMAP 2D coords)
- Points colored by cluster ID (default) or sentiment (toggle)
- **Hierarchical edge bundling:** smooth curves between clusters via PathLayer
  - Width: `weight × 4` pixels
  - Opacity: `15 + weight × 30` (alpha channel)
- **Click comment** → detail panel (body, emotion, sentiment, stance, parent post)
- **Year filter** and **sentiment toggle**

---

## 18. Database Schema Reference

### Collection Tables
```sql
posts (id TEXT PK, subreddit, author, title, selftext, url, score,
       num_comments, created_utc, source, keyword_match)
comments (id TEXT PK, post_id FK, parent_id, author, body, score,
          created_utc, depth)
classifications (post_id TEXT PK, relevant, confidence, category, tags,
                 summary, reasoning)
collection_jobs (id INTEGER PK, source, subreddit, query, status,
                 posts_collected, ...)
```

### Analysis Tables
```sql
analysis_texts (post_id TEXT PK, embed_text, summary_source)
embeddings (post_id TEXT PK, vector BLOB, model_name)
topic_assignments (post_id TEXT PK, topic_id, probability, umap_x, umap_y,
                   level1_id, level2_id)
topics (topic_id INTEGER PK, level, parent_id, count, keywords,
        auto_label, llm_label, llm_description)
post_edges (source_id, target_id, weight)
topic_edges (source_id, target_id, weight)
post_sentiments (post_id TEXT PK, emotions_json, dominant_emotion,
                 sentiment_group, created_month)
```

### Comment Analysis Tables
```sql
comment_emotions (comment_id TEXT PK, emotions, dominant_emotion, sentiment)
comment_stance (comment_id TEXT PK, agree_score, disagree_score,
                neutral_score, stance)
comment_embeddings (comment_id TEXT PK, vector BLOB, model_name)
comment_galaxy_coords (comment_id TEXT PK, x, y, cluster_id)
comment_clusters (cluster_id INTEGER PK, count, keywords, label, description)
comment_cluster_assignments (comment_id, cluster_id, umap_x, umap_y)
comment_cluster_bundles (source_id, target_id, weight, path)
comment_edges (source_id, target_id, weight)
```

### Aggregation Tables
```sql
topic_emotion_agg (topic_id, level, num_comments, emotion_distribution,
                   dominant_emotion, agree_pct, disagree_pct, neutral_pct)
topic_category_meta (topic_id INTEGER PK, tags_json, subreddits_json,
                     paragraph_summary)
topic_overlap_edges (source_id, target_id, overlap_count, shared_tags_json)
topics_over_time (topic_id, time_bin, frequency, keywords)
```

---

## 19. Models & Parameters Reference

### Models Used
| Model | Purpose | Where |
|-------|---------|-------|
| Qwen3-32B (Ollama) | LLM classification, topic labels, category summaries | Frame Desktop :11434 |
| nomic-embed-text v1.5 (Ollama) | 768D text embeddings | Frame Desktop :11434 |
| SamLowe/roberta-base-go_emotions | 28-label emotion classification | HuggingFace (local) |
| roberta-large-mnli | Zero-shot stance detection | HuggingFace (local) |

### Key Hyperparameters
| Parameter | Value | Used In |
|-----------|-------|---------|
| UMAP n_neighbors (post cluster) | 15 | Post topic clustering |
| UMAP n_neighbors (comment cluster) | 30 | Comment galaxy clustering (10D) |
| UMAP min_dist (cluster) | 0.0 | Tight clustering |
| UMAP min_dist (viz) | 0.1-0.15 | Readable 2D layout |
| HDBSCAN min_cluster_size (posts) | 10 | Minimum topic size |
| HDBSCAN min_cluster_size (comments) | 1500 | Minimum comment cluster size |
| HDBSCAN min_samples (comments) | 50 | Density requirement |
| HDBSCAN cluster_selection (comments) | leaf | Fine-grained cluster selection |
| Comment TF-IDF max_df | 0.4 | Filter words in >40% of docs |
| Comment TF-IDF ngram_range | (1, 2) | Include bigrams |
| KNN k (posts) | 5 | Post similarity edges |
| KNN weight threshold | 0.3 | Edge filtering |
| GoEmotions score threshold | 0.05 | Emotion label filtering |
| Sentiment multiplier | 1.2 | Positive/negative boundary |
| Edge bundling beta | 0.85 | 85% bundled, 15% straight |
| B-spline sample points | 64 | Smoothness of bundle curves |
| LLM temperature | 0.1 (classify), 0.3 (labels) | Determinism vs creativity |

### Batch Sizes
| Operation | Batch Size |
|-----------|-----------|
| LLM classification | 5 posts/request |
| Text embedding | 64 texts/request |
| GoEmotions | 32 texts/batch |
| NLI stance | 16 texts/batch |
| Bundling embedding sample | 2,000 per cluster |
