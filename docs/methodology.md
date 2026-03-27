# Research Methodology: Hierarchical Topic Modeling and Emotion Analysis of AI-in-K-12 Discourse on Reddit

## 1. Research Motivation

### 1.1 The Problem

The rapid adoption of generative AI tools (ChatGPT, Gemini, Claude, etc.) in education since late 2022 has created an unprecedented disruption in K-12 classrooms. Teachers face immediate, practical challenges: students using AI to complete assignments, questions about when AI use constitutes cheating, pressure to integrate AI into instruction, and a lack of institutional guidance. Unlike higher education, where researchers have direct access to faculty and student populations, K-12 teacher perspectives are harder to capture at scale through traditional survey methods.

### 1.2 Why Reddit

Reddit offers unique advantages for studying K-12 educator discourse on AI:

- **Anonymity**: Teachers speak candidly about institutional challenges, student behavior, and policy frustrations — topics they might self-censor in surveys or interviews associated with their school districts.
- **Temporal depth**: Discussions span from the pre-ChatGPT era (2023) through rapid adoption, policy formation, and evolving attitudes (2024-2026), enabling longitudinal analysis.
- **Community structure**: Education-focused subreddits (r/Teachers, r/education, r/edtech, r/CSEducation, etc.) create natural topical communities where educators discuss AI with peers, not researchers.
- **Scale**: Hundreds of thousands of posts across 11 subreddits provide statistical power that interview-based qualitative research cannot achieve.
- **Ecological validity**: Reddit discussions represent organic, unsolicited discourse — teachers sharing real experiences as they happen, rather than responding to researcher-designed prompts.

This approach follows a growing body of research using Reddit as a lens into educational discourse (Bao et al., 2024; Tlili et al., 2024; Xue et al., 2025).

### 1.3 Research Questions

1. **RQ1 (Topics)**: What are the dominant themes in K-12 educator discourse about AI, and how are they hierarchically organized?
2. **RQ2 (Temporal)**: How have these topics evolved over time since the release of ChatGPT (November 2022)?
3. **RQ3 (Emotion)**: What emotions do educators express when discussing different AI-related topics, and how do emotional patterns differ across themes?
4. **RQ4 (Stance)**: To what extent do comment responses agree or disagree with the original post's position, and does stance vary by topic?

---

## 2. Data Collection

### 2.1 Scope

| Parameter | Value |
|-----------|-------|
| **Subreddits** | r/education, r/edtech, r/Teachers, r/teaching, r/StudentTeaching, r/ELATeachers, r/CSEducation, r/ChatGPT, r/matheducation, r/ScienceTeachers, r/historyteachers |
| **Date range** | January 2023 – March 2026 |
| **Search queries** | 20 queries (e.g., "AI in classroom", "ChatGPT school", "AI cheating", "AI grading") |
| **Total posts retrieved** | ~276,000 |

### 2.2 Collection Method

Posts were collected via the **Arctic Shift API**, a community-maintained archive of historical Reddit data. Arctic Shift was chosen over the official Reddit API (PRAW) for historical coverage and absence of rate limiting on bulk retrieval. For each of the 11 target subreddits, we performed:

1. **Targeted queries**: 20 search queries matching post titles
2. **Broad sweeps**: Full subreddit scans within the date range (excluded for large subreddits like r/ChatGPT to avoid noise)

Collection is resumable via a `collection_jobs` table tracking the last timestamp cursor per (source, subreddit, query) combination.

### 2.3 Filtering Pipeline

The filtering pipeline reduces 276K posts to a focused, relevant dataset through three stages:

#### Stage 1: Keyword Pre-Filter (Local, <1 min)

A fast regex-based filter requiring each post to contain at least one AI-related term AND one education-related term:

- **AI terms** (38): `ai`, `chatgpt`, `gpt`, `llm`, `copilot`, `gemini`, `claude`, `generative ai`, `gptzero`, `turnitin ai`, etc.
- **Education terms** (42): `student`, `teacher`, `classroom`, `school`, `k-12`, `homework`, `grading`, `curriculum`, `plagiarism`, etc.

