import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { build } from 'esbuild';
import { PerspectiveCamera, Vector3 } from 'three';

// Dated regression against the approved industry/stock layout. An explicit
// baseline path may be supplied when moving this diagnostic to another machine.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const baselinePath = process.argv.find(arg => arg.startsWith('--baseline='))?.slice(11) ||
  path.join(root, '..', 'diagnostics', 'concept-starfield-20260924', 'backups', 'atlas.js');
const scratch = await mkdtemp(path.join(os.tmpdir(), 'atlas-concept-starfield-'));

async function bundle(name, source) {
  const outfile = path.join(scratch, `${name}.mjs`);
  await build({
    absWorkingDir: root, outfile, bundle: true, format: 'esm', platform: 'node', logLevel: 'silent',
    stdin: {contents: `export * from 'audit-atlas';
      export {marketVisualsForNodes} from './src/lib/market-visual.js';`, resolveDir: root},
    plugins: [{name: 'atlas-version-under-test', setup(builder) {
      builder.onResolve({filter: /^audit-atlas$/}, () => ({path: 'atlas.js', namespace: 'atlas-version'}));
      // The backup lives outside src/lib: dependencies must still resolve from
      // the original atlas directory, never relative to the backup location.
      builder.onLoad({filter: /.*/, namespace: 'atlas-version'}, () => ({
        contents: source, loader: 'js', resolveDir: path.join(root, 'src', 'lib'),
      }));
    }}],
  });
  return pathToFileURL(outfile).href;
}

const coords = graph => graph.nodes.map(node => [node.key, node.x, node.y, node.z, node.vx, node.vy, node.vz]);
const edgeData = (model, graph) => graph.edges.map(edge => ({
  i: edge.i, source: edge.s.key, target: edge.t.key, kind: edge.kind,
  directed: edge.directed, evidence: edge.evidence, relation: model.edgeRelation(graph, edge),
}));
function semantics(model, graph) {
  return {
    mode: graph.mode, relationMode: graph.relationMode, system: graph.system,
    boardKind: graph.boardKind, boardCode: graph.boardCode, boardName: graph.boardName,
    totalMembers: graph.totalMembers, depth: graph.depth, adj: graph.adj, pathAdj: graph.pathAdj,
    clusters: graph.CLUSTERS.map(({anchor, dir, ...data}) => data),
    nodes: graph.nodes.map(node => ({
      i: node.i, key: node.key, name: node.name, cid: node.cid, w: node.w,
      desc: node.desc, meta: node.meta, degree: graph.deg(node),
      alpha: node.alpha, scale: node.scale, vis: node.vis,
    })),
    edges: edgeData(model, graph),
    layoutReferences: graph.layoutReferences, layoutGrouping: graph.layoutGrouping,
    directory: graph.directoryNodes.map(node => node.key),
    visuals: model.marketVisualsForNodes(graph.nodes),
  };
}
function assertFinite(graph, label) {
  assert.ok(graph.nodes.every(node => [node.x, node.y, node.z, node.vx, node.vy, node.vz]
    .every(value => Number.isFinite(Math.fround(value)))), `${label}: coordinates fit Float32 GPU buffers`);
  for (const [view, points] of Object.entries(graph.anchors)) {
    assert.equal(points.length, graph.nodes.length, `${label}/${view}: each node has an anchor`);
    assert.ok(points.flat().every(value => Number.isFinite(Math.fround(value))), `${label}/${view}: finite anchors`);
  }
  assert.ok(graph.fitDist() > 0 && graph.fitDist() < 1400, `${label}: fits camera far plane`);
}
function assertCameraCoverage(graph, label) {
  const point = new Vector3();
  for (const aspect of [0.5, 1, 1.75]) {
    const distance = graph.fitDist(aspect);
    const camera = new PerspectiveCamera(46, aspect, 1, 1400);
    // The original bounding-sphere framing must still contain the overview
    // throughout its normal auto-orbit after the small anchor expansion.
    const phi = 1.15;
    for (let step = 0; step < 192; step++) {
      const theta = 0.7 + step * Math.PI / 96;
      camera.position.set(distance * Math.sin(phi) * Math.cos(theta), distance * Math.cos(phi),
        distance * Math.sin(phi) * Math.sin(theta));
      camera.lookAt(0, 0, 0); camera.updateMatrixWorld();
      for (const node of graph.nodes) {
        point.set(node.x, node.y, node.z).project(camera);
        assert.ok(Math.abs(point.x) <= 1 && Math.abs(point.y) <= 1 && point.z >= -1 && point.z <= 1,
          `${label}: ${node.name} remains framed at aspect=${aspect}, phi=${phi}, theta=${theta.toFixed(3)} ` +
          `(NDC ${point.x.toFixed(3)},${point.y.toFixed(3)},${point.z.toFixed(3)})`);
      }
    }
    // Manual rotation intentionally permits a closer inspection. It must
    // retain finite projection and depth coverage, but its most extreme
    // angles must not force the initial overview unnecessarily far away.
    for (const manualPhi of [0.12, 0.3, 2.8, Math.PI - 0.12]) for (let step = 0; step < 32; step++) {
      const theta = 0.7 + step * Math.PI / 16;
      camera.position.set(distance * Math.sin(manualPhi) * Math.cos(theta), distance * Math.cos(manualPhi),
        distance * Math.sin(manualPhi) * Math.sin(theta));
      camera.lookAt(0, 0, 0); camera.updateMatrixWorld();
      for (const node of graph.nodes) {
        point.set(node.x, node.y, node.z).project(camera);
        assert.ok([point.x, point.y, point.z].every(Number.isFinite) && point.z >= -1 && point.z <= 1,
          `${label}: ${node.name} retains finite visible depth at manual phi=${manualPhi}, aspect=${aspect}`);
      }
    }
  }
}
function assertSameLayout(beforeModel, afterModel, before, after, label) {
  assert.deepEqual(semantics(afterModel, after), semantics(beforeModel, before), `${label}: all semantics and visual metrics unchanged`);
  assert.deepEqual(after.anchors, before.anchors, `${label}: every anchor byte-equivalent numerically`);
  assert.deepEqual(coords(after), coords(before), `${label}: every position and velocity byte-equivalent numerically`);
  assert.deepEqual(after.CLUSTERS, before.CLUSTERS, `${label}: all cluster settings unchanged`);
  for (const aspect of [0.5, 1, 1.75]) {
    assert.equal(after.fitDist(aspect), before.fitDist(aspect), `${label}: camera framing unchanged`);
  }
  assertFinite(after, label);
}

