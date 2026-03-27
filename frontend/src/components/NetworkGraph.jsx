import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { forceCollide, forceManyBody } from 'd3-force'
import Tooltip from './Tooltip'
import DetailPanel from './DetailPanel'
import TimelineBar from './TimelineBar'
import { fetchTimeline, fetchCategories, fetchCategoryEdges, fetchTopicPosts, fetchPostDetail } from '../api'

const HUB_COLORS = [
  '#636EFA', '#EF553B', '#00CC96', '#AB63FA', '#FFA15A', '#19D3F3',
  '#FF6692', '#B6E880', '#FF97FF', '#FECB52', '#72B7B2', '#E45756',
]

const SUBREDDIT_COLORS = {
  Teachers: '#636EFA',
  education: '#EF553B',
  edtech: '#00CC96',
  ChatGPT: '#AB63FA',
  teaching: '#FFA15A',
  ELATeachers: '#19D3F3',
  historyteachers: '#FF6692',
  ScienceTeachers: '#B6E880',
  matheducation: '#FF97FF',
  CSEducation: '#FECB52',
  StudentTeaching: '#72B7B2',
}

// ── Sentiment groups ──────────────────────────────────────────────────
const SENTIMENT_GROUPS = {
  sentiment_frustrated: { label: 'Frustrated',  color: '#ef4444' },
  sentiment_concerned:  { label: 'Concerned',   color: '#f97316' },
  sentiment_sad:        { label: 'Sad',          color: '#a855f7' },
  sentiment_optimistic: { label: 'Optimistic',   color: '#22c55e' },
  sentiment_curious:    { label: 'Curious',       color: '#3b82f6' },
  sentiment_neutral:    { label: 'Neutral',       color: '#64748b' },
}

// GoEmotions label → sentiment group (fallback when API doesn't provide sentiment_group)
const EMOTION_TO_SENTIMENT = {
  anger: 'sentiment_frustrated', annoyance: 'sentiment_frustrated',
  disapproval: 'sentiment_frustrated', disgust: 'sentiment_frustrated',
  fear: 'sentiment_concerned', nervousness: 'sentiment_concerned',
  caring: 'sentiment_concerned', confusion: 'sentiment_concerned',
  sadness: 'sentiment_sad', grief: 'sentiment_sad',
  disappointment: 'sentiment_sad', remorse: 'sentiment_sad',
  embarrassment: 'sentiment_sad',
  joy: 'sentiment_optimistic', optimism: 'sentiment_optimistic',
  excitement: 'sentiment_optimistic', pride: 'sentiment_optimistic',
  gratitude: 'sentiment_optimistic', admiration: 'sentiment_optimistic',
  approval: 'sentiment_optimistic', love: 'sentiment_optimistic',
  relief: 'sentiment_optimistic', amusement: 'sentiment_optimistic',
  curiosity: 'sentiment_curious', surprise: 'sentiment_curious',
  realization: 'sentiment_curious', desire: 'sentiment_curious',
  neutral: 'sentiment_neutral',
}

function getSentimentGroup(emotion) {
  return EMOTION_TO_SENTIMENT[emotion] || 'sentiment_neutral'
}

function getSentimentColor(emotion) {
  const group = getSentimentGroup(emotion)
  return SENTIMENT_GROUPS[group]?.color || '#64748b'
}

function dominantSentiment(sentCounts) {
  let max = 0, dominant = 'sentiment_neutral'
  for (const [group, count] of Object.entries(sentCounts)) {
    if (count > max) { max = count; dominant = group }
  }
  return dominant
}

const SCALE = 80

