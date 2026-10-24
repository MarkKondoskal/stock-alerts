const $ = s => document.querySelector(s); let password = sessionStorage.getItem('dashboardPassword') || ''; let watchlist = {};
const fmt = (n, digits=2) => Number(n||0).toLocaleString('en-US',{minimumFractionDigits:digits,maximumFractionDigits:digits});
async function api(path, opts={}) { const headers={'Content-Type':'application/json',...(opts.headers||{})}; if(password) headers.Authorization='Bearer '+password; const r=await fetch(path,{...opts,headers}); let d={}; try{d=await r.json()}catch{} if(!r.ok) throw new Error(d.error||`Request failed (${r.status})`); return d; }
function toast(msg,type='success'){const el=$('#toast');el.textContent=msg;el.className='toast '+type;setTimeout(()=>el.classList.add('hidden'),4200)}
function connected(on){$('#login').classList.toggle('hidden',on);document.querySelectorAll('.view').forEach(x=>x.classList.toggle('hidden',!on||x.id!=='overview'));$('#connection').textContent=on?'GitHub connected':'Not connected';$('#connection').className='pill '+(on?'good':'bad');}
function showTab(tab){document.querySelectorAll('.tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));document.querySelectorAll('.view').forEach(v=>v.classList.toggle('hidden',v.id!==tab));}
async function connect(){try{await api('/api/private/accounts');sessionStorage.setItem('dashboardPassword',password);connected(true);await loadOverview();showTab('overview');$('#login-error').textContent='';}catch(e){connected(false);$('#login-error').textContent=e.message;}}
function numInput(value,cls='target-input',placeholder='—'){return `<input class="${cls}" type="number" step="any" value="${value??''}" placeholder="${placeholder}">`}
function targetArray(a){return Array.isArray(a)?a.join(', '):''}
function parseTargets(v){return v.split(',').map(x=>x.trim()).filter(Boolean).map(Number).filter(Number.isFinite)}
function vals(item,metric,dir){const m=item.valuation_targets?.[metric];if(Array.isArray(m)) return dir==='trim'?m:[];return m?.[dir]||[]}
function renderWatchlist(){const rows=Object.entries(watchlist).sort(([a],[b])=>a.localeCompare(b)).map(([ticker,item])=>`<tr data-ticker="${ticker}"><td><span class="ticker">${ticker}</span></td><td><input class="target-input prices" value="${targetArray(item.price_targets)}" placeholder="e.g. 45, 50" title="Comma-separated downside price targets"></td><td><input class="target-input fxpe-trim" value="${targetArray(vals(item,'FxPE','trim'))}" placeholder="e.g. 35"></td><td><input class="target-input fxpe-buy" value="${targetArray(vals(item,'FxPE','buy'))}" placeholder="e.g. 25"></td><td><input class="target-input pe-trim" value="${targetArray(vals(item,'PE','trim'))}" placeholder="—"></td><td><input class="target-input pe-buy" value="${targetArray(vals(item,'PE','buy'))}" placeholder="—"></td><td><input class="target-input ps-trim" value="${targetArray(vals(item,'P/S','trim'))}" placeholder="—"></td><td><input class="target-input ps-buy" value="${targetArray(vals(item,'P/S','buy'))}" placeholder="—"></td><td><button class="remove-row" title="Remove ticker">×</button></td></tr>`).join('');$('#watchlist-rows').innerHTML=rows||'<tr><td colspan="9" class="muted">No watchlist tickers found.</td></tr>';document.querySelectorAll('.remove-row').forEach(b=>b.onclick=()=>{const tr=b.closest('tr');delete watchlist[tr.dataset.ticker];tr.remove()})}
function collectWatchlist(){const result={};document.querySelectorAll('#watchlist-rows tr[data-ticker]').forEach(tr=>{const ticker=tr.dataset.ticker.trim().toUpperCase();if(!ticker)return;const get=sel=>parseTargets(tr.querySelector(sel).value);const price_targets=get('.prices');const valuation_targets={};for(const [metric,trimSel,buySel] of [['FxPE','.fxpe-trim','.fxpe-buy'],['PE','.pe-trim','.pe-buy'],['P/S','.ps-trim','.ps-buy']]){const trim=get(trimSel),buy=get(buySel);if(trim.length||buy.length)valuation_targets[metric]={trim,buy};}result[ticker]={price_targets,valuation_targets}});return result}
async function loadWatchlist(){watchlist=await api('/api/watchlist');renderWatchlist();$('#watchlist-status').textContent=`Loaded ${Object.keys(watchlist).length} tickers from GitHub.`}
async function saveWatchlist(){try{const data=collectWatchlist();const d=await api('/api/watchlist',{method:'PUT',body:JSON.stringify(data)});watchlist=data;toast('Watchlist committed to GitHub.');$('#watchlist-status').textContent='Saved to GitHub'+(d.commit?' · commit created':'')+'.';}catch(e){toast(e.message,'error')}}
const esc = text => String(text??'').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function loadOverview(){
  // The private dashboard and /public use identical source account records.
  // Older UI versions loaded portfolio/marks_portfolio.json instead.
  return window.loadPrivateHoldings();
}
async function loadWorkflows(){const runs=await api('/api/workflows');$('#workflow-list').innerHTML=runs.map(x=>{const status=x.status==='completed'?(x.conclusion||'completed'):x.status;const cls=['success','neutralized'].includes(status)?'good':(['failure','cancelled','timed_out'].includes(status)?'bad':'');return `<div class="workflow"><div><b>${x.name||x.path||'Workflow'}</b><small>${new Date(x.created_at).toLocaleString()} · ${x.event||'run'} · <a href="${x.html_url}" target="_blank" rel="noopener" style="color:#a5b4fc">View run ↗</a></small></div><span class="pill ${cls}">${status}</span></div>`}).join('')||'<p class="muted">No workflow runs returned.</p>'}
$('#login-form').onsubmit=async e=>{e.preventDefault();password=$('#password').value;await connect()};$('#sync').onclick=async()=>{if(!password)return toast('Connect first.','error');try{await Promise.all([loadOverview(),loadWatchlist(),loadWorkflows()]);toast('Synced current repository state.')}catch(e){toast(e.message,'error')}};document.querySelectorAll('.tab').forEach(b=>b.onclick=async()=>{if(!password)return;showTab(b.dataset.tab);try{if(b.dataset.tab==='watchlist')await loadWatchlist();if(b.dataset.tab==='workflows')await loadWorkflows();if(b.dataset.tab==='trades')await Promise.all([loadTrades(),loadTradeHistory()]);if(b.dataset.tab==='sentiment')await window.StockSentiment?.load('private')}catch(e){toast(e.message,'error')}});$('#reload-overview').onclick=()=>loadOverview().catch(e=>toast(e.message,'error'));$('#reload-workflows').onclick=()=>loadWorkflows().catch(e=>toast(e.message,'error'));$('#save-watchlist').onclick=saveWatchlist;$('#add-ticker').onclick=()=>{const t=prompt('Ticker symbol (e.g. MA):');if(!t)return;const ticker=t.trim().toUpperCase();if(!/^[A-Z0-9.^_-]{1,20}$/.test(ticker))return toast('Ticker contains unsupported characters.','error');if(watchlist[ticker])return toast('Ticker already exists.','error');watchlist[ticker]={price_targets:[],valuation_targets:{}};renderWatchlist()};$('#dispatch').onclick=async()=>{const workflow=$('#workflow-select').value;if(workflow==='watchlist_manager.yml'){toast('For now, edit targets in Watchlist & Alerts. The manager workflow requires action/ticker/target inputs, which are not exposed in this simple dispatch button.','error');return}try{const d=await api('/api/workflows/dispatch',{method:'POST',body:JSON.stringify({workflow})});toast(d.message);setTimeout(()=>loadWorkflows().catch(()=>{}),2500)}catch(e){toast(e.message,'error')}};$('#discord-test').onclick=async()=>{try{const d=await api('/api/discord/test',{method:'POST',body:'{}'});toast(d.message)}catch(e){toast(e.message,'error')}};$('#logout').onclick=()=>{password='';sessionStorage.removeItem('dashboardPassword');$('#password').value='';connected(false);toast('Disconnected this browser.')};
if(password){$('#password').value=password;connect() }else connected(false);

let accountSnapshots={};
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
  const value=quantity>0&&price>0&&Number.isFinite(quantity*price)?
    new Intl.NumberFormat('en-US',{style:'currency',currency:ccy}).format(quantity*price):'—';
  const held=accountSnapshots[account]?.positions?.find(x=>x.ticker===ticker)?.quantity||0;
  const after=Number.isFinite(quantity)?held+(action==='BUY'?quantity:-quantity):held;
  $('#trade-preview').textContent=`${action} ${ticker||'—'} · ${value} ${value==='—'?'':`· Shares before ${fmt(held,4)} → after ${fmt(after,4)}`} · ${account==='us'?'Merrill':'Nordnet'}`;
}
async function loadTradeHistory(){
  const d=await api('/api/private/trades');
  $('#trade-history-rows').innerHTML=(d.transactions||[]).map(t=>`<tr><td>${esc(t.date)}</td><td>${t.account==='us'?'Merrill':'Nordnet'}</td><td>${esc(t.action)}</td><td class="ticker">${esc(t.ticker)}</td><td>${fmt(t.quantity,4)}</td><td>${esc(t.currency)} ${fmt(t.price)}</td></tr>`).join('')||'<tr><td colspan="6">No manual trades recorded yet. Historical broker imports remain in the underlying private ledgers.</td></tr>';
  $('#trade-history-note').textContent=`${d.count||0} manually recorded transactions in private ledger · showing latest 30`;
}
$('#trade-account').onchange=()=>loadTrades().catch(e=>toast(e.message,'error'));
$('#trade-ticker').addEventListener('input',chooseTradeCurrency);
for (const name of ['#trade-quantity','#trade-price','#trade-action','#trade-currency']) $(name).addEventListener('input',previewTrade);
$('#trade-refresh').onclick=()=>loadTrades().catch(e=>toast(e.message,'error'));
$('#trade-history-refresh').onclick=()=>loadTradeHistory().catch(e=>toast(e.message,'error'));
const initialTradeDate=new Date();while(initialTradeDate.getDay()===0||initialTradeDate.getDay()===6)initialTradeDate.setDate(initialTradeDate.getDate()-1);
$('#trade-date').value=[initialTradeDate.getFullYear(),String(initialTradeDate.getMonth()+1).padStart(2,'0'),String(initialTradeDate.getDate()).padStart(2,'0')].join('-');
$('#trade-form').onsubmit=async event=>{
  event.preventDefault();
  const payload={account:$('#trade-account').value,action:$('#trade-action').value,ticker:$('#trade-ticker').value.trim().toUpperCase(),date:$('#trade-date').value,quantity:$('#trade-quantity').value,price:$('#trade-price').value,currency:$('#trade-currency').value};
  const amount=Number(payload.quantity)*Number(payload.price);
  if(!payload.ticker||!Number.isFinite(amount)||amount<=0)return toast('Enter valid ticker, shares and price.','error');
  if(!confirm(`Record ${payload.action} ${payload.quantity} ${payload.ticker} at ${payload.price} ${payload.currency} in ${payload.account.toUpperCase()} on ${payload.date}? This commits to your PRIVATE GitHub account. It does not place a brokerage order.`))return;
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
    $('#trade-status').textContent=result.message;
    toast(result.message);
    await Promise.all([loadTrades(),loadTradeHistory(),loadOverview()]);
  }catch(e){$('#trade-status').textContent=e.message;toast(e.message,'error')}
  finally{button.disabled=false}
};
