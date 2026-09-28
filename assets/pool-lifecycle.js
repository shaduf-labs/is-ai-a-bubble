// Platform-owned lifecycle history. Closing an interval on owner-authorized
// resumption preserves elapsed suspended days; never delete past intervals.
export const poolSuspensions = {
  'union-alpha': [{ suspended_at: '2026-09-27T05:48:52.165Z', resumed_at: null }],
}
export const suspensionsFor = slug => poolSuspensions[slug] || []
export function isSuspended(slug, now = Date.now()) {
  return suspensionsFor(slug).some(interval => Date.parse(interval.suspended_at) <= now &&
    (interval.resumed_at === null || now < Date.parse(interval.resumed_at)))
}
