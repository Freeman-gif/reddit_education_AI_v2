import { useState, useEffect, useCallback, useRef } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { forceCollide, forceManyBody } from 'd3-force'
import Tooltip from './Tooltip'
import DetailPanel from './DetailPanel'
import { fetchYears, fetchCommentGalaxy, fetchCommentCluster } from '../api'

const HUB_COLORS = [
  '#636EFA', '#EF553B', '#00CC96', '#AB63FA', '#FFA15A', '#19D3F3',
  '#FF6692', '#B6E880', '#FF97FF', '#FECB52', '#72B7B2', '#E45756',
]

const SENTIMENT_COLORS = {
  positive: '#32CD32',
  negative: '#DC143C',
  neutral: '#A9A9A9',
}

const SCALE = 80

export default function CommentGalaxy() {
  const fgRef = useRef()
  const [graphData, setGraphData] = useState({ nodes: [], links: [] })
  const [tooltip, setTooltip] = useState(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [sentimentMode, setSentimentMode] = useState(false)
  const [years, setYears] = useState([])
  const [selectedYears, setSelectedYears] = useState([])

  // Load available years on mount
  useEffect(() => {
    fetchYears().then(d => setYears(d.comment_years || []))
  }, [])

  // Load graph data
  useEffect(() => {
    fetchCommentGalaxy(selectedYears).then(data => {
        const nodes = []
        const links = []
        const colorMap = {}

        // Cluster hub nodes
        data.hubs.forEach((h, i) => {
          const color = HUB_COLORS[i % HUB_COLORS.length]
          colorMap[h.cluster_id] = color
          nodes.push({
            id: `cluster-${h.cluster_id}`,
            label: h.label || `Cluster ${h.cluster_id}`,
            type: 'comment-hub',
            clusterId: h.cluster_id,
            count: h.count || 0,
            description: h.description || '',
            color,
            size: Math.max(6, Math.min(18, 6 + Math.log(1 + (h.count || 0)) * 3)),
            fx: h.cx * SCALE,
            fy: h.cy * SCALE,
          })
        })

        // Comment nodes
        data.comments.forEach(c => {
          nodes.push({
            id: c.comment_id,
            type: 'comment',
            body: (c.body || '').slice(0, 200),
            author: c.author || '[deleted]',
            score: c.score || 0,
            postId: c.post_id,
            postTitle: c.post_title || '',
            emotion: c.dominant_emotion || 'neutral',
            sentiment: c.sentiment || 'neutral',
            stance: c.stance || '',
            clusterId: c.cluster_id,
            clusterColor: colorMap[c.cluster_id] || '#636EFA',
            color: colorMap[c.cluster_id] || '#636EFA',
            size: Math.max(3, Math.min(9, 3 + Math.log(1 + (c.score || 0)) * 1.5)),
            x: c.umap_x * SCALE,
            y: c.umap_y * SCALE,
          })
          // Membership edge
          links.push({
            source: `cluster-${c.cluster_id}`,
            target: c.comment_id,
            type: 'membership',
          })
        })

        // KNN edges
        data.edges.forEach(e => {
          links.push({
            source: e.source_id,
            target: e.target_id,
            weight: e.weight,
            type: 'knn',
          })
        })

        setGraphData({ nodes, links })
      })
  }, [selectedYears])

  // Zoom to fit after data loads
  useEffect(() => {
    if (graphData.nodes.length > 0 && fgRef.current) {
      setTimeout(() => fgRef.current.zoomToFit(400, 40), 500)
    }
  }, [graphData])

  // Configure D3 forces
  useEffect(() => {
    const fg = fgRef.current
    if (!fg) return
    fg.d3Force('link')
      .distance(link => {
        if (link.type === 'membership') return 40
        return 60
      })
    fg.d3Force('charge', forceManyBody().strength(-50))
    fg.d3Force('collision', forceCollide(node => (node.size || 5) + 2))
    fg.d3Force('center', null)
  }, [])

  const toggleYear = useCallback((year) => {
    setSelectedYears(prev =>
      prev.includes(year) ? prev.filter(y => y !== year) : [...prev, year]
    )
  }, [])

  const handleNodeClick = useCallback((node) => {
    if (node.type === 'comment-hub') {
      fetchCommentCluster(node.clusterId)
        .then(data => setSelectedNode({ type: 'comment-hub', data }))
    } else if (node.type === 'comment') {
      // Show comment detail client-side
      setSelectedNode({
        type: 'comment',
        data: {
          body: node.body,
          author: node.author,
          score: node.score,
          emotion: node.emotion,
          sentiment: node.sentiment,
          stance: node.stance,
          postTitle: node.postTitle,
          postId: node.postId,
        },
      })
    }
  }, [])

  const handleNodeHover = useCallback((node) => {
    if (!node) {
      setTooltip(null)
      document.body.style.cursor = 'default'
      return
    }
    document.body.style.cursor = 'pointer'
    const fg = fgRef.current
    if (!fg) return
    const coords = fg.graph2ScreenCoords(node.x, node.y)
    setTooltip({ node, x: coords.x, y: coords.y })
  }, [])

  const paintNode = useCallback((node, ctx, globalScale) => {
    const r = node.size || 5

    ctx.beginPath()
    ctx.arc(node.x, node.y, r, 0, Math.PI * 2)

    if (node.type === 'comment' && sentimentMode) {
      ctx.fillStyle = SENTIMENT_COLORS[node.sentiment] || '#A9A9A9'
    } else {
      ctx.fillStyle = node.color
    }
    ctx.fill()

    ctx.strokeStyle = 'white'
    ctx.lineWidth = 1 / globalScale
    ctx.stroke()

    if (node.type === 'comment-hub') {
      const fontSize = Math.max(8, 12 / globalScale)
      ctx.font = `bold ${fontSize}px -apple-system, sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'
      ctx.strokeStyle = '#111111'
      ctx.lineWidth = 3 / globalScale
      ctx.strokeText(node.label, node.x, node.y + r + 2 / globalScale)
      ctx.fillStyle = '#ffffff'
      ctx.fillText(node.label, node.x, node.y + r + 2 / globalScale)
    }
  }, [sentimentMode])

  const paintLink = useCallback((link, ctx) => {
    if (!link.source.x || !link.target.x) return
    ctx.beginPath()
    ctx.moveTo(link.source.x, link.source.y)
    ctx.lineTo(link.target.x, link.target.y)
    if (link.type === 'membership') {
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)'
      ctx.lineWidth = 0.5
    } else {
      ctx.strokeStyle = `rgba(255, 255, 255, ${Math.min(0.2, (link.weight || 0.5) * 0.25)})`
      ctx.lineWidth = Math.max(0.3, (link.weight || 0.5) * 1.5)
    }
    ctx.stroke()
  }, [])

  return (
    <>
      <div className="filter-bar">
        <label className="sentiment-toggle">
          <input
            type="checkbox"
            checked={sentimentMode}
            onChange={e => setSentimentMode(e.target.checked)}
          />
          <span className="toggle-label">Sentiment</span>
          {sentimentMode && (
            <span className="legend-inline">
              <span className="legend-dot" style={{ background: '#32CD32' }} /> pos
              <span className="legend-dot" style={{ background: '#DC143C' }} /> neg
              <span className="legend-dot" style={{ background: '#A9A9A9' }} /> neutral
            </span>
          )}
        </label>
        <div className="year-filter">
          {years.map(y => (
            <button
              key={y}
              className={`year-pill ${selectedYears.includes(y) ? 'active' : ''}`}
              onClick={() => toggleYear(y)}
            >
              {y}
            </button>
          ))}
        </div>
      </div>

      <ForceGraph2D
        ref={fgRef}
        graphData={graphData}
        backgroundColor="#111111"
        dagMode={null}
        nodeCanvasObject={paintNode}
        nodePointerAreaPaint={(node, color, ctx) => {
          ctx.beginPath()
          ctx.arc(node.x, node.y, (node.size || 5) * 1.5, 0, Math.PI * 2)
          ctx.fillStyle = color
          ctx.fill()
        }}
        linkCanvasObject={paintLink}
        onNodeClick={handleNodeClick}
        onNodeHover={handleNodeHover}
        onBackgroundClick={() => setSelectedNode(null)}
        d3AlphaDecay={0.05}
        d3VelocityDecay={0.3}
        warmupTicks={50}
        cooldownTime={3000}
        minZoom={0.3}
        maxZoom={8}
      />

      {tooltip && <Tooltip data={tooltip} />}

      <DetailPanel data={selectedNode} onClose={() => setSelectedNode(null)} />
    </>
  )
}
