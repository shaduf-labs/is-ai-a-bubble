const DAY = 86_400_000
const stamp = value => typeof value === 'string' && value.trim() ? Date.parse(value) : NaN
const utcDay = milliseconds => Math.floor(milliseconds / DAY)

// Use only completed work already included in the verified public release.
// Never infer pool age from repository creation or failed/private runs.
export function firstResearchAt(history) {
  return (history?.runs || [])
    .filter(run => run.status === 'completed' && Number.isFinite(stamp(run.completed_at)))
    .map(run => run.completed_at)
    .sort((a, b) => stamp(a) - stamp(b))[0] || null
}

export function researchDays(startedAt, now = Date.now()) {
  const start = stamp(startedAt)
  if (!Number.isFinite(start) || !Number.isFinite(now) || start > now) return null
  return Math.max(1, utcDay(now) - utcDay(start))
}

export function researchFreshness(updatedAt, now = Date.now()) {
  const updated = stamp(updatedAt)
  if (!Number.isFinite(updated)) return 'Not published'
  const days = utcDay(now) - utcDay(updated)
  if (updated <= now && days === 0) return 'Updated today'
  if (days === 1) return 'Updated yesterday'
  if (days > 1) return `Updated ${days} days ago`
  return `Updated ${new Date(updated).toLocaleDateString('en-GB', {day:'numeric', month:'short', year:'numeric', timeZone:'UTC'})}`
}

export function updateResearchDates(root, now = Date.now()) {
  root.querySelectorAll('[data-research-started]').forEach(node => {
    const days = researchDays(node.dataset.researchStarted, now)
    node.hidden = days === null
    if (days === null) return
    node.querySelector('[data-research-days]').textContent = String(days)
    node.querySelector('[data-research-days-label]').textContent = `${days === 1 ? 'day' : 'days'} of research`
  })
  root.querySelectorAll('[data-research-updated]').forEach(node => {
    node.textContent = researchFreshness(node.getAttribute('datetime'), now)
  })
}

// Both labels stay current even when a cached page remains open overnight.
// Hidden tabs need no timer; returning to them refreshes the dates immediately.
if (typeof document !== 'undefined') {
  let timer
  const refresh = () => {
    clearTimeout(timer)
    updateResearchDates(document)
    if (!document.hidden) timer = setTimeout(refresh, DAY - Date.now() % DAY + 100)
  }
  refresh()
  window.addEventListener('pageshow', refresh)
  window.addEventListener('pagehide', () => clearTimeout(timer))
  document.addEventListener('visibilitychange', refresh)
}
