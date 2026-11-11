const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
test('research cards escape article text and never render private notes',()=>{
  const context=vm.createContext({window:{},URL,document:{getElementById:()=>null}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../web/static/research.js'),'utf8'),context);
  const ui=context.window.Research;
  const card=ui.cards([{id:'a',kind:'own',title:'<img src=x onerror=alert(1)>',url:'javascript:alert(1)',author:'Mark',summary:'<script>x</script>',private_notes:'PRIVATE SECRET',tickers:[]}],'public');
  assert.ok(!card.includes('<img'));assert.ok(!card.includes('<script>'));assert.ok(!card.includes('javascript:'));
  assert.ok(!card.includes('PRIVATE SECRET'));assert.ok(!card.includes('data-edit-research'));
  assert.equal(ui.safeUrl('https://markkondoskal.substack.com/p/first-substack'),'https://markkondoskal.substack.com/p/first-substack');
});
