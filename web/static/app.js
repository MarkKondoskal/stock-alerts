const $ = s => document.querySelector(s); let password = sessionStorage.getItem('dashboardPassword') || ''; let watchlist = {}; let watchlistRevision = ''; let watchMarket = {}; let watchSort = 'ticker';
const fmt = (n, digits=2) => Number(n||0).toLocaleString('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits});
async function api(path, opts={}, onResponse) { const headers={'Content-Type':'application/json',...(opts.headers||{})}; if(password) headers.Authorization='Bearer '+password; const r=await fetch(path,{...opts,headers}); let d={}; try{d=await r.json()}catch{} if(!r.ok) throw new Error(d.error||`Request failed (${r.status})`); onResponse?.(r); return d; }
function toast(msg,type='success'){const el=$('#toast');el.textContent=msg;el.className='toast '+type;setTimeout(()=>el.classList.add('hidden'),4200)}
function connected(on){$('#login').classList.toggle('hidden',on);document.querySelectorAll('.view').forEach(x=>x.classList.toggle('hidden',!on||x.id!=='overview'));$('#connection').textContent=on?'GitHub connected':'Not connected';$('#connection').className='pill '+(on?'good':'bad');}
function showTab(tab){document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));document.querySelectorAll('.view').forEach(v=>v.classList.toggle('hidden',v.id!==tab));}
async function connect(){try{await api('/api/private/accounts');sessionStorage.setItem('dashboardPassword',password);connected(true);await loadOverview();showTab('overview');$('#login-error').textContent='';}catch(e){connected(false);$('#login-error').textContent=e.message;}}
function numInput(value,cls='target-input',placeholder='—'){return `<input class="${cls}" type="number" step="any" value="${value??''}" placeholder="${placeholder}">`}
function targetArray(a){return Array.isArray(a)?esc(a.join(', ')):''}
function parseTargets(v){const values=v.split(',').map(x=>x.trim()).filter(Boolean).map(Number);if(values.some(x=>!Number.isFinite(x)||x<=0))throw new Error('Targets must be positive finite numbers.');return values}
function vals(item,metric,dir){const m=item.valuation_targets?.[metric];if(Array.isArray(m)) return dir==='trim'?m:[];return m?.[dir]||[]}
function renderWatchlist(){const rows=Object.entries(watchlist).sort(([a,av],[b,bv])=>(watchSort==='nearest'?(WatchlistUI.nearest(av,watchMarket[a]?.market||{})-WatchlistUI.nearest(bv,watchMarket[b]?.market||{})):0)||a.localeCompare(b)).map(([ticker,item])=>{
const market=watchMarket[ticker]?.market||{};const inputs=[['Price buy','prices',item.price_targets],['Forward P/E trim','fxpe-trim',vals(item,'FxPE','trim')],['Forward P/E buy','fxpe-buy',vals(item,'FxPE','buy')],['P/E trim','pe-trim',vals(item,'PE','trim')],['P/E buy','pe-buy',vals(item,'PE','buy')],['P/S trim','ps-trim',vals(item,'P/S','trim')],['P/S buy','ps-buy',vals(item,'P/S','buy')]];
return `<tr data-ticker="${esc(ticker)}"><td><span class="ticker">${esc(ticker)}</span></td><td>${WatchlistUI.price(market)}</td><td>${WatchlistUI.valuations(market)}</td><td class="watch-proximity">${WatchlistUI.proximity(item,market)}</td><td><details class="watch-target-editor"><summary class="watch-summary">${inputs.filter(x=>x[2]?.length).map(x=>`${esc(x[0])}: ${targetArray(x[2])}`).join('<br>')||'Add targets'}</summary>${inputs.map(([label,cls,values])=>`<label>${esc(label)}<input class="target-input ${cls}" value="${targetArray(values)}" placeholder="Comma-separated targets"></label>`).join('')}</details></td><td><button class="remove-row" title="Remove ticker">×</button></td></tr>`;}).join('');$('#watchlist-rows').innerHTML=rows||'<tr><td colspan="6" class="muted">No watchlist tickers found.</td></tr>';document.querySelectorAll('.remove-row').forEach(b=>b.onclick=()=>{const tr=b.closest('tr');delete watchlist[tr.dataset.ticker];tr.remove()});document.querySelectorAll('#watchlist-rows input').forEach(input=>input.oninput=()=>{try{const tr=input.closest('tr');const item=collectWatchlist()[tr.dataset.ticker];tr.querySelector('.watch-proximity').innerHTML=WatchlistUI.proximity(item,watchMarket[tr.dataset.ticker]?.market||{})}catch{}})}

