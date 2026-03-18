const EMOTION_COLORS = {
  admiration: '#FFD700', amusement: '#FF69B4', anger: '#FF0000',
  annoyance: '#FF4500', approval: '#32CD32', caring: '#FF82AB',
  confusion: '#DDA0DD', curiosity: '#00CED1', desire: '#FF1493',
  disappointment: '#708090', disapproval: '#DC143C', disgust: '#556B2F',
  embarrassment: '#DB7093', excitement: '#FF6347', fear: '#8B008B',
  gratitude: '#00FA9A', grief: '#4B0082', joy: '#FFD700',
  love: '#FF69B4', nervousness: '#9370DB', neutral: '#A9A9A9',
  optimism: '#7FFF00', pride: '#DAA520', realization: '#87CEEB',
  relief: '#98FB98', remorse: '#6A5ACD', sadness: '#4169E1',
  surprise: '#FF8C00',
}

function StanceBadge({ stance }) {
  if (!stance) return null
  const colors = { agree: '#32CD32', disagree: '#DC143C', neutral: '#A9A9A9' }
  return (
    <span className="badge" style={{
      background: (colors[stance] || '#888') + '33',
      color: colors[stance] || '#888',
    }}>
      {stance}
    </span>
  )
}

function EmotionBar({ emotions }) {
  if (!emotions?.length) return null
  const total = emotions.reduce((s, e) => s + e.cnt, 0)
  return (
    <div className="emotion-bar-container">
      <div className="emotion-bar">
        {emotions.slice(0, 8).map(e => (
          <div
            key={e.dominant_emotion}
            className="emotion-bar-segment"
            style={{
              width: `${(e.cnt / total) * 100}%`,
              backgroundColor: EMOTION_COLORS[e.dominant_emotion] || '#888',
            }}
            title={`${e.dominant_emotion}: ${e.cnt}`}
          />
        ))}
      </div>
      <div className="emotion-bar-legend">
        {emotions.slice(0, 6).map(e => (
          <span key={e.dominant_emotion} className="emotion-legend-item">
            <span className="emotion-dot" style={{ backgroundColor: EMOTION_COLORS[e.dominant_emotion] || '#888' }} />
            {e.dominant_emotion} ({e.cnt})
          </span>
        ))}
      </div>
    </div>
  )
}

function HubPanel({ data }) {
  const keywords = Array.isArray(data.keywords) ? data.keywords : []
  const stanceTotal = Object.values(data.stance || {}).reduce((s, v) => s + v, 0)
  return (
    <>
      <h3 style={{ color: '#fff', marginBottom: 4 }}>{data.llm_label || data.auto_label}</h3>
      <div className="stat-row">
        <span className="badge badge-score">{data.count} posts</span>
      </div>
      {data.llm_description && (
        <p className="panel-desc">{data.llm_description}</p>
      )}
      {keywords.length > 0 && (
        <div className="keyword-section">
          <div className="section-label">Keywords</div>
          <div className="keyword-pills">
            {keywords.slice(0, 8).map((kw, i) => (
              <span key={i} className="keyword-pill">{kw}</span>
            ))}
          </div>
        </div>
      )}
      {data.top_posts?.length > 0 && (
        <div className="section">
          <div className="section-label">Top Posts</div>
          {data.top_posts.map(p => (
            <div key={p.post_id} className="post-item">
              <div className="post-item-title">{p.title}</div>
              <div className="post-item-meta">
                <span className="badge badge-sub">r/{p.subreddit}</span>
                <span className="badge badge-score">Score: {p.score}</span>
              </div>
            </div>
          ))}
        </div>
      )}
      {data.emotions?.length > 0 && (
        <div className="section">
          <div className="section-label">Emotion Breakdown</div>
          <EmotionBar emotions={data.emotions} />
        </div>
      )}
      {stanceTotal > 0 && (
        <div className="section">
          <div className="section-label">Stance Distribution</div>
          <div className="stat-row">
            {Object.entries(data.stance).map(([s, cnt]) => (
              <StanceBadge key={s} stance={`${s} (${Math.round(cnt / stanceTotal * 100)}%)`} />
            ))}
          </div>
        </div>
      )}
    </>
  )
}