export default function NetworkGraph() {
  const fgRef = useRef()
  const [graphData, setGraphData] = useState({ nodes: [], links: [] })
  const [tooltip, setTooltip] = useState(null)
  const [selectedNode, setSelectedNode] = useState(null)

  const [viewMode, setViewMode] = useState('categories')
  const [drilldownTopic, setDrilldownTopic] = useState(null)

  const [categoryData, setCategoryData] = useState(null)
  const [drilldownData, setDrilldownData] = useState(null)

  const [timeline, setTimeline] = useState(null)
  const [timeRange, setTimeRange] = useState(null)

  // Color mode toggle: 'community' | 'sentiment'
  const [colorMode, setColorMode] = useState('community')

  useEffect(() => {
    Promise.all([
      fetchTimeline(),
      fetchCategories(),
      fetchCategoryEdges(),
    ]).then(([tl, cats, edges]) => {
      setTimeline(tl)
      setCategoryData({ cats, edges })
    })
  }, [])

  const topicColorMap = useMemo(() => {
    if (!categoryData) return {}
    const map = {}
    categoryData.cats.forEach((c, i) => {
      map[String(c.topic_id)] = HUB_COLORS[i % HUB_COLORS.length]
    })
    return map
  }, [categoryData])

  const selectedMonths = useMemo(() => {
    if (!timeline || !timeRange) return null
    const [lo, hi] = timeRange
    const set = new Set()
    for (let i = lo; i <= hi; i++) set.add(timeline.months[i].month)
    return set
  }, [timeline, timeRange])

  // Compute per-topic sentiment distributions (reactive to timeline)
  const topicSentiments = useMemo(() => {
    if (!timeline) return {}
    const months = timeline.months
    const lo = timeRange ? timeRange[0] : 0
    const hi = timeRange ? timeRange[1] : months.length - 1
    const result = {}
    for (let i = lo; i <= hi; i++) {
      const sent = months[i].sentiment_by_topic || {}
      for (const [tid, groups] of Object.entries(sent)) {
        if (!result[tid]) result[tid] = {}
        for (const [group, count] of Object.entries(groups)) {
          result[tid][group] = (result[tid][group] || 0) + count
        }
      }
    }
    return result
  }, [timeline, timeRange])

  const filteredStats = useMemo(() => {
    if (!timeline) return null
    const months = timeline.months
    if (!selectedMonths) {
      return { total: months.reduce((s, m) => s + m.total, 0), label: 'All time' }
    }
    let total = 0
    const [lo, hi] = timeRange
    for (let i = lo; i <= hi; i++) total += months[i].total
    return { total, label: `${months[lo].month} — ${months[hi].month}` }
  }, [timeline, selectedMonths, timeRange])

  // ── Category Overview Mode ──────────────────────────────────────────
  useEffect(() => {
    if (viewMode !== 'categories' || !categoryData) return

    const { cats, edges: catEdges } = categoryData
    const nodes = []
    const links = []

    cats.forEach((c, i) => {
      const communityColor = HUB_COLORS[i % HUB_COLORS.length]
      const tid = String(c.topic_id)

      let count = c.count || 0
      if (selectedMonths && timeline) {
        count = 0
        const [lo, hi] = timeRange
        for (let j = lo; j <= hi; j++) {
          count += (timeline.months[j].by_topic[tid] || 0)
        }
      }

      const sentDist = topicSentiments[tid] || {}
      const domSent = dominantSentiment(sentDist)
      const sentimentColor = SENTIMENT_GROUPS[domSent]?.color || '#64748b'

      nodes.push({
        id: `cat-${c.topic_id}`,
        type: 'category',
        topicId: c.topic_id,
        label: c.llm_label || c.auto_label || `Topic ${c.topic_id}`,
        count,
        totalCount: c.count || 0,
        description: c.llm_description || '',
        paragraph_summary: c.paragraph_summary || '',
        tags: c.tags_json || [],
        subreddits: c.subreddits_json || [],
        keywords: c.keywords || [],
        communityColor,
        sentimentColor,
        sentimentGroup: domSent,
        sentimentDist: sentDist,
        color: colorMode === 'sentiment' ? sentimentColor : communityColor,
        size: Math.max(25, Math.min(50, 20 + Math.sqrt(count) * 1.2)),
        fx: c.cx * SCALE,
        fy: c.cy * SCALE,
      })
    })

    catEdges.forEach(e => {
      links.push({
        source: `cat-${e.source_id}`,
        target: `cat-${e.target_id}`,
        type: 'overlap-edge',
        weight: e.overlap_count || 1,
      })
    })

    setGraphData({ nodes, links })
  }, [viewMode, categoryData, selectedMonths, timeline, timeRange, colorMode, topicSentiments])

  useEffect(() => {
    if (viewMode !== 'drilldown' || !drilldownTopic) return
    setDrilldownData(null)
    fetchTopicPosts(drilldownTopic.topicId).then(setDrilldownData)
  }, [viewMode, drilldownTopic])

  // ── Post Drill-Down Mode ────────────────────────────────────────────
  useEffect(() => {
    if (viewMode !== 'drilldown' || !drilldownData) return

    const nodes = []
    const links = []

    drilldownData.posts.forEach(p => {
      if (selectedMonths && p.created_month && !selectedMonths.has(p.created_month)) return

      const sub = p.subreddit || ''
      const communityColor = SUBREDDIT_COLORS[sub] || '#888888'
      const sentGroup = p.sentiment_group || getSentimentGroup(p.dominant_emotion || 'neutral')
      const sentimentColor = SENTIMENT_GROUPS[sentGroup]?.color || '#64748b'

      nodes.push({
        id: p.post_id,
        type: 'post',
        title: p.title || '',
        score: p.score || 0,
        numComments: p.num_comments || 0,
        subreddit: sub,
        summary: (p.summary || '').slice(0, 200),
        category: p.category || '',
        emotion: p.dominant_emotion || 'neutral',
        sentimentGroup: sentGroup,
        communityColor,
        sentimentColor,
        color: colorMode === 'sentiment' ? sentimentColor : communityColor,
        size: Math.max(3, Math.min(9, 3 + Math.log(1 + (p.score || 0)) * 1.5)),
        x: p.umap_x * SCALE,
        y: p.umap_y * SCALE,
      })
    })

    const postIds = new Set(nodes.map(n => n.id))
    drilldownData.edges.forEach(e => {
      if (postIds.has(e.source_id) && postIds.has(e.target_id)) {
        links.push({
          source: e.source_id,
          target: e.target_id,
          type: 'knn-edge',
          weight: e.weight || 0.5,
        })
      }
    })

    setGraphData({ nodes, links })
  }, [viewMode, drilldownData, selectedMonths, colorMode])

  useEffect(() => {
    if (graphData.nodes.length > 0 && fgRef.current) {
      // Longer delay for drilldown to let force simulation settle
      const delay = viewMode === 'drilldown' ? 800 : 500
      const timer = setTimeout(() => {
        if (fgRef.current) fgRef.current.zoomToFit(400, 60)
      }, delay)
      return () => clearTimeout(timer)
    }
  }, [graphData, viewMode])

  const configureForcesRef = useRef(null)
  configureForcesRef.current = () => {
    const fg = fgRef.current
    if (!fg) return
    if (viewMode === 'categories') {
      fg.d3Force('link')?.distance(200)
      fg.d3Force('charge', forceManyBody().strength(-300))
      fg.d3Force('collision', forceCollide(node => (node.size || 25) + 10))
      fg.d3Force('center', null)
    } else {
      fg.d3Force('link')?.distance(30)
      fg.d3Force('charge', forceManyBody().strength(-20))
      fg.d3Force('collision', forceCollide(node => (node.size || 5) + 2))
      fg.d3Force('center', null)
    }
  }

  useEffect(() => {
    const timer = setTimeout(() => configureForcesRef.current(), 100)
    return () => clearTimeout(timer)
  }, [viewMode, drilldownTopic])

  const handleNodeClick = useCallback((node) => {
    if (node.type === 'category') {
      setTooltip(null)
      setSelectedNode(null)
      setGraphData({ nodes: [], links: [] }) // Clear stale data before re-mount
      setDrilldownTopic({ topicId: node.topicId, label: node.label, color: node.color })
      setViewMode('drilldown')
    } else if (node.type === 'post') {
      fetchPostDetail(node.id).then(data => setSelectedNode({ type: 'post', data }))
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

  const handleBackToCategories = useCallback(() => {
    setTooltip(null)
    setSelectedNode(null)
    setGraphData({ nodes: [], links: [] }) // Clear stale data before re-mount
    setDrilldownTopic(null)
    setDrilldownData(null)
    setViewMode('categories')
  }, [])

  const paintNode = useCallback((node, ctx, globalScale) => {
    const r = node.size || 5

    if (node.type === 'category') {
      ctx.beginPath()
      ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
      const gradient = ctx.createRadialGradient(node.x, node.y, r * 0.5, node.x, node.y, r * 1.3)
      gradient.addColorStop(0, node.color)
      gradient.addColorStop(1, node.color + '00')
      ctx.fillStyle = gradient
      ctx.fill()

      ctx.beginPath()
      ctx.arc(node.x, node.y, r * 0.85, 0, Math.PI * 2)
      ctx.fillStyle = node.color
      ctx.fill()
      ctx.strokeStyle = 'rgba(255,255,255,0.5)'
      ctx.lineWidth = 2 / globalScale
      ctx.stroke()

      const countSize = Math.max(10, 16 / globalScale)
      ctx.font = `bold ${countSize}px -apple-system, sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'middle'
      ctx.fillStyle = '#ffffff'
      ctx.fillText(node.count, node.x, node.y)

      const labelSize = Math.max(10, 14 / globalScale)
      ctx.font = `bold ${labelSize}px -apple-system, sans-serif`
      ctx.textBaseline = 'top'
      ctx.strokeStyle = '#111111'
      ctx.lineWidth = 3 / globalScale
      ctx.strokeText(node.label, node.x, node.y + r + 4 / globalScale)
      ctx.fillStyle = '#ffffff'
      ctx.fillText(node.label, node.x, node.y + r + 4 / globalScale)
    } else {
      ctx.beginPath()
      ctx.arc(node.x, node.y, r, 0, Math.PI * 2)
      ctx.fillStyle = node.color
      ctx.fill()
      ctx.strokeStyle = 'rgba(255,255,255,0.4)'
      ctx.lineWidth = 0.5 / globalScale
      ctx.stroke()
    }
  }, [])

  const paintLink = useCallback((link, ctx) => {
    if (!link.source.x || !link.target.x) return
    ctx.beginPath()
    ctx.moveTo(link.source.x, link.source.y)
    ctx.lineTo(link.target.x, link.target.y)

    if (link.type === 'overlap-edge') {
      const alpha = Math.min(0.6, 0.1 + (link.weight || 1) * 0.003)
      ctx.strokeStyle = `rgba(255, 255, 255, ${alpha})`
      ctx.lineWidth = Math.max(1, Math.min(6, (link.weight || 1) * 0.03))
    } else if (link.type === 'knn-edge') {
      const w = link.weight || 0.5
      ctx.strokeStyle = `rgba(255, 255, 255, ${Math.min(0.2, w * 0.25)})`
      ctx.lineWidth = Math.max(0.3, w * 1.5)
    } else {
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.1)'
      ctx.lineWidth = 0.5
    }
    ctx.stroke()
  }, [])

  const legendItems = useMemo(() => {
    if (colorMode === 'sentiment') {
      const counts = {}
      graphData.nodes.forEach(n => {
        const g = n.sentimentGroup || 'sentiment_neutral'
        counts[g] = (counts[g] || 0) + (n.type === 'category' ? n.count : 1)
      })
      return Object.entries(SENTIMENT_GROUPS)
        .filter(([key]) => counts[key])
        .sort((a, b) => (counts[b[0]] || 0) - (counts[a[0]] || 0))
        .map(([key, { label, color }]) => ({
          key, label, color, count: counts[key] || 0,
        }))
    }

    if (viewMode === 'drilldown') {
      const subs = {}
      graphData.nodes.forEach(n => {
        if (n.type === 'post' && n.subreddit) {
          subs[n.subreddit] = (subs[n.subreddit] || 0) + 1
        }
      })
      return Object.entries(subs)
        .sort((a, b) => b[1] - a[1])
        .map(([sub, count]) => ({
          key: sub, label: `r/${sub}`, color: SUBREDDIT_COLORS[sub] || '#888', count,
        }))
    }

    return []
  }, [colorMode, viewMode, graphData])

  const visibleStats = useMemo(() => {
    const posts = graphData.nodes.filter(n => n.type === 'post').length
    const edges = graphData.links.length
    return { posts, edges }
  }, [graphData])

  return (
    <>
      <div className="filter-bar">
        {viewMode === 'drilldown' && (
          <button className="back-btn" onClick={handleBackToCategories}>
            &larr; Back to Categories
          </button>
        )}
        {viewMode === 'drilldown' && drilldownTopic && (
          <span className="breadcrumb">
            <span className="breadcrumb-dot" style={{ background: drilldownTopic.color }} />
            {drilldownTopic.label}
          </span>
        )}

        <div className="color-toggle">
          <button
            className={`toggle-opt ${colorMode === 'community' ? 'active' : ''}`}
            onClick={() => setColorMode('community')}
          >
            Community
          </button>
          <button
            className={`toggle-opt ${colorMode === 'sentiment' ? 'active' : ''}`}
            onClick={() => setColorMode('sentiment')}
          >
            Sentiment
          </button>
        </div>

        {filteredStats && (
          <span className="filter-stats">
            {viewMode === 'categories'
              ? `${filteredStats.total} posts`
              : `${visibleStats.posts} posts, ${visibleStats.edges} edges`
            }
            {timeRange && <span className="filter-date-label">{filteredStats.label}</span>}
          </span>
        )}
      </div>

      <button className="reset-btn" onClick={() => {
        setSelectedNode(null)
        if (fgRef.current) fgRef.current.zoomToFit(400, 60)
      }}>Reset View</button>

      <ForceGraph2D
        key={viewMode === 'categories' ? 'cat' : `drill-${drilldownTopic?.topicId}`}
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
        cooldownTicks={viewMode === 'categories' ? 0 : 100}
        d3AlphaMin={viewMode === 'categories' ? 1 : 0.01}
        minZoom={0.3}
        maxZoom={8}
      />

      {legendItems.length > 0 && (
        <div className="subreddit-legend">
          {legendItems.map(({ key, label, color, count }) => (
            <div key={key} className="subreddit-legend-item">
              <span className="legend-dot" style={{ background: color }} />
              <span>{label}</span>
              <span className="legend-count">{count}</span>
            </div>
          ))}
        </div>
      )}

      {timeline && timeline.months.length > 0 && (
        <TimelineBar
          months={timeline.months}
          topicColors={colorMode === 'sentiment' ? null : topicColorMap}
          selection={timeRange}
          onSelect={setTimeRange}
        />
      )}

      {tooltip && <Tooltip data={tooltip} />}
      <DetailPanel data={selectedNode} onClose={() => setSelectedNode(null)} />
    </>
  )
}
