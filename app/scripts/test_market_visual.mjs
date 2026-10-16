import assert from 'node:assert/strict';
import {mkdtemp, rm} from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {marketVisualsForNodes, MARKET_VISUAL_LIMITS as limits} from '../src/lib/market-visual.js';

const asNodes = caps => caps.map((mv, i) => ({key: String(i), meta: {mv}}));
function assertBounded(visuals) {
  for (const item of visuals) {
    assert.ok(Number.isFinite(item.size) && item.size >= limits.minSize && item.size <= limits.maxSize);
    assert.ok(Number.isFinite(item.brightness) && item.brightness >= limits.minBrightness && item.brightness <= limits.maxBrightness);
  }
}
function assertMonotonic(nodes, label) {
  const visuals = marketVisualsForNodes(nodes);
  assertBounded(visuals);
  const valid = nodes.map((node, i) => ({mv: node.meta.mv, visual: visuals[i]}))
    .filter(item => Number.isFinite(item.mv) && item.mv > 0).sort((a, b) => a.mv - b.mv);
  for (let i = 1; i < valid.length; i++) {
    const a = valid[i - 1], b = valid[i];
    if (a.mv === b.mv) assert.deepEqual(a.visual, b.visual, `${label}: tied caps have tied visuals`);
    else {
      assert.ok(b.visual.size > a.visual.size, `${label}: more total cap means larger star`);
      assert.ok(b.visual.brightness > a.visual.brightness, `${label}: more total cap means brighter star`);
    }
  }
}

const source = asNodes([10, 100, 1000]);
source.forEach(node => { Object.freeze(node.meta); Object.freeze(node) }); Object.freeze(source);
const ordinary = marketVisualsForNodes(source);
assert.ok(Math.abs(ordinary[1].strength - 0.5) < 1e-12, 'equal multiplicative cap changes span equal log intervals');
assert.deepEqual(marketVisualsForNodes([...source].reverse()), [...ordinary].reverse(), 'input order has no effect on a node metric');
assertMonotonic(asNodes([Number.MIN_VALUE, 1e-100, 1, 20, 500, 1e50, Number.MAX_VALUE]), 'extreme caps');
const missing = marketVisualsForNodes(asNodes([null, undefined, 0, -1, NaN, Infinity, '100']));
assertBounded(missing);
assert.ok(missing.every(item => !item.hasMarketCap && item.size > limits.minSize && item.brightness > limits.minBrightness),
  'unavailable metrics use a readable neutral floor');