function PostPanel({ data }) {
  const { post, comments } = data
  return (
    <>
      <h3 style={{ color: '#fff', marginBottom: 4 }}>{post.title}</h3>
      <div className="stat-row">
        <span className="badge badge-sub">r/{post.subreddit}</span>
        {post.category && <span className="badge badge-emotion">{post.category}</span>}
        <span className="badge badge-score">Score: {post.score}</span>
      </div>
      {post.summary && <p className="panel-desc">{post.summary}</p>}
      {comments?.length > 0 && (
        <div className="section">
          <div className="section-label">Comments ({comments.length})</div>
          <div className="comments-scroll">
            {comments.slice(0, 10).map(c => (
              <div key={c.id} className="comment-item">
                <div className="comment-header">
                  <strong>{c.author || '[deleted]'}</strong>
                  {c.dominant_emotion && (
                    <span className="emotion-tag">
                      <span className="emotion-dot" style={{ backgroundColor: EMOTION_COLORS[c.dominant_emotion] || '#888' }} />
                      {c.dominant_emotion}
                    </span>
                  )}
                  <StanceBadge stance={c.stance} />
                  {c.score != null && (
                    <span style={{ color: '#666', fontSize: 11, marginLeft: 'auto' }}>{c.score} pts</span>
                  )}
                </div>
                <div className="comment-body">{(c.body || '').slice(0, 300)}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
}

function EmotionHubPanel({ data }) {
  const sentimentTotal = Object.values(data.sentiment || {}).reduce((s, v) => s + v, 0)
  return (
    <>
      <h3 style={{ color: EMOTION_COLORS[data.emotion] || '#fff', marginBottom: 4 }}>
        {data.emotion}
      </h3>
      <div className="stat-row">
        <span className="badge badge-score">{data.total} comments</span>
      </div>
      {sentimentTotal > 0 && (
        <div className="section">
          <div className="section-label">Sentiment Breakdown</div>
          <div className="stat-row">
            {Object.entries(data.sentiment).map(([s, cnt]) => (
              <span key={s} className="badge" style={{
                background: s === 'positive' ? '#32CD3233' : s === 'negative' ? '#DC143C33' : '#A9A9A933',
                color: s === 'positive' ? '#32CD32' : s === 'negative' ? '#DC143C' : '#A9A9A9',
              }}>
                {s}: {cnt} ({Math.round(cnt / sentimentTotal * 100)}%)
              </span>
            ))}
          </div>
        </div>
      )}
      {data.top_posts?.length > 0 && (
        <div className="section">
          <div className="section-label">Top Posts</div>
          {data.top_posts.map(p => (
            <div key={p.post_id} className="post-item">
              <div className="post-item-title">{p.title}</div>
              <div className="post-item-meta">
                <span className="badge badge-sub">r/{p.subreddit}</span>
                <span className="badge badge-score">{p.comment_count} comments</span>
              </div>
            </div>
          ))}
        </div>
      )}
      {data.comments?.length > 0 && (
        <div className="section">
          <div className="section-label">Recent Comments</div>
          <div className="comments-scroll">
            {data.comments.slice(0, 10).map(c => (
              <div key={c.id} className="comment-item">
                <div className="comment-header">
                  <strong>{c.author || '[deleted]'}</strong>
                  <span className="badge badge-sub">r/{c.subreddit}</span>
                  <StanceBadge stance={c.stance} />
                </div>
                <div className="comment-body">{(c.body || '').slice(0, 300)}</div>
                <div className="comment-post-ref">{c.post_title}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
}

function CommentClusterPanel({ data }) {
  const keywords = Array.isArray(data.keywords) ? data.keywords : []
  const sentimentTotal = Object.values(data.sentiment || {}).reduce((s, v) => s + v, 0)
  return (
    <>
      <h3 style={{ color: '#fff', marginBottom: 4 }}>{data.label}</h3>
      <div className="stat-row">
        <span className="badge badge-score">{data.count} comments</span>
      </div>
      {data.description && <p className="panel-desc">{data.description}</p>}
      {keywords.length > 0 && (
        <div className="keyword-section">
          <div className="section-label">Keywords</div>
          <div className="keyword-pills">
            {keywords.slice(0, 8).map((kw, i) => (
              <span key={i} className="keyword-pill">{kw}</span>
            ))}
          </div>
        </div>
      )}
      {data.emotions?.length > 0 && (
        <div className="section">
          <div className="section-label">Emotion Breakdown</div>
          <EmotionBar emotions={data.emotions} />
        </div>
      )}
      {sentimentTotal > 0 && (
        <div className="section">
          <div className="section-label">Sentiment</div>
          <div className="stat-row">
            {Object.entries(data.sentiment).map(([s, cnt]) => (
              <span key={s} className="badge" style={{
                background: s === 'positive' ? '#32CD3233' : s === 'negative' ? '#DC143C33' : '#A9A9A933',
                color: s === 'positive' ? '#32CD32' : s === 'negative' ? '#DC143C' : '#A9A9A9',
              }}>
                {s}: {cnt} ({Math.round(cnt / sentimentTotal * 100)}%)
              </span>
            ))}
          </div>
        </div>
      )}
      {data.top_comments?.length > 0 && (
        <div className="section">
          <div className="section-label">Top Comments</div>
          <div className="comments-scroll">
            {data.top_comments.map(c => (
              <div key={c.id} className="comment-item">
                <div className="comment-header">
                  <strong>{c.author || '[deleted]'}</strong>
                  {c.dominant_emotion && (
                    <span className="emotion-tag">
                      <span className="emotion-dot" style={{ backgroundColor: EMOTION_COLORS[c.dominant_emotion] || '#888' }} />
                      {c.dominant_emotion}
                    </span>
                  )}
                  <StanceBadge stance={c.stance} />
                </div>
                <div className="comment-body">{(c.body || '').slice(0, 300)}</div>
                <div className="comment-post-ref">{c.post_title}</div>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  )
}

function CommentPanel({ data }) {
  return (
    <>
      <div className="stat-row" style={{ marginBottom: 8 }}>
        <strong style={{ color: '#bbb' }}>{data.author}</strong>
        {data.score != null && (
          <span className="badge badge-score">{data.score} pts</span>
        )}
      </div>
      <p className="panel-desc">{data.body}</p>
      <div className="stat-row">
        {data.emotion && (
          <span className="emotion-tag">
            <span className="emotion-dot" style={{ backgroundColor: EMOTION_COLORS[data.emotion] || '#888' }} />
            {data.emotion}
          </span>
        )}
        {data.sentiment && (
          <span className="badge" style={{
            background: data.sentiment === 'positive' ? '#32CD3233' : data.sentiment === 'negative' ? '#DC143C33' : '#A9A9A933',
            color: data.sentiment === 'positive' ? '#32CD32' : data.sentiment === 'negative' ? '#DC143C' : '#A9A9A9',
          }}>
            {data.sentiment}
          </span>
        )}
        <StanceBadge stance={data.stance} />
      </div>
      {data.postTitle && (
        <div className="section">
          <div className="section-label">Parent Post</div>
          <div className="post-item-title">{data.postTitle}</div>
        </div>
      )}
    </>
  )
}

export default function DetailPanel({ data, onClose }) {
  if (!data) return null

  return (
    <div className={`side-panel ${data ? 'open' : ''}`}>
      <button className="side-panel-close" onClick={onClose}>&times;</button>
      <div className="side-panel-content">
        {data.type === 'hub' && <HubPanel data={data.data} />}
        {(data.type === 'post' || data.type === 'comment-post') && <PostPanel data={data.data} />}
        {data.type === 'emotion-hub' && <EmotionHubPanel data={data.data} />}
        {data.type === 'comment-hub' && <CommentClusterPanel data={data.data} />}
        {data.type === 'comment' && <CommentPanel data={data.data} />}
      </div>
    </div>
  )
}
