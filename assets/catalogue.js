/* Pure filtering and ordering are shared by the browser and catalogue checks. */
(() => {
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
      &&(ignoreTags||!state.tags.length||state.tags.some(t=>(p.tags||[]).includes(t)))
      &&words.every(w=>(p.title+' '+p.question+' '+(p.card?.question||'')+' '+(p.card?.text||'')+' '+(p.description||'')+' '+(p.tags||[]).join(' ')).toLocaleLowerCase().includes(w)));
  }
  function select(pools,state) {const order=Object.hasOwn(SORTS,state.sort)?SORTS[state.sort]:SORTS.newest;return filter(pools,state).sort((a,b)=>order(a,b)||collator.compare(a.title,b.title)||a.slug.localeCompare(b.slug));}
  function paginate(results,requestedPage,size=24) {
    const pages=Math.max(1,Math.ceil(results.length/size));
    const page=Math.min(pages,Math.max(1,Number.parseInt(requestedPage,10)||1));
    return {pages,page,shown:results.slice((page-1)*size,page*size)};
  }
  function parse(search) {
    const q=new URLSearchParams(search);
    return {query:q.get('q')||'',categories:[...new Set(q.getAll('category'))],tags:[...new Set(q.getAll('tag'))],sort:Object.hasOwn(SORTS,q.get('sort'))?q.get('sort'):'newest',page:Math.max(1,Number.parseInt(q.get('page'),10)||1)};
  }
  function topics(pools,state,limit=6) {
    const available=filter(pools,state,{ignoreTags:true}),counts=new Map();
    for(const pool of available)for(const tag of new Set(pool.tags||[]))counts.set(tag,(counts.get(tag)||0)+1);
    const groups=[...available].sort((a,b)=>a.slug.localeCompare(b.slug)).map(p=>[...(p.tags||[])].sort((a,b)=>counts.get(b)-counts.get(a)));
    const shortcuts=[];
    for(let depth=0;groups.some(tags=>depth<tags.length)&&shortcuts.length<limit;depth++)for(const tags of groups){
      if(tags[depth]&&!shortcuts.includes(tags[depth]))shortcuts.push(tags[depth]);
      if(shortcuts.length===limit)break;
    }
    return {counts,shortcuts:[...new Set([...shortcuts,...state.tags])]};
  }
  const model={filter,select,parse,paginate,topics,SORTS};
  if(typeof module!=='undefined'&&module.exports)module.exports=model;
  if(typeof document==='undefined')return;
  window.ShadufCatalogueModel=model;
  const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];
  const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let library,state=parse(location.search),pageSize=24,view='cards',navigate,queryTimer;
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
    selected.innerHTML=state.tags.map(tag=>`<button type="button" data-remove-tag="${escape(tag)}" aria-label="Remove tag: ${escape(tag)}">${escape(tag)}<span aria-hidden="true">×</span></button>`).join('');
    $$('[data-filter-tag]').forEach(input=>input.checked=state.tags.includes(input.value));
    $$('[data-catalogue-tag]').forEach(button=>button.setAttribute('aria-pressed',state.tags.includes(button.dataset.catalogueTag)));
    $$('[data-tag-count]').forEach(n=>n.textContent=counts.get(n.dataset.tagCount)||0);
    filterTagOptions(counts);
    $('[data-catalogue-empty]').hidden=results.length!==0;
    $('.catalogue-pagination').hidden=pages<=1;
    $('[data-catalogue-page-label]').textContent=`${(state.page-1)*pageSize+1}–${Math.min(state.page*pageSize,results.length)} of ${results.length} pools`;
    $('[data-catalogue-prev]').disabled=state.page===1;$('[data-catalogue-next]').disabled=state.page===pages;
    remember();
  }
  function changed({push=false}={}) {state.page=1;syncUrl({push});render();}
  function filterTagOptions(counts=topics(library.pools,state).counts) {
    const query=$('[data-tag-search]').value.trim().toLocaleLowerCase();let shown=0;
    $$('[data-tag-option]').forEach(row=>{const tag=row.querySelector('input').value;row.hidden=(!counts.has(tag)&&!state.tags.includes(tag))||!tag.toLocaleLowerCase().includes(query);if(!row.hidden)shown++;});
    $('[data-no-tag-results]').hidden=shown!==0;
  }
  function init(lib,go) {clearTimeout(queryTimer);library=lib;navigate=go;state=parse(location.search);render();}
  function returnUrl(){try{return sessionStorage.getItem('shaduf-catalogue-return')||'/';}catch{return '/';}}
  document.addEventListener('click',e=>{
    if(!e.target.closest('.catalogue-tags'))$('.catalogue-tags')?.removeAttribute('open');
    const b=e.target.closest('button,a');if(!b)return;
    if(b.hasAttribute('data-top-category')){
      if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
      if(!library||!navigate)return;
      e.preventDefault();
      if(document.body.dataset.kind!=='home'){navigate?.(b.href);return;}
      clearTimeout(queryTimer);state.categories=b.dataset.topCategory?[b.dataset.topCategory]:[];state.tags=[];state.query='';changed({push:true});$('#pool-catalogue').scrollIntoView({behavior:'instant',block:'start'});return;
    }
    if(b.hasAttribute('data-catalogue-view')){view=b.dataset.catalogueView;try{localStorage.setItem('shaduf-catalogue-view',view);}catch{}render();return;}
    if(b.hasAttribute('data-catalogue-tag')){const t=b.dataset.catalogueTag;state.tags=state.tags.includes(t)?state.tags.filter(x=>x!==t):[...state.tags,t];changed({push:true});return;}
    if(b.hasAttribute('data-remove-tag')){const index=state.tags.indexOf(b.dataset.removeTag);state.tags=state.tags.filter(t=>t!==b.dataset.removeTag);changed({push:true});const remaining=$$('[data-remove-tag]');(remaining[Math.min(index,remaining.length-1)]||$('.catalogue-tags>summary'))?.focus({preventScroll:true});return;}
    if(b.hasAttribute('data-clear-tags')){state.tags=[];changed({push:true});return;}
    if(b.hasAttribute('data-reset-catalogue')){clearTimeout(queryTimer);state.query='';state.categories=[];state.tags=[];changed({push:true});return;}
    if(b.hasAttribute('data-catalogue-prev')||b.hasAttribute('data-catalogue-next')){state.page+=b.hasAttribute('data-catalogue-next')?1:-1;syncUrl({push:true});render();$('#pool-catalogue').scrollIntoView({block:'start'});return;}
    if(!b.closest('.catalogue-tags'))$('.catalogue-tags')?.removeAttribute('open');
  });
  document.addEventListener('change',e=>{
    const t=e.target;if(t.matches('[data-catalogue-sort]')){state.sort=t.value;changed({push:true});}
    if(t.matches('[data-filter-tag]')){state.tags=t.checked?[...new Set([...state.tags,t.value])]:state.tags.filter(x=>x!==t.value);changed({push:true});}
  });
  document.addEventListener('input',e=>{
    if(e.target.matches('[data-catalogue-search]')){clearTimeout(queryTimer);const value=e.target.value;queryTimer=setTimeout(()=>{state.query=value;changed();},120);}
    if(e.target.matches('[data-tag-search]'))filterTagOptions();
  });
  document.addEventListener('keydown',e=>{if(e.key==='Escape')$('.catalogue-tags')?.removeAttribute('open');});
  window.ShadufCatalogue={init,returnUrl};
})();
