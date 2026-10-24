"use strict";

// Private-only display. All numerical values come from authenticated API routes;
// /api/public/analytics/snapshot intentionally never returns share counts or values.
const privateHoldingsState = {
    account: 'combined', currency: 'USD', etfs: 'excluded',
    period: 'YTD', gainersPeriod: '1M', version: 0,
};
const privateCharts = Object.create(null);
let privatePerformanceRequest = 0;
let privateGainersRequest = 0;
const privatePalette = ['#2dd4bf','#a78bfa','#60a5fa','#fbbf24','#fb7185','#34d399','#fb923c','#e879f9','#818cf8','#bef264','#38bdf8','#f472b6'];
const privateLabel = { combined: 'Combined', us: 'US · Merrill', dk: 'DK · Nordnet' };
const privateNum = (n, precision=2) => n === null || n === undefined || !Number.isFinite(Number(n))
    ? '—' : Number(n).toLocaleString('en-US',{minimumFractionDigits:precision,maximumFractionDigits:precision});
function privateMoney(n, decimals=2) {
    if(n === null || n === undefined || !Number.isFinite(Number(n))) return '—';
    const neg = Number(n) < 0 ? '-' : '';
    const sign = privateHoldingsState.currency === 'USD' ? '$' : '';
    const suffix = privateHoldingsState.currency === 'DKK' ? ' kr' : '';
    return neg + sign + privateNum(Math.abs(Number(n)),decimals) + suffix;
}
function privatePercent(n) {return n === null || n === undefined || !Number.isFinite(Number(n)) ? '—' : (Number(n)>0?'+':'')+privateNum(n)+'%';}
function privateSignedMoney(n){return n === null || n === undefined ? '—' : (Number(n)>0?'+':'')+privateMoney(n);}
function privateEscape(v) {return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function privateColor(node,n) {node.classList.toggle('private-positive',Number(n)>0);node.classList.toggle('private-negative',Number(n)<0);}
function privateSet(id,text){const element=document.getElementById(id);if(element)element.textContent=text;}
function privateQuery(period){const s=privateHoldingsState;return `?account=${encodeURIComponent(s.account)}&currency=${s.currency}&etfs=${s.etfs}&period=${period}`;}
function privateCheckChart(){if(typeof Chart==='undefined') throw Error('Chart library unavailable. Check your connection and reload.');}
function privateChart(id,type,data,options={}){
    privateCheckChart();
    if(privateCharts[id]) privateCharts[id].destroy();
    privateCharts[id]=new Chart(document.getElementById(id),{type,data,options:{responsive:true,maintainAspectRatio:false,
        color:'#aaa',animation:{duration:120},...options}});
}
function privateEmptyChart(id){if(privateCharts[id]){privateCharts[id].destroy();delete privateCharts[id];}}
function privateSelectButtons(selector,value){document.querySelectorAll(selector).forEach(b=>{const choice=b.dataset.privateAccount??b.dataset.privateCurrency??b.dataset.privateEtfs;const active=choice===value;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});}
function privateBuildPeriods(container,choices,key,callback){
    const el=document.getElementById(container);el.replaceChildren();
    choices.forEach(p=>{const b=document.createElement('button');b.type='button';b.textContent=p==='ALL'?'All':p;
        b.classList.toggle('active',p===privateHoldingsState[key]); b.setAttribute('aria-pressed',String(p===privateHoldingsState[key]));
        b.addEventListener('click',()=>{privateHoldingsState[key]=p;privateBuildPeriods(container,choices,key,callback);callback();});el.append(b);});
}
function privateDoughnut(id,names,values,labels){
    if(!names.length || values.every(v=>!v)){privateEmptyChart(id);return;}
    privateChart(id,'doughnut',{labels:names,datasets:[{data:values,backgroundColor:names.map((_,i)=>privatePalette[i%privatePalette.length]),borderColor:'#111',borderWidth:2}]},
        {cutout:'67%',plugins:{legend:{position:'right',labels:{color:'#bbb',boxWidth:10,font:{size:10}}},
        tooltip:{callbacks:{label:ctx=>`${ctx.label}: ${privateMoney(labels[ctx.dataIndex])} · ${privateNum(ctx.parsed/values.reduce((a,b)=>a+b,0)*100)}%`}}}});
}
function privateRenderSnapshot(s){
    privateSet('private-market-value',privateMoney(s.market_value));
    privateSet('private-cost-basis',privateMoney(s.cost_basis));
    privateSet('private-unrealized',privateSignedMoney(s.unrealized_pl));
    privateColor(document.getElementById('private-unrealized'),s.unrealized_pl);
    privateSet('private-unrealized-pct',`${privatePercent(s.unrealized_pl_pct)} on open positions · not realized`);
    privateSet('private-position-count',String(s.position_count));
    privateSet('private-ticker-count',`${s.ticker_count} distinct tickers across selected accounts`);
    const dates=Object.entries(s.positions_as_of||{}).map(([account,day])=>`${privateLabel[account]} ${day||'unknown'}`).join(' · ');
    privateSet('private-freshness',`${dates||'Account dates unavailable'} · Latest available closes · ${s.currency} · ETFs ${s.include_etfs?'included':'excluded'}`);
    const rows=(s.holdings||[]).map(h=>{
        const alloc=Number(h.allocation_pct||0);
        return `<tr class="${h.market_value===null?'private-price-missing':''}">
          <td class="ticker">${privateEscape(h.ticker)}</td><td>${privateEscape(h.sector)}</td><td>${(h.accounts||[]).map(a=>privateEscape(privateLabel[a]||a)).join(' / ')}</td>
          <td class="num">${privateNum(h.quantity,4)}</td><td class="num">${privateMoney(h.average_cost_per_share,2)}</td>
          <td class="num">${privateMoney(h.current_price)}</td><td class="num"><b>${privateMoney(h.market_value)}</b></td>
          <td class="num">${privateMoney(h.cost_basis)}</td><td class="num ${h.unrealized_pl>0?'private-positive':h.unrealized_pl<0?'private-negative':''}">${privateSignedMoney(h.unrealized_pl)}</td>
          <td class="num ${h.return_since_cost_pct>0?'private-positive':h.return_since_cost_pct<0?'private-negative':''}">${privatePercent(h.return_since_cost_pct)}</td>
          <td class="num"><div class="private-allocation-wrap"><span>${h.allocation_pct==null?'—':`${privateNum(h.allocation_pct)}%`}</span><span class="private-allocation-track"><span class="private-allocation-fill" style="display:block;width:${Math.max(0,Math.min(100,alloc))}%"></span></span></div></td>
        </tr>`;
    });
    document.getElementById('private-holdings-rows').innerHTML=rows.join('')||'<tr><td colspan="11">No holdings in the selected view.</td></tr>';
    const missing=s.missing_tickers?.length?` Missing latest prices: ${s.missing_tickers.join(', ')}; the total excludes these positions.`:'';
    const costs=s.incomplete_cost_tickers?.length?` Missing cost basis: ${s.incomplete_cost_tickers.join(', ')}.`:'';
    privateSet('private-valuation-note',`${s.valuation_basis}. ${s.cost_basis_note}${missing}${costs} No bank cash balances included.`);
    const active=(s.holdings||[]).filter(h=>h.market_value!==null);
    privateDoughnut('private-holdings-chart',active.map(h=>h.ticker),active.map(h=>h.market_value),active.map(h=>h.market_value));
    privateDoughnut('private-sector-chart',(s.sectors||[]).map(h=>h.sector),(s.sectors||[]).map(h=>h.market_value),(s.sectors||[]).map(h=>h.market_value));
}
async function privateLoadSnapshot(version){
    try{
        const s=await api('/api/private/holdings/snapshot'+privateQuery(privateHoldingsState.period));
        if(version!==privateHoldingsState.version)return;
        privateRenderSnapshot(s);
    }catch(error){if(version!==privateHoldingsState.version)return;
        privateSet('private-freshness','Private holdings unavailable: '+error.message);
        document.getElementById('private-holdings-rows').innerHTML='<tr><td colspan="11">Could not fetch current account positions or prices. Try Refresh holdings.</td></tr>';
        for(const id of ['private-market-value','private-cost-basis','private-unrealized','private-position-count','private-ticker-count'])privateSet(id,'—');
        for(const id of ['private-holdings-chart','private-sector-chart'])privateEmptyChart(id);
    }
}
async function privateLoadPerformance(version){
    const requestId = ++privatePerformanceRequest;
    const {period}=privateHoldingsState;
    privateSet('private-performance-note','Loading historical performance…');
    try{
        const result=await api('/api/private/holdings/analytics'+privateQuery(period));
        if(version!==privateHoldingsState.version||period!==privateHoldingsState.period||requestId!==privatePerformanceRequest)return;
        const spy=new Map((result.spy||[]).map(p=>[p.date,Number(p.value)]));
        const aligned=(result.performance||[]).filter(p=>spy.has(p.date));
        if(aligned.length<2){privateEmptyChart('private-performance-chart');
            privateSet('private-performance-return','—');privateSet('private-spy-difference','—');
            privateSet('private-performance-baseline','Not enough verified history for this period');
            privateSet('private-performance-note',result.performance_note||'Historical reconstruction is unavailable for this selection.');return;}
        const last=aligned[aligned.length-1],value=Number(last.value),benchmark=spy.get(last.date);
        privateSet('private-performance-return',privatePercent(value));privateColor(document.getElementById('private-performance-return'),value);
        privateSet('private-spy-difference',(value-benchmark>=0?'+':'')+privateNum(value-benchmark)+' pp');
        privateColor(document.getElementById('private-spy-difference'),value-benchmark);
        privateSet('private-performance-baseline',`Both lines start at 0% on ${aligned[0].date} · Through ${last.date}`);
        privateChart('private-performance-chart','line',{
            labels:aligned.map(p=>p.date),datasets:[
                {label:'Portfolio',data:aligned.map(p=>p.value),borderColor:'#2dd4bf',backgroundColor:'rgba(45,212,191,.10)',fill:true,borderWidth:2.5,pointRadius:0,tension:.16},
                {label:'SPY · matched dates',data:aligned.map(p=>spy.get(p.date)),borderColor:'#bb92ef',borderWidth:2,pointRadius:0,tension:.16},
            ]},{interaction:{intersect:false,mode:'index'},plugins:{legend:{display:true,labels:{color:'#bbb'}},
                tooltip:{callbacks:{label:c=>`${c.dataset.label}: ${privatePercent(c.parsed.y)}`}}},
                scales:{x:{grid:{display:false},ticks:{color:'#92929f',maxTicksLimit:6,maxRotation:0}},
                    y:{position:'right',grid:{color:'#ffffff16'},ticks:{color:'#92929f',callback:n=>n+'%'}}}});
        privateSet('private-performance-note',`Matched comparison: ${aligned[0].date} to ${last.date}. ${result.performance_note||''}`);
    }catch(error){if(version!==privateHoldingsState.version||requestId!==privatePerformanceRequest)return;
        privateEmptyChart('private-performance-chart');privateSet('private-performance-return','—');privateSet('private-spy-difference','—');
        privateSet('private-performance-note','Historical analytics unavailable: '+error.message);}
}
async function privateLoadGainers(version){
    const requestId = ++privateGainersRequest;
    const period=privateHoldingsState.gainersPeriod;
    privateSet('private-gainers-note','Loading price returns…');
    try{
        const data=await api('/api/private/holdings/analytics'+privateQuery(period));
        if(version!==privateHoldingsState.version||period!==privateHoldingsState.gainersPeriod||requestId!==privateGainersRequest)return;
        const all=[...(data.gainers||[])].sort((a,b)=>b.return_pct-a.return_pct);
        if(!all.length){privateEmptyChart('private-gainers-chart');privateSet('private-gainers-note','No price history available for this period.');return;}
        const top=all.slice(0,5),bottom=all.slice(-5).filter(h=>!top.some(t=>t.ticker===h.ticker));
        const shown=[...top,...bottom];
        privateChart('private-gainers-chart','bar',{
            labels:shown.map(h=>h.ticker),datasets:[{label:'Price return',data:shown.map(h=>h.return_pct),
                backgroundColor:shown.map(h=>h.return_pct>=0?'#34d399':'#fb7185'),borderRadius:4}]},
        {indexAxis:'y',plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>privatePercent(c.parsed.x)}}},
            scales:{x:{grid:{color:'#ffffff14'},ticks:{color:'#aaa',callback:x=>x+'%'}},y:{grid:{display:false},ticks:{color:'#aaa'}}}});
        privateSet('private-gainers-note',`Individual stock price returns (${period}); independent of the portfolio chart period.`);
    }catch(error){if(version!==privateHoldingsState.version||requestId!==privateGainersRequest)return;
        privateEmptyChart('private-gainers-chart');privateSet('private-gainers-note','Gainers unavailable: '+error.message);}
}
window.loadPrivateHoldings=async function(){
    const version=++privateHoldingsState.version;
    // Latest account positions must NOT depend on the selected chart period.
    await Promise.allSettled([privateLoadSnapshot(version),privateLoadPerformance(version),privateLoadGainers(version)]);
};
function privateUpdateAll(){window.loadPrivateHoldings().catch(e=>toast(e.message,'error'));}
for(const b of document.querySelectorAll('[data-private-account]'))b.addEventListener('click',()=>{
    privateHoldingsState.account=b.dataset.privateAccount;privateSelectButtons('[data-private-account]',privateHoldingsState.account);privateUpdateAll();
});
for(const b of document.querySelectorAll('[data-private-currency]'))b.addEventListener('click',()=>{
    privateHoldingsState.currency=b.dataset.privateCurrency;privateSelectButtons('[data-private-currency]',privateHoldingsState.currency);privateUpdateAll();
});
for(const b of document.querySelectorAll('[data-private-etfs]'))b.addEventListener('click',()=>{
    privateHoldingsState.etfs=b.dataset.privateEtfs;privateSelectButtons('[data-private-etfs]',privateHoldingsState.etfs);privateUpdateAll();
});
privateBuildPeriods('private-performance-periods',['1D','1W','1M','3M','6M','YTD','1Y','3Y','ALL'],'period',()=>{
    const version=privateHoldingsState.version;
    // Retain existing snapshot; only update its associated performance curve.
    privateLoadPerformance(version).catch(e=>toast(e.message,'error'));
});
privateBuildPeriods('private-gainers-periods',['1D','1W','1M','3M','6M','YTD','1Y','3Y','ALL'],'gainersPeriod',()=>{
    const version=privateHoldingsState.version;
    privateLoadGainers(version).catch(e=>toast(e.message,'error'));
});
