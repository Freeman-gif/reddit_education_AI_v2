# AI in K-12 Education — Reddit Discourse Analysis

Interactive force-directed graph visualization of how educators discuss AI on Reddit. Analyzes posts and comments across 11 education subreddits using NLP pipelines for topic modeling, emotion analysis, and stance detection.

**Live Demo:** [GitHub Pages](https://freeman-gif.github.io/reddit_education_AI_v2/)

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, Vite, react-force-graph-2d, D3-force |
| Backend | FastAPI (Python), SQLite |
| Deployment | GitHub Pages (static), Frame Desktop (live API) |

## Pipeline Overview

```
Reddit Posts (11 subreddits)
  → Keyword Pre-Filter (regex, AI + education term matching)
  → LLM Classification (relevance, category, tags, summary)
  → Embedding (768-dim vectors)
  → Clustering (K-Means + UMAP 2D projection)
  → Emotion & Stance Analysis (per comment)
  → Interactive Graph Dashboard
```

## Models & Methods

### Keyword Pre-Filter
- Regex matching requiring both an AI term (38 terms) and an education term (42 terms)
- Word boundary matching for short terms to prevent false positives

### LLM Classification
- **Model:** Qwen3-32B (local, via Ollama)
- **Output:** Binary relevance, category (10 classes), descriptive tags, 1-2 sentence summary
- **Temperature:** 0.1 for near-deterministic output

### Document Embedding
- **Model:** nomic-embed-text v1.5 (768-dim, via Ollama)
- **Input:** Composite text — `"search_document: {summary}. Tags: {tags}. Category: {category}"`

### Topic Clustering (Posts)
- **Method:** K-Means on 768D embeddings, with silhouette score to select optimal k
- **Visualization:** UMAP 2D projection (n_neighbors=15, min_dist=0.15, cosine metric)
- **Edges:** KNN in UMAP space (k=5, weight threshold > 0.2), hub-to-hub cosine similarity > 0.5
- **Labels:** LLM-generated via Qwen3:8b from top TF-IDF keywords + sample titles

### Comment Clustering
- Same pipeline as posts — embed with nomic-embed-text, K-Means, UMAP, KNN edges, LLM labels

### Emotion Analysis
- **Model:** SamLowe/roberta-base-go_emotions (fine-tuned RoBERTa)
- **Output:** 28 fine-grained emotion labels (GoEmotions taxonomy), mapped to positive/negative/neutral sentiment
- **Applied to:** All comments

### Stance Detection
- **Model:** roberta-large-mnli (zero-shot NLI)
- **Method:** Entailment scoring against "This comment expresses {agreement/disagreement}" hypotheses
- **Output:** agree/disagree/neutral scores per comment

### Cluster Label Generation
- **Model:** Qwen3:8b (local, via Ollama)
- **Input:** Top TF-IDF keywords + sample posts/comments per cluster
- **Output:** 2-5 word descriptive label

## Dashboard Features

### Topic Network
- All posts displayed as force-directed graph, colored by topic cluster
- Hub nodes as labeled cluster centroids
- D3 physics: custom link distances, collision detection, no center force
- Click post → side panel with title, summary, original text, comments
- Click hub → keywords, top posts, emotion breakdown, stance distribution
- Year multi-select filter

### Comment Galaxy
- All comments as force-directed graph, colored by cluster
- Sentiment toggle: switch node colors to positive (green) / negative (red) / neutral (gray)
- Click comment → full body, emotion, sentiment, stance, parent post
- Click hub → keywords, emotion/sentiment breakdown, top comments
- Year multi-select filter

## Auto-Update

A cron job runs every 3 hours on the host server:
1. Embeds new posts and comments
2. Re-clusters with K-Means
3. Re-generates LLM labels
4. Skips if LLM classification is actively running (to avoid DB locks)
