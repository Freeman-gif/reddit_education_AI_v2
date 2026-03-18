import { useState, useEffect } from 'react'
import NetworkGraph from './components/NetworkGraph'
import CommentGalaxy from './components/CommentGalaxy'
import { fetchStats } from './api'

const TABS = ['Topic Network', 'Comment Galaxy']

export default function App() {
  const [activeTab, setActiveTab] = useState(0)
  const [stats, setStats] = useState(null)

  useEffect(() => {
    fetchStats().then(setStats).catch(() => {})
  }, [])

  return (
    <>
      <div className="header">
        <h1>AI in K-12 Education</h1>
        {stats && (
          <div className="stats">
            <div><span>{stats.total_posts}</span> posts</div>
            <div><span>{stats.total_comments}</span> comments</div>
            <div><span>{stats.topics_l1}</span> L1 topics</div>
            <div><span>{stats.post_edges}</span> KNN edges</div>
          </div>
        )}
      </div>
      <div className="tabs">
        {TABS.map((label, i) => (
          <button
            key={label}
            className={`tab ${activeTab === i ? 'active' : ''}`}
            onClick={() => setActiveTab(i)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="graph-container">
        {activeTab === 0 && <NetworkGraph />}
        {activeTab === 1 && <CommentGalaxy />}
      </div>
    </>
  )
}
