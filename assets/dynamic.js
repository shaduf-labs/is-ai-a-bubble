(() => {
  const page = document.querySelector('[data-account-page]')
  if (!page) return
  const status = page.querySelector('[data-account-page-status]')
  const logoutButton = page.querySelector('[data-dynamic-logout]')
  const pools = page.querySelector('[data-my-pools]')
  const poolList = pools?.querySelector('[data-my-pools-list]')
  const poolStatus = pools?.querySelector('[data-my-pools-status]')
  let currentSession = null
  let poolRevision = 0
  let poolController = null

  const stopPoolRequest = () => {
    poolRevision += 1
    poolController?.abort()
    poolController = null
  }
  const replacePoolList = (...nodes) => {
    if (!poolList) return
    poolList.replaceChildren(...nodes)
    poolList.setAttribute('aria-busy', 'false')
  }
  const message = (text, className = '') => {
    const node = document.createElement('p')
    node.className = className
    node.textContent = text
    return node
  }
  const renderPoolLoading = () => {
    if (!poolList) return
    poolList.setAttribute('aria-busy', 'true')
    poolList.replaceChildren(message('Loading your pools…', 'my-pools-loading'))
    if (poolStatus) poolStatus.textContent = ''
  }
  const renderPoolEmpty = () => {
    const empty = document.createElement('div')
    empty.className = 'my-pools-empty'
    empty.append(message('You haven’t followed or purchased any pools yet'))
    const explore = document.createElement('a')
    explore.href = '/#pool-catalogue'
    explore.textContent = 'Explore pools'
    empty.append(explore)
    replacePoolList(empty)
    if (poolStatus) poolStatus.textContent = ''
  }
  const renderPoolError = () => {
    const error = document.createElement('div')
    error.className = 'my-pools-error'
    error.append(message('We couldn’t load your pools'))
    const retry = document.createElement('button')
    retry.type = 'button'
    retry.textContent = 'Try again'
    retry.addEventListener('click', () => loadPools())
    error.append(retry)
    replacePoolList(error)
  }
  const safePoolHref = (value) => {
    if (typeof value !== 'string') return ''
    try {
      const url = new URL(value, location.origin)
      return url.origin === location.origin && /^\/(?:p|pro)\/[a-z0-9][a-z0-9-]*\/$/i.test(url.pathname) && !url.search && !url.hash ? url.pathname : ''
    } catch { return '' }
  }
  const renderPools = (items) => {
    if (!Array.isArray(items)) return renderPoolError()
    if (!items.length) return renderPoolEmpty()
    const fragment = document.createDocumentFragment()
    for (const item of items) {
      if (!item || typeof item.pool_id !== 'string' || typeof item.title !== 'string' || !['follow','purchase'].includes(item.relationship)) return renderPoolError()
      if (item.relationship === 'follow' && item.following !== true) return renderPoolError()
      if (item.relationship === 'purchase' && !['active','expired','revoked','unavailable'].includes(item.access_status)) return renderPoolError()
      const row = document.createElement('article')
      row.className = 'my-pool-item'
      row.dataset.poolId = item.pool_id
      const copy = document.createElement('div')
      const title = document.createElement('h3')
      title.textContent = item.available === true ? item.title : 'Pool unavailable'
      const badge = document.createElement('span')
      badge.className = 'my-pool-badge'
      if (item.relationship === 'purchase') {
        badge.classList.add(`is-${item.access_status}`)
        if (item.access_status === 'active') {
          const until = new Date(item.access_until)
          if (!Number.isFinite(until.getTime())) return renderPoolError()
          badge.textContent = `Pro · Access until ${until.toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'})}`
        } else if (item.access_status === 'expired') badge.textContent = 'Pro · Event ended / Access ended'
        else if (item.access_status === 'revoked') badge.textContent = 'Pro · Access unavailable'
        else badge.textContent = 'Pro · Couldn’t check access'
      } else badge.textContent = 'Following'
      copy.append(title, badge)
      const actions = document.createElement('div')
      actions.className = 'my-pool-actions'
      const href = item.available === true ? safePoolHref(item.href) : ''
      if (href && (item.relationship === 'follow' || item.access_status === 'active')) {
        const open = document.createElement('a')
        open.href = href
        open.textContent = 'Open pool'
        actions.append(open)
      }
      if (item.relationship === 'purchase') {
        if (item.access_status === 'revoked') {
          const contact = document.createElement('a')
          contact.href = 'mailto:info@shaduf.ai'
          contact.textContent = 'Contact us'
          actions.append(contact)
        }
        row.append(copy, actions)
        fragment.append(row)
        continue
      }
      const unfollow = document.createElement('button')
      unfollow.type = 'button'
      unfollow.textContent = 'Unfollow'
      unfollow.setAttribute('aria-label', `Unfollow ${item.available === true ? item.title : item.pool_id}`)
      unfollow.addEventListener('click', async () => {
        if (!currentSession?.authenticated || unfollow.disabled) return
        unfollow.disabled = true
        unfollow.textContent = 'Removing…'
        if (poolStatus) poolStatus.textContent = ''
        try {
          const response = await fetch(`/api/follows/${encodeURIComponent(item.pool_id)}`, { method: 'DELETE', headers: { 'x-shaduf-csrf': currentSession.csrf_token || '' } })
          if (response.status === 401) {
            stopPoolRequest()
            replacePoolList()
            await window.ShadufAuth?.refresh()
            return
          }
          if (!response.ok) throw new Error('unfollow_failed')
          row.remove()
          if (!poolList?.querySelector('.my-pool-item')) renderPoolEmpty()
          if (poolStatus) poolStatus.textContent = 'Removed from My pools.'
          window.ShadufAuth?.announceFollows()
        } catch {
          unfollow.disabled = false
          unfollow.textContent = 'Unfollow'
          if (poolStatus) poolStatus.textContent = 'We couldn’t remove this pool. Try again.'
        }
      })
      actions.append(unfollow)
      row.append(copy, actions)
      fragment.append(row)
    }
    replacePoolList(fragment)
    if (poolStatus) poolStatus.textContent = ''
  }
  async function loadPools() {
    if (!poolList || !currentSession?.authenticated) return
    const revision = ++poolRevision
    poolController?.abort()
    poolController = new AbortController()
    renderPoolLoading()
    try {
      const response = await fetch('/api/me/pools', { credentials: 'same-origin', cache: 'no-store', signal: poolController.signal })
      if (revision !== poolRevision) return
      if (response.status === 401) {
        stopPoolRequest()
        replacePoolList()
        await window.ShadufAuth?.refresh()
        return
      }
      if (!response.ok) return renderPoolError()
      const value = await response.json()
      if (revision === poolRevision) renderPools(value.items)
    } catch (error) {
      if (revision === poolRevision && error?.name !== 'AbortError') renderPoolError()
    } finally {
      if (revision === poolRevision) poolController = null
    }
  }

  logoutButton?.addEventListener('click', async () => {
    logoutButton.disabled = true
    logoutButton.textContent = 'Signing out…'
    status.textContent = ''
    const ok = await window.ShadufAuth?.logout()
    if (ok) {
      stopPoolRequest()
      replacePoolList()
      location.reload()
    } else {
      logoutButton.disabled = false
      logoutButton.textContent = 'Sign out'
      status.textContent = 'We could not sign you out. Please try again.'
    }
  })
  window.ShadufAuth?.subscribe((session) => {
    if (session.status === 'error') {
      currentSession = null
      stopPoolRequest()
      if (poolList) renderPoolError()
      status.textContent = 'We could not refresh your account. Check your connection and try again.'
      return
    }
    if (session.status !== 'ready') return
    status.textContent = ''
    const renderedAuthenticated = page.dataset.authenticated === 'true'
    const renderedIdentity = page.querySelector('[data-account-identity]')?.textContent || ''
    if (renderedAuthenticated !== Boolean(session.authenticated) || session.authenticated && renderedIdentity !== session.display_identity) {
      currentSession = null
      stopPoolRequest()
      replacePoolList()
      location.reload()
      return
    }
    currentSession = session
    if (session.authenticated) loadPools()
    else { stopPoolRequest(); replacePoolList() }
  })
  window.ShadufAuth?.subscribeFollows(() => { if (currentSession?.authenticated) loadPools() })
})()
