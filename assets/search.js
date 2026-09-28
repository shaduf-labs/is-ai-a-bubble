// Public search uses published metadata only; ordering never invents a date.
export function normalizeSearchText(value = '') {
  return String(value).normalize('NFKC').toLocaleLowerCase().replace(/[\p{P}\p{Z}]+/gu, ' ').trim().replace(/\s+/g, ' ')
}

const timestamp = item => {
  const date = item.research_completed_at || item.updated_at
  return typeof date === 'string' && Number.isFinite(Date.parse(date)) ? Date.parse(date) : -Infinity
}

export function rankSearchItems(items, query) {
  const phrase = normalizeSearchText(query), terms = phrase.split(' ').filter(Boolean)
  if (!terms.length) return []
  const matches = []
  for (const item of items) {
    const title = normalizeSearchText(item.title)
    const pool = normalizeSearchText([item.pool_title, item.pool_slug].filter(Boolean).join(' '))
    const summary = normalizeSearchText(item.summary)
    const keywords = normalizeSearchText([item.kind, ...(item.keywords || [])].join(' '))
    const all = `${title} ${pool} ${summary} ${keywords}`
    if (!terms.every(term => all.includes(term))) continue
    const poolWords = new Set(pool.split(' '))
    const poolQuery = terms.every(term => poolWords.has(term))
    let score
    if (title === phrase) score = 10000
    // A pool-name query should expose its current answer and newest research,
    // even when an old report repeats that name more often in its title.
    else if (poolQuery) score = item.kind === 'Pool' ? 9000 : item.kind === 'Research report' ? 8000 : item.kind === 'Page' ? 7000 : 6000
    else score = (terms.every(term => title.includes(term)) ? 1000 : 0)
      + terms.filter(term => title.includes(term)).length * 100
      + terms.filter(term => summary.includes(term)).length * 10
    matches.push({ item, score })
  }
  matches.sort((a, b) => b.score - a.score || timestamp(b.item) - timestamp(a.item)
    || String(a.item.id || a.item.href).localeCompare(String(b.item.id || b.item.href), 'en'))
  const seen = new Set()
  return matches.filter(({ item }) => {
    const key = item.canonical_url || item.href
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }).map(({ item }) => item)
}

// A small state boundary makes delayed index requests safe during fast typing,
// clearing, closing, retrying and loading the next group of results.
export function createSearchSession({ loadItems, onChange, pageSize = 12 }) {
  let revision = 0, matches = [], limit = pageSize, query = ''
  const publish = status => onChange({ status, query, total: matches.length, items: matches.slice(0, limit) })
  return {
    async search(value) {
      const request = ++revision
      query = value
      matches = []
      limit = pageSize
      if (!normalizeSearchText(value)) { publish('empty'); return }
      publish('loading')
      try {
        const items = await loadItems()
        if (request !== revision) return
        matches = rankSearchItems(items, value)
        publish('ready')
      } catch {
        if (request === revision) publish('error')
      }
    },
    more() { limit += pageSize; publish('ready') },
    cancel() { revision += 1 },
  }
}
