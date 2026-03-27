#!/bin/bash
# Auto-refresh clustering pipeline — runs every 3 hours via cron
# Embeds new posts/comments, re-clusters topics, and rebuilds comment galaxy
# Skips if classification is actively running to avoid DB locks

cd ~/reddit_scrap
VENV=~/reddit_scrap/.venv/bin/python3
LOG=/tmp/refresh_clusters.log

# Pause any DB-writing processes during refresh to avoid locks
CLASSIFY_PID=$(pgrep -f "run.py filter llm" || true)
COMMENTS_PID=$(pgrep -f "collect_comments" || true)

if [ -n "$CLASSIFY_PID" ]; then
    echo "$(date): Pausing classify (PID $CLASSIFY_PID)" >> $LOG
    kill -STOP $CLASSIFY_PID 2>/dev/null
fi
if [ -n "$COMMENTS_PID" ]; then
    echo "$(date): Pausing comments (PID $COMMENTS_PID)" >> $LOG
    kill -STOP $COMMENTS_PID 2>/dev/null
fi

echo "$(date): Starting refresh..." >> $LOG

# Post pipeline: embed → recluster → label topics
$VENV scripts/embed_posts.py >> $LOG 2>&1
$VENV scripts/recluster_topics.py >> $LOG 2>&1
$VENV scripts/label_topic_clusters.py >> $LOG 2>&1

# Comment pipeline: embed → HDBSCAN galaxy (includes labeling) → edge bundles
$VENV scripts/embed_comments.py >> $LOG 2>&1
$VENV scripts/precompute_galaxy.py >> $LOG 2>&1
$VENV scripts/compute_bundles.py >> $LOG 2>&1

# Resume paused processes
if [ -n "$CLASSIFY_PID" ] && kill -0 $CLASSIFY_PID 2>/dev/null; then
    kill -CONT $CLASSIFY_PID 2>/dev/null
    echo "$(date): Resumed classify (PID $CLASSIFY_PID)" >> $LOG
fi
if [ -n "$COMMENTS_PID" ] && kill -0 $COMMENTS_PID 2>/dev/null; then
    kill -CONT $COMMENTS_PID 2>/dev/null
    echo "$(date): Resumed comments (PID $COMMENTS_PID)" >> $LOG
fi

echo "$(date): Refresh complete." >> $LOG
