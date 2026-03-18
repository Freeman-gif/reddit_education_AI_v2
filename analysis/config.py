"""Analysis-specific configuration (models, parameters, paths)."""

from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_DIR = Path(__file__).parent.parent
DATA_DIR = PROJECT_DIR / "data"
DB_PATH = DATA_DIR / "reddit_ai_k12.db"
BERTOPIC_DIR = DATA_DIR / "bertopic_model"

# ── Ollama (Frame Desktop) ──────────────────────────────────────────────────
OLLAMA_BASE_URL = "http://192.168.1.146:11434"
OLLAMA_CHAT_URL = f"{OLLAMA_BASE_URL}/v1/chat/completions"
OLLAMA_EMBED_URL = f"{OLLAMA_BASE_URL}/api/embed"
OLLAMA_CHAT_MODEL = "qwen3:32b"
OLLAMA_EMBED_MODEL = "nomic-embed-text"
EMBEDDING_DIM = 768
EMBED_BATCH_SIZE = 64

# ── BERTopic Parameters ─────────────────────────────────────────────────────
UMAP_CLUSTER_PARAMS = dict(
    n_neighbors=15, n_components=5, min_dist=0.0, metric="cosine", random_state=42
)
UMAP_VIZ_PARAMS = dict(
    n_neighbors=15, n_components=2, min_dist=0.1, metric="cosine", random_state=42
)
HDBSCAN_PARAMS = dict(
    min_cluster_size=10, min_samples=3, cluster_selection_method="eom"
)
VECTORIZER_PARAMS = dict(
    stop_words="english", ngram_range=(1, 2), min_df=2
)

# ── Hierarchy ────────────────────────────────────────────────────────────────
# Auto-scaled in hierarchy.py based on dataset size.
# These are targets for the full dataset (~4-7K posts).
# For smaller datasets, hierarchy.py will reduce proportionally.
L1_TOPICS = 15   # broad themes
L2_TOPICS = 50   # niche topics

# ── Emotion Analysis ────────────────────────────────────────────────────────
GO_EMOTIONS_MODEL = "SamLowe/roberta-base-go_emotions"
NLI_MODEL = "roberta-large-mnli"
EMOTION_BATCH_SIZE = 32
NLI_BATCH_SIZE = 16
EMOTION_CHECKPOINT_INTERVAL = 1000

# Emotion → sentiment mapping
POSITIVE_EMOTIONS = {
    "admiration", "amusement", "approval", "caring", "curiosity", "desire",
    "excitement", "gratitude", "joy", "love", "optimism", "pride", "relief",
}
NEGATIVE_EMOTIONS = {
    "anger", "annoyance", "disappointment", "disapproval", "disgust",
    "embarrassment", "fear", "grief", "nervousness", "remorse", "sadness",
}
NEUTRAL_EMOTIONS = {"confusion", "realization", "surprise", "neutral"}

# ── Dashboard ────────────────────────────────────────────────────────────────
DASH_HOST = "0.0.0.0"
DASH_PORT = 8050
DASH_DEBUG = False

# ── Topics Over Time ────────────────────────────────────────────────────────
TIME_BINS = 20