// Acceptance follows the original seven reference directions and their real
// overlap grouping. The only tuning is a 16% radial expansion; the force
// layout, not an invented per-node cloud, still spreads nodes around them.
function referenceReport(graph) {
  return {nodes: graph.nodes.length, edges: graph.edges.length,
    references: graph.layoutReferences.map(({code, name}) => ({code, name})),
    clusters: graph.CLUSTERS.map(cluster => ({
      referenceCode: cluster.referenceCode, direction: cluster.dir,
      members: graph.nodes.filter(node => node.cid === cluster.id).length,
    })), fitDist: graph.fitDist()};
}
function assertOriginalReferences(before, after) {
  assert.equal(before.layoutReferences.length, 7, 'original snapshot selects seven real reference concepts');
  assert.equal(after.CLUSTERS.length, 7, 'concept layout retains the original seven reference directions');
  assert.deepEqual(after.CLUSTERS, before.CLUSTERS,
    'reference codes, names, directions, colors and cluster settings remain exactly original');
  assert.deepEqual(after.nodes.map(node => [node.key, node.cid]), before.nodes.map(node => [node.key, node.cid]),
    'each concept retains its original real-overlap group');
  assert.deepEqual(after.CLUSTERS.map(cluster => cluster.referenceCode), after.layoutReferences.map(reference => reference.code),
    'all seven cluster directions correspond to the original reference concepts');
  after.nodes.forEach((node, i) => {
    assert.equal(node.cluster.referenceCode, before.nodes[i].cluster.referenceCode,
      `${node.name}: reference concept unchanged`);
    after.anchors.atlas[i].forEach((coordinate, axis) => {
      const expected = before.anchors.atlas[i][axis] * 1.16;
      assert.ok(Math.abs(coordinate - expected) <= 1e-12,
        `${node.name}: atlas target is exactly the original target expanded 16%, within floating-point rounding`);
    });
  });
}

