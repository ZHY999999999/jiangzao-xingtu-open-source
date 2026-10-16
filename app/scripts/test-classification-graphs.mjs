import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'esbuild';
import { ArrowHelper, BufferGeometry, BufferAttribute, PerspectiveCamera, Vector3 } from 'three';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const scratch = await mkdtemp(path.join(os.tmpdir(), 'atlas-classification-'));

async function loadModel(name, fixture, industryFixture = {boards: [], relations: [], stockNames: {}}, supplyFixture = {relations: []}) {
  const outfile = path.join(scratch, `${name}.mjs`);
  await build({
    absWorkingDir: root, outfile, bundle: true, format: 'esm', platform: 'node', logLevel: 'silent',
    stdin: {contents: `export * from './src/lib/atlas.js'; export * from './src/lib/evidence.js';
      export {getTheme, setTheme} from './src/lib/theme.ts';`, resolveDir: root, loader: 'js'},
    plugins: fixture ? [{name: 'isolated-classification-fixture', setup(builder) {
      builder.onLoad({filter: /evidence-data\.json$/}, () => ({contents: JSON.stringify(fixture), loader: 'json'}));
      builder.onResolve({filter: /(?:industry|supply-chain)-relations\.json$/}, args => ({path: args.path, namespace: 'fixture-ledger'}));
      builder.onLoad({filter: /.*/, namespace: 'fixture-ledger'}, args => ({
        contents: JSON.stringify(args.path.includes('supply-chain') ? supplyFixture : industryFixture), loader: 'json',
      }));
      builder.onLoad({filter: /stardata\.js$/}, () => ({contents: `export const DATA = ${JSON.stringify({
        meta: {tradeDate: '20260918', seed: 4824, anchors: []}, nodes: [], clusters: [],
      })}`, loader: 'js'}));
    }}] : [],
  });
  return import(pathToFileURL(outfile).href);
}

function graphIntegrity(model, kind) {
  const graph = model.getBoardGraph(kind, 'overlap'), records = model.getBoardRecords(kind);
  assert.equal(graph.mode, kind);
  assert.equal(graph.boardKind, kind);
  assert.equal(graph.nodes.length, records.length, `${kind}: every catalog record becomes a node`);
  assert.deepEqual(new Set(graph.nodes.map(node => node.meta.code)), new Set(records.map(board => board.code)));
  assert.strictEqual(model.getBoardGraph(kind, 'overlap'), graph, 'board graphs are cached');
  for (const node of graph.nodes) {
    assert.equal(node.meta.level, kind);
    assert.ok(node.cluster.name.startsWith('布局分区 '));
    assert.ok([node.x, node.y, node.z].every(value => Number.isFinite(Math.fround(value))),
      `${kind}: coordinates must fit the Float32 GPU buffers, not just JavaScript numbers`);
  }
  for (const edge of graph.edges) {
    assert.equal(edge.kind, 'rel');
    assert.equal(edge.evidence.selectionRule, 'shared-members');
    assert.equal(edge.evidence.rankingRule, 'jaccard-then-shared-count');
    const relation = model.getBoardRelation(edge.s.meta.code, edge.t.meta.code, kind);
    assert.ok(relation.sharedCount > 0, 'no layout-only or invented relationship');
    assert.equal(relation.sharedCount, edge.evidence.sharedCount);
    assert.equal(relation.overlapPct, edge.evidence.overlapPct);
  }
  return graph;
}

