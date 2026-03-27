const SENTIMENT_LABELS = {
  sentiment_frustrated: 'Frustrated',
  sentiment_concerned: 'Concerned',
  sentiment_sad: 'Sad',
  sentiment_optimistic: 'Optimistic',
  sentiment_curious: 'Curious',
  sentiment_neutral: 'Neutral',
}

const SENTIMENT_COLORS = {
  sentiment_frustrated: '#ef4444',
  sentiment_concerned: '#f97316',
  sentiment_sad: '#a855f7',
  sentiment_optimistic: '#22c55e',
  sentiment_curious: '#3b82f6',
  sentiment_neutral: '#64748b',
}

export default function Tooltip({ data }) {
  if (!data?.node) return null

  const { node, x, y } = data

  const style = {
    left: Math.min(x + 16, window.innerWidth - 380),
    top: Math.min(y - 10, window.innerHeight - 300),
  }

  if (node.type === 'category') {
    const tags = (node.tags || []).slice(0, 5)
    const subs = (node.subreddits || []).slice(0, 4)

    // Sentiment distribution for category tooltip
    const sentDist = node.sentimentDist || {}
    const sentEntries = Object.entries(sentDist)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 4)
    const sentTotal = Object.values(sentDist).reduce((s, v) => s + v, 0)

    return (
      <div className="tooltip-overlay tooltip-category" style={style}>
        <h3>{node.label}</h3>
        <div className="meta">
          <span className="badge badge-sub">{node.count} posts</span>
          {node.sentimentGroup && (
            <span className="badge" style={{
              background: (SENTIMENT_COLORS[node.sentimentGroup] || '#64748b') + '33',
              color: SENTIMENT_COLORS[node.sentimentGroup] || '#64748b',
            }}>
              {SENTIMENT_LABELS[node.sentimentGroup] || node.sentimentGroup}
            </span>
          )}
        </div>
        {node.paragraph_summary && (
          <div className="summary">{node.paragraph_summary}</div>
        )}
        {/* Sentiment distribution bar */}
        {sentEntries.length > 0 && sentTotal > 0 && (
          <div className="tooltip-sem-bar">
            <div className="sem-bar">
              {sentEntries.map(([group, count]) => (
                <div
                  key={group}
                  className="sem-bar-seg"
                  style={{
                    width: `${(count / sentTotal) * 100}%`,
                    background: SENTIMENT_COLORS[group] || '#64748b',
                  }}
                  title={`${SENTIMENT_LABELS[group]}: ${count}`}
                />
              ))}
            </div>
            <div className="sem-bar-labels">
              {sentEntries.map(([group, count]) => (
                <span key={group} style={{ color: SENTIMENT_COLORS[group] || '#64748b', fontSize: 10 }}>
                  {SENTIMENT_LABELS[group]} {Math.round(count / sentTotal * 100)}%
                </span>
              ))}
            </div>
          </div>
        )}
        {tags.length > 0 && (
          <div className="tooltip-tags">
            {tags.map(t => (
              <span key={t.tag} className="tooltip-tag-pill">
                {t.tag} <span className="tag-count">{t.count}</span>
              </span>
            ))}
          </div>
        )}
        {subs.length > 0 && (
          <div className="tooltip-subs">
            {subs.map(s => (
              <span key={s.subreddit} className="badge badge-sub" style={{ marginRight: 4 }}>
                r/{s.subreddit} ({s.count})
              </span>
            ))}
          </div>
        )}
        <div className="summary" style={{ marginTop: 6, color: '#666', fontStyle: 'italic' }}>
          Click to explore posts
        </div>
      </div>
    )
  }

  if (node.type === 'hub') {
    return (
      <div className="tooltip-overlay" style={style}>
        <h3>{node.label}</h3>
        <div className="meta">
          <span className="badge badge-sub">{node.count} posts</span>
        </div>
        {node.description && <div className="summary">{node.description}</div>}
        <div className="summary" style={{ marginTop: 6, color: '#666', fontStyle: 'italic' }}>
          Click to expand
        </div>
      </div>
    )
  }

  if (node.type === 'post') {
    return (
      <div className="tooltip-overlay" style={style}>
        <h3>{node.title || 'Untitled'}</h3>
        <div className="meta">
          <span className="badge badge-sub">r/{node.subreddit}</span>
          <span className="badge badge-emotion">{node.emotion}</span>
          <span className="badge badge-score">Score: {node.score}</span>
          {node.sentimentGroup && (
            <span className="badge" style={{
              background: (SENTIMENT_COLORS[node.sentimentGroup] || '#64748b') + '33',
              color: SENTIMENT_COLORS[node.sentimentGroup] || '#64748b',
            }}>
              {SENTIMENT_LABELS[node.sentimentGroup] || node.sentimentGroup}
            </span>
          )}
        </div>
        {node.summary && <div className="summary">{node.summary}</div>}
      </div>
    )
  }

  if (node.type === 'comment-scatter') {
    return (
      <div className="tooltip-overlay" style={style}>
        <h3>{node.clusterLabel}</h3>
        <div className="meta">
          <span className="badge badge-emotion">{node.emotion}</span>
          <span className="badge badge-sub">{node.sentiment}</span>
        </div>
      </div>
    )
  }

  if (node.type === 'emotion-hub') {
    return (
      <div className="tooltip-overlay" style={style}>
        <h3>{node.label}</h3>
        <div className="meta">
          <span className="badge badge-emotion">{node.count} comments</span>
        </div>
      </div>
    )
  }

  if (node.type === 'comment-post') {
    return (
      <div className="tooltip-overlay" style={style}>
        <h3>{node.title || 'Post'}</h3>
        <div className="meta">
          <span className="badge badge-sub">{node.commentCount} comments</span>
        </div>
      </div>
    )
  }

  return null
}