try {
  const baselineSource = await readFile(baselinePath, 'utf8');
  const baselineUrl = await bundle('baseline', baselineSource);
  const baseline = await import(baselineUrl);
  const oldConcept = baseline.conceptGraph;
  if (process.argv.includes('--baseline-report')) {
    console.log(JSON.stringify({baseline: referenceReport(oldConcept)}, null, 2));
  } else {
    const currentUrl = await bundle('current', await readFile(path.join(root, 'src', 'lib', 'atlas.js'), 'utf8'));
    const current = await import(currentUrl);
    const repeated = await import(`${currentUrl}?independent-instance=1`);
    const concept = current.conceptGraph;
    assert.equal(oldConcept.nodes.length, 395, 'reference snapshot contains 395 concepts');
    assert.equal(oldConcept.edges.length, 607, 'reference snapshot contains 607 real overlap edges');
    assert.deepEqual(semantics(current, concept), semantics(baseline, oldConcept),
      'concept layout changes preserve all 395 nodes, 607 edges, labels, metadata, metrics and adjacency');
    assert.deepEqual(current.META, baseline.META, 'snapshot facts and reference meanings unchanged');
    assert.deepEqual(concept.anchors.shell, oldConcept.anchors.shell, 'explicit sphere-view anchors unchanged');
    assert.deepEqual(concept.anchors.tier, oldConcept.anchors.tier, 'explicit tier-view anchors unchanged');
    assert.deepEqual(coords(concept), coords(repeated.conceptGraph), 'fresh builds reproduce all concept positions exactly');
    assert.deepEqual(concept.anchors, repeated.conceptGraph.anchors, 'fresh builds reproduce all concept anchors exactly');
    assertFinite(concept, 'concept');

    const before = referenceReport(oldConcept), after = referenceReport(concept);
    assertOriginalReferences(oldConcept, concept);
    assert.notDeepEqual(coords(concept), coords(oldConcept), 'small concept-only anchor expansion changes the settled positions');
    assertCameraCoverage(concept, 'concept');

    const unchanged = [];
    for (const [kind, relationMode, system] of [
      ['industry', 'network', 'ths'], ['industry', 'overlap', 'ths'],
      ['industry', 'classification', 'ths'], ['subindustry', 'classification', 'ths'],
    ]) {
      const label = `${system}/${kind}/${relationMode}`;
      const oldGraph = baseline.getBoardGraph(kind, relationMode, system);
      const newGraph = current.getBoardGraph(kind, relationMode, system);
      assertSameLayout(baseline, current, oldGraph, newGraph, label);
      // Force reheats/views to catch accidental changes hidden by first-frame caching.
      if (relationMode === 'network') for (const view of ['shell', 'tier', 'atlas']) {
        for (const graph of [oldGraph, newGraph]) {
          graph.setView(view); graph.reheat(0.55);
          for (let frame = 0; frame < 600; frame++) graph.layout();
        }
        assertSameLayout(baseline, current, oldGraph, newGraph, `${label}/${view}`);
      }
      unchanged.push({label, nodes: newGraph.nodes.length, edges: newGraph.edges.length});
    }
    const rankedConcepts = [...oldConcept.nodes].sort((a, b) => b.meta.count - a.meta.count);
    const rankedIndustries = [...baseline.getBoardGraph('industry', 'network').nodes]
      .filter(node => node.meta?.count > 0).sort((a, b) => b.meta.count - a.meta.count);
    const stockCases = [
      ['concept', rankedConcepts[0]],
      ['concept', rankedConcepts.find(node => node.meta.count > 3 && node.meta.count < 30)],
      ['concept', oldConcept.nodes.find(node => node.name === '人工智能') || rankedConcepts[1]],
      ['industry', rankedIndustries[0]],
    ];
    for (const [kind, node] of stockCases) {
      assert.ok(node, `${kind}: representative drilldown board exists`);
      const label = `stock/${kind}/${node.name}`;
      const oldGraph = baseline.buildStockGraph(node.meta.code, undefined, kind);
      const newGraph = current.buildStockGraph(node.meta.code, undefined, kind);
      assert.ok(oldGraph && newGraph, `${label}: stock drilldown remains available`);
      assertSameLayout(baseline, current, oldGraph, newGraph, label);
      unchanged.push({label, nodes: newGraph.nodes.length, edges: newGraph.edges.length});
    }
    for (const view of ['shell', 'tier', 'atlas']) {
      for (const graph of [concept, repeated.conceptGraph]) {
        graph.setView(view); graph.reheat(0.55);
        for (let frame = 0; frame < 600; frame++) graph.layout();
      }
      assertFinite(concept, `concept/${view}/reheated`);
      assert.deepEqual(coords(concept), coords(repeated.conceptGraph), `concept/${view}: reheating stays reproducible`);
    }
    console.log(JSON.stringify({status: 'PASS', anchorExpansion: 1.16, baseline: before, restored: after, unchanged}, null, 2));
  }
} finally {
  assert.equal(path.dirname(path.resolve(scratch)), path.resolve(os.tmpdir()));
  assert.ok(path.basename(scratch).startsWith('atlas-concept-starfield-'));
  await rm(scratch, {recursive: true, force: true});
}