Short terms (e.g., "ai", "ml") use word boundaries to prevent false matches. This stage reduces 276K → ~9,200 posts.

#### Stage 2: LLM Classification (Qwen3-32B, ~5 hours)

Keyword-matched posts are classified by **Qwen3-32B** (running locally via Ollama on a dedicated workstation) using a structured prompt that produces:

- **Relevance**: Binary (relevant / not relevant to AI in K-12 education)
- **Category**: One of 10 categories (teacher_use, student_cheating, policy, attitude, ai_detection, professional_development, ai_tools, personalized_learning, general_discussion, not_relevant)
- **Tags**: 2-6 descriptive tags across dimensions (AI tool, grade level, subject, theme)
- **Summary**: 1-2 sentence LLM-generated summary
- **Confidence**: 0.0-1.0 score

Posts about higher education without K-12 relevance, or about technology broadly without AI specifics, are excluded. Expected yield: ~4,000-7,000 relevant posts.

#### Stage 3: Comment Collection

Top-level and nested comments are collected for all relevant posts, providing the corpus for emotion and stance analysis. Target: 50,000-400,000 comments depending on post engagement.

### 2.4 Rationale for Local LLM Classification

We use a locally-hosted LLM (Qwen3-32B) rather than manual coding or cloud APIs for several reasons:

- **Scale**: Manually coding 9,000+ posts is infeasible for a single researcher
- **Reproducibility**: The classification prompt is deterministic (temperature=0.1) and version-controlled
- **Cost**: Local inference has zero marginal cost vs. $100+ for cloud API classification of 9K posts
- **Privacy**: Reddit data never leaves the local network
- **Structured output**: The LLM generates categories, tags, and summaries simultaneously, enriching the dataset beyond binary relevance

---

## 3. Topic Modeling

### 3.1 Why BERTopic

We chose **BERTopic** (Grootendorst, 2022) over traditional topic models for several reasons:

| Method | Limitation for This Study |
|--------|--------------------------|
| **LDA** (Blei et al., 2003) | Bag-of-words representation loses semantic meaning; struggles with short texts (Reddit posts); requires pre-specifying topic count |
| **NMF** | Similar bag-of-words limitations; linear decomposition misses non-linear topic structures |
| **Top2Vec** (Angelov, 2020) | No hierarchical structure; limited interpretability tools |
| **BERTopic** | Leverages transformer embeddings for semantic understanding; density-based clustering (HDBSCAN) automatically discovers topic count; supports hierarchical decomposition; provides c-TF-IDF for interpretable keywords |

BERTopic's modular architecture (embedding → dimensionality reduction → clustering → topic representation) allows us to swap components independently. This is particularly important because:

1. **Short texts**: Reddit posts are often short; semantic embeddings capture meaning that bag-of-words misses
2. **Unknown topic count**: We don't know a priori how many themes exist — HDBSCAN discovers this automatically
3. **Hierarchy**: Education AI discourse has natural hierarchical structure (e.g., "academic integrity" → "AI detection tools" → "GPTZero complaints")
4. **Temporal analysis**: BERTopic natively supports `topics_over_time()` for tracking theme evolution

### 3.2 Embedding Model

We use **Nomic Embed Text v1.5** (`nomic-embed-text`) for document embeddings:

- **768-dimensional** dense vectors
- Trained with a contrastive objective on diverse text, including web forum data
- Runs locally via Ollama (no API costs, no data leaves the network)
- Supports the `search_document:` prefix for optimal retrieval-style embedding

Each post is embedded as a composite text: `"search_document: {summary}. Tags: {tags}. Category: {category}"`. Using the LLM-generated summary rather than raw post text provides a normalized, semantically dense input that reduces noise from off-topic tangents, URLs, and formatting artifacts.

### 3.3 Clustering Pipeline

```
Embeddings (768-dim) → UMAP (5-dim) → HDBSCAN → c-TF-IDF → Topic Labels
                     → UMAP (2-dim) → Visualization coordinates
```

