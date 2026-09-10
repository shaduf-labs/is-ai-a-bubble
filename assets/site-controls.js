(() => {
  if (!document.body.dataset.designVersion) return
  const $ = selector => document.querySelector(selector)
  const leftMedia=matchMedia('(max-width:700px)'),rightMedia=matchMedia('(max-width:1000px)')
  function syncDrawers(){
    for(const [name,media] of [['left',leftMedia],['right',rightMedia]]){
      const pane=$(`[data-${name}-surface]`),trigger=$(`[data-open-${name}]`)
      const closed=media.matches&&!document.body.classList.contains(`${name}-open`)
      if(pane){pane.inert=closed;if(closed)pane.setAttribute('aria-hidden','true');else pane.removeAttribute('aria-hidden')}
      trigger?.setAttribute('aria-expanded',String(!closed&&media.matches))
    }
  }
  new MutationObserver(syncDrawers).observe(document.body,{attributes:true,attributeFilter:['class']})
  leftMedia.addEventListener('change',syncDrawers);rightMedia.addEventListener('change',syncDrawers);syncDrawers()
  fetch('/catalogue.json').then(r => {if(!r.ok)throw Error('Catalogue unavailable');return r.json()}).then(data => {
    window.ShadufCatalogue?.init(data, href => location.assign(href))
    window.addEventListener('popstate', () => window.ShadufCatalogue?.init(data, href => location.assign(href)))
  }).catch(() => {/* Server-rendered cards and links remain usable. */})
  $('[data-close-left]')?.addEventListener('click', () => {
    document.body.classList.remove('left-open')
    $('[data-open-left]')?.setAttribute('aria-expanded','false')
  })
  const outline=$('[data-page-outline]')
  if(outline){const headings=[...document.querySelectorAll('.agent-document :is(h2,h3)[id]')];for(const heading of headings){const a=document.createElement('a');a.href='#'+encodeURIComponent(heading.id);a.textContent=heading.textContent;outline.append(a)}if(!headings.length)outline.hidden=true}
  const track=$('.ticker-track'), group=track?.firstElementChild
  if(group){const copy=group.cloneNode(true);copy.className='ticker-clone';copy.setAttribute('aria-hidden','true');copy.inert=true;for(const a of copy.querySelectorAll('a'))a.tabIndex=-1;track.append(copy)}
  $('[data-toggle-ticker]')?.addEventListener('click', event => {const paused=$('.activity-ticker')?.classList.contains('paused');event.currentTarget.setAttribute('aria-pressed',String(paused));event.currentTarget.setAttribute('aria-label',paused?'Resume activity ticker':'Pause activity ticker')})
  let logoPlayback=null
  const stop=()=>{if(logoPlayback)return;window.ShadufMotion?.stop();$('#transition-layer')?.classList.remove('is-loading')}
  window.addEventListener('pageshow',stop)
  document.addEventListener('click',event=>{
    const a=event.target.closest('a[href]')
    if(!a||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey||a.target||a.hasAttribute('download'))return
    if(logoPlayback){event.preventDefault();return}
    if(!a.matches('.wordmark, .about-link, .explore-about-link')||!window.ShadufMotion?.playOnce)return
    event.preventDefault()
    const layer=$('#transition-layer'),destination=a.href
    layer?.classList.add('is-loading','is-logo-playback')
    logoPlayback=window.ShadufMotion.playOnce({slow:true,reduced:matchMedia('(prefers-reduced-motion: reduce)').matches})
    logoPlayback.then(()=>{logoPlayback=null;layer?.classList.remove('is-loading','is-logo-playback');location.assign(destination)})
  },true)
  document.addEventListener('click',event=>{
    const a=event.target.closest('a[href]')
    if(!a||event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey||a.target||a.hasAttribute('download'))return
    const url=new URL(a.href,location.href)
    if(url.origin!==location.origin||!['http:','https:'].includes(url.protocol)||url.pathname===location.pathname&&url.search===location.search)return
    if(!(/^\/p\//.test(url.pathname)||['/','/explore/','/about/'].includes(url.pathname)))return
    if(matchMedia('(prefers-reduced-motion: reduce)').matches)return
    $('#transition-layer')?.classList.add('is-loading');window.ShadufMotion?.start()
    // Never delay navigation to finish an animation.
  })
})()
