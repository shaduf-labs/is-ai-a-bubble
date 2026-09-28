/* Pure filtering and ordering are shared by the browser and catalogue checks. */
(() => {
  const {tagKey,tagLabel}=globalThis.ShadufDiscovery;
  const keys=values=>[...new Set((values||[]).map(tagKey).filter(Boolean))];
  const collator=new Intl.Collator('en',{sensitivity:'base',numeric:true});
  function byDate(a,b,direction) {
    const left=Date.parse(a.latest_research_at),right=Date.parse(b.latest_research_at);
    if(!Number.isFinite(left))return Number.isFinite(right)?1:0;
    if(!Number.isFinite(right))return -1;
    return (left-right)*direction;
  }
  const SORTS={
    newest:(a,b)=>byDate(a,b,-1),
    oldest:(a,b)=>byDate(a,b,1),
    az:(a,b)=>collator.compare(a.title,b.title),
    za:(a,b)=>collator.compare(b.title,a.title),
  };
  function filter(pools,state,{ignoreTags=false}={}) {
    const words=(state.query||'').toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
    return pools.filter(p=>(!state.categories.length||state.categories.some(c=>(p.categories||[]).includes(c)))
      &&(ignoreTags||!state.tags.length||state.tags.some(t=>keys(p.tags).includes(tagKey(t))))
      &&words.every(w=>(p.title+' '+p.question+' '+(p.card?.question||'')+' '+(p.card?.text||'')+' '+(p.description||'')+' '+(p.tags||[]).join(' ')).toLocaleLowerCase().includes(w)));
  }
  function select(pools,state) {
    const order=Object.hasOwn(SORTS,state.sort)?SORTS[state.sort]:SORTS.newest;
    const ordered=filter(pools,state).sort((a,b)=>order(a,b)||collator.compare(a.title,b.title)||a.slug.localeCompare(b.slug));
    if(state.sort!=='newest'||state.query.trim()||state.categories.length||state.tags.length)return ordered;
    const featured=ordered.filter(p=>Number.isInteger(p.featured_position)&&p.featured_position>0),result=ordered.filter(p=>!featured.includes(p));
    for(const pool of featured.sort((a,b)=>a.featured_position-b.featured_position))result.splice(Math.min(pool.featured_position-1,result.length),0,pool);
    return result;
  }
  function paginate(results,requestedPage,size=24) {
    const pages=Math.max(1,Math.ceil(results.length/size));
    const page=Math.min(pages,Math.max(1,Number.parseInt(requestedPage,10)||1));
    return {pages,page,shown:results.slice((page-1)*size,page*size)};
  }
  function parse(search) {
    const q=new URLSearchParams(search);
    return {query:q.get('q')||'',categories:[...new Set(q.getAll('category'))],tags:keys(q.getAll('tag')),sort:Object.hasOwn(SORTS,q.get('sort'))?q.get('sort'):'newest',page:Math.max(1,Number.parseInt(q.get('page'),10)||1)};
  }
  function topics(pools,state,limit=6) {
    const available=filter(pools,state,{ignoreTags:true}),counts=new Map();
    for(const pool of available)for(const tag of keys(pool.tags))counts.set(tag,(counts.get(tag)||0)+1);
    const groups=[...available].sort((a,b)=>a.slug.localeCompare(b.slug)).map(p=>keys(p.tags).sort((a,b)=>counts.get(b)-counts.get(a)));
    const shortcuts=[];
    for(let depth=0;groups.some(tags=>depth<tags.length)&&shortcuts.length<limit;depth++)for(const tags of groups){
      if(tags[depth]&&!shortcuts.includes(tags[depth]))shortcuts.push(tags[depth]);
      if(shortcuts.length===limit)break;
    }
    return {counts,shortcuts:[...new Set([...shortcuts,...keys(state.tags)])]};
  }
  const model={filter,select,parse,paginate,topics,SORTS};
  if(typeof module!=='undefined'&&module.exports)module.exports=model;
  if(typeof document==='undefined')return;
  window.ShadufCatalogueModel=model;
  const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
  const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let library,state=parse(location.search),pageSize=24,view='cards',navigate,queryTimer;
  let tagLabels=new Map();
  const displayTag=key=>tagLabels.get(tagKey(key))||key;
  const disclosures='.catalogue-tags,.pool-more-tags,.category-menu';
  function closeDisclosures(restoreFocus=false,except=null){
    $$(disclosures).forEach(detail=>{if(detail.open&&detail!==except){detail.open=false;if(restoreFocus)detail.querySelector('summary')?.focus({preventScroll:true});}});
  }
  try{view=localStorage.getItem('shaduf-catalogue-view')==='list'?'list':'cards';}catch{}
  function remember() {try{sessionStorage.setItem('shaduf-catalogue-return',location.pathname+location.search+'#pool-catalogue');}catch{}}
  function syncUrl({push=false}={}) {
    const q=new URLSearchParams();if(state.query)q.set('q',state.query);
    state.categories.forEach(c=>q.append('category',c));state.tags.forEach(t=>q.append('tag',t));
    if(state.sort!=='newest')q.set('sort',state.sort);if(state.page>1)q.set('page',state.page);
    const url=location.pathname+(q.size?'?'+q:'');
    if(url!==location.pathname+location.search)history[push?'pushState':'replaceState']({},'',url);
    remember();
  }
  function render() {
    if(!library)return;
    const home=document.body.dataset.kind==='home';
    const pool=library.pools.find(p=>p.slug===document.body.dataset.pool);
    $$('[data-top-category]').forEach(a=>{const c=a.dataset.topCategory;const yes=home?(c?state.categories.includes(c):!state.categories.length):(pool?.categories||[]).includes(c);a.classList.toggle('active',yes);if(yes)a.setAttribute('aria-current','page');else a.removeAttribute('aria-current');});
    const categoryIds=home?state.categories:(pool?.categories||[]);
    const categoryNames=categoryIds.map(id=>library.categories.find(c=>c.id===id)?.label||id);
    $$('[data-current-category]').forEach(node=>node.textContent=categoryNames.join(', ')||'Explore');
    if(!home||!$('.catalogue-grid'))return;
    const results=select(library.pools,state),{pages,page,shown}=paginate(results,state.page,pageSize);state.page=page;
    const visible=new Set(shown.map(p=>p.slug));
    const nodes=new Map($$('[data-library-pool]').map(n=>[n.dataset.libraryPool,n]));
    const grid=$('.catalogue-grid');grid.dataset.layout=view;
    for(const p of results)if(nodes.has(p.slug))grid.append(nodes.get(p.slug));
    nodes.forEach((node,slug)=>node.hidden=!visible.has(slug));
    $$('[data-catalogue-view]').forEach(b=>b.setAttribute('aria-pressed',b.dataset.catalogueView===view));
    $('[data-catalogue-search]').value=state.query;$('[data-catalogue-sort]').value=state.sort;
    $('#pool-list-title').textContent=state.categories.length?state.categories.map(c=>library.categories.find(x=>x.id===c)?.label||c).join(' & ')+' research':'Explore research pools';
    $('[data-catalogue-count]').textContent=results.length+' '+(results.length===1?'pool':'pools')+(results.length!==library.pools.length?' / '+library.pools.length:'');
    const {counts}=topics(library.pools,state);
    $('[data-tags-selected]').textContent=state.tags.length?'('+state.tags.length+')':'';
    const selected=$('[data-selected-tags]');
    selected.hidden=!state.tags.length;
    selected.innerHTML=state.tags.map(tag=>`<button type="button" data-remove-tag="${escape(tag)}" aria-label="Remove tag: ${escape(displayTag(tag))}">Tag: ${escape(displayTag(tag))}<span aria-hidden="true">×</span></button>`).join('');
    $$('[data-filter-tag]').forEach(input=>input.checked=state.tags.includes(tagKey(input.value)));
    $$('[data-catalogue-tag]').forEach(link=>{if(state.tags.includes(tagKey(link.dataset.catalogueTag)))link.setAttribute('aria-current','true');else link.removeAttribute('aria-current');});
    $$('[data-tag-count]').forEach(n=>n.textContent=counts.get(tagKey(n.dataset.tagCount))||0);
    filterTagOptions(counts);
    $('[data-catalogue-empty]').hidden=results.length!==0;
    $('.catalogue-pagination').hidden=pages<=1;
    $('[data-catalogue-page-label]').textContent=`${(state.page-1)*pageSize+1}–${Math.min(state.page*pageSize,results.length)} of ${results.length} pools`;
    $('[data-catalogue-prev]').disabled=state.page===1;$('[data-catalogue-next]').disabled=state.page===pages;
    remember();
  }
  function changed({push=false}={}) {state.page=1;syncUrl({push});render();}
  function filterTagOptions(counts=topics(library.pools,state).counts) {
    const query=tagKey($('[data-tag-search]').value);let shown=0;
    $$('[data-tag-option]').forEach(row=>{const tag=tagKey(row.querySelector('input').value);row.hidden=(!counts.has(tag)&&!state.tags.includes(tag))||!tag.includes(query);if(!row.hidden)shown++;});
    $('[data-no-tag-results]').hidden=shown!==0;
  }
  function init(lib,go) {clearTimeout(queryTimer);library=lib;navigate=go;tagLabels=new Map();for(const p of [...lib.pools].sort((a,b)=>a.slug.localeCompare(b.slug)))for(const label of p.tags||[])if(!tagLabels.has(tagKey(label)))tagLabels.set(tagKey(label),tagLabel(label));state=parse(location.search);render();}
  function returnUrl(){try{return sessionStorage.getItem('shaduf-catalogue-return')||'/';}catch{return '/';}}
  document.addEventListener('click',e=>{
    closeDisclosures(false,e.target.closest(disclosures));
    const b=e.target.closest('button,a');if(!b)return;
    if(b.hasAttribute('data-top-category')){
      if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
      if(!library||!navigate)return;
      e.preventDefault();
      closeDisclosures(true);
      if(document.body.dataset.kind!=='home'){navigate?.(b.href);return;}
      clearTimeout(queryTimer);state.categories=b.dataset.topCategory?[b.dataset.topCategory]:[];state.tags=[];state.query='';changed({push:true});$('#pool-catalogue').scrollIntoView({behavior:'instant',block:'start'});return;
    }
    if(b.hasAttribute('data-catalogue-view')){view=b.dataset.catalogueView;try{localStorage.setItem('shaduf-catalogue-view',view);}catch{}render();return;}
    if(b.hasAttribute('data-catalogue-tag')){
      if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||document.body.dataset.kind!=='home'||!library)return;
      e.preventDefault();clearTimeout(queryTimer);const t=tagKey(b.dataset.catalogueTag);state.tags=state.tags.includes(t)?state.tags.filter(x=>x!==t):[...state.tags,t];
      const card=b.closest('[data-library-pool]');closeDisclosures(true);changed({push:true});if(card?.hidden)$('.catalogue-tags>summary')?.focus({preventScroll:true});return;
    }
    if(b.hasAttribute('data-remove-tag')){const index=state.tags.indexOf(b.dataset.removeTag);state.tags=state.tags.filter(t=>t!==b.dataset.removeTag);changed({push:true});const remaining=$$('[data-remove-tag]');(remaining[Math.min(index,remaining.length-1)]||$('.catalogue-tags>summary'))?.focus({preventScroll:true});return;}
    if(b.hasAttribute('data-clear-tags')){state.tags=[];changed({push:true});return;}
    if(b.hasAttribute('data-reset-catalogue')){clearTimeout(queryTimer);state.query='';state.categories=[];state.tags=[];changed({push:true});return;}
    if(b.hasAttribute('data-catalogue-prev')||b.hasAttribute('data-catalogue-next')){state.page+=b.hasAttribute('data-catalogue-next')?1:-1;syncUrl({push:true});render();$('#pool-catalogue').scrollIntoView({block:'start'});return;}
    if(!b.closest('.catalogue-tags'))$('.catalogue-tags')?.removeAttribute('open');
  });
  document.addEventListener('change',e=>{
    const t=e.target;if(t.matches('[data-catalogue-sort]')){state.sort=t.value;changed({push:true});}
    if(t.matches('[data-filter-tag]')){const key=tagKey(t.value);state.tags=t.checked?[...new Set([...state.tags,key])]:state.tags.filter(x=>x!==key);changed({push:true});}
  });
  document.addEventListener('input',e=>{
    if(e.target.matches('[data-catalogue-search]')){clearTimeout(queryTimer);const value=e.target.value;queryTimer=setTimeout(()=>{state.query=value;changed();},120);}
    if(e.target.matches('[data-tag-search]'))filterTagOptions();
  });
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&$$(disclosures).some(detail=>detail.open)){e.preventDefault();closeDisclosures(true);}});
  window.addEventListener('resize',()=>closeDisclosures());
  window.ShadufCatalogue={init,returnUrl};
})();