**UMAP** (McInnes et al., 2018) reduces dimensionality while preserving local and global structure:
- Clustering pass: 5 components, `min_dist=0.0` (tight clusters), cosine metric
- Visualization pass: 2 components, `min_dist=0.1` (readable scatter plot)

**HDBSCAN** (Campello et al., 2013) performs density-based clustering:
- `min_cluster_size=15`: Minimum 15 posts to form a topic (prevents micro-topics)
- `min_samples=5`: Robustness against noise
- `cluster_selection_method='eom'` (Excess of Mass): Favors smaller, more specific clusters over large catch-all topics

**c-TF-IDF** (class-based TF-IDF) extracts interpretable keywords per topic by treating each topic as a "document" and computing term importance relative to the corpus.

### 3.4 Hierarchical Decomposition

BERTopic discovers leaf-level topics automatically (expected: 30-80 topics). We construct a two-level hierarchy:

- **L1 (Broad themes, ~15 topics)**: Created via `reduce_topics(nr_topics=15)`. These represent high-level discourse areas (e.g., "Academic Integrity", "AI Tools in Practice", "Policy & Administration").
- **L2 (Niche topics, ~50 topics)**: Created via `reduce_topics(nr_topics=50)`. These capture specific conversations within broad themes (e.g., under "Academic Integrity": "GPTZero false positives", "essay rewriting detection", "honor code updates").

Each L1 and L2 topic receives a human-readable label and description generated by Qwen3-32B, using the top c-TF-IDF keywords and representative documents as context.

### 3.5 Temporal Topic Modeling

BERTopic's Dynamic Topic Modeling (DTM) via `topics_over_time()` bins posts into 20 time periods and tracks topic frequency evolution. This reveals:
- When specific concerns emerged (e.g., AI detection tools surging in early 2024)
- Whether discourse has shifted from reactive (cheating concerns) to proactive (pedagogical integration)
- Seasonal patterns (beginning/end of school year effects)

---

## 4. Emotion Analysis

### 4.1 Why GoEmotions over VADER/TextBlob

Traditional sentiment analysis (VADER, TextBlob) provides only a positive/negative/neutral polarity score. This is insufficient for understanding educator discourse for several reasons:

| Approach | Limitation |
|----------|------------|
| **VADER** (Hutto & Gilbert, 2014) | Rule-based; designed for social media but only provides compound polarity; cannot distinguish fear from anger, or curiosity from approval |
| **TextBlob** | Pattern-based; even cruder than VADER; poor on informal text |
| **GoEmotions** (Demszky et al., 2020) | 28 fine-grained emotion labels; trained on Reddit comments; multi-label (a comment can express both frustration and curiosity) |

**GoEmotions** (via `SamLowe/roberta-base-go_emotions`) is particularly well-suited because:

1. **Reddit-native**: Trained on 58K Reddit comments, so it understands informal register, sarcasm markers, and Reddit-specific language
2. **Fine-grained**: 28 emotions capture nuances critical for understanding educator sentiment — e.g., distinguishing *frustration* (with lack of policy) from *fear* (of job displacement) from *curiosity* (about tools)
3. **Multi-label**: A teacher's comment can simultaneously express *approval* of AI tutoring and *concern* about equity — both are captured

The 28 GoEmotions labels are mapped to three sentiment categories for aggregation:
- **Positive** (13): admiration, amusement, approval, caring, curiosity, desire, excitement, gratitude, joy, love, optimism, pride, relief
- **Negative** (11): anger, annoyance, disappointment, disapproval, disgust, embarrassment, fear, grief, nervousness, remorse, sadness
- **Neutral** (4): confusion, realization, surprise, neutral

### 4.2 NLI-Based Stance Detection

Beyond emotion, we analyze whether comment responses **agree or disagree** with the original post's position. This reveals community consensus and debate within topics.

We use **zero-shot NLI** (Natural Language Inference) via `roberta-large-mnli`:
- The comment text serves as the premise
- The hypothesis template: "This comment expresses {agreement/disagreement}."
- The entailment probability for each label yields agree/disagree/neutral scores

