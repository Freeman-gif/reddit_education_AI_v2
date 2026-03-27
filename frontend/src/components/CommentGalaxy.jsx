import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import DeckGL from 'deck.gl'
import { ScatterplotLayer, PathLayer } from 'deck.gl'
import { OrthographicView } from 'deck.gl'
import Tooltip from './Tooltip'
import DetailPanel from './DetailPanel'
import { fetchYears, fetchCommentGalaxy, fetchCommentDetail, fetchCommentBundles } from '../api'

const HUB_COLORS = [
  [99, 110, 250, 200],   // #636EFA
  [239, 85, 59, 200],    // #EF553B
  [0, 204, 150, 200],    // #00CC96
  [171, 99, 250, 200],   // #AB63FA
  [255, 161, 90, 200],   // #FFA15A
  [25, 211, 243, 200],   // #19D3F3
  [255, 102, 146, 200],  // #FF6692
  [182, 232, 128, 200],  // #B6E880
  [255, 151, 255, 200],  // #FF97FF
  [254, 203, 82, 200],   // #FECB52
  [114, 183, 178, 200],  // #72B7B2
  [228, 87, 86, 200],    // #E45756
]

const SENTIMENT_COLORS = {
  positive: [50, 205, 50, 200],
  negative: [220, 20, 60, 200],
  neutral: [169, 169, 169, 200],
}

const COL = { comment_id: 0, x: 1, y: 2, cluster_id: 3, sentiment: 4, dominant_emotion: 5, year: 6 }

