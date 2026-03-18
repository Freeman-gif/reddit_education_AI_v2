import { useState, useEffect, useCallback, useRef } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { forceCollide, forceManyBody } from 'd3-force'
import Tooltip from './Tooltip'
import DetailPanel from './DetailPanel'
import { fetchYears, fetchHubs, fetchHubEdges, fetchAllPosts, fetchHubDetail, fetchPostDetail } from '../api'

const HUB_COLORS = [
  '#636EFA', '#EF553B', '#00CC96', '#AB63FA', '#FFA15A', '#19D3F3',
  '#FF6692', '#B6E880', '#FF97FF', '#FECB52', '#72B7B2', '#E45756',
]

const SCALE = 80

export default function NetworkGraph() {
  const fgRef = useRef()
  const [graphData, setGraphData] = useState({ nodes: [], links: [] })
  const [tooltip, setTooltip] = useState(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [years, setYears] = useState([])
  const [selectedYears, setSelectedYears] = useState([])

  // Load available years on mount
  useEffect(() => {
    fetchYears().then(d => setYears(d.post_years || []))
  }, [])

  const toggleYear = useCallback((year) => {
    setSelectedYears(prev =>
      prev.includes(year) ? prev.filter(y => y !== year) : [...prev, year]
    )
  }, [])

  // Load everything
  useEffect(() => {
    Promise.all([
      fetchHubs(),
      fetchHubEdges(),
      fetchAllPosts(selectedYears),
    ]).then(([hubs, hubEdges, allPosts]) => {
      const nodes = []
      const links = []
      const colorMap = {}

      // Hub nodes
      hubs.forEach((h, i) => {
        const color = HUB_COLORS[i % HUB_COLORS.length]
        colorMap[h.topic_id] = color
        nodes.push({
          id: `hub-${h.topic_id}`,
          label: h.llm_label || h.auto_label || `Topic ${h.topic_id}`,
          type: 'hub',
          topicId: h.topic_id,
          count: h.count || 0,
          description: h.llm_description || '',
          color,
          size: Math.max(6, Math.min(18, 6 + Math.log(1 + (h.count || 0)) * 3)),
          fx: h.cx * SCALE,
          fy: h.cy * SCALE,
        })
      })

      // Hub-to-hub edges
      hubEdges.forEach(e => {
        links.push({
          source: `hub-${e.source_id}`,
          target: `hub-${e.target_id}`,
          type: 'topic-edge',
        })
      })

      // All post nodes — colored by topic
      allPosts.posts.forEach(p => {
        nodes.push({
          id: p.post_id,
          type: 'post',
          title: p.title || '',
          score: p.score || 0,
          numComments: p.num_comments || 0,
          subreddit: p.subreddit || '',
          summary: (p.summary || '').slice(0, 200),
          category: p.category || '',
          emotion: p.dominant_emotion || 'neutral',
          color: colorMap[p.topic_id] || '#636EFA',
          size: Math.max(3, Math.min(9, 3 + Math.log(1 + (p.score || 0)) * 1.5)),
          x: p.umap_x * SCALE,
          y: p.umap_y * SCALE,
        })
        // Membership edge: hub → post
        links.push({
          source: `hub-${p.topic_id}`,
          target: p.post_id,
          type: 'membership',
        })
      })

      // KNN edges between posts
      allPosts.edges.forEach(e => {
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

  // Configure D3 forces for natural radial clustering
  useEffect(() => {
    const fg = fgRef.current
    if (!fg) return

    fg.d3Force('link')
      .distance(link => {
        if (link.type === 'membership') return 40
        if (link.type === 'topic-edge') return 150
        return 60
      })

    fg.d3Force('charge', forceManyBody().strength(-50))
    fg.d3Force('collision', forceCollide(node => (node.size || 5) + 2))
    fg.d3Force('center', null)
  }, [])

  // Click handler
  const handleNodeClick = useCallback((node) => {
    if (node.type === 'hub') {
      fetchHubDetail(node.topicId)
        .then(data => setSelectedNode({ type: 'hub', data }))
    } else if (node.type === 'post') {
      fetchPostDetail(node.id)
        .then(data => setSelectedNode({ type: 'post', data }))
    }
  }, [])

  // Hover handler
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

  // Custom node painting
  const paintNode = useCallback((node, ctx, globalScale) => {
    const r = node.size || 5

    // Solid filled circle
    ctx.beginPath()
    ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
    ctx.fillStyle = node.color
    ctx.fill()

    // Crisp 1px white border
    ctx.strokeStyle = 'white'
    ctx.lineWidth = 1 / globalScale
    ctx.stroke()

    // Label below the node (hubs only)
    if (node.type === 'hub') {
      const fontSize = Math.max(10, 14 / globalScale)
      ctx.font = `bold ${fontSize}px -apple-system, sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'

      ctx.strokeStyle = '#111111'
      ctx.lineWidth = 3 / globalScale
      ctx.strokeText(node.label, node.x, node.y + r + 2 / globalScale)

      ctx.fillStyle = '#ffffff'
      ctx.fillText(node.label, node.x, node.y + r + 2 / globalScale)
    }
  }, [])

  // Custom link painting
  const paintLink = useCallback((link, ctx) => {
    if (!link.source.x || !link.target.x) return

    ctx.beginPath()
    ctx.moveTo(link.source.x, link.source.y)
    ctx.lineTo(link.target.x, link.target.y)

    if (link.type === 'topic-edge') {
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.25)'
      ctx.lineWidth = 1.5
    } else if (link.type === 'membership') {
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
      <button className="reset-btn" onClick={() => {
        setSelectedNode(null)
        if (fgRef.current) fgRef.current.zoomToFit(400, 60)
      }}>Reset View</button>

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
