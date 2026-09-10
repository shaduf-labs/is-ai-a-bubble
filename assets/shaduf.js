(() => {
  const body = document.body
  const toast = document.querySelector('[data-toast]')
  const applyLanguage = (locale, persist = false) => {
    if (!document.querySelector(`[data-language="${CSS.escape(locale)}"]`)) return
    if (persist) { try { localStorage.setItem('shaduf_language', locale) } catch {} }
    document.querySelectorAll('[data-language-label]').forEach((node) => { node.textContent = locale.toUpperCase() })
    const prioritize = (selector) => document.querySelectorAll(selector).forEach((container) => {
      const items = [...container.children].filter((item) => item.matches('[data-locale]'))
      items.sort((a, b) => {
        const freshness = Number(a.dataset.stale === 'true') - Number(b.dataset.stale === 'true')
        const language = Number(b.dataset.locale === locale) - Number(a.dataset.locale === locale)
        const originalOrder = Number(a.dataset.catalogueOrder || 0) - Number(b.dataset.catalogueOrder || 0)
        return freshness || language || originalOrder
      }).forEach((item) => container.append(item))
    })
    prioritize('.explore-list')
    prioritize('.related-dock')
  }
  document.querySelectorAll('[data-language]').forEach((node) => node.addEventListener('click', () => applyLanguage(node.dataset.language, true)))
  let savedLanguage = ''
  try { savedLanguage = localStorage.getItem('shaduf_language') || '' } catch {}
  applyLanguage(savedLanguage || document.documentElement.lang || 'en')
  const exploreQuery = new URLSearchParams(location.search).get('q')?.trim().toLowerCase()
  if (exploreQuery && document.querySelector('[data-explore-row]')) {
    let visible = 0
    document.querySelectorAll('[data-explore-row]').forEach((row) => {
      row.hidden = !row.dataset.searchText.includes(exploreQuery)
      if (!row.hidden) visible += 1
    })
    const empty = document.querySelector('[data-explore-empty]')
    if (empty) empty.hidden = visible !== 0
    document.querySelectorAll('.category-strip a[href*="?q="]').forEach((link) => {
      if (new URL(link.href).searchParams.get('q')?.toLowerCase() === exploreQuery) link.setAttribute('aria-current', 'page')
    })
  }
  const showToast = (message) => {
    if (!toast) return
    toast.textContent = message
    toast.classList.add('visible')
    window.clearTimeout(showToast.timer)
    showToast.timer = window.setTimeout(() => toast.classList.remove('visible'), 2600)
  }

  const leftDrawerButtons = [...document.querySelectorAll('[data-open-left]')]
  const rightDrawerButtons = [...document.querySelectorAll('[data-open-right]')]
  const setDrawer = (name) => {
    body.classList.toggle('left-open', name === 'left')
    body.classList.toggle('right-open', name === 'right')
    leftDrawerButtons.forEach((node) => node.setAttribute('aria-expanded', String(name === 'left')))
    rightDrawerButtons.forEach((node) => node.setAttribute('aria-expanded', String(name === 'right')))
  }
  const closeDrawers = () => setDrawer(null)
  leftDrawerButtons.forEach((node) => node.addEventListener('click', () => setDrawer(body.classList.contains('left-open') ? null : 'left')))
  rightDrawerButtons.forEach((node) => node.addEventListener('click', () => setDrawer(body.classList.contains('right-open') ? null : 'right')))
  document.querySelectorAll('[data-close-right],[data-drawer-backdrop]').forEach((node) => node.addEventListener('click', closeDrawers))

  const search = document.querySelector('[data-search-dialog]')
  const searchResults = search?.querySelector('[data-search-results]')
  let searchIndexPromise
  const loadSearchIndex = () => searchIndexPromise ||= fetch('/search-index.json').then((response) => {
    if (!response.ok) throw new Error('search index unavailable')
    return response.json()
  }).then((data) => Array.isArray(data.items) ? data.items : [])
  const renderSearchResults = async (query) => {
    if (!searchResults) return
    const terms = query.toLowerCase().trim().split(/\s+/).filter(Boolean)
    searchResults.replaceChildren()
    if (!terms.length) {
      const hint = document.createElement('p')
      hint.textContent = 'Search published pools, pages, reports, and evidence.'
      searchResults.append(hint)
      return
    }
    try {
      const items = await loadSearchIndex()
      const matches = items.map((item) => {
        const haystack = [item.title, item.summary, item.kind, ...(item.keywords || [])].join(' ').toLowerCase()
        const score = terms.reduce((total, term) => total + (haystack.includes(term) ? 1 : 0), 0)
        return { item, score }
      }).filter(({ score }) => score === terms.length).slice(0, 12)
      if (!matches.length) {
        const empty = document.createElement('p')
        empty.textContent = 'No published result matches this search.'
        searchResults.append(empty)
        return
      }
      for (const { item } of matches) {
        const link = document.createElement('a')
        link.className = 'search-result'
        link.href = item.href
        const meta = document.createElement('small')
        meta.textContent = item.kind
        const title = document.createElement('strong')
        title.textContent = item.title
        const summary = document.createElement('span')
        summary.textContent = item.summary
        link.append(meta, title, summary)
        searchResults.append(link)
      }
    } catch {
      const error = document.createElement('p')
      error.textContent = 'Search is temporarily unavailable.'
      searchResults.append(error)
    }
  }
  const openSearch = (value = '') => {
    if (!search) return
    const input = search.querySelector('input[type="search"]')
    if (input && value) input.value = input.value ? `${input.value} ${value}` : value
    if (!search.open) search.showModal()
    if (input) renderSearchResults(input.value)
    window.setTimeout(() => input?.focus(), 0)
  }
  search?.querySelector('input[type="search"]')?.addEventListener('input', (event) => renderSearchResults(event.currentTarget.value))
  document.querySelectorAll('[data-open-search]').forEach((node) => node.addEventListener('click', () => openSearch()))
  document.querySelectorAll('[data-search-tag]').forEach((node) => node.addEventListener('click', () => openSearch(node.dataset.searchTag || node.textContent.trim())))
  document.addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openSearch() }
    if (event.key === 'Escape') closeDrawers()
  })

  const ticker = document.querySelector('.activity-ticker')
  document.querySelector('[data-toggle-ticker]')?.addEventListener('click', (event) => {
    ticker?.classList.toggle('paused')
    event.currentTarget.textContent = ticker?.classList.contains('paused') ? '▶' : 'Ⅱ'
  })

  const peek = document.querySelector('[data-peek-layer]')
  const peekFrame = peek?.querySelector('[data-peek-frame]')
  const peekOpen = peek?.querySelector('[data-peek-open]')
  const openPeek = (href, side = false) => {
    if (!peek || !peekFrame || !peekOpen) return
    peek.classList.toggle('side', side)
    peek.classList.add('open')
    peek.setAttribute('aria-hidden', 'false')
    peekFrame.src = href
    peekOpen.href = href
    body.style.overflow = 'hidden'
    track('report_open', { target_id: href })
  }
  const closePeek = () => {
    if (!peek || !peekFrame) return
    peek.classList.remove('open', 'side')
    peek.setAttribute('aria-hidden', 'true')
    peekFrame.src = 'about:blank'
    body.style.overflow = ''
  }
  document.querySelectorAll('a[data-peek],a.report-link').forEach((node) => node.addEventListener('click', (event) => { event.preventDefault(); openPeek(node.href, node.dataset.peek === 'side') }))
  peek?.querySelectorAll('[data-close-peek]').forEach((node) => node.addEventListener('click', closePeek))
  peek?.querySelector('[data-peek-side]')?.addEventListener('click', () => peek.classList.toggle('side'))

  async function session() {
    try {
      const response = await fetch('/api/session', { credentials: 'same-origin' })
      return response.ok ? response.json() : { authenticated: false }
    } catch { return { authenticated: false } }
  }
  async function track(event_name, properties = {}) {
    const pool_id = body.dataset.poolId || ''
    const page_id = body.dataset.pageId || ''
    const payload = { event_id: crypto.randomUUID(), event_name, pool_id, page_id, source_group: sourceGroup(), ...properties }
    try { await fetch('/api/events', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload), keepalive: true }) } catch {}
  }
  function sourceGroup() {
    const referrer = document.referrer
    if (!referrer) return 'direct'
    try {
      const host = new URL(referrer).hostname
      if (host === location.hostname) return 'internal'
      if (/google|bing|duckduckgo|yandex/.test(host)) return 'search'
      if (/chatgpt|perplexity|claude/.test(host)) return 'ai_referral'
      return 'referral'
    } catch { return 'unknown' }
  }
  document.querySelectorAll('[data-track]').forEach((node) => node.addEventListener('click', () => track(node.dataset.track, { target_id: node.dataset.targetId || node.getAttribute('href') || '' })))
  document.querySelectorAll('.page-tree a[href$="/research/"]').forEach((node) => node.addEventListener('click', () => track('history_open', { target_id: node.getAttribute('href') || '' })))
  document.querySelectorAll('.agent-document a[href^="http"]').forEach((node) => node.addEventListener('click', () => track('evidence_open', { target_id: node.hostname })))
  if ('IntersectionObserver' in window) {
    const relatedObserver = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue
        relatedObserver.unobserve(entry.target)
        track('related_pool_impression', { target_id: entry.target.dataset.targetId || '' })
      }
    }, { threshold: 0.6 })
    document.querySelectorAll('.related-dock a[data-target-id]').forEach((node) => relatedObserver.observe(node))
  }

  const toolFrames = new Map([...document.querySelectorAll('[data-tool-frame]')].map((frame) => [frame.contentWindow, frame]))
  document.querySelectorAll('[data-tool-frame]').forEach((frame) => frame.addEventListener('load', () => {
    frame.contentWindow?.postMessage({ type: 'shaduf:theme', theme: 'light' }, '*')
  }))
  window.addEventListener('message', (event) => {
    const frame = toolFrames.get(event.source)
    if (!frame || event.origin !== 'null' || !event.data || typeof event.data !== 'object') return
    if (event.data.type === 'shaduf:resize') {
      const height = Math.max(240, Math.min(1200, Number(event.data.height) || 0))
      frame.style.height = `${height}px`
    } else if (event.data.type === 'shaduf:fullscreen') {
      frame.requestFullscreen?.().catch(() => {})
    } else if (event.data.type === 'shaduf:navigate' && typeof event.data.path === 'string') {
      const destination = new URL(event.data.path, location.origin)
      if (destination.origin === location.origin && destination.pathname.startsWith('/p/')) location.assign(destination.href)
    } else if (event.data.type === 'shaduf:tool-started') track('tool_started', { target_id: frame.dataset.toolId || '' })
    else if (event.data.type === 'shaduf:tool-completed') track('tool_completed', { target_id: frame.dataset.toolId || '' })
  })

  document.querySelector('[data-follow]')?.addEventListener('click', async (event) => {
    const button = event.currentTarget
    const current = await session()
    if (!current.authenticated) {
      location.href = `/api/auth/github/start?return_to=${encodeURIComponent(location.pathname)}`
      return
    }
    const response = await fetch(`/api/follows/${encodeURIComponent(body.dataset.poolId || '')}`, { method: 'POST', headers: { 'x-shaduf-csrf': current.csrf_token || '' } })
    if (response.ok) { button.textContent = 'Following'; showToast('Pool saved — notifications are not enabled') }
    else showToast('Follow could not be saved')
  })

  const fundingButton = document.querySelector('[data-funding-intent]')
  fundingButton?.addEventListener('click', async () => {
    fundingButton.disabled = true
    const response = await submitFundingIntent()
    const responseBody = response.ok ? null : await response.clone().json().catch(() => null)
    if (response.ok) showToast('Funding interest recorded — no payment was made')
    else if (responseBody?.error?.code === 'turnstile_required') await openTurnstile(responseBody)
    else showToast('Funding interest could not be recorded')
    fundingButton.disabled = false
  })

  async function submitFundingIntent(turnstile_token = '') {
    return fetch('/api/funding-intents', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ pool_id: body.dataset.poolId || '', source_group: sourceGroup(), turnstile_token }),
    })
  }

  async function openTurnstile(required = {}) {
    const config = required.turnstile_site_key ? required : await fetch('/api/config').then((response) => response.json()).catch(() => ({}))
    if (!config.turnstile_site_key) { showToast('Verification is unavailable'); return }
    const dialog = document.createElement('dialog')
    dialog.className = 'verification-dialog'
    dialog.innerHTML = '<form method="dialog"><header><strong>Confirm this request</strong><button value="cancel" aria-label="Close">×</button></header><p>This verification appears only after unusual request volume.</p><div data-turnstile-mount></div></form>'
    document.body.append(dialog)
    dialog.addEventListener('close', () => dialog.remove(), { once: true })
    dialog.showModal()
    try {
      await loadScript('https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit')
      window.turnstile.render(dialog.querySelector('[data-turnstile-mount]'), {
        sitekey: config.turnstile_site_key,
        callback: async (token) => {
          const retry = await submitFundingIntent(token)
          if (retry.ok) { dialog.close(); showToast('Funding interest recorded — no payment was made') }
          else showToast('Verification could not be completed')
        },
      })
    } catch { dialog.close(); showToast('Verification could not be loaded') }
  }

  function loadScript(src) {
    const existing = document.querySelector(`script[src="${src}"]`)
    if (existing?.dataset.loaded === 'true') return Promise.resolve()
    return new Promise((resolve, reject) => {
      const script = existing || document.createElement('script')
      script.src = src
      script.async = true
      script.defer = true
      script.addEventListener('load', () => { script.dataset.loaded = 'true'; resolve() }, { once: true })
      script.addEventListener('error', reject, { once: true })
      if (!existing) document.head.append(script)
    })
  }

  document.querySelector('[data-logout-form]')?.addEventListener('submit', async (event) => {
    event.preventDefault()
    const current = await session()
    const response = await fetch('/api/auth/logout', { method: 'POST', headers: { 'x-shaduf-csrf': current.csrf_token || '' } })
    if (response.ok) location.href = '/'
  })
})()
