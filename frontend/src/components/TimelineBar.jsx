import { useState, useRef, useCallback, useMemo, useEffect } from 'react'

const SENTIMENT_BAR_COLORS = {
  sentiment_frustrated: '#ef4444',
  sentiment_concerned: '#f97316',
  sentiment_sad: '#a855f7',
  sentiment_optimistic: '#22c55e',
  sentiment_curious: '#3b82f6',
  sentiment_neutral: '#64748b',
}

/**
 * Horizontal bar chart of monthly post counts with drag-to-select range.
 *
 * Props:
 *   months      – [{month, total, by_topic, sentiment_by_topic}, ...]
 *   topicColors – {topicId: color, ...} or null (null = sentiment mode)
 *   selection   – [startIdx, endIdx] | null
 *   onSelect    – (range: [startIdx, endIdx] | null) => void
 */
export default function TimelineBar({ months, topicColors, selection, onSelect }) {
  const svgRef = useRef()
  const [dragging, setDragging] = useState(false)
  const [dragStart, setDragStart] = useState(null)
  const [hoverIdx, setHoverIdx] = useState(null)

  const W = months.length  // one bar per month
  const BAR_W = 16
  const GAP = 2
  const totalW = W * (BAR_W + GAP)
  const H = 56
  const maxCount = useMemo(() => Math.max(1, ...months.map(m => m.total)), [months])

  // Convert page X to month index
  const xToIdx = useCallback((pageX) => {
    const svg = svgRef.current
    if (!svg) return 0
    const rect = svg.getBoundingClientRect()
    const x = pageX - rect.left + svg.parentElement.scrollLeft
    return Math.max(0, Math.min(W - 1, Math.floor(x / (BAR_W + GAP))))
  }, [W])

  const handleMouseDown = useCallback((e) => {
    e.preventDefault()
    const idx = xToIdx(e.pageX)
    setDragging(true)
    setDragStart(idx)
  }, [xToIdx])

  const handleMouseMove = useCallback((e) => {
    const idx = xToIdx(e.pageX)
    setHoverIdx(idx)
    if (!dragging) return
    const lo = Math.min(dragStart, idx)
    const hi = Math.max(dragStart, idx)
    onSelect([lo, hi])
  }, [dragging, dragStart, xToIdx, onSelect])

  const handleMouseUp = useCallback((e) => {
    if (!dragging) return
    setDragging(false)
    const idx = xToIdx(e.pageX)
    const lo = Math.min(dragStart, idx)
    const hi = Math.max(dragStart, idx)
    onSelect([lo, hi])
  }, [dragging, dragStart, xToIdx, onSelect])

  // Clear selection on double-click
  const handleDoubleClick = useCallback(() => {
    onSelect(null)
  }, [onSelect])

  // Attach window listeners for drag
  useEffect(() => {
    if (!dragging) return
    const up = (e) => { handleMouseUp(e); setDragging(false) }
    window.addEventListener('mouseup', up)
    return () => window.removeEventListener('mouseup', up)
  }, [dragging, handleMouseUp])

  // Year labels
  const yearLabels = useMemo(() => {
    const labels = []
    let lastYear = ''
    months.forEach((m, i) => {
      const year = m.month.slice(0, 4)
      if (year !== lastYear) {
        labels.push({ idx: i, year })
        lastYear = year
      }
    })
    return labels
  }, [months])

  // Selected range info
  const rangeInfo = useMemo(() => {
    if (!selection) return null
    const [lo, hi] = selection
    let total = 0
    for (let i = lo; i <= hi; i++) total += months[i].total
    return {
      from: months[lo].month,
      to: months[hi].month,
      total,
    }
  }, [selection, months])

  return (
    <div className="timeline-container">
      <div className="timeline-header">
        <span className="timeline-label">Timeline</span>
        {rangeInfo ? (
          <span className="timeline-range-info">
            {rangeInfo.from} — {rangeInfo.to} ({rangeInfo.total} posts)
            <button className="timeline-clear" onClick={() => onSelect(null)}>Clear</button>
          </span>
        ) : (
          <span className="timeline-hint">Drag to select time range</span>
        )}
        {hoverIdx !== null && months[hoverIdx] && (
          <span className="timeline-hover-info">
            {months[hoverIdx].month}: {months[hoverIdx].total} posts
          </span>
        )}
      </div>
      <div className="timeline-scroll">
        <svg
          ref={svgRef}
          width={totalW}
          height={H + 18}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onDoubleClick={handleDoubleClick}
          onMouseLeave={() => setHoverIdx(null)}
          style={{ cursor: dragging ? 'grabbing' : 'crosshair' }}
        >
          {/* Selection highlight */}
          {selection && (
            <rect
              x={selection[0] * (BAR_W + GAP) - 1}
              y={0}
              width={(selection[1] - selection[0] + 1) * (BAR_W + GAP) + 2}
              height={H}
              fill="rgba(99, 110, 250, 0.15)"
              rx={3}
            />
          )}

          {/* Bars */}
          {months.map((m, i) => {
            const barH = Math.max(2, (m.total / maxCount) * (H - 4))
            const x = i * (BAR_W + GAP)
            const y = H - barH
            const inSelection = !selection || (i >= selection[0] && i <= selection[1])
            const isHover = hoverIdx === i

            // Stacked bars: by topic (community) or by semantic group
            let stackY = H
            let segments
            if (topicColors) {
              // Community mode: stack by topic
              const topicIds = Object.keys(m.by_topic || {})
              segments = topicIds.map(tid => {
                const count = m.by_topic[tid]
                const segH = Math.max(0, (count / maxCount) * (H - 4))
                stackY -= segH
                return { key: tid, y: stackY, h: segH, color: topicColors[tid] || '#636EFA' }
              })
            } else {
              // Sentiment mode: aggregate all topics into sentiment groups
              const sentCounts = {}
              const sentByTopic = m.sentiment_by_topic || {}
              for (const groups of Object.values(sentByTopic)) {
                for (const [group, count] of Object.entries(groups)) {
                  sentCounts[group] = (sentCounts[group] || 0) + count
                }
              }
              segments = Object.entries(sentCounts).map(([group, count]) => {
                const segH = Math.max(0, (count / maxCount) * (H - 4))
                stackY -= segH
                return { key: group, y: stackY, h: segH, color: SENTIMENT_BAR_COLORS[group] || '#64748b' }
              })
            }

            return (
              <g key={m.month}>
                {segments.map((seg, si) => (
                  <rect
                    key={seg.key}
                    x={x}
                    y={seg.y}
                    width={BAR_W}
                    height={Math.max(1, seg.h)}
                    fill={seg.color}
                    opacity={inSelection ? (isHover ? 1 : 0.8) : 0.2}
                    rx={si === segments.length - 1 ? 2 : 0}
                  />
                ))}
              </g>
            )
          })}

          {/* Year labels */}
          {yearLabels.map(({ idx, year }) => (
            <text
              key={year}
              x={idx * (BAR_W + GAP) + BAR_W / 2}
              y={H + 13}
              fill="#666"
              fontSize={10}
              textAnchor="start"
            >
              {year}
            </text>
          ))}
        </svg>
      </div>
    </div>
  )
}
