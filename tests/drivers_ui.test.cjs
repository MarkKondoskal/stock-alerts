const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
function setup() {
  const note = {};
  const ctx = vm.createContext({document:{getElementById:()=>note}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/static/drivers_ui.js'),'utf8'),ctx);
  return {ui:ctx.PerformanceDrivers,note};
}
test('top contributors and detractors are distinct and bounded',()=>{
  const {ui}=setup();
  const rows=Array.from({length:15},(_,i)=>({ticker:'T'+i,contribution_pp:i-7}));
  const selected=ui.selected(rows);
  assert.equal(selected.length,10);
  assert.equal(new Set(selected.map(row=>row.ticker)).size,10);
  assert.equal(selected[0].contribution_pp,7);
  assert.ok(selected.some(row=>row.contribution_pp===-7));
});
test('empty and changed selections clear stale bars and use percentage points',()=>{
  const {ui,note}=setup();let cleared=0,chart;
  const options={chartId:'chart',noteId:'note',period:'1M',draw:(...args)=>chart=args,clear:()=>cleared++};
  ui.render({drivers:[{ticker:'A',contribution_pp:1.5}],drivers_note:'Verified dates'},options);
  assert.equal(cleared,1);assert.ok(note.textContent.includes('percentage points'));
  assert.equal(chart[2].datasets[0].data[0],1.5);
  ui.render({drivers:[],drivers_note:'Unavailable'},options);
  assert.equal(cleared,2);assert.equal(note.textContent,'Unavailable');
});