function directedIntegrity(model, graph, type) {
  assert.ok(graph.directoryNodes.every(node => node.meta.boardKind === graph.boardKind && !node.meta.context));
  assert.deepEqual(new Set(graph.directoryNodes.map(node => node.meta.code)),
    new Set(model.getBoardRecords(graph.boardKind, graph.system).map(board => board.code)));
  for (const edge of graph.edges) {
    assert.equal(edge.directed, true);
    assert.equal(edge.evidence.relationType, type);
    assert.ok(edge.evidence.sourceRefs.length);
    assert.equal(edge.evidence.verificationStatus, 'verified');
    assert.ok(edge.s.key.startsWith(`${edge.s.meta.system}:${edge.s.meta.boardKind}:`));
    const relation = model.edgeRelation(graph, edge);
    assert.equal(relation.sharedCount, null);
    assert.equal(relation.type, type);
    assert.equal(relation.from.code, edge.s.meta.code);
    assert.equal(relation.to.code, edge.t.meta.code);
    assert.equal(relation.mappingBasis, edge.evidence.mappingBasis, 'product-to-industry mapping limitations are preserved');
    assert.equal(relation.boundary, edge.evidence.boundary || null, 'relation-specific boundaries are preserved');
    const placement = model.edgeArrowPlacement(edge);
    assert.ok(placement && [...placement.origin.toArray(), ...placement.direction.toArray(), placement.length].every(Number.isFinite));
    assert.ok(placement.direction.dot(new Vector3(edge.t.x - edge.s.x, edge.t.y - edge.s.y, edge.t.z - edge.s.z)) > 0,
      'the actual arrow orientation points to the declared target');
    const arrow = new ArrowHelper(placement.direction, placement.origin, placement.length, '#ffffff', placement.headLength, placement.headWidth);
    arrow.updateMatrixWorld(true);
    const tip = arrow.cone.localToWorld(new Vector3(0, 0, 0));
    const expected = placement.origin.clone().addScaledVector(placement.direction, placement.length);
    assert.ok(tip.distanceTo(expected) < 1e-8, 'THREE arrow tip is placed at the directed end of the line');
    arrow.dispose();
  }
  renderCoordinates(graph, `${graph.system}/${graph.boardKind}/${type}`);
}

function renderCoordinates(graph, label) {
  const positions = new Float32Array(graph.nodes.flatMap(node => [node.x, node.y, node.z]));
  assert.ok(positions.every(Number.isFinite), `${label}: every GPU node coordinate is finite`);
  const edgePositions = new Float32Array(graph.edges.flatMap(edge =>
    [edge.s.x, edge.s.y, edge.s.z, edge.t.x, edge.t.y, edge.t.z]));
  assert.ok(edgePositions.every(Number.isFinite), `${label}: every GPU edge coordinate is finite`);
  for (const [part, array] of [['nodes', positions], ['edges', edgePositions], ['no-edges', new Float32Array(0)]]) {
    const geometry = new BufferGeometry();
    geometry.setAttribute('position', new BufferAttribute(array, 3));
    geometry.computeBoundingSphere();
    const sphere = geometry.boundingSphere;
    assert.ok(sphere && [sphere.radius, ...sphere.center.toArray()].every(Number.isFinite),
      `${label}/${part}: THREE computes a finite bounding sphere`);
    geometry.dispose();
  }
  assert.ok(graph.fitDist() < 1400, `${label}: the whole graph fits within the camera far plane`);
  viewportProjection(graph, label);
  // Layout changes and search/selection reheats must not magnify a hub instability.
  for (const view of ['shell', 'tier', 'atlas']) {
    graph.setView(view); graph.reheat(1);
    for (let i = 0; i < 600; i++) graph.layout();
    assert.ok(graph.nodes.every(node => [node.x, node.y, node.z].every(value => Number.isFinite(Math.fround(value)))),
      `${label}/${view}: repeated layout must remain GPU-representable`);
    assert.ok(graph.fitDist() < 1400, `${label}/${view}: camera framing remains usable`);
    viewportProjection(graph, `${label}/${view}`);
  }
}

function viewportProjection(graph, label) {
  const point = new Vector3();
  for (const [width, height] of [[1400, 800], [889, 1032], [390, 780]]) {
    const distance = graph.fitDist(width / height);
    const camera = new PerspectiveCamera(46, width / height, 1, 1400);
    for (const phi of [0.3, 1.15, 2.8]) for (const theta of [0, 0.7, 2.1, 4.5]) {
      camera.position.set(distance * Math.sin(phi) * Math.cos(theta), distance * Math.cos(phi),
        distance * Math.sin(phi) * Math.sin(theta));
      camera.lookAt(0, 0, 0); camera.updateMatrixWorld();
      for (const node of graph.nodes) {
        point.set(node.x, node.y, node.z).project(camera);
        assert.ok(Math.abs(point.x) <= 1 && Math.abs(point.y) <= 1 && Math.abs(point.z) <= 1,
          `${label}/${width}x${height}: ${node.name} stays in frame while rotating at default zoom`);
      }
    }
  }
}