function collectWatchlist(){const result={};document.querySelectorAll('#watchlist-rows tr[data-ticker]').forEach(tr=>{const ticker=tr.dataset.ticker.trim().toUpperCase();if(!ticker)return;const get=sel=>parseTargets(tr.querySelector(sel).value);const price_targets=get('.prices');const valuation_targets={};for(const [metric,trimSel,buySel] of [['FxPE','.fxpe-trim','.fxpe-buy'],['PE','.pe-trim','.pe-buy'],['P/S','.ps-trim','.ps-buy']]){const trim=get(trimSel),buy=get(buySel);if(trim.length||buy.length)valuation_targets[metric]={trim,buy};}result[ticker]={price_targets,valuation_targets}});return result}
async function loadWatchlist(){watchlist=await api('/api/watchlist',{},r=>{watchlistRevision=r.headers.get('ETag')||''});try{watchMarket=await api('/api/public/watchlist-market')}catch{watchMarket={}}renderWatchlist();$('#watchlist-status').textContent=`Loaded ${Object.keys(watchlist).length} tickers. Prices and multiples are latest available observations.`;loadAlertHistory()}
async function loadAlertHistory(){try{const data=await api('/api/private/alert-history');const labels={pending:'Delivery not confirmed',unknown:'Delivery uncertain',accepted:'Discord accepted',failed_or_unconfirmed:'Failed or unconfirmed'};$('#alert-history-rows').innerHTML=data.events.map(e=>`<tr><td>${esc(new Date(e.created_at).toLocaleString())}</td><td>${esc(e.ticker)}</td><td>${esc(e.metric)} ${esc(e.direction)} · ${esc(e.target)}</td><td>${esc(e.actual)}</td><td>${esc(labels[e.status]||'Unknown')}</td></tr>`).join('')||'<tr><td colspan="5">No recorded alert attempts yet.</td></tr>'}catch(e){$('#alert-history-rows').innerHTML='<tr><td colspan="5">Could not load alert history. Reload Watchlist to retry.</td></tr>'}}

async function saveWatchlist(){try{const data=collectWatchlist();const d=await api('/api/watchlist',{method:'PUT',headers:{'If-Match':watchlistRevision},body:JSON.stringify(data)},r=>{watchlistRevision=r.headers.get('ETag')||''});watchlist=data;renderWatchlist();toast('Watchlist committed to GitHub.');$('#watchlist-status').textContent='Saved to GitHub'+(d.commit?' · commit created':'')+'.';}catch(e){toast(e.message,'error')}}
const esc = text => String(text??'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function loadOverview(){
  // The private dashboard and /public use identical source account records.
  // Older UI versions loaded portfolio/marks_portfolio.json instead.
  return window.loadPrivateHoldings();
}
async function loadWorkflows(){const [runs]=await Promise.all([api('/api/workflows'),window.loadSystemHealth()]);$('#workflow-list').innerHTML=runs.map(x=>{const status=x.status==='completed'?(x.conclusion||'completed'):x.status;const cls=['success','neutralized'].includes(status)?'good':(['failure','cancelled','timed_out'].includes(status)?'bad':'');return `<div class="workflow"><div><b>${x.name||x.path||'Workflow'}</b><small>${new Date(x.created_at).toLocaleString()} · ${x.event||'run'} · <a href="${x.html_url}" target="_blank" rel="noopener" style="color:#a5b4fc">View run ↗</a></small></div><span class="pill ${cls}">${status}</span></div>`}).join('')||'<p class="muted">No workflow runs returned.</p>'}
$('#login-form').onsubmit=async e=>{e.preventDefault();password=$('#password').value;await connect()};$('#sync').onclick=async()=>{if(!password)return toast('Connect first.','error');try{await Promise.all([loadOverview(),loadWatchlist(),loadWorkflows()]);toast('Synced current repository state.')}catch(e){toast(e.message,'error')}};document.querySelectorAll('.tab').forEach(b=>b.onclick=async()=>{if(!password)return;showTab(b.dataset.tab);try{if(b.dataset.tab==='watchlist')await loadWatchlist();if(b.dataset.tab==='workflows')await loadWorkflows();if(b.dataset.tab==='trades')await Promise.all([loadTrades(),loadTradeHistory()]);if(b.dataset.tab==='sentiment')await window.StockSentiment?.load('private')}catch(e){toast(e.message,'error')}});$('#reload-overview').onclick=()=>loadOverview().catch(e=>toast(e.message,'error'));$('#reload-workflows').onclick=()=>loadWorkflows().catch(e=>toast(e.message,'error'));$('#save-watchlist').onclick=saveWatchlist;$('#add-ticker').onclick=()=>{const t=prompt('Ticker symbol (e.g. MA):');if(!t)return;const ticker=t.trim().toUpperCase();if(!/^[A-Z0-9.^_-]{1,20}$/.test(ticker))return toast('Ticker contains unsupported characters.','error');if(watchlist[ticker])return toast('Ticker already exists.','error');watchlist[ticker]={price_targets:[],valuation_targets:{}};renderWatchlist()};$('#dispatch').onclick=async()=>{const workflow=$('#workflow-select').value;if(workflow==='watchlist_manager.yml'){toast('For now, edit targets in Watchlist & Alerts. The manager workflow requires action/ticker/target inputs, which are not exposed in this simple dispatch button.','error');return}try{const d=await api('/api/workflows/dispatch',{method:'POST',body:JSON.stringify({workflow})});toast(d.message);setTimeout(()=>loadWorkflows().catch(()=>{}),2500)}catch(e){toast(e.message,'error')}};$('#discord-test').onclick=async()=>{try{const d=await api('/api/discord/test',{method:'POST',body:'{}'});toast(d.message)}catch(e){toast(e.message,'error')}};$('#logout').onclick=()=>{password='';sessionStorage.removeItem('dashboardPassword');$('#password').value='';connected(false);toast('Disconnected this browser.')};
if(password){$('#password').value=password;connect() }else connected(false);

