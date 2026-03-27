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

export async function fetchTimeline() {
  return fetchJson(STATIC ? staticUrl('timeline') : '/api/timeline')
}

export async function fetchCategories() {
  return fetchJson(STATIC ? staticUrl('categories') : '/api/categories')
}

export async function fetchCategoryEdges() {
  return fetchJson(STATIC ? staticUrl('categories_edges') : '/api/categories/edges')
}

export async function fetchTopicPosts(topicId) {
  return fetchJson(STATIC ? staticUrl(`posts_topic_${topicId}`) : `/api/posts/${topicId}`)
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

export async function fetchCommentGalaxy() {
  if (STATIC) {
    return fetchJson(staticUrl('comments_galaxy_scatter'))
  }
  return fetchJson('/api/comments/galaxy')
}

export async function fetchCommentBundles() {
  if (STATIC) {
    try {
      return await fetchJson(staticUrl('cluster_bundles'))
    } catch {
      return { bundles: [] }
    }
  }
  return fetchJson('/api/comments/bundles')
}

export async function fetchCommentDetail(commentId) {
  if (STATIC) {
    // Static mode: no individual comment detail files
    return { error: 'not available in static mode' }
  }
  return fetchJson(`/api/comment/${commentId}`)
}

export async function fetchCommentCluster(clusterId) {
  return fetchJson(STATIC ? staticUrl(`comment_cluster_${clusterId}`) : `/api/comment-cluster/${clusterId}`)
}
