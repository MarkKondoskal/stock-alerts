(function(root){
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const states={public:{articles:[]},private:{articles:[],revision:''}};
  function cards(items,scope){
    return items.map(item=>`<article class="research-card ${item.featured?'research-featured':''}"><span class="research-badge">${item.featured?'Featured · ':''}${item.kind==='own'?'My research':'Reading list'}${scope==='private'?` · ${item.published?'Public':'Private'}`:''}</span><h3>${esc(item.title)}</h3><div class="research-meta">${esc([item.author,item.publication,item.published_at].filter(Boolean).join(' · '))}</div><div class="research-tags">${(item.tickers||[]).map(t=>`<span class="research-tag">${esc(t)}</span>`).join('')}</div>${item.summary?`<p>${esc(item.summary)}</p>`:''}<div class="research-card-actions"><a class="research-link" href="${esc(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer">Read original ↗</a>${scope==='private'?`<button type="button" class="research-action" data-edit-research="${esc(item.id)}">Edit</button>`:''}</div></article>`).join('')||'<p class="research-empty">No articles here yet. Research will appear as it is added.</p>';
  }
  function safeUrl(value){try{const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password?url.href:'#'}catch{return '#'}}
  function draw(scope){
    const container=document.getElementById('research-'+scope);
    const filter=container.querySelector('[data-research-filter]').value;
    const search=container.querySelector('[data-research-search]').value.toLowerCase();
    const articles=states[scope].articles.filter(item=>(filter==='all'||item.kind===filter)&&[item.title,item.author,item.summary,...(item.tickers||[])].join(' ').toLowerCase().includes(search));
    articles.sort((a,b)=>Number(b.featured)-Number(a.featured)||(b.published_at||'').localeCompare(a.published_at||''));
    container.querySelector('[data-research-cards]').innerHTML=cards(articles,scope);
    container.querySelectorAll('[data-edit-research]').forEach(button=>button.onclick=()=>edit(button.dataset.editResearch));
  }
  async function load(scope){
    const state=states[scope];const status=document.querySelector('#research-'+scope+' [data-research-status]');
    if(scope==='private'&&state.revision&&!document.getElementById('research-editor').hidden){status.textContent='Save or cancel the current edit before refreshing the library.';return}
    status.className='research-status';status.textContent='Loading research…';
    try{
      if(scope==='private'){
        const data=await root.api('/api/private/research',{},response=>state.revision=response.headers.get('ETag'));
        state.articles=data.articles;
      }else{
        const response=await fetch('/api/public/research');const data=await response.json();
        if(!response.ok)throw Error(data.error||'Could not load research');state.articles=data.articles;
      }
      draw(scope);status.textContent=scope==='private'?'Only articles marked Public appear on the public dashboard. Notes remain private.':'';
    }catch(error){status.className='research-status research-error';status.textContent=error.message}
  }
  function edit(id){
    const form=document.getElementById('research-editor');form.reset();
    const item=states.private.articles.find(item=>item.id===id)||{id:crypto.randomUUID(),kind:'own',author:'Mark Kondoskal',publication:'Substack',tickers:[],published:false,featured:false};
    form.dataset.id=item.id;
    for(const field of ['title','url','author','publication','summary','private_notes','published_at','kind'])form.elements[field].value=item[field]||'';
    form.elements.tickers.value=(item.tickers||[]).join(', ');
    for(const field of ['published','featured'])form.elements[field].checked=!!item[field];
    form.querySelector('[data-research-remove]').hidden=!id;form.hidden=false;form.elements.url.focus();
  }
  async function save(remove=false){
    const form=document.getElementById('research-editor'),state=states.private;
    const status=document.querySelector('#research-private [data-research-status]');
    const buttons=form.querySelectorAll('button');buttons.forEach(b=>b.disabled=true);
    try{
      const item={id:form.dataset.id};
      for(const field of ['title','url','author','publication','summary','private_notes','published_at','kind'])item[field]=form.elements[field].value.trim();
      item.tickers=form.elements.tickers.value.split(',').map(t=>t.trim()).filter(Boolean);
      for(const field of ['published','featured'])item[field]=form.elements[field].checked;
      const articles=state.articles.filter(article=>article.id!==item.id);
      if(!remove)articles.push(item);
      const data=await root.api('/api/private/research',{method:'PUT',headers:{'If-Match':state.revision},body:JSON.stringify({version:1,articles})},response=>state.revision=response.headers.get('ETag'));
      state.articles=data.articles;form.hidden=true;draw('private');status.className='research-status';status.textContent='Research saved to the private repository.';
    }catch(error){status.className='research-status research-error';status.textContent=error.message}
    finally{buttons.forEach(b=>b.disabled=false)}
  }
  function init(){
    for(const scope of ['public','private']){
      const container=document.getElementById('research-'+scope);if(!container)continue;
      container.querySelector('[data-research-filter]').onchange=()=>draw(scope);
      container.querySelector('[data-research-search]').oninput=()=>draw(scope);
      container.querySelector('[data-research-reload]').onclick=()=>load(scope);
    }
    const form=document.getElementById('research-editor');
    if(form){form.elements.kind.onchange=()=>{if(form.elements.kind.value==='reading'&&form.elements.author.value==='Mark Kondoskal')form.elements.author.value=''};document.getElementById('research-add').onclick=()=>edit();form.onsubmit=event=>{event.preventDefault();save()};form.querySelector('[data-research-cancel]').onclick=()=>form.hidden=true;form.querySelector('[data-research-remove]').onclick=()=>save(true)}
  }
  root.Research={load,cards,safeUrl};init();
})(window);