function resizePreservesZoom(model, graph) {
  const wideFit = graph.fitDist(1400 / 800), narrowFit = graph.fitDist(889 / 1032);
  const cameraState = {dist: wideFit * 0.6, tDist: wideFit * 0.5,
    theta: 2.1, tTheta: 2.2, phi: 1.15, tPhi: 1.2, tx: 12, ty: 8, tz: -4, cx: 10, cy: 7, cz: -3};
  const original = {...cameraState};
  model.resizeCameraFit(cameraState, wideFit, narrowFit);
  assert.ok(Math.abs(cameraState.tDist / narrowFit - 0.5) < 1e-12, 'resize preserves intentional 200% zoom');
  assert.ok(Math.abs(cameraState.dist / narrowFit - 0.6) < 1e-12, 'resize preserves the ongoing zoom animation');
  for (const key of ['theta', 'tTheta', 'phi', 'tPhi', 'tx', 'ty', 'tz', 'cx', 'cy', 'cz']) {
    assert.equal(cameraState[key], original[key], `resize preserves selected center and direction (${key})`);
  }
  model.resizeCameraFit(cameraState, narrowFit, wideFit);
  assert.ok(Math.abs(cameraState.tDist - original.tDist) < 1e-10, 'resizing back does not accumulate zoom changes');
}

function fallbackHarness(model, graph) {
  const state = {}, element = () => ({textContent: ''});
  const emit = Object.fromEntries(['gate', 'list', 'drawer', 'tools', 'relation', 'theme'].map(key =>
    [key, value => { state[key] = value }]));
  const api = model.createAtlas({graph, emit, els: {
    stage: {}, hudSel: element(), sNode: element(), sEdge: element(), sDeg: element(),
  }});
  assert.equal(state.gate, true, 'Node has no WebGL and must enter the working fallback');
  return {api, state};
}

