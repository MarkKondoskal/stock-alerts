const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

test('untrusted tickers and target attributes are escaped', () => {
  const source = fs.readFileSync(path.join(__dirname, '../web/static/app.js'), 'utf8');
  let html = '';
  const context = vm.createContext({
    document: {querySelectorAll: () => []},
    $: () => ({set innerHTML(value) {html = value;}}),
    watchlist: {'"><img src=x onerror=alert(1)>': {price_targets: ['" onfocus="alert(1)']}}
  });
  const esc = source.split('\n').find(line => line.startsWith('const esc ='));
  const functions = ['targetArray', 'vals', 'renderWatchlist'].map(name =>
    source.split('\n').find(line => line.startsWith(`function ${name}(`)));
  vm.runInContext([esc, ...functions, 'renderWatchlist();'].join('\n'), context);
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('value="" onfocus='));
  assert.ok(html.includes('&lt;img'));
});
