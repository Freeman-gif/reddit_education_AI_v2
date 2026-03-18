/**
 * Data layer that works in both API mode (Frame Desktop) and static mode (GitHub Pages).
 * In static mode, fetches pre-exported JSON from /data/*.json
 */

const STATIC = import.meta.env.VITE_STATIC === 'true'
const BASE = import.meta.env.BASE_URL || '/'

function staticUrl(name) {
  return `${BASE}data/${name}.json`
}

async function fetchJson(url) {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${r.status} ${url}`)
  return r.json()
}

export async function fetchStats() {
  return fetchJson(STATIC ? staticUrl('stats') : '/api/stats')
}

export async function fetchYears() {
  return fetchJson(STATIC ? staticUrl('years') : '/api/years')
}

export async function fetchHubs() {
  return fetchJson(STATIC ? staticUrl('hubs') : '/api/hubs')
}

export async function fetchHubEdges() {
  return fetchJson(STATIC ? staticUrl('hubs_edges') : '/api/hubs/edges')
}

export async function fetchAllPosts(years) {
  if (STATIC) {
    const data = await fetchJson(staticUrl('posts_all'))
    if (years && years.length > 0) {
      const yearSet = new Set(years)
      const posts = data.posts.filter(p => yearSet.has(p.year))
      const postIds = new Set(posts.map(p => p.post_id))
      const edges = data.edges.filter(e => postIds.has(e.source_id) && postIds.has(e.target_id))
      return { posts, edges }
    }
    return data
  }
  const yearParam = years?.length > 0 ? `?years=${years.join(',')}` : ''
  return fetchJson(`/api/posts/all${yearParam}`)
}

export async function fetchHubDetail(topicId) {
  return fetchJson(STATIC ? staticUrl(`hub_${topicId}`) : `/api/hub/${topicId}`)
}

export async function fetchPostDetail(postId) {
  if (STATIC) {
    try {
      return await fetchJson(staticUrl(`post_${postId}`))
    } catch {
      return { post: { title: 'Detail not available in static mode' }, comments: [] }
    }
  }
  return fetchJson(`/api/post/${postId}`)
}

export async function fetchCommentGalaxy(years) {
  if (STATIC) {
    const data = await fetchJson(staticUrl('comments_galaxy'))
    if (years && years.length > 0) {
      const yearSet = new Set(years)
      const comments = data.comments.filter(c => yearSet.has(c.year))
      const commentIds = new Set(comments.map(c => c.comment_id))
      const edges = data.edges.filter(e => commentIds.has(e.source_id) && commentIds.has(e.target_id))
      // Recalculate hub centroids for filtered data
      const clusterMap = {}
      comments.forEach(c => {
        if (!clusterMap[c.cluster_id]) clusterMap[c.cluster_id] = { xs: [], ys: [] }
        clusterMap[c.cluster_id].xs.push(c.umap_x)
        clusterMap[c.cluster_id].ys.push(c.umap_y)
      })
      const hubs = data.hubs.filter(h => clusterMap[h.cluster_id]).map(h => ({
        ...h,
        cx: clusterMap[h.cluster_id].xs.reduce((a, b) => a + b, 0) / clusterMap[h.cluster_id].xs.length,
        cy: clusterMap[h.cluster_id].ys.reduce((a, b) => a + b, 0) / clusterMap[h.cluster_id].ys.length,
      }))
      return { hubs, comments, edges }
    }
    return data
  }
  const yearParam = years?.length > 0 ? `?years=${years.join(',')}` : ''
  return fetchJson(`/api/comments/galaxy${yearParam}`)
}

export async function fetchCommentCluster(clusterId) {
  return fetchJson(STATIC ? staticUrl(`comment_cluster_${clusterId}`) : `/api/comment-cluster/${clusterId}`)
}
