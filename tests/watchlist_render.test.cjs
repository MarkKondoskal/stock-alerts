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
    watchSort: 'ticker',
    watchMarket: {},
    watchlist: {'"><img src=x onerror=alert(1)>': {price_targets: ['" onfocus="alert(1)']}}
  });
  const esc = source.split('\n').find(line => line.startsWith('const esc ='));
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/static/watchlist_ui.js'), 'utf8'), context);
  const functions = ['targetArray', 'vals'].map(name =>
    source.split('\n').find(line => line.startsWith(`function ${name}(`)));
  vm.runInContext([esc, ...functions, source.slice(source.indexOf('function renderWatchlist()'), source.indexOf('function collectWatchlist()')), 'renderWatchlist();'].join('\n'), context);
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('value="" onfocus='));
  assert.ok(html.includes('&lt;img'));
});

test('directional distances, unavailable values and prices are safe', () => {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/static/watchlist_ui.js'), 'utf8'), context);
  const ui = context.WatchlistUI;
  const targets = {price_targets: [80], valuation_targets: {PE: {buy: [20], trim: [40]}}};
  const output = ui.proximity(targets, {price: 100, valuations: {PE: 25}});
  assert.ok(output.includes('20.0% fall needed'));
  assert.ok(output.includes('60.0% rise needed'));
  assert.ok(ui.proximity(targets, {price: 70}).includes('Condition met'));
  assert.ok(ui.proximity({price_targets:[96]}, {price:100}).includes('watch-near'));
  assert.ok(ui.proximity({price_targets:[105]}, {price:100}).includes('watch-met'));
  assert.ok(!ui.proximity({price_targets:[90]}, {price:100}).includes('watch-near'));
  assert.ok(!ui.valuations({}).includes('Latest provider fundamentals'));
  assert.ok(!ui.proximity(targets, {}).includes('NaN'));
  assert.ok(Math.abs(ui.nearest(targets, {price: 100}) - 0.2) < 1e-10);
  assert.equal(ui.nearest(targets, {}), Infinity);
  assert.ok(!ui.price({price: 100, currency: '<img src=x>'}).includes('<img'));
});