This approach is preferred over training a custom stance classifier because:
1. No labeled stance data is needed (zero-shot)
2. RoBERTa-large-MNLI is the strongest general-purpose NLI model
3. The NLI framing naturally captures textual entailment, which maps well to agreement/disagreement

### 4.3 Processing Strategy

Given the large comment volume (50K-400K), we optimize for the AMD Ryzen AI Max+ 395 workstation:

- **GPU acceleration**: PyTorch with ROCm on the integrated Radeon 8060S GPU (RDNA 3.5, 128GB unified memory)
- **Batch processing**: go_emotions at batch size 32, NLI at batch size 16 (larger model)
- **Depth-first**: Top-level comments (depth=0) are processed first — these are the most substantive responses
- **Checkpointing**: Progress saved to database every 1,000 comments, enabling resumption after interruption

---

## 5. Aggregation and Visualization

### 5.1 Pre-Aggregation

To enable real-time dashboard interactivity, we pre-compute:

- **Topic-emotion matrix**: For each L1/L2 topic, the average intensity of each emotion across all associated comments
- **Topic-stance distribution**: Agree/disagree/neutral percentages per topic
- **Temporal frequencies**: Topic counts per time bin for trend visualization

### 5.2 Interactive Dashboard

A **Plotly Dash** web application provides four complementary views:

1. **Semantic Map**: 2D UMAP scatter plot of all posts, colored by L1 topic (or L2, category, subreddit). Click-to-drill enables exploring specific clusters. This provides an intuitive overview of the discourse landscape.

2. **Timeline**: Stacked area chart showing topic frequency evolution over 20 time bins. Reveals emergence, growth, and decline of themes. Toggle between L1 (broad trends) and leaf topics (specific events).

3. **Emotion Heatmap**: Rows = L2 topics, columns = 28 emotions, cell color = average intensity. Accompanied by a stacked bar chart of stance distribution per topic. This reveals which topics provoke strong emotions and which generate consensus vs. debate.

4. **Explorer**: Searchable, filterable data table of all relevant posts. Click to expand full post text with comments annotated by emotion labels and stance. Enables qualitative close reading informed by quantitative analysis.

---

## 6. Infrastructure

### 6.1 Hardware

All processing runs on a dedicated local workstation ("Frame Desktop"):

| Component | Specification |
|-----------|--------------|
| **CPU** | AMD Ryzen AI Max+ 395 (Strix Halo), 32 cores / 64 threads, up to 5.1 GHz |
| **RAM** | 128 GB unified memory (shared CPU/GPU) |
| **GPU** | Integrated Radeon 8060S (RDNA 3.5, 40 CUs), accessed via ROCm 6.4 |
| **NPU** | XDNA 2 AI accelerator (available for future optimization) |
| **Storage** | 457 GB NVMe SSD |
| **OS** | Ubuntu 24.04.3 LTS, kernel 6.17 |

### 6.2 Software Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **LLM inference** | Ollama + Qwen3-32B | Classification, summary generation, topic labeling |
| **Embedding** | Ollama + nomic-embed-text (768-dim) | Document embedding for BERTopic |
| **Topic modeling** | BERTopic + UMAP + HDBSCAN | Clustering and topic discovery |
| **Emotion analysis** | HuggingFace Transformers + GoEmotions (RoBERTa-base) | 28-label emotion classification |
| **Stance detection** | HuggingFace Transformers + RoBERTa-large-MNLI | Zero-shot NLI stance |
| **GPU framework** | PyTorch 2.7.1 + ROCm 6.2.4 | GPU-accelerated inference on AMD iGPU |
| **Database** | SQLite (WAL mode) | Persistent storage with incremental processing |
| **Dashboard** | Plotly Dash + Bootstrap | Interactive web visualization |
| **Deployment** | GitHub Actions + SSH | CI/CD to Frame Desktop |

### 6.3 Reproducibility

