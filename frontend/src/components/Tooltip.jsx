export default function Tooltip({ data }) {
  if (!data?.node) return null

  const { node, x, y } = data

  // Position: offset from cursor, keep on screen
  const style = {
    left: Math.min(x + 16, window.innerWidth - 380),
    top: Math.min(y - 10, window.innerHeight - 200),
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
        </div>
        {node.summary && <div className="summary">{node.summary}</div>}
      </div>
    )
  }

  // Emotion hub / comment-post in galaxy
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