export default function CommentGalaxy() {
  const deckRef = useRef()
  const [rawData, setRawData] = useState(null)
  const [clusters, setClusters] = useState([])
  const [tooltip, setTooltip] = useState(null)
  const [selectedNode, setSelectedNode] = useState(null)
  const [sentimentMode, setSentimentMode] = useState(false)
  const [years, setYears] = useState([])
  const [selectedYears, setSelectedYears] = useState([])
  const [viewState, setViewState] = useState(null)
  const [bundles, setBundles] = useState([])
  const [showBundles, setShowBundles] = useState(true)

  // Load available years on mount
  useEffect(() => {
    fetchYears().then(d => setYears(d.comment_years || []))
  }, [])

  // Load galaxy data + bundles once
  useEffect(() => {
    fetchCommentGalaxy().then(data => {
      setRawData(data.data)
      setClusters(data.clusters || [])
    })
    fetchCommentBundles().then(data => {
      setBundles(data.bundles || [])
    })
  }, [])

  // Filter by year client-side
  const points = useMemo(() => {
    if (!rawData) return []
    if (selectedYears.length === 0) return rawData
    const yearSet = new Set(selectedYears)
    return rawData.filter(row => yearSet.has(row[COL.year]))
  }, [rawData, selectedYears])

  // Compute initial view state from data bounds
  useEffect(() => {
    if (points.length === 0) return
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
    for (const row of points) {
      if (row[COL.x] < minX) minX = row[COL.x]
      if (row[COL.x] > maxX) maxX = row[COL.x]
      if (row[COL.y] < minY) minY = row[COL.y]
      if (row[COL.y] > maxY) maxY = row[COL.y]
    }
    const cx = (minX + maxX) / 2
    const cy = (minY + maxY) / 2
    const rangeX = maxX - minX || 1
    const rangeY = maxY - minY || 1
    const zoom = Math.log2(Math.min(
      (window.innerWidth * 0.8) / rangeX,
      (window.innerHeight * 0.8) / rangeY,
    ))
    setViewState({
      target: [cx, cy, 0],
      zoom: Math.max(-2, Math.min(zoom, 6)),
      minZoom: -3,
      maxZoom: 10,
    })
  }, [points])

  // Build cluster label map
  const clusterMap = useMemo(() => {
    const m = {}
    clusters.forEach(c => { m[c.cluster_id] = c })
    return m
  }, [clusters])

  const toggleYear = useCallback((year) => {
    setSelectedYears(prev =>
      prev.includes(year) ? prev.filter(y => y !== year) : [...prev, year]
    )
  }, [])

  const handleClick = useCallback((info) => {
    if (!info.object) {
      setSelectedNode(null)
      return
    }
    const row = info.object
    const commentId = row[COL.comment_id]
    fetchCommentDetail(commentId).then(data => {
      if (data.error) return
      setSelectedNode({
        type: 'comment',
        data: {
          body: data.body,
          author: data.author,
          score: data.score,
          emotion: data.dominant_emotion,
          sentiment: data.sentiment,
          stance: data.stance,
          postTitle: data.post_title,
          postId: data.post_id,
        },
      })
    })
  }, [])

  const handleHover = useCallback((info) => {
    if (!info.object) {
      setTooltip(null)
      return
    }
    const row = info.object
    const cluster = clusterMap[row[COL.cluster_id]]
    setTooltip({
      node: {
        type: 'comment-scatter',
        clusterLabel: cluster?.label || `Cluster ${row[COL.cluster_id]}`,
        sentiment: row[COL.sentiment],
        emotion: row[COL.dominant_emotion],
      },
      x: info.x,
      y: info.y,
    })
  }, [clusterMap])

  const bundleLayer = useMemo(() => new PathLayer({
    id: 'cluster-bundles',
    data: bundles,
    getPath: d => d.path,
    getColor: d => [255, 255, 255, Math.floor(15 + d.weight * 30)],
    getWidth: d => Math.max(1, d.weight * 4),
    widthMinPixels: 1,
    widthMaxPixels: 5,
    widthUnits: 'pixels',
    visible: showBundles,
    billboard: false,
  }), [bundles, showBundles])

  const layer = useMemo(() => new ScatterplotLayer({
    id: 'comment-scatter',
    data: points,
    pickable: true,
    radiusMinPixels: 2,
    radiusMaxPixels: 8,
    getPosition: d => [d[COL.x], d[COL.y], 0],
    getFillColor: d => {
      if (sentimentMode) {
        return SENTIMENT_COLORS[d[COL.sentiment]] || SENTIMENT_COLORS.neutral
      }
      return HUB_COLORS[d[COL.cluster_id] % HUB_COLORS.length]
    },
    getRadius: 0.15,
    updateTriggers: {
      getFillColor: sentimentMode,
    },
  }), [points, sentimentMode])

  if (!viewState) {
    return <div style={{ width: '100%', height: '100%', background: '#111111', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#666' }}>Loading galaxy...</div>
  }

  return (
    <>
      <div className="filter-bar">
        <label className="sentiment-toggle">
          <input
            type="checkbox"
            checked={showBundles}
            onChange={e => setShowBundles(e.target.checked)}
          />
          <span className="toggle-label">Cluster Links</span>
        </label>
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

      <div style={{ width: '100%', height: '100%', background: '#111111', position: 'relative' }}>
        <DeckGL
          ref={deckRef}
          views={new OrthographicView({ id: 'ortho' })}
          initialViewState={viewState}
          controller={true}
          layers={[bundleLayer, layer]}
          onClick={handleClick}
          onHover={handleHover}
          getCursor={({ isHovering }) => isHovering ? 'pointer' : 'grab'}
        />
      </div>

      {tooltip && <Tooltip data={tooltip} />}

      <DetailPanel data={selectedNode} onClose={() => setSelectedNode(null)} />

      {/* Cluster legend */}
      {!sentimentMode && clusters.length > 0 && (
        <div style={{
          position: 'absolute', bottom: 12, left: 12, background: 'rgba(0,0,0,0.75)',
          borderRadius: 8, padding: '8px 12px', fontSize: 11, color: '#ccc', maxWidth: 300,
          pointerEvents: 'none',
        }}>
          {clusters.map(c => {
            const rgba = HUB_COLORS[c.cluster_id % HUB_COLORS.length]
            return (
              <div key={c.cluster_id} style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
                <span style={{
                  width: 10, height: 10, borderRadius: '50%', flexShrink: 0,
                  background: `rgba(${rgba[0]},${rgba[1]},${rgba[2]},1)`,
                }} />
                <span>{c.label} ({c.count})</span>
              </div>
            )
          })}
        </div>
      )}
    </>
  )
}
