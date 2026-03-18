#!/bin/bash
# Auto-refresh clustering pipeline — runs every 3 hours via cron
# Embeds new posts/comments and re-clusters everything
# Skips if classification is actively running to avoid DB locks

cd ~/reddit_scrap
VENV=~/reddit_scrap/.venv/bin/python3
LOG=/tmp/refresh_clusters.log

# Skip if classify is still running
if screen -ls | grep -q classify && ! grep -q "CLASSIFICATION_DONE" /tmp/classify.log 2>/dev/null; then
    echo "$(date): Skipped — classification still running" >> $LOG
    exit 0
fi

echo "$(date): Starting refresh..." >> $LOG

$VENV scripts/embed_posts.py >> $LOG 2>&1
$VENV scripts/recluster_topics.py >> $LOG 2>&1
$VENV scripts/embed_comments.py >> $LOG 2>&1
$VENV scripts/cluster_comments.py >> $LOG 2>&1
$VENV scripts/label_topic_clusters.py >> $LOG 2>&1
$VENV scripts/label_comment_clusters.py >> $LOG 2>&1

echo "$(date): Refresh complete." >> $LOG
