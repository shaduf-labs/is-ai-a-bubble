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

  const platformAuth = document.querySelector('[data-platform-auth]')
  const accountControl = document.querySelector('[data-account-control]')
  const accountMenu = accountControl?.querySelector('[data-account-menu]')
  const authLabel = platformAuth?.querySelector('[data-auth-label]')
  const authChevron = platformAuth?.querySelector('[data-auth-chevron]')
  const controllerRevision = document.currentScript?.src?.match(/[?&]v=([^&#]+)/)?.[1] || 'my-pools-1'
  let sessionState = { status: 'loading', authenticated: null }
  let sessionRequest = null
  const sessionListeners = new Set()
  const followListeners = new Set()
  const authChannel = typeof BroadcastChannel === 'function' ? new BroadcastChannel('shaduf-auth') : null

  const closeAccountMenu = (restoreFocus = false) => {
    if (!accountMenu || accountMenu.hidden) return
    accountMenu.hidden = true
    platformAuth?.setAttribute('aria-expanded', 'false')
    if (restoreFocus) platformAuth?.focus?.()
  }
  const notifySession = () => sessionListeners.forEach((listener) => listener(sessionState))
  const notifyFollows = () => followListeners.forEach((listener) => listener())
  const announceFollows = () => { notifyFollows(); authChannel?.postMessage({ type: 'follows-changed' }) }
  const renderAccountMenu = () => {
    if (!accountMenu || !sessionState.authenticated) return
    accountMenu.replaceChildren()
    accountMenu.setAttribute('role', 'menu')
    const identity = document.createElement('div')
    identity.className = 'account-menu-identity'
    const name = document.createElement('strong')
    name.textContent = sessionState.display_identity
    const method = document.createElement('span')
    method.textContent = `Signed in with ${sessionState.provider === 'github' ? 'GitHub' : 'Email'}`
    identity.append(name, method)
    const accountLink = document.createElement('a')
    accountLink.href = platformAuth?.dataset.accountHref || '/account/'
    accountLink.textContent = 'Account'
    accountLink.setAttribute('role', 'menuitem')
    const signOut = document.createElement('button')
    signOut.type = 'button'
    signOut.dataset.accountSignout = ''
    signOut.textContent = 'Sign out'
    signOut.setAttribute('role', 'menuitem')
    const status = document.createElement('p')
    status.className = 'account-menu-status'
    status.setAttribute('role', 'status')
    status.setAttribute('aria-live', 'polite')
    signOut.addEventListener('click', async () => {
      signOut.disabled = true
      signOut.textContent = 'Signing out…'
      status.textContent = ''
      const ok = await logout()
      if (ok) closeAccountMenu(true)
      else {
        signOut.disabled = false
        signOut.textContent = 'Sign out'
        status.textContent = 'We could not sign you out. Please try again.'
      }
    })
    accountMenu.append(identity, accountLink, signOut, status)
  }
  const renderSession = () => {
    if (!platformAuth || !authLabel) return
    closeAccountMenu()
    platformAuth.disabled = sessionState.status === 'loading'
    platformAuth.setAttribute('aria-busy', String(sessionState.status === 'loading'))
    platformAuth.classList.toggle('is-authenticated', Boolean(sessionState.authenticated))
    if (sessionState.status === 'loading') {
      authLabel.textContent = 'Account'
      platformAuth.setAttribute('aria-label', 'Checking account')
      if (authChevron) authChevron.hidden = true
    } else if (sessionState.authenticated) {
      authLabel.textContent = sessionState.display_identity
      platformAuth.setAttribute('aria-label', `${sessionState.display_identity}, account menu`)
      if (authChevron) authChevron.hidden = false
      renderAccountMenu()
    } else if (sessionState.status === 'error') {
      authLabel.textContent = 'Account'
      platformAuth.setAttribute('aria-label', 'Account status unavailable. Try again')
      if (authChevron) authChevron.hidden = true
    } else {
      authLabel.textContent = 'Sign in'
      platformAuth.setAttribute('aria-label', 'Sign in')
      if (authChevron) authChevron.hidden = true
    }
    notifySession()
  }
  async function session({ force = false, loading = true } = {}) {
    if (!force && sessionState.status !== 'loading') return sessionState
    if (sessionRequest) return sessionRequest
    if (loading && platformAuth) { sessionState = { status: 'loading', authenticated: null }; renderSession() }
    sessionRequest = (async () => {
      let timer = 0
      try {
        const request = fetch('/api/session', { credentials: 'same-origin' })
        const response = platformAuth && typeof window.setTimeout === 'function'
          ? await Promise.race([request, new Promise((_, reject) => { timer = window.setTimeout(() => reject(new Error('session_timeout')), 5000) })])
          : await request
        if (!response.ok) throw new Error('session_unavailable')
        const value = await response.json()
        if (value.authenticated === true && (value.provider === 'email' || value.provider === 'github') && typeof value.display_identity === 'string' && value.display_identity) {
          sessionState = { status: 'ready', authenticated: true, provider: value.provider, display_identity: value.display_identity, csrf_token: value.csrf_token || '' }
        } else if (value.authenticated === false) sessionState = { status: 'ready', authenticated: false }
        else throw new Error('session_invalid')
      } catch {
        sessionState = { status: 'error', authenticated: null }
      } finally {
        if (timer) window.clearTimeout(timer)
        sessionRequest = null
        renderSession()
      }
      return sessionState
    })()
    return sessionRequest
  }
  async function logout() {
    let current = sessionState
    if (!current.authenticated) current = await session({ force: true, loading: false })
    if (!current.authenticated) return false
    try {
      const response = await fetch('/api/auth/logout', { method: 'POST', headers: { 'x-shaduf-csrf': current.csrf_token || '' } })
      if (!response.ok) return false
      sessionState = { status: 'ready', authenticated: false }
      renderSession()
      authChannel?.postMessage({ type: 'session-changed' })
      return true
    } catch { return false }
  }
  const authHost = document.createElement('div')
  const authRoot = authHost.attachShadow({ mode: 'closed' })
  authRoot.innerHTML = `<link rel="stylesheet" href="/assets/auth-modal.css?v=${encodeURIComponent(controllerRevision)}"><dialog><main><button class="close" type="button" aria-label="Close">×</button><h2>Sign in</h2><p>Your first sign-in creates an account.</p><form><label>Email<input type="email" autocomplete="email" required></label><button class="primary submit" type="submit">Email me a sign-in link</button><p class="status" role="status" aria-live="polite"></p><button class="change" type="button" hidden>Change email</button></form><p class="or">or</p><button class="primary github" type="button">Continue with GitHub</button></main></dialog>`
  document.body.append(authHost)
  const authDialog = authRoot.querySelector('dialog')
  const authForm = authRoot.querySelector('form'), authInput = authRoot.querySelector('input'), authStatus = authRoot.querySelector('.status'), authSubmit = authRoot.querySelector('.submit'), authChange = authRoot.querySelector('.change'), authGithub = authRoot.querySelector('.github'), authClose = authRoot.querySelector('.close')
  let authOpener = null, authPopup = null, authTimer = 0
  const setAuthStatus = (message, state = '') => { authStatus.textContent = message; if (authStatus.dataset) authStatus.dataset.state = state }
  const closeAuth = () => { window.clearInterval(authTimer); authTimer = 0; if (authDialog.open) authDialog.close(); authOpener?.focus?.(); authOpener = null }
  const refreshAuth = async () => { const current = await session({ force: true, loading: false }); if (current.authenticated) { authChannel?.postMessage({ type: 'session-changed' }); closeAuth(); return true } return false }
  const openAuth = (opener) => { authOpener = opener; setAuthStatus(''); authChange.hidden = true; authSubmit.textContent = 'Email me a sign-in link'; if (!authDialog.open) authDialog.showModal(); authInput.focus() }
  authClose.addEventListener('click', closeAuth)
  authDialog.addEventListener('cancel', event => { event.preventDefault(); closeAuth() })
  authDialog.addEventListener('close', () => { window.clearInterval(authTimer); authTimer = 0 })
  authInput.addEventListener('invalid', () => setAuthStatus('Enter a valid email address.', 'error'))
  authChange.addEventListener('click', () => { authChange.hidden = true; authSubmit.textContent = 'Email me a sign-in link'; setAuthStatus(''); authInput.focus(); authInput.select() })
  authForm.addEventListener('submit', async event => {
    event.preventDefault()
    if (authForm.reportValidity && !authForm.reportValidity()) return
    const email = authInput.value.trim()
    authSubmit.disabled = true
    authSubmit.textContent = 'Sending…'
    setAuthStatus('Sending your sign-in link…')
    try {
      const response = await fetch('/api/auth/email/request',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({email,return_to:location.pathname})})
      const result = await response.json().catch(() => ({}))
      if (!response.ok) {
        const code = result?.error?.code
        setAuthStatus(code === 'invalid_email' ? 'Enter a valid email address.' : code === 'email_cooldown' || code === 'rate_limited' ? 'Please wait a minute before requesting another link.' : code === 'email_delivery_failed' ? 'We could not send the link. Please try again.' : 'Sign-in email is temporarily unavailable. Please try again.', 'error')
        return
      }
      setAuthStatus(`Check your email at ${email}. If it is not there, check Spam.`)
      authSubmit.textContent = 'Send again'
      authChange.hidden = false
    } catch { setAuthStatus('We could not reach sign-in. Check your connection and try again.', 'error') }
    finally { authSubmit.disabled = false; if (authSubmit.textContent === 'Sending…') authSubmit.textContent = 'Email me a sign-in link' }
  })
  authGithub.addEventListener('click', () => {
    window.clearInterval(authTimer)
    setAuthStatus('Opening GitHub…')
    authPopup = window.open(`/api/auth/github/start?return_to=${encodeURIComponent('/sign-in/popup-complete/')}`,'shaduf-github-auth','popup,width=520,height=680')
    if (!authPopup) {
      const link=document.createElement('a')
      link.href=`/api/auth/github/start?return_to=${encodeURIComponent(location.pathname)}`
      link.target='_blank'
      link.rel='noopener'
      link.textContent='Open GitHub sign in in a new tab'
      authStatus.replaceChildren(document.createTextNode('Your browser blocked the popup. '),link)
      if (authStatus.dataset) authStatus.dataset.state = 'error'
      return
    }
    const deadline=Date.now()+120000
    authTimer = window.setInterval(async () => {
      if (await refreshAuth()) return window.clearInterval(authTimer)
      if (authPopup.closed) { window.clearInterval(authTimer); setAuthStatus('GitHub sign-in was not completed. Try again.', 'error') }
      else if (Date.now() >= deadline) { window.clearInterval(authTimer); setAuthStatus('GitHub sign-in took too long. Try again.', 'error') }
    }, 750)
  })
  platformAuth?.addEventListener('click', async event => {
    event.preventDefault()
    let current = sessionState
    if (current.status === 'loading' || current.status === 'error') current = await session({ force: true })
    if (current.authenticated) {
      accountMenu.hidden = !accountMenu.hidden
      platformAuth.setAttribute('aria-expanded', String(!accountMenu.hidden))
      if (!accountMenu.hidden) accountMenu.querySelector('[role="menuitem"]')?.focus()
      return
    }
    openAuth(platformAuth)
    if (current.status === 'error') setAuthStatus('We could not check your current session. You can still try to sign in.', 'error')
  })
  document.querySelectorAll('[data-account-page-signin]').forEach((button) => button.addEventListener('click', () => openAuth(button)))
  document.addEventListener('click', event => { if (accountControl && !accountControl.contains(event.target)) closeAccountMenu() })
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && accountMenu && !accountMenu.hidden) { event.preventDefault(); closeAccountMenu(true) } })
  window.addEventListener('focus', () => { if (authDialog.open) refreshAuth(); else if (platformAuth) session({ force: true }) })
  window.addEventListener('pageshow', () => { if (platformAuth) session({ force: true }) })
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible' && platformAuth) session({ force: true }) })
  authChannel?.addEventListener('message', event => {
    if (event.data?.type === 'session-changed') session({ force: true })
    else if (event.data?.type === 'follows-changed') notifyFollows()
  })
  window.ShadufAuth = {
    refresh: () => session({ force: true }),
    open: openAuth,
    logout,
    announceFollows,
    subscribe(listener) { sessionListeners.add(listener); listener(sessionState); return () => sessionListeners.delete(listener) },
    subscribeFollows(listener) { followListeners.add(listener); return () => followListeners.delete(listener) },
  }
  if (platformAuth) session({ force: true })
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

  const toolFrames = new Map()
  const registeredToolFrames = new WeakSet()
  const requestToolMeasurement = (frame) => {
    frame.contentWindow?.postMessage({ type: 'shaduf:theme', theme: 'light' }, '*')
    frame.contentWindow?.postMessage({ type: 'shaduf:measure' }, '*')
  }
  const fitToolFrame = (frame, contentHeight) => {
    const style = window.getComputedStyle(frame)
    const pixel = (value) => Number.parseFloat(value) || 0
    const frameChrome = style.boxSizing === 'border-box'
      ? pixel(style.borderTopWidth) + pixel(style.borderBottomWidth) + pixel(style.paddingTop) + pixel(style.paddingBottom)
      : 0
    frame.style.height = `${Math.ceil(contentHeight + frameChrome)}px`
  }
  const registerToolFrame = (frame) => {
    if (frame?.tagName !== 'IFRAME' || registeredToolFrames.has(frame)) return
    registeredToolFrames.add(frame)
    if (frame.contentWindow) toolFrames.set(frame.contentWindow, frame)
    frame.addEventListener('load', () => {
      for (const [source, registered] of toolFrames) if (registered === frame) toolFrames.delete(source)
      if (frame.contentWindow) toolFrames.set(frame.contentWindow, frame)
      requestToolMeasurement(frame)
    })
    window.requestAnimationFrame(() => requestToolMeasurement(frame))
  }
  const registerToolFrames = (root = document) => {
    if (root?.tagName === 'IFRAME' && root.matches('[data-tool-frame],[data-agent-document] iframe[sandbox~="allow-scripts"][src]')) registerToolFrame(root)
    root.querySelectorAll?.('[data-tool-frame],[data-agent-document] iframe[sandbox~="allow-scripts"][src]').forEach(registerToolFrame)
  }
  registerToolFrames()
  if ('MutationObserver' in window) new MutationObserver((records) => {
    for (const record of records) for (const node of record.addedNodes) if (node?.nodeType === 1) registerToolFrames(node)
  }).observe(document.documentElement, { childList: true, subtree: true })
  window.addEventListener('message', (event) => {
    const frame = toolFrames.get(event.source)
    if (!frame || event.origin !== 'null' || !event.data || typeof event.data !== 'object') return
    if (event.data.type === 'shaduf:resize') {
      const height = Number(event.data.height)
      if (!Number.isFinite(height) || height <= 0) return
      frame.dataset.shadufResizeReady = 'true'
      fitToolFrame(frame,height)
    } else if (event.data.type === 'shaduf:ready') {
      requestToolMeasurement(frame)
    } else if (event.data.type === 'shaduf:fullscreen') {
      frame.requestFullscreen?.().catch(() => {})
    } else if (event.data.type === 'shaduf:navigate' && typeof event.data.path === 'string') {
      const destination = new URL(event.data.path, location.origin)
      if (destination.origin === location.origin && destination.pathname.startsWith('/p/')) location.assign(destination.href)
    } else if (event.data.type === 'shaduf:tool-started') track('tool_started', { target_id: frame.dataset.toolId || '' })
    else if (event.data.type === 'shaduf:tool-completed') track('tool_completed', { target_id: frame.dataset.toolId || '' })
  })

  const followButton = document.querySelector('[data-follow]')
  if (followButton) {
    const followLabel = followButton.querySelector('span') || followButton
    const poolId = body.dataset.poolId || ''
    let followState = 'unknown'
    let followBusy = false
    let followRevision = 0
    const renderFollow = () => {
      followButton.classList.toggle('is-following', followState === 'following')
      followButton.disabled = followBusy || followState === 'loading'
      followButton.setAttribute('aria-busy', String(followBusy || followState === 'loading'))
      if (followBusy) followLabel.textContent = followState === 'following' ? 'Removing…' : 'Saving…'
      else if (followState === 'following') followLabel.textContent = '✓ Following'
      else if (followState === 'error') followLabel.textContent = 'Retry'
      else if (followState === 'loading') followLabel.textContent = 'Checking…'
      else followLabel.textContent = 'Follow this pool'
      followButton.setAttribute('aria-label', followState === 'following' ? 'Unfollow this pool' : followState === 'error' ? 'Retry loading saved pool state' : 'Follow this pool')
    }
    const refreshFollow = async () => {
      const revision = ++followRevision
      let current = sessionState
      if (current.status === 'loading' || current.status === 'error') current = await session({ force: true, loading: false })
      if (revision !== followRevision) return
      if (!current.authenticated) { followState = 'guest'; followBusy = false; renderFollow(); return }
      followState = 'loading'; renderFollow()
      try {
        const response = await fetch('/api/me/pools', { credentials: 'same-origin', cache: 'no-store' })
        if (revision !== followRevision) return
        if (response.status === 401) {
          await session({ force: true, loading: false })
          if (revision !== followRevision) return
          followState = 'guest'
        } else if (!response.ok) followState = 'error'
        else {
          const value = await response.json()
          followState = Array.isArray(value.items) && value.items.some(item => item?.pool_id === poolId && item?.following === true) ? 'following' : 'not-following'
        }
      } catch { if (revision === followRevision) followState = 'error' }
      if (revision === followRevision) { followBusy = false; renderFollow() }
    }
    followButton.addEventListener('click', async () => {
      if (followBusy || followState === 'loading') return
      let current = sessionState
      if (!current.authenticated) current = await session({ force: true, loading: false })
      if (!current.authenticated) { openAuth(followButton); return }
      if (followState === 'unknown' || followState === 'error') { await refreshFollow(); return }
      const confirmed = followState
      followBusy = true; renderFollow()
      try {
        const response = await fetch(`/api/follows/${encodeURIComponent(poolId)}`, {
          method: confirmed === 'following' ? 'DELETE' : 'POST',
          headers: { 'x-shaduf-csrf': current.csrf_token || '' },
        })
        if (response.status === 401) {
          await session({ force: true, loading: false })
          followState = 'guest'
          showToast('Your session ended. Sign in to save this pool.')
        } else if (!response.ok) {
          followState = confirmed
          showToast(confirmed === 'following' ? 'Unfollow could not be saved. Try again.' : 'Follow could not be saved. Try again.')
        } else {
          const value = await response.json().catch(() => ({}))
          followState = value.following === true ? 'following' : 'not-following'
          showToast(followState === 'following' ? 'Saved to My pools' : 'Removed from My pools')
          announceFollows()
        }
      } catch {
        followState = confirmed
        showToast(confirmed === 'following' ? 'Unfollow could not be saved. Try again.' : 'Follow could not be saved. Try again.')
      } finally { followBusy = false; renderFollow() }
    })
    window.ShadufAuth.subscribe((current) => {
      followRevision += 1
      if (current.status === 'ready' && !current.authenticated) { followState = 'guest'; followBusy = false; renderFollow() }
      else if (current.status === 'ready' && current.authenticated) refreshFollow()
      else if (current.status === 'error') { followState = 'error'; followBusy = false; renderFollow() }
    })
    window.ShadufAuth.subscribeFollows(refreshFollow)
    window.addEventListener('focus', refreshFollow)
    document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') refreshFollow() })
  }

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