assert.ok(missing.every(item => item.size === missing[0].size && item.brightness === missing[0].brightness));
assert.deepEqual(marketVisualsForNodes([]), []);
const equal = marketVisualsForNodes(asNodes([100, 100, 100]));
assert.ok(equal.every(item => item.strength === limits.equalStrength), 'single-valued graphs use a neutral midpoint');
assert.deepEqual(marketVisualsForNodes(asNodes([100]))[0], equal[0]);

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const scratch = await mkdtemp(path.join(os.tmpdir(), 'atlas-market-visual-'));
try {
  const stocks = Object.fromEntries(Array.from({length: 160}, (_, i) => {
    const code = `${String(i + 1).padStart(6, '0')}.SZ`;
    return [code, {code, name: `测试股${i + 1}`, mv: (i + 1) ** 2, amount: 160 - i,
      concepts: [], thsIndustries: [], revenue: null}];
  }));
  const codes = Object.keys(stocks);
  const board = (code, name, members, level) => ({code, name, members, level});
  const fixture = {schemaVersion: 2, status: 'complete', tradeDate: '20260918', membershipAsOf: '20260918',
    financialPeriod: '20260630', stocks,
    boards: {
      small: board('885001.TI', '小概念', codes.slice(0, 1)),
      medium: board('885002.TI', '中概念', codes.slice(0, 10)),
      large: board('885003.TI', '大概念', codes),
    }, industries: {
      small: board('881001.TI', '小行业', codes.slice(0, 1), 'industry'),
      medium: board('881002.TI', '中行业', codes.slice(0, 10), 'industry'),
      large: board('881003.TI', '大行业', codes, 'industry'),
    }};
  const outfile = path.join(scratch, 'model.mjs');
  await build({absWorkingDir: root, outfile, bundle: true, format: 'esm', platform: 'node', logLevel: 'silent',
    stdin: {contents: `export * from './src/lib/atlas.js'; export {EVIDENCE} from './src/lib/evidence.js';`, resolveDir: root},
    plugins: [{name: 'market-fixture', setup(builder) {
      builder.onLoad({filter: /evidence-data\.json$/}, () => ({contents: JSON.stringify(fixture), loader: 'json'}));
      builder.onLoad({filter: /(?:industry|supply-chain)-relations\.json$/}, () => ({
        contents: JSON.stringify({boards: [], relations: [], stockNames: {}}), loader: 'json',
      }));
    }}],
  });
  const model = await import(pathToFileURL(outfile).href);
  const concept = model.conceptGraph;
  const industry = model.getBoardGraph('industry', 'overlap');
  const before = model.buildStockGraph('885003.TI');
  assertMonotonic(concept.nodes, 'concept boards');
  assertMonotonic(industry.nodes, 'industry boards');
  assertMonotonic(before.nodes, 'drilled stocks');
  const positions = graph => graph.nodes.map(node => [node.key, node.cid, node.w, node.x, node.y, node.z]);
  const originalLayout = positions(before);
  for (const [i, code] of codes.entries()) {
    model.EVIDENCE.stocks[code].mv = 100000 / (i + 1);
    model.EVIDENCE.stocks[code].amount = i + 1;
  }
  const after = model.buildStockGraph('885003.TI');
  assert.deepEqual(after.CLUSTERS.map(cluster => cluster.name), before.CLUSTERS.map(cluster => cluster.name),
    'live cap updates do not replace the layout reference stars');
  assert.deepEqual(positions(after), originalLayout, 'live quotes do not change membership, order, weights or positions');
  assert.deepEqual(after.anchors, before.anchors, 'live quotes do not move any layout anchor');
  assert.notEqual(after.nodes[0].meta.mv, before.nodes[0].meta.mv, 'displayed metrics still use the new quote');

  const state = {}, el = () => ({textContent: ''});
  const emit = Object.fromEntries(['gate', 'list', 'drawer', 'tools', 'relation', 'theme'].map(key =>
    [key, value => { state[key] = value }]));
  const api = model.createAtlas({graph: before, emit, els: {
    stage: {}, hudSel: el(), sNode: el(), sEdge: el(), sDeg: el(),
  }});
  assert.equal(state.gate, true, 'Node intentionally exercises the no-WebGL fallback');
  api.selectAt(0);
  const selected = state.drawer.i, oldSize = before.nodes[0].size;
  before.nodes[0].meta.mv = 1e8;
  before.nodes[0].meta.amount = 321;
  before.nodes[0].alpha = 0.27;
  before.nodes[0].scale = 1.18;
  api.updateMarketMetrics();
  assert.equal(state.drawer.i, selected, 'refresh preserves selection');
  assert.equal(state.drawer.meta.mv, 1e8, 'refresh updates the selected drawer');
  assert.equal(state.drawer.meta.amount, 321);
  assert.equal(state.drawer.marketVisual.size, before.nodes[0].size);
  assert.equal(state.list.rows.find(row => row.i === selected).on, true, 'refreshed list retains selection');
  assert.ok(before.nodes[0].size > oldSize, 'refresh changes visual size');
  assert.equal(before.nodes[0].alpha, 0.27, 'market brightness does not overwrite interaction opacity');
  assert.equal(before.nodes[0].scale, 1.18, 'market sizing does not overwrite selection scale');
  assert.deepEqual(positions(before), originalLayout, 'refresh does not reset or move the graph');
  api.dispose();
  console.log('PASS: bounded log cap visuals, missing/tied/extreme metrics, board/stock monotonicity, stable layouts and refresh fallback');
} finally {
  assert.equal(path.dirname(path.resolve(scratch)), path.resolve(os.tmpdir()));
  assert.ok(path.basename(scratch).startsWith('atlas-market-visual-'));
  await rm(scratch, {recursive: true, force: true});
}