let accountSnapshots={};
let correctingTrade=null;
let tradeOffset=0;
async function loadTrades(){
  accountSnapshots=await api('/api/private/accounts');
  const account=$('#trade-account').value;
  const d=accountSnapshots[account];
  const positions=d?.positions||[];
  $('#trade-rows').innerHTML=positions.map(x=>`<tr><td>${esc(x.ticker)}</td><td>${fmt(x.quantity,4)}</td><td>${esc(x.cost_currency)} ${fmt(x.average_cost_per_share)}</td></tr>`).join('')||'<tr><td colspan="3">No open holdings</td></tr>';
  $('#trade-status').textContent=`${account==='us'?'Merrill':'Nordnet'} positions snapshot: ${d?.positions_as_of||'unknown'}`;
  // Nordnet mostly holds USD stocks, while .CO is quoted in DKK.
  chooseTradeCurrency();
}
function chooseTradeCurrency(){
  const account=$('#trade-account').value;
  const ticker=$('#trade-ticker').value.trim().toUpperCase();
  const existing=accountSnapshots[account]?.positions?.find(x=>x.ticker===ticker);
  $('#trade-currency').value=existing?.cost_currency || (account==='us'||!ticker.endsWith('.CO')?'USD':'DKK');
  previewTrade();
}
function previewTrade(){
  const account=$('#trade-account').value;
  const quantity=Number($('#trade-quantity').value), price=Number($('#trade-price').value);
  const action=$('#trade-action').value;
  const ticker=$('#trade-ticker').value.trim().toUpperCase();
  const ccy=$('#trade-currency').value;
  const split=action==='SPLIT';
  $('#trade-quantity-label').textContent=split?'New shares per old share':'Shares';
  $('#trade-price-label').hidden=split;
  $('#trade-price').required=!split;
  $('#trade-fee').disabled=split;
  $('#trade-fee-currency-label').hidden=split;
  const feeCurrency=$('#trade-fee-currency').value;
  const crossFee=!split&&Number($('#trade-fee').value)>0&&feeCurrency&&feeCurrency!==ccy;
  $('#trade-fee-rate-label').hidden=!crossFee;
  $('#trade-fee-rate').required=Boolean(crossFee);
  if(split){
    $('#trade-preview').textContent='Split ' + (ticker||'—') + ' · ' + quantity + ' new shares per old share';
    return;
  }
  const value=quantity>0&&price>0&&Number.isFinite(quantity*price)?
    new Intl.NumberFormat('en-US',{style:'currency',currency:ccy}).format(quantity*price):'—';
  const held=accountSnapshots[account]?.positions?.find(x=>x.ticker===ticker)?.quantity||0;
  const after=Number.isFinite(quantity)?held+(action==='BUY'?quantity:-quantity):held;
  $('#trade-preview').textContent=`${action} ${ticker||'—'} · ${value} ${value==='—'?'':`· Shares before ${fmt(held,4)} → after ${fmt(after,4)}`} · ${account==='us'?'Merrill':'Nordnet'}`;
}
async function loadTradeHistory(offset=0){
  const d=await api('/api/private/trades?offset='+offset);
  tradeOffset=offset;
  const tbody=$('#trade-history-rows');
  tbody.replaceChildren();
  for(const t of d.transactions||[]){
    const row=tbody.insertRow();
    for(const value of [t.date,t.account==='us'?'Merrill':'Nordnet',t.action,t.ticker,
      t.split_ratio ?? t.quantity,t.action==='SPLIT'?'—':t.currency+' '+fmt(t.price),
      t.fee==null?'—':t.currency+' '+fmt(t.fee),t.realized==null?'—':(t.realized_currency||t.currency)+' '+fmt(t.realized)]){
      row.insertCell().textContent=value;
    }
    row.insertCell().append(tradeNoteEditor(t));
    const cell=row.insertCell();
    if(t.correctable){
      const button=document.createElement('button');
      button.type='button';
      button.textContent='Correct';
      button.className='ghost';
      button.onclick=()=>selectCorrection(t);
      cell.append(button);
    }
  }
  const count=d.count||0;
  $('#trade-history-note').textContent=count
    ? 'Showing '+(offset+1)+'–'+Math.min(offset+30,count)+' of '+count+' trades'
    : 'No trades available.';
  $('#trade-history-prev').disabled=offset===0;
  $('#trade-history-next').disabled=offset+30>=count;
}
function tradeNoteEditor(trade){
  const details=document.createElement('details');
  const summary=document.createElement('summary');
  const textarea=document.createElement('textarea');
  textarea.setAttribute('aria-label','Reason for '+trade.action+' '+trade.ticker+' on '+trade.date);
  textarea.maxLength=2000;
  textarea.rows=4;
  textarea.value=trade.note;
  const label=document.createElement('label');
  const publish=document.createElement('input');
  publish.type='checkbox';
  publish.checked=trade.published;
  publish.disabled=trade.action==='SPLIT';
  label.append(publish,' Share this note on the public site');
  label.hidden=!trade.activity_public;
  const help=document.createElement('small');
  help.textContent=trade.activity_public
    ? 'This trade’s date, ticker and side are already public. Keep account details and amounts out of any note you share.'
    : 'Split notes stay private.';
  const save=document.createElement('button');
  save.type='button';
  save.className='ghost';
  save.textContent='Save note';
  const status=document.createElement('small');
  status.setAttribute('role','status');
  const updateLabel=()=>{
    const visibility=trade.published?'Public note':trade.activity_public?'Public trade · private note':'Private';
    summary.textContent=(trade.note?'Edit note':'Add note')+' · '+visibility;
  };
  updateLabel();
  save.onclick=async()=>{
    if(publish.checked&&!confirm('Publish this note for anyone to read?'))return;
    save.disabled=true;
    try{
      const result=await api('/api/private/trades/journal',{method:'PATCH',body:JSON.stringify({
        account:trade.account,trade_id:trade.trade_id,note:textarea.value,published:publish.checked,
      })});
      trade.note=textarea.value=result.note;
      trade.published=result.published;
      updateLabel();
      status.textContent=result.published?'Saved and published.':'Note saved privately.';
    }catch(error){status.textContent=error.message;}
    finally{save.disabled=false;}
  };
  const editor=document.createElement('div');
  editor.className='trade-note-editor';
  editor.append(textarea,label,help,save,status);
  details.append(summary,editor);
  return details;
}
function selectCorrection(trade){
  correctingTrade=trade;
  $('#trade-correction').hidden=!trade;
  $('#trade-account').disabled=Boolean(trade);
  if(!trade){previewTrade();return;}
  for(const field of ['account','ticker','date','action','currency']) $('#trade-'+field).value=trade[field];
  $('#trade-quantity').value=trade.split_ratio??trade.quantity;
  $('#trade-price').value=trade.action==='SPLIT'?'':trade.price;
  $('#trade-fee').value=trade.fee_original??trade.fee??0;
  $('#trade-fee-currency').value=trade.fee_currency??'';
  $('#trade-fee-rate').value=trade.fee_exchange_rate??'';
  $('#trade-reference').value=trade.broker_reference??'';
  $('#trade-correction-note').textContent='Correcting '+trade.ticker+' on '+trade.date;
  previewTrade();
  $('#trade-form').scrollIntoView({block:'start'});
}
$('#trade-cancel-correction').onclick=()=>selectCorrection(null);
$('#trade-account').onchange=()=>loadTrades().catch(e=>toast(e.message,'error'));
$('#trade-ticker').addEventListener('input',chooseTradeCurrency);
for (const name of ['#trade-quantity','#trade-price','#trade-action','#trade-currency','#trade-fee','#trade-fee-currency','#trade-fee-rate']) $(name).addEventListener('input',previewTrade);
$('#trade-refresh').onclick=()=>loadTrades().catch(e=>toast(e.message,'error'));
$('#trade-history-refresh').onclick=()=>loadTradeHistory(tradeOffset).catch(e=>toast(e.message,'error'));
$('#trade-history-prev').onclick=()=>loadTradeHistory(tradeOffset-30).catch(e=>toast(e.message,'error'));
$('#trade-history-next').onclick=()=>loadTradeHistory(tradeOffset+30).catch(e=>toast(e.message,'error'));
const initialTradeDate=new Date();while(initialTradeDate.getDay()===0||initialTradeDate.getDay()===6)initialTradeDate.setDate(initialTradeDate.getDate()-1);
$('#trade-date').value=[initialTradeDate.getFullYear(),String(initialTradeDate.getMonth()+1).padStart(2,'0'),String(initialTradeDate.getDate()).padStart(2,'0')].join('-');
$('#trade-form').onsubmit=async event=>{
  event.preventDefault();
  const payload={account:$('#trade-account').value,action:$('#trade-action').value,ticker:$('#trade-ticker').value.trim().toUpperCase(),date:$('#trade-date').value,quantity:$('#trade-quantity').value,price:$('#trade-price').value,currency:$('#trade-currency').value};
  const split=payload.action==='SPLIT';
  if(split) payload.price='';
  payload.fee=split?'0':$('#trade-fee').value;
  payload.fee_currency=split?'':$('#trade-fee-currency').value;
  payload.fee_exchange_rate=$('#trade-fee-rate').required?$('#trade-fee-rate').value:'';
  payload.broker_reference=$('#trade-reference').value.trim();
  if(correctingTrade) payload.corrects=correctingTrade.event_id;
  const amount=Number(payload.quantity)*(split?1:Number(payload.price));
  if(!payload.ticker||!Number.isFinite(amount)||amount<=0)return toast('Enter valid ticker, shares and price.','error');
  const details=split?'split ratio '+payload.quantity:payload.quantity+' shares at '+payload.price+' '+payload.currency+' with fee '+(payload.fee||'0');
  if(!confirm((correctingTrade?'Correct ':'Record ')+payload.action+' '+payload.ticker+' · '+details+' · '+payload.date+'?'))return;
  // Retain the same ID if a request times out and the user retries unchanged.
  const fingerprint=JSON.stringify(payload);
  let pending;
  try{pending=JSON.parse(sessionStorage.getItem('pendingTrade')||'null')}catch{}
  payload.client_trade_id=pending?.fingerprint===fingerprint?pending.id:crypto.randomUUID();
  sessionStorage.setItem('pendingTrade',JSON.stringify({id:payload.client_trade_id,fingerprint}));
  const button=$('#trade-submit');button.disabled=true;
  try{
    const result=await api('/api/private/trades',{method:'POST',body:JSON.stringify(payload)});
    sessionStorage.removeItem('pendingTrade');
    selectCorrection(null);
    $('#trade-status').textContent=result.message;
    toast(result.message);
    await Promise.all([loadTrades(),loadTradeHistory(),loadOverview()]);
  }catch(e){$('#trade-status').textContent=e.message;toast(e.message,'error')}
  finally{button.disabled=false}
};

$('#reload-alert-history').onclick=loadAlertHistory;

$('#watchlist-sort-private').onchange=e=>{try{watchlist=collectWatchlist();watchSort=e.target.value;renderWatchlist()}catch(error){e.target.value=watchSort;toast(error.message,'error')}};