try {
  const stocks = Object.fromEntries(Array.from({length: 165}, (_, i) => {
    const code = `${String(i + 1).padStart(6, '0')}.SZ`;
    return [code, {code, name: `测试股${i + 1}`, amount: 165 - i, mv: 165 - i, revenue: 165 - i,
      pct: null, turnover: null, industry: '基础资料行业', reportPeriod: '20260630',
      concepts: i < 3 ? ['概念01', '概念02', '概念03'] : [],
      thsIndustries: [{code: '881001.TI', name: '真实行业甲', level: 'industry'}]}];
  }));
  const codes = Object.keys(stocks), boards = {};
  for (let i = 1; i <= 45; i++) {
    const name = `概念${String(i).padStart(2, '0')}`;
    boards[name] = {code: `885${String(i).padStart(3, '0')}.TI`, name, members: codes.slice(0, 3)};
  }
  boards['空概念'] = {code: '885099.TI', name: '空概念', members: []};
  boards['融资融券'] = {code: '885338.TI', name: '融资融券', members: codes};
  const native = (code, name, level, members) => ({code, name, level, members,
    source: '同花顺 · Tushare Pro ths_index/ths_member', membershipAsOf: '20260922'});
  const fixture = {schemaVersion: 2, status: 'complete', tradeDate: '20260918', membershipAsOf: '20260922',
    financialPeriod: '20260630', boards, stocks, industries: {
      '881001.TI': native('881001.TI', '真实行业甲', 'industry', codes),
      '881002.TI': native('881002.TI', '真实行业乙', 'industry', [codes[0], codes[164]]),
      '884001.TI': native('884001.TI', '同名细分', 'subindustry', [codes[0], codes[1]]),
      '884002.TI': native('884002.TI', '同名细分', 'subindustry', [codes[1], codes[2]]),
    }};
  const model = await loadModel('fixture', fixture);
  const concept = graphIntegrity(model, 'concept');
  const industry = graphIntegrity(model, 'industry');
  const subindustry = graphIntegrity(model, 'subindustry');
  assert.ok(concept.CLUSTERS.some(cluster => concept.nodes.filter(node => node.cid === cluster.id).length > 32),
    'a layout group must not impose the former 32-node capacity');
  assert.ok(concept.nodes.some(node => node.name === '空概念' && model.conceptGraph.deg(node) === 0));
  assert.ok(concept.nodes.some(node => node.name === '融资融券'), 'broad attributes remain in the complete catalog');
  assert.ok(concept.layoutReferences.every(board => board.name !== '融资融券'), 'universal sets are not visual reference points');
  assert.equal(concept.deg(concept.nodes.find(node => node.name === '融资融券')), 2,
    'Jaccard makes similar small boards prefer each other over the universal set');
  assert.equal(subindustry.nodes.length, 2, 'identical names at distinct native codes stay distinct');
  assert.equal(model.getBoardEvidence('同名细分', 'subindustry'), null, 'ambiguous names require a native code');
  assert.equal(model.getBoardEvidence('884001.TI', 'industry'), null, 'levels cannot contaminate each other');
  assert.equal(model.getConceptEvidence('881001.TI'), null, 'industries cannot become concepts');
  assert.equal(model.getBoardEvidence('真实行业甲', 'industry').code, '881001.TI');
  assert.deepEqual(model.getBoardCandidates('881001.TI', undefined, 'industry'), codes.slice(0, 5));
  assert.deepEqual(model.getIndustryCandidates('881001.TI', undefined, 'industry'), codes.slice(0, 5));

  const base = model.buildStockGraph('881001.TI', undefined, 'industry');
  assert.equal(base.nodes.some(node => node.meta.code === codes[164]), false);
  const focused = model.buildStockGraph('真实行业甲', codes[164], 'industry');
  assert.equal(focused.mode, 'stock');
  assert.equal(focused.boardKind, 'industry');
  assert.equal(focused.boardCode, '881001.TI');
  assert.equal(focused.conceptName, '真实行业甲');
  assert.equal(focused.totalMembers, 165);
  assert.ok(focused.nodes.some(node => node.meta.code === codes[164]));
  assert.ok(focused.nodes.every(node => node.meta.thsIndustries[0].code === '881001.TI'));
  assert.deepEqual(model.EVIDENCE.stocks[codes[164]].concepts, []);
  assert.equal(model.getStockRelation(codes[3], codes[4]).sharedCount, 0, 'same industry alone is not concept overlap');
  assert.equal(model.buildStockGraph('概念01').boardKind, 'concept', 'legacy two-argument calls stay concepts');

  const {api, state} = fallbackHarness(model, industry);
  api.selectAt(0);
  assert.equal(state.drawer.meta.code, industry.nodes[0].meta.code);
  const relation = api.selectEdge(0);
  assert.equal(relation.kind, 'industry');
  assert.equal(relation.sharedCount, 2);
  assert.match(relation.source, /ths_index\/ths_member/);
  assert.equal(relation.asOf, '20260922');
  assert.equal(relation.hierarchyVerified, false);
  assert.ok(!relation.reason.includes('每个概念'));
  assert.match(relation.reason, /Jaccard/);
  model.setTheme('light');
  assert.equal(state.theme, 'light');
  api.setActive(false);
  api.setActive(true);
  api.clearRelation();
  api.setQuery('881002');
  assert.equal(state.list.rows.length, 1);
  assert.equal(state.list.rows[0].name, '真实行业乙');
  api.dispose();

  const updated = await loadModel('updated-trade-date', {...fixture, tradeDate: '20260921', membershipAsOf: '20260923'});
  assert.equal(updated.META.tradeDate, '20260921', 'quote updates must not depend on the retired layout snapshot date');
  assert.equal(updated.META.membershipAsOf, '20260923');
  assert.equal(updated.META.financialPeriod, fixture.financialPeriod);
  assert.notEqual(updated.META.seed, model.META.seed, 'deterministic layout seeds follow the authoritative evidence snapshot');
  for (const kind of ['concept', 'industry', 'subindustry']) {
    const graph = graphIntegrity(updated, kind);
    assert.ok(graph.nodes.every(node => node.meta.tradeDate === '20260921'));
  }

  const swBoard = (code, level, members = []) => ({code, name: `测试申万${code}`, level, members,
    source: '隔离测试分类来源', membershipAsOf: '20260922'});
  const ledgerRow = (id, type, fromKind, fromCode, toKind, toCode, verificationStatus = 'verified') => ({
    id, type, from: {system: 'sw2021', kind: fromKind, code: fromCode},
    to: {system: 'sw2021', kind: toKind, code: toCode}, statement: '仅用于隔离测试的关系',
    asOf: '2026-09-22', verificationStatus,
    sourceRefs: [{url: 'https://example.test/fixture', title: '隔离测试来源', locator: 'fixture', excerpt: '测试记录'}],
  });
  const swFixture = {schemaVersion: 1, system: 'sw2021', asOf: '2026-09-22', boards: [
    swBoard('801000.SI', 'sector', codes), swBoard('802000.SI', 'sector', codes.slice(0, 2)),
    swBoard('801010.SI', 'industry', [...codes, '999998.SZ']), swBoard('802010.SI', 'industry', codes.slice(0, 2)),
    swBoard('801011.SI', 'subindustry', [codes[0], '999998.SZ']), swBoard('802011.SI', 'subindustry', [codes[1]]),
    swBoard('802012.SI', 'subindustry'),
  ], stockNames: {'999998.SZ': '仅分类中有名称的测试股'}, relations: [
    ledgerRow('parent-a', 'classification', 'sector', '801000.SI', 'industry', '801010.SI'),
    ledgerRow('parent-b', 'classification', 'sector', '802000.SI', 'industry', '802010.SI'),
    ledgerRow('child-a', 'classification', 'industry', '801010.SI', 'subindustry', '801011.SI'),
    ledgerRow('child-b', 'classification', 'industry', '802010.SI', 'subindustry', '802011.SI'),
    ledgerRow('child-empty', 'classification', 'industry', '802010.SI', 'subindustry', '802012.SI'),
    ledgerRow('unverified', 'classification', 'industry', '802010.SI', 'industry', '801010.SI', 'candidate'),
  ]};
  const supplyFixture = {relations: [
    ledgerRow('supply-a-b', 'supply-chain', 'industry', '801010.SI', 'industry', '802010.SI'),
    ledgerRow('supply-b-a', 'supply-chain', 'industry', '802010.SI', 'industry', '801010.SI'),
    ledgerRow('supply-a-child', 'supply-chain', 'industry', '801010.SI', 'subindustry', '802011.SI'),
    ledgerRow('supply-candidate', 'supply-chain', 'subindustry', '802011.SI', 'industry', '801010.SI', 'candidate'),
  ]};
  const typed = await loadModel('typed-relations', fixture, swFixture, supplyFixture);
  const swIndustry = typed.getBoardGraph('industry', 'classification', 'sw2021');
  const swSub = typed.getBoardGraph('subindustry', 'classification', 'sw2021');
  assert.equal(swIndustry.nodes.length, 4); assert.equal(swIndustry.edges.length, 2);
  assert.equal(swSub.nodes.length, 7); assert.equal(swSub.edges.length, 5);
  directedIntegrity(typed, swIndustry, 'classification'); directedIntegrity(typed, swSub, 'classification');
  assert.strictEqual(typed.getBoardGraph('industry', 'classification', 'sw2021'), swIndustry);
  const ancestor = swSub.nodes.find(node => node.meta.code === '801000.SI');
  const descendant = swSub.nodes.find(node => node.meta.code === '801011.SI');
  assert.equal(swSub.depth[ancestor.i], 0); assert.equal(swSub.depth[descendant.i], 2);
  assert.equal(swSub.findPath(ancestor.i, descendant.i).length, 3);
  assert.equal(swSub.findPath(descendant.i, ancestor.i), null, 'classification paths cannot reverse the parent direction');
  const supply = typed.getBoardGraph('industry', 'supply-chain', 'sw2021');
  assert.equal(supply.nodes.length, 3); assert.equal(supply.edges.length, 3);
  assert.ok(supply.depth.every(depth => depth === 0), 'supply cycles do not become classification depths');
  directedIntegrity(typed, supply, 'supply-chain');
  const supplyTarget = supply.nodes.find(node => node.meta.code === '802011.SI');
  const supplySource = supply.nodes.find(node => node.meta.code === '801010.SI');
  assert.equal(supplyTarget.meta.context, true);
  assert.equal(supply.findPath(supplyTarget.i, supplySource.i), null, 'no reverse supply path is invented');
  assert.equal(typed.getBoardGraph('concept', 'classification', 'sw2021').system, 'ths', 'concepts always use their original catalog');
  assert.strictEqual(typed.getBoardGraph('sector', 'classification', 'sw2021'), swIndustry, 'sector links open in the containing industry graph');
  const swFocused = typed.buildStockGraph('801011.SI', '999998.SZ', 'subindustry', 'sw2021');
  assert.equal(swFocused.system, 'sw2021');
  assert.ok(swFocused.nodes.some(node => node.meta.code === '999998.SZ' && node.meta.pct === null));
  const typedFallback = fallbackHarness(typed, swSub);
  typedFallback.api.selectAt(descendant.i);
  assert.equal(typedFallback.state.drawer.meta.system, 'sw2021');
  assert.equal(typedFallback.state.drawer.meta.boardKind, 'subindustry');
  assert.equal(typedFallback.api.selectEdge(0).relationType, 'classification');
  typedFallback.api.dispose();
  assert.throws(() => typed.buildGraph({clusters: [{id: 'test', name: 'test', dark: '#fff', light: '#000', anchor: [1, 0, 0]}],
    nodesArr: [['a', 'test', 1, ''], ['b', 'test', 1, '']], edgesArr: [['a', 'b', 'pre'], ['b', 'a', 'pre']]}),
    /分类父子关系出现环/);
  if (process.argv.includes('--fixture-only')) {
    console.log(JSON.stringify({status: 'PASS', scope: 'isolated fixtures including typed hierarchy, directed supply cycles, arrows and fallback'}));
  } else {

  const real = await loadModel('current-data');
  const counts = {};
  for (const kind of ['concept', 'industry', 'subindustry']) {
    const graph = graphIntegrity(real, kind);
    renderCoordinates(graph, kind);
    resizePreservesZoom(real, graph);
    const distribution = graph.CLUSTERS.map(cluster => ({name: cluster.name,
      count: graph.nodes.filter(node => node.cid === cluster.id).length}));
    const maxDegree = Math.max(0, ...graph.nodes.map(graph.deg));
    counts[kind] = {nodes: graph.nodes.length, edges: graph.edges.length, maxDegree, distribution};
    if (kind === 'concept') {
      assert.equal(graph.layoutReferences.length, 7);
      assert.ok(distribution.every(group => group.count > 1), 'each visual reference has a useful surrounding group');
      assert.ok(Math.max(...distribution.map(group => group.count)) < graph.nodes.length / 2,
        'one broad concept must not absorb most of the catalog layout');
      assert.ok(maxDegree < graph.nodes.length / 5,
        'similarity-based edges must not collapse into one universal hub');
    }
  }
  for (const [code, kind] of [['881129.TI', 'industry'], ['884262.TI', 'subindustry'], ['886033.TI', 'concept'], ['885338.TI', 'concept']]) {
    const graph = real.buildStockGraph(code, undefined, kind);
    if (graph) renderCoordinates(graph, `${kind}/${code}`);
  }
  for (const kind of ['industry', 'subindustry']) for (const mode of ['classification', 'supply-chain']) {
    const graph = real.getBoardGraph(kind, mode, 'sw2021');
    directedIntegrity(real, graph, mode); resizePreservesZoom(real, graph);
    counts[`sw2021/${kind}/${mode}`] = {nodes: graph.nodes.length, directory: graph.directoryNodes.length, edges: graph.edges.length};
  }
  const unknownStock = Object.keys(real.INDUSTRY_DATA.stockNames || {}).find(code => !real.EVIDENCE.stocks[code]);
  if (unknownStock) {
    const owner = real.getBoardRecords('subindustry', 'sw2021').find(board => board.members.includes(unknownStock));
    if (owner) {
      const graph = real.buildStockGraph(owner.code, unknownStock, 'subindustry', 'sw2021');
      assert.ok(graph.nodes.some(node => node.meta.code === unknownStock && node.meta.pct === null),
        'a name-only SW member remains selectable without invented quote data');
      assert.equal(graph.totalMembers, owner.members.length);
    }
  }
  assert.ok(counts.concept.nodes >= 284, 'current concept data must not regress to the old 215-node layout');
  console.log(JSON.stringify({status: 'PASS', fixture: 'complete catalog, isolation, focused stock, native sources, fallback', current: counts}));
  }
} finally {
  assert.equal(path.dirname(path.resolve(scratch)), path.resolve(os.tmpdir()), 'only remove this test-created temporary directory');
  await rm(scratch, {recursive: true, force: true});
}