- All code is version-controlled in a Git repository
- LLM classification uses temperature=0.1 for near-deterministic output
- UMAP uses `random_state=42` for reproducible embeddings
- The SQLite database contains all intermediate results, enabling re-analysis without re-running expensive phases
- The pipeline is resumable at any phase — each stage checks for existing results before processing

---

## 7. Estimated Processing Times

| Phase | Description | Estimated Time | Bottleneck |
|-------|-------------|---------------|------------|
| 0 | Data preparation (summary regeneration) | ~5 min | Qwen3-32B for missing summaries |
| 1 | Embedding + clustering | ~5 min | Ollama embedding (batch 64) |
| 2 | Hierarchy + LLM labeling | ~15 min | Qwen3-32B label generation |
| 3 | Emotion + stance analysis | ~1-3 hrs (GPU) | go_emotions + NLI on ROCm iGPU |
| 4 | Aggregation | ~2 min | SQL queries |
| **Total** | | **~2-4 hours** | Phase 3 dominates |

Note: Phase 3 estimate assumes GPU acceleration via ROCm. CPU-only would be ~3-7 hours.

---

## 8. Limitations

1. **Platform bias**: Reddit skews younger, more tech-savvy, and more male than the general K-12 teacher population. Results represent the Reddit-active subset of educators.
2. **Self-selection**: Teachers who post about AI are likely those with stronger opinions (positive or negative), potentially missing the "silent majority."
3. **LLM classification**: While Qwen3-32B achieves high accuracy on structured classification tasks, some misclassification is inevitable. The confidence score and reasoning field enable quality auditing.
4. **Emotion model limitations**: GoEmotions was trained on general Reddit comments, not education-specific text. Domain-specific emotions (e.g., "pedagogical concern") are not in the label set.
5. **Stance as proxy**: NLI-based stance detection measures textual agreement/disagreement, which may not fully capture nuanced positions (e.g., "yes, but...").
6. **Temporal coverage**: Arctic Shift may have incomplete coverage for some subreddits or time periods.

---

## References

Angelov, D. (2020). Top2Vec: Distributed representations of topics. *arXiv preprint arXiv:2008.09470*.

Bao, Y., Jiang, T., & Wang, L. (2024). Reddit comment analysis: Sentiment prediction and topic modeling using VADER and BERTopic. *Proceedings of the International Conference on Data Science and Information Technology*.

Blei, D. M., Ng, A. Y., & Jordan, M. I. (2003). Latent Dirichlet allocation. *Journal of Machine Learning Research*, 3, 993–1022.

Campello, R. J. G. B., Moulavi, D., & Sander, J. (2013). Density-based clustering based on hierarchical density estimates. In *Advances in Knowledge Discovery and Data Mining* (pp. 160–172). Springer.

Demszky, D., Movshovitz-Attias, D., Ko, J., Cowen, A., Nemade, G., & Ravi, S. (2020). GoEmotions: A dataset of fine-grained emotions. In *Proceedings of the 58th Annual Meeting of the Association for Computational Linguistics* (pp. 4040–4054). ACL.

Grootendorst, M. (2022). BERTopic: Neural topic modeling with a class-based TF-IDF procedure. *arXiv preprint arXiv:2203.05794*.

Hutto, C. J., & Gilbert, E. (2014). VADER: A parsimonious rule-based model for sentiment analysis of social media text. In *Proceedings of the International AAAI Conference on Web and Social Media*, 8(1), 216–225.

McInnes, L., Healy, J., & Melville, J. (2018). UMAP: Uniform Manifold Approximation and Projection for dimension reduction. *arXiv preprint arXiv:1802.03426*.

Tlili, A., Padilla-Zea, N., Garzón, J., & Burgos, D. (2024). Reacting to Generative AI: Insights from student and faculty discussions on Reddit. In *Proceedings of the 16th ACM Web Science Conference (WebSci '24)*. ACM.

Xue, Y., Wu, M., Gao, Z., & Chen, T. (2025). Understanding user perceptions of DeepSeek: Insights from sentiment, topic and network analysis. *Frontiers in Artificial Intelligence*, 8, 1574818.
