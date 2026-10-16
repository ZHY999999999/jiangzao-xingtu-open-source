import * as THREE from 'three';
import { getTheme, subscribeTheme, toggleTheme } from './theme';
import { marketVisualsForNodes } from './market-visual.js';

import {
  EVIDENCE, getBoardEvidence, getBoardRecords, getBoardMembers, getStockEvidence, getBoardCandidates,
  getStockRelation, getBoardRelation, getStockEdges, getIndustryRelations, getIndustryNetwork,
} from './evidence.js';

if (EVIDENCE.schemaVersion !== 2 || !['complete', 'partial_optional'].includes(EVIDENCE.status)) {
  throw new Error('星图证据数据尚未就绪，需要完成版本 2 的成分与行情同步。');
}

// Live quotes change visual metrics only. Preserve the original reference stars,
// stock selection and ordering so opening a board after a refresh keeps its map.
const layoutStockMetrics = new Map(Object.values(EVIDENCE.stocks || {}).map(stock =>
  [stock.code, {mv: stock.mv, amount: stock.amount}]));

/* ═══════════════════════════════════════════════════════════════════════
   数据 —— 概念、行业、细分行业均从完整证据目录构建，不使用旧布局的节选。
   概念按成分股重合度归入七个布局分区；同花顺行业按业务与共同主题网络聚合。
   共同主题为无向数据推导，业务箭头只读取已核实来源，不能互相替代。
   布局分区本身不构成分类证据，共现不表示资金流向或收益因果。
   ═══════════════════════════════════════════════════════════════════════ */

/* 七个天区共用一组等亮度光谱色与固定球面方位 —— 方位不动、数据不变，
   每次打开的版图就一致。 */
const PALETTE = [
  {dark:'#7d9bff', light:'#4a5fd8', anchor:[-0.85, -0.42, 0.30]},
  {dark:'#4cc9f0', light:'#0e8fbe', anchor:[-0.55,  0.30, 0.78]},
  {dark:'#3ddc97', light:'#0f9c68', anchor:[ 0.10,  0.72, 0.40]},
  {dark:'#c084fc', light:'#8f45dd', anchor:[ 0.86,  0.26, -0.10]},
  {dark:'#ffb340', light:'#c47a06', anchor:[ 0.42, -0.70, -0.30]},
  {dark:'#ff70a6', light:'#d92066', anchor:[ 0.30,  0.34, -0.88]},
  {dark:'#c2e34a', light:'#6f9412', anchor:[-0.62, -0.15, -0.72]},
];

const META = {
  tradeDate: EVIDENCE.tradeDate,
  membershipAsOf: EVIDENCE.membershipAsOf,
  asOf: EVIDENCE.membershipAsOf,
  financialPeriod: EVIDENCE.financialPeriod,
  financialAsOf: EVIDENCE.financialAsOf || null,
  generatedAt: EVIDENCE.generatedAt || null,
  seed: hashStr(`${EVIDENCE.tradeDate}|${EVIDENCE.membershipAsOf}`),
  anchors: [],
};
// 布局取景与三维相机必须共享同一个视角值。
const FOV = 46;

/* ═══════════════════════════════════════════════════════════════════════
   建图工厂 —— 同一份数据每次打开版图一致：锚点固定、初始散布用固定种子、
   力导向预跑到彻底冷却。概念星图与个股星图共用这一个工厂。
   spec = {clusters:[{id,name}], nodesArr:[[名称,聚类id,权重,释义]],
           edgesArr:[[源,目标,'pre'|'supply'|'business'|'theme'|'rel',证据]], metaByName, seed}
   ═══════════════════════════════════════════════════════════════════════ */
export function buildGraph(spec) {
const CLUSTERS = spec.clusters;
for (const c of CLUSTERS) c.color = c[getTheme()];
const NODES = spec.nodesArr;
const EDGES = spec.edgesArr;
const METABYNAME = spec.metaByName || {};
const industryNetwork = spec.mode === 'industry' && spec.relationMode === 'network';
const conceptStarfield = spec.mode === 'concept' && spec.relationMode === 'overlap';

/* ═══════════════════════════════════════════════════════════════════════
   建图 —— 名称对不上的边直接丢掉并在控制台点名，
   因为这份边表是给人手改的，一个错字不该让整页白屏。
   ═══════════════════════════════════════════════════════════════════════ */

const CMAP = Object.fromEntries(CLUSTERS.map(c => [c.id, c]));
const nodes = NODES.map(([name, cid, w, desc, key = name], i) => ({
  i, key, name, cid, w, desc, cluster: CMAP[cid], meta: METABYNAME[key] || null,
  out: [], in: [], rel: [], supplyOut: [], supplyIn: [],
  x: 0, y: 0, z: 0, vx: 0, vy: 0, vz: 0,
  sx: 0, sy: 0, sz: 0, vis: true, alpha: 1, scale: 1,
}));
const byKey = Object.fromEntries(nodes.map(n => [n.key, n]));

const edges = [];
for (const [a, b, kind, evidence = {}] of EDGES) {
  const s = byKey[a], t = byKey[b];
  if (!s || !t) { console.warn('[atlas] 丢弃无效边：', a, '→', b); continue }
  const directed = kind === 'pre' || kind === 'supply' || (kind === 'business' && evidence.directed === true);
  edges.push({s, t, kind, evidence, directed, i: edges.length, alpha: 1});
  if (kind === 'pre') { s.out.push(t); t.in.push(s) }
  else if (directed) { s.supplyOut.push(t); t.supplyIn.push(s) }
  else { s.rel.push(t); t.rel.push(s) }
}
const deg = n => n.out.length + n.in.length + n.rel.length + n.supplyOut.length + n.supplyIn.length;
const adj = nodes.map(() => []);
const pathAdj = nodes.map(() => []);
for (const e of edges) {
  adj[e.s.i].push(e.t.i); adj[e.t.i].push(e.s.i);
  pathAdj[e.s.i].push(e.t.i);
  if (!e.directed) pathAdj[e.t.i].push(e.s.i);
}
function findPath(from, to, visibleOnly = false) {
  if (!nodes[from] || !nodes[to]) return null;
  const prev = new Array(nodes.length).fill(-1), seen = new Set([from]), queue = [from];
  for (let cursor = 0; cursor < queue.length; cursor++) {
    const current = queue[cursor];
    if (current === to) break;
    for (const next of pathAdj[current]) if (!seen.has(next) && (!visibleOnly || nodes[next].vis)) {
      seen.add(next); prev[next] = current; queue.push(next);
    }
  }
  if (!seen.has(to)) return null;
  const chain = [];
  for (let current = to; current !== -1; current = prev[current]) { chain.unshift(current); if (current === from) break }
  return chain;
}

/* ═══════════════════════════════════════════════════════════════════════
   布局 —— 三种，共用同一套力，只换「锚」。
   星图：锚在聚类方位；球面：锚在球壳上按聚类分带；分层：锚按拓扑深度分层。
   ═══════════════════════════════════════════════════════════════════════ */

const R = 42;
for (const c of CLUSTERS) {
  const [x, y, z] = c.anchor, l = Math.hypot(x, y, z) || 1;
  c.dir = [x / l, y / l, z / l];
}

// Only verified classification edges define depth. Supply chains may contain
// cycles and must never be interpreted as a classification hierarchy.
const depth = new Array(nodes.length).fill(0);
(function computeDepth() {
  const pending = nodes.map(node => node.in.length);
  const queue = nodes.filter(node => !node.in.length), visited = new Set();
  for (let cursor = 0; cursor < queue.length; cursor++) {
    const node = queue[cursor]; visited.add(node.i);
    for (const child of node.out) {
      depth[child.i] = Math.max(depth[child.i], depth[node.i] + 1);
      if (--pending[child.i] === 0) queue.push(child);
    }
  }
  if (visited.size !== nodes.length) throw new Error('分类父子关系出现环，请核对来源数据。');
})();
const maxDepth = Math.max(1, ...depth);

const anchors = {atlas: [], shell: [], tier: []};
nodes.forEach((n, i) => {
  const d = n.cluster.dir;
  // 星图：聚类方位 × 半径，度数高的靠内 —— 枢纽概念自然落在天区中心。
  // Preserve the original seven reference directions and relationship-led
  // expansion. Only ease the overview's anchor spacing outward by 16%.
  const pull = (1 - Math.min(deg(n), 12) / 26) * (conceptStarfield ? 1.16 : 1);
  anchors.atlas.push([d[0] * R * pull, d[1] * R * pull, d[2] * R * pull]);

  // 球面：所有节点摊在同一层壳上，按聚类占据经度带 —— 看整体密度用。
  const ci = CLUSTERS.indexOf(n.cluster);
  const within = nodes.filter(m => m.cid === n.cid).indexOf(n);
  const cnt = nodes.filter(m => m.cid === n.cid).length;
  if (industryNetwork) {
    // Spread each community in its tangent plane instead of stacking all of
    // its anchors on one ray. This changes placement only, never evidence.
    const normal = new THREE.Vector3(...d);
    const tangent = new THREE.Vector3().crossVectors(normal,
      Math.abs(d[1]) > .9 ? new THREE.Vector3(1, 0, 0) : new THREE.Vector3(0, 1, 0)).normalize();
    const bitangent = new THREE.Vector3().crossVectors(normal, tangent);
    const angle = within * Math.PI * (3 - Math.sqrt(5));
    const radius = Math.sqrt((within + .5) / cnt) * (8 + Math.sqrt(cnt) * 1.6);
    anchors.atlas[i] = d.map((value, axis) => value * R * 1.06 + radius *
      (Math.cos(angle) * tangent.getComponent(axis) + Math.sin(angle) * bitangent.getComponent(axis)));
  }
  const lon = (ci / CLUSTERS.length + within / cnt / CLUSTERS.length) * Math.PI * 2;
  const lat = (within / cnt - 0.5) * 1.5;
  anchors.shell.push([
    R * 0.95 * Math.cos(lat) * Math.cos(lon),
    R * 0.95 * Math.sin(lat),
    R * 0.95 * Math.cos(lat) * Math.sin(lon),
  ]);

  // 正式分类按父到子的深度从上到下排列；其余模式保持几何展平。
  anchors.tier.push([
    d[0] * R * 0.72,
    (spec.relationMode === 'classification' ? 0.5 - depth[i] / maxDepth : depth[i] / maxDepth - 0.5) * R * 1.5,
    d[2] * R * 0.72,
  ]);
});

let view = 'atlas';
/* 初始散布用固定种子：力导向对初值敏感，「同一份数据每次打开版图一致」
   要求连初始抖动都可复现。种子随数据日期走 —— 数据更新，版图才重新洗牌。 */
function mulberry32(a) {
  return function () {
    a |= 0; a = a + 0x6D2B79F5 | 0;
    let t = Math.imul(a ^ a >>> 15, 1 | a);
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}
const rand = mulberry32(spec.seed || 1);
nodes.forEach((n, i) => {
  const a = anchors.atlas[i];
  n.x = a[0] + (rand() - .5) * 16;
  n.y = a[1] + (rand() - .5) * 16;
  n.z = a[2] + (rand() - .5) * 16;
});

/* 三个系数的平衡就是这张图好不好看的全部。
   斥力太大 → 图涨出画面，聚类失去意义；锚点引力太大 → 拓扑被压扁成七个圆盘。
   调的时候只动 KR/KA 的比值，REST 决定相邻概念的观感疏密。 */
let alpha = 1;                       // 力导向的「温度」，收敛后停机
const REST = 9, KS = 0.04, KR = 130, KA = industryNetwork ? 0.105 : 0.05;
// Full catalogs contain broad concepts with hundreds of neighbors. Bound each
// hub's total spring stiffness, rather than dropping truthful membership edges:
// the old constant-per-edge force can overflow Float32 rendering coordinates.
const springStrength = edges.map(edge => KS * Math.min(1, 12 / Math.max(deg(edge.s), deg(edge.t))) *
  (industryNetwork && edge.s.cid !== edge.t.cid ? 0.42 : 1));

function layout() {
  if (alpha < 0.004) return;
  const a = anchors[view];
  // 斥力 O(n²)，布局只在首次建图和视角切换时运行。
  for (let i = 0; i < nodes.length; i++) {
    const p = nodes[i];
    for (let j = i + 1; j < nodes.length; j++) {
      const q = nodes[j];
      let dx = p.x - q.x, dy = p.y - q.y, dz = p.z - q.z;
      let d2 = dx * dx + dy * dy + dz * dz + 0.6;
      const f = KR / d2;
      const d = Math.sqrt(d2);
      dx /= d; dy /= d; dz /= d;
      p.vx += dx * f; p.vy += dy * f; p.vz += dz * f;
      q.vx -= dx * f; q.vy -= dy * f; q.vz -= dz * f;
    }
  }
  for (const e of edges) {
    const p = e.s, q = e.t;
    let dx = q.x - p.x, dy = q.y - p.y, dz = q.z - p.z;
    const d = Math.hypot(dx, dy, dz) || 1;
    const f = (d - REST) * springStrength[e.i];
    dx /= d; dy /= d; dz /= d;
    p.vx += dx * f; p.vy += dy * f; p.vz += dz * f;
    q.vx -= dx * f; q.vy -= dy * f; q.vz -= dz * f;
  }
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i], an = a[i];
    n.vx += (an[0] - n.x) * KA; n.vy += (an[1] - n.y) * KA; n.vz += (an[2] - n.z) * KA;
    const damp = 0.82;
    n.vx *= damp; n.vy *= damp; n.vz *= damp;
    n.x += n.vx * alpha; n.y += n.vy * alpha; n.z += n.vz * alpha;
  }
  alpha *= 0.988;
}
// 预跑到彻底冷却（alpha 0.988^600 ≈ 0.0007 < 停机阈值 0.004）：
// 首帧就是冻结态，任何设备、任何帧率下，同一份数据的版图逐点一致。
for (let k = 0; k < 600; k++) layout();

/* 取景距离从收敛后的包围球反算，不写死。
   写死的那个数在换了数据、改了斥力系数之后一定会错，而且错法是「一半的图在画面外」。 */
function fitDist(aspect = 1) {
  let r = 0;
  for (const n of nodes) r = Math.max(r, Math.hypot(n.x, n.y, n.z));
  const safeAspect = Number.isFinite(aspect) && aspect > 0 ? aspect : 1;
  const verticalHalfFov = FOV * Math.PI / 360;
  const limitingHalfFov = Math.atan(Math.tan(verticalHalfFov) * Math.min(1, safeAspect));
  return Math.max(r, 12) / Math.sin(limitingHalfFov) * 1.04;
}

return {
  CLUSTERS, nodes, edges, deg, adj, pathAdj, findPath, depth, anchors, fitDist,
  directoryNodes: nodes.filter(node => !node.meta?.context),
  relationMode: spec.relationMode || (spec.mode === 'stock' ? 'shared-concepts' : 'overlap'),
  system: spec.system || 'ths',
  mode: spec.mode || 'concept', conceptName: spec.conceptName || null,
  boardKind: spec.boardKind || 'concept', boardCode: spec.boardCode || null,
  boardName: spec.boardName || spec.conceptName || null,
  totalMembers: spec.totalMembers ?? nodes.length,
  layout,
  getView: () => view,
  setView(v) { view = v },
  reheat(t = 0.55) { alpha = Math.max(alpha, t) },
};
}

/* ── 概念星图：模块加载即建好（预跑在工厂里完成）。 ─────────────────── */
function hashStr(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

const isMetric = value => typeof value === 'number' && Number.isFinite(value);
const metricText = (value, digits = 2) => isMetric(value) ? value.toFixed(digits) : '暂无数据';
const moneyText = value => !isMetric(value) ? '暂无数据' :
  value >= 10000 ? `${(value / 10000).toFixed(2)} 万亿` : `${value.toFixed(2)} 亿`;
const dateText = value => String(value || '').replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3');
const byMetric = key => (a, b) =>
  (isMetric(b[key]) ? b[key] : -Infinity) - (isMetric(a[key]) ? a[key] : -Infinity) || a.code.localeCompare(b.code);
const byLayoutMetric = key => (a, b) => byMetric(key)(
  {code: a.code, [key]: layoutStockMetrics.get(a.code)?.[key]},
  {code: b.code, [key]: layoutStockMetrics.get(b.code)?.[key]},
);
function sumMetric(stocks, key) {
  const values = stocks.map(s => s[key]).filter(isMetric);
  return values.length ? values.reduce((sum, v) => sum + v, 0) : null;
}

const compareText = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const kindLabel = kind => ({concept: '概念', sector: '一级行业', industry: '行业', subindustry: '细分行业'})[kind];
const systemLabel = system => system === 'sw2021' ? '申万2021' : '同花顺';
const boardKey = (kind, code, system = 'ths') => `${system}:${kind}:${code}`;

function sharedMemberCount(a, b) {
  const [small, large] = a.size <= b.size ? [a, b] : [b, a];
  let count = 0;
  for (const code of small) if (large.has(code)) count++;
  return count;
}

// This only chooses visual reference points. Every catalog record, including
// broad trading/index/ownership/earnings attributes, remains a visible node.
const genericLayoutAttribute = /融资融券|(?:沪|深|港)股通|样本|成[份分]股|MSCI|富时|标普|中证|上证|深证|创业板指|北证|(?:年报|中报|季报)预|ST板块|新股与次新股|国企改革|中字头|证金持股|基金重仓|高股息|红利|专精特新/i;
const bySimilarity = (a, b) => b.similarity - a.similarity || b.sharedCount - a.sharedCount || compareText(a.code, b.code);

/** Jaccard overlap ranks real relationships without favoring universal sets. */
function boardEdges(boards, memberSets) {
  const codes = boards.map(board => board.code);
  const neighbors = new Map(codes.map(code => [code, []]));
  const chosen = new Map();
  for (let i = 0; i < codes.length; i++) for (let j = i + 1; j < codes.length; j++) {
    const a = codes[i], b = codes[j], sharedCount = sharedMemberCount(memberSets.get(a), memberSets.get(b));
    if (!sharedCount) continue;
    const similarity = sharedCount / (memberSets.get(a).size + memberSets.get(b).size - sharedCount);
    neighbors.get(a).push({code: b, sharedCount, similarity}); neighbors.get(b).push({code: a, sharedCount, similarity});
  }
  for (const code of codes) {
    const best = neighbors.get(code).sort(bySimilarity).slice(0, 2);
    for (const other of best) {
      const pair = [code, other.code].sort(compareText), key = pair.join('|');
      if (!chosen.has(key)) chosen.set(key, [...pair, 'rel', {
        selectionRule: 'shared-members', rankingRule: 'jaccard-then-shared-count',
        sharedCount: other.sharedCount, overlapPct: other.similarity * 100, selectedBy: [],
      }]);
      chosen.get(key)[3].selectedBy.push(code);
    }
  }
  return [...chosen.values()].sort((a, b) => compareText(a[0], b[0]) || compareText(a[1], b[1]));
}

function buildBoardGraph(kind, system = 'ths') {
  const boards = getBoardRecords(kind, system).slice().sort((a, b) => compareText(a.code, b.code));
  const metaByName = {}, memberSets = new Map();
  for (const board of boards) {
    const members = getBoardMembers(board.code, kind, system), stocks = members.map(getStockEvidence).filter(Boolean);
    memberSets.set(board.code, new Set(members));
    metaByName[board.code] = {
      ...board, level: kind, boardKind: kind, system, context: false,
      pct: isMetric(board.pct) ? board.pct : null, officialPct: isMetric(board.pct) ? board.pct : null,
      weightedPct: isMetric(board.weightedPct) ? board.weightedPct : null,
      amount: sumMetric(stocks, 'amount'), mv: sumMetric(stocks, 'mv'), count: members.length,
      amountCount: stocks.filter(stock => isMetric(stock.amount)).length,
      mvCount: stocks.filter(stock => isMetric(stock.mv)).length,
      members, tradeDate: EVIDENCE.tradeDate, membershipAsOf: board.membershipAsOf || EVIDENCE.membershipAsOf,
    };
  }
  const ranked = boards.slice().sort((a, b) => byMetric('amount')(metaByName[a.code], metaByName[b.code]));
  const references = kind === 'concept' ? ranked.filter(board => !genericLayoutAttribute.test(board.name)).slice(0, PALETTE.length) : [];
  const clusters = PALETTE.map((color, i) => ({
    id: `${kind}-${i}`, name: `布局分区 ${i + 1}${references[i] ? ` · ${references[i].name}` : ''}`,
    referenceCode: references[i]?.code || null, ...color,
  }));
  const referenceIndex = new Map(references.map((board, i) => [board.code, i]));
  const rankIndex = new Map(ranked.map((board, i) => [board.code, i]));
  const nodesArr = boards.map(board => {
    const meta = metaByName[board.code], ownReference = referenceIndex.get(board.code);
    // Zero-overlap boards still belong to the graph. Hash ties never impose a capacity cap.
    let group = ownReference ?? hashStr(board.code) % clusters.length;
    if (kind === 'concept' && ownReference === undefined) {
      let best = null;
      references.forEach((reference, i) => {
        const a = memberSets.get(board.code), b = memberSets.get(reference.code);
        const sharedCount = sharedMemberCount(a, b);
        if (!sharedCount) return;
        const candidate = {code: reference.code, sharedCount, similarity: sharedCount / (a.size + b.size - sharedCount)};
        if (!best || bySimilarity(candidate, best) < 0) { best = candidate; group = i }
      });
    }
    const fraction = rankIndex.get(board.code) / Math.max(1, boards.length);
    const weight = ownReference !== undefined ? 6 : fraction < .1 ? 5 : fraction < .3 ? 4 : fraction < .6 ? 3 : 2;
    const desc = `${board.code} · ${systemLabel(system)}${kindLabel(kind)} · ${dateText(EVIDENCE.tradeDate)} · ` +
      `${meta.count} 只成分股，成交合计 ${moneyText(meta.amount)}；` +
      `板块指数涨跌 ${isMetric(meta.pct) ? metricText(meta.pct) + '%' : '暂无数据'}。` +
      `成员归属快照 ${dateText(meta.membershipAsOf)}。`;
    return [board.name, clusters[group].id, weight, desc, boardKey(kind, board.code, system)];
  });
  const graph = buildGraph({mode: kind, boardKind: kind, system, relationMode: 'overlap', clusters, nodesArr,
    edgesArr: boardEdges(boards, memberSets).map(([a, b, ...rest]) => [boardKey(kind, a, system), boardKey(kind, b, system), ...rest]),
    metaByName: Object.fromEntries(boards.map(board => [boardKey(kind, board.code, system), metaByName[board.code]])),
    seed: META.seed + hashStr(`${system}:${kind}`)});
  graph.layoutReferences = references.map(board => ({...metaByName[board.code], name: board.name}));
  return graph;
}

function buildIndustryGraph(kind, relationMode, system) {
  const records = new Map();
  const refKey = ref => boardKey(ref.kind, ref.code, ref.system || system);
  const addRecord = (board, boardKind, boardSystem = system) => {
    if (!board) return;
    records.set(boardKey(boardKind, board.code, boardSystem), {board, kind: boardKind, system: boardSystem});
  };
  for (const board of getBoardRecords(kind, system)) addRecord(board, kind);
  if (relationMode === 'classification') {
    for (const level of ['sector', 'industry']) for (const board of getBoardRecords(level, system)) addRecord(board, level);
  }
  const verified = type => getIndustryRelations(type, system).filter(relation =>
    relation.verificationStatus === 'verified' && relation.type === type && relation.from && relation.to &&
    relation.sourceRefs?.some(source => source.url));
  const classification = verified('classification');
  const requested = relationMode === 'classification' ? classification : verified('supply-chain');
  if (relationMode === 'supply-chain') for (const relation of requested) {
    for (const ref of [relation.from, relation.to]) {
      addRecord(getBoardEvidence(ref.code, ref.kind, ref.system || system), ref.kind, ref.system || system);
    }
  }
  // Missing or out-of-scope endpoints do not acquire invented stand-in nodes.
  const relations = requested.filter(relation => records.has(refKey(relation.from)) && records.has(refKey(relation.to)));
  const parents = new Map();
  for (const relation of classification) {
    const child = refKey(relation.to), parent = refKey(relation.from);
    if (!parents.has(child)) parents.set(child, []);
    parents.get(child).push(parent);
  }
  for (const values of parents.values()) values.sort(compareText);
  const sectors = getBoardRecords('sector', system).slice().sort((a, b) => compareText(a.code, b.code));
  const clusters = sectors.map((sector, i) => {
    const y = 1 - 2 * (i + 0.5) / sectors.length, radius = Math.sqrt(Math.max(0, 1 - y * y));
    const angle = i * Math.PI * (3 - Math.sqrt(5));
    return {id: boardKey('sector', sector.code, system), name: sector.name,
      ...PALETTE[i % PALETTE.length], anchor: [Math.cos(angle) * radius, y, Math.sin(angle) * radius]};
  });
  const sectorKeys = new Set(clusters.map(cluster => cluster.id));
  const unassigned = `${system}:unassigned-layout`;
  function clusterFor(key) {
    const visited = new Set(); let current = key;
    while (current && !visited.has(current)) {
      if (sectorKeys.has(current)) return current;
      visited.add(current); current = parents.get(current)?.[0];
    }
    return unassigned;
  }
  const ordered = [...records].sort(([a], [b]) => compareText(a, b));
  if (!clusters.length || ordered.some(([key]) => clusterFor(key) === unassigned)) {
    clusters.push({id: unassigned, name: '尚无已核实上级分类', ...PALETTE[6]});
  }
  const metaByName = {};
  const nodesArr = ordered.map(([key, record]) => {
    const {board, kind: nodeKind, system: nodeSystem} = record;
    const members = getBoardMembers(board.code, nodeKind, nodeSystem);
    const stocks = members.map(getStockEvidence).filter(Boolean);
    const meta = metaByName[key] = {...board, members, level: nodeKind, boardKind: nodeKind,
      system: nodeSystem, context: nodeKind !== kind || nodeSystem !== system,
      count: members.length, amount: sumMetric(stocks, 'amount'), mv: sumMetric(stocks, 'mv'),
      amountCount: stocks.filter(stock => isMetric(stock.amount)).length,
      mvCount: stocks.filter(stock => isMetric(stock.mv)).length,
      pct: isMetric(board.pct) ? board.pct : null, officialPct: isMetric(board.pct) ? board.pct : null,
      tradeDate: EVIDENCE.tradeDate, membershipAsOf: board.membershipAsOf || EVIDENCE.membershipAsOf};
    const desc = `${board.code} · ${systemLabel(nodeSystem)}${kindLabel(nodeKind)} · ${meta.count} 家成员；` +
      `分类来源：${board.source || '见关系依据'}；成员查询 ${dateText(meta.membershipAsOf)}。`;
    return [board.name, clusterFor(key), nodeKind === 'sector' ? 7 : nodeKind === 'industry' ? 5 : 3, desc, key];
  });
  const graph = buildGraph({mode: kind, boardKind: kind, system, relationMode, clusters, nodesArr, metaByName,
    edgesArr: relations.map(relation => [refKey(relation.from), refKey(relation.to),
      relationMode === 'classification' ? 'pre' : 'supply',
      {...relation, relationId: relation.id, relationType: relation.type}]),
    seed: META.seed + hashStr(`${system}:${kind}:${relationMode}`)});
  graph.layoutReferences = sectors;
  return graph;
}

// Deterministic greedy modularity grouping of the displayed network. Business
// evidence has weight 3 and derived theme evidence weight 1 for placement only;
// neither the weights nor the groups are industry classifications or new edges.
function industryNetworkGroups(boards, relations) {
  const communities = new Map(boards.map(board => [board.code,
    {id: board.code, codes: [board.code], degree: 0, links: new Map()}]));
  let totalWeight = 0;
  for (const relation of relations) {
    const a = communities.get(relation.from), b = communities.get(relation.to);
    const weight = relation.type === 'business' ? 3 : 1;
    a.degree += weight; b.degree += weight; totalWeight += weight;
    a.links.set(b.id, (a.links.get(b.id) || 0) + weight);
    b.links.set(a.id, (b.links.get(a.id) || 0) + weight);
  }
  const isolated = boards.filter(board => !communities.get(board.code).degree).map(board => board.code);
  for (const code of isolated) communities.delete(code);
  while (communities.size > 1) {
    let best = null;
    for (const a of communities.values()) for (const [other, between] of a.links) {
      if (compareText(a.id, other) >= 0) continue;
      const b = communities.get(other);
      const gain = between / totalWeight - a.degree * b.degree / (2 * totalWeight ** 2);
      const key = `${a.id}|${b.id}`;
      if (gain > 1e-12 && (!best || gain > best.gain + 1e-12 ||
        (Math.abs(gain - best.gain) <= 1e-12 && compareText(key, best.key) < 0))) best = {a, b, gain, key};
    }
    if (!best) break;
    const {a, b} = best;
    a.codes.push(...b.codes); a.codes.sort(compareText); a.degree += b.degree;
    a.links.delete(b.id);
    for (const [other, weight] of b.links) {
      if (other === a.id) continue;
      a.links.set(other, (a.links.get(other) || 0) + weight);
      const neighbor = communities.get(other);
      neighbor.links.delete(b.id);
      neighbor.links.set(a.id, (neighbor.links.get(a.id) || 0) + weight);
    }
    communities.delete(b.id);
  }
  const groups = [...communities.values()].sort((a, b) => b.codes.length - a.codes.length || compareText(a.id, b.id));
  if (isolated.length || !groups.length) groups.push({id: 'evidence-gap', codes: isolated, evidenceGap: true});
  return groups;
}

function buildIndustryNetworkGraph() {
  const kind = 'industry', system = 'ths';
  const boards = getBoardRecords(kind, system).slice().sort((a, b) => compareText(a.code, b.code));
  const byCode = new Map(boards.map(board => [board.code, board]));
  const network = getIndustryNetwork();
  const relations = network.relations.filter(relation =>
    ['business', 'theme'].includes(relation.type) && relation.from !== relation.to &&
    byCode.has(relation.from) && byCode.has(relation.to));
  const groups = industryNetworkGroups(boards, relations);
  const grouping = new Map();
  const clusters = groups.map((group, i) => {
    const y = 1 - 2 * (i + 0.5) / groups.length, radius = Math.sqrt(Math.max(0, 1 - y * y));
    const angle = i * Math.PI * (3 - Math.sqrt(5));
    const id = `industry-network:${group.id}`;
    for (const code of group.codes) grouping.set(code, id);
    return {id, name: group.evidenceGap ? '关系证据待补' : `关系分组 ${i + 1} · ${byCode.get(group.codes[0]).name}`,
      ...PALETTE[i % PALETTE.length], ...(group.evidenceGap ? {dark: '#98a1b2', light: '#6b7280'} : {}),
      anchor: [Math.cos(angle) * radius, y, Math.sin(angle) * radius],
      evidenceGap: !!group.evidenceGap, memberCodes: [...group.codes],
      description: group.evidenceGap ? '当前规则下没有已展示关系，保留节点等待补充证据。' : '仅按已展示关系安排位置，不是行业分类。'};
  });
  const counts = new Map(boards.map(board => [board.code, {business: 0, theme: 0}]));
  for (const relation of relations) for (const code of [relation.from, relation.to]) counts.get(code)[relation.type]++;
  const metaByName = {};
  const nodesArr = boards.map(board => {
    const members = getBoardMembers(board.code, kind, system), stocks = members.map(getStockEvidence).filter(Boolean);
    const relationCounts = counts.get(board.code), evidenceGap = !relationCounts.business && !relationCounts.theme;
    const key = boardKey(kind, board.code, system);
    const meta = metaByName[key] = {...board, level: kind, boardKind: kind, system, context: false,
      pct: isMetric(board.pct) ? board.pct : null, officialPct: isMetric(board.pct) ? board.pct : null,
      weightedPct: isMetric(board.weightedPct) ? board.weightedPct : null,
      amount: sumMetric(stocks, 'amount'), mv: sumMetric(stocks, 'mv'), count: members.length,
      amountCount: stocks.filter(stock => isMetric(stock.amount)).length,
      mvCount: stocks.filter(stock => isMetric(stock.mv)).length,
      members, tradeDate: EVIDENCE.tradeDate, membershipAsOf: board.membershipAsOf || EVIDENCE.membershipAsOf,
      relationCounts, evidenceGap,
      evidenceGapReason: evidenceGap ? '当前没有满足证据规则的业务或共同主题连线；不代表不存在实际业务联系。' : null};
    const desc = `${board.code.replace(/\.TI$/, '')} · 同花顺行业 · ${meta.count} 只成分股，成交合计 ${moneyText(meta.amount)}；` +
      `已核业务 ${relationCounts.business} 条，共同产业主题 ${relationCounts.theme} 条。` +
      (meta.evidenceGapReason || '主题连线由双方不同公司的概念归属推导，不证明供货关系。');
    return [board.name, grouping.get(board.code), Math.min(6, 2 + Math.floor(Math.sqrt(relationCounts.business + relationCounts.theme))), desc, key];
  });
  const graph = buildGraph({mode: kind, boardKind: kind, system, relationMode: 'network', clusters, nodesArr, metaByName,
    edgesArr: relations.map(relation => [boardKey(kind, relation.from, system), boardKey(kind, relation.to, system),
      relation.type, {...relation, relationId: relation.id, relationType: relation.type}]),
    seed: META.seed + hashStr('ths:industry:network')});
  graph.coverage = {...network.coverage, renderedRelationCount: relations.length};
  graph.layoutGrouping = {method: 'weighted-greedy-modularity', businessWeight: 3, themeWeight: 1,
    boundary: '关系分组仅用于可重复布局，不是同花顺行业分类，也不产生额外连线。'};
  graph.layoutReferences = [];
  return graph;
}

const boardGraphCache = new Map();
export function getBoardGraph(kind = 'concept', relationMode = 'network', system = 'ths') {
  if (kind === 'sector') kind = 'industry';
  if (!['concept', 'industry', 'subindustry'].includes(kind)) kind = 'concept';
  if (kind === 'concept') { system = 'ths'; relationMode = 'overlap' }
  if (!['classification', 'supply-chain', 'overlap', 'network'].includes(relationMode)) relationMode = 'network';
  if (relationMode === 'network' && (kind !== 'industry' || system !== 'ths')) relationMode = 'classification';
  const cacheKey = `${system}:${kind}:${relationMode}`;
  if (!boardGraphCache.has(cacheKey)) boardGraphCache.set(cacheKey, relationMode === 'network' ? buildIndustryNetworkGraph() : relationMode === 'overlap' ?
    buildBoardGraph(kind, system) : buildIndustryGraph(kind, relationMode, system));
  return boardGraphCache.get(cacheKey);
}

const conceptGraph = getBoardGraph('concept');
META.anchors = conceptGraph.layoutReferences;
META.nodes = conceptGraph.nodes.length;
META.edges = conceptGraph.edges.length;
META.avgDeg = Number((META.edges * 2 / Math.max(1, META.nodes)).toFixed(2));

/* 个股图使用完整成分表选取成交额前 150，再补入市值参照、经营规模候选及
   用户点名股票。参照节点只用于稳定布局，不能据此判断产业地位。 */
function buildStockGraph(boardNameOrCode, focusName, kind = 'concept', system = 'ths') {
  if (kind === 'concept') system = 'ths';
  const board = getBoardEvidence(boardNameOrCode, kind, system);
  const members = getBoardMembers(boardNameOrCode, kind, system);
  if (!members.length) return null;
  const stocks = members.map(getStockEvidence).filter(Boolean);
  if (!stocks.length) return null;
  const scale = [...stocks].sort(byLayoutMetric('mv')).slice(0, 5);
  const selectedCodes = new Set([...stocks].sort(byLayoutMetric('amount')).slice(0, 150).map(s => s.code));
  for (const stock of scale) selectedCodes.add(stock.code);
  for (const code of getBoardCandidates(board.code, undefined, kind, system)) selectedCodes.add(code);
  const focus = stocks.find(s => s.code === focusName || s.name === focusName);
  if (focus) selectedCodes.add(focus.code);
  const selectedStocks = stocks.filter(s => selectedCodes.has(s.code)).sort(byLayoutMetric('amount'));
  const scaleCodes = new Set(scale.map(s => s.code));
  const clusters = scale.map((s, i) => ({
    id: 's' + i, name: `${s.name} · 市值参照`, ...PALETTE[i % PALETTE.length],
  }));
  const conceptSets = new Map(stocks.map(s => [s.code, new Set(s.concepts || [])]));
  function clusterIndex(stock) {
    const own = scale.findIndex(s => s.code === stock.code);
    if (own >= 0) return own;
    let best = 0, bestOverlap = -1;
    scale.forEach((reference, i) => {
      const common = (reference.concepts || []).filter(name => conceptSets.get(stock.code).has(name)).length;
      if (common > bestOverlap) { best = i; bestOverlap = common }
    });
    return best;
  }
  const metaByName = {};
  const nodesArr = selectedStocks.map((stock, rank) => {
    const fraction = rank / selectedStocks.length;
    const weight = scaleCodes.has(stock.code) ? 6 : fraction < .1 ? 5 : fraction < .3 ? 4 : fraction < .6 ? 3 : 2;
    metaByName[stock.code] = {
      ...stock, to: isMetric(stock.turnover) ? stock.turnover : null, concepts: [...(stock.concepts || [])],
      thsIndustries: (stock.thsIndustries || []).map(industry => ({...industry})),
      boardKind: kind, boardCode: board.code, system,
      pct: isMetric(stock.pct) ? stock.pct : null,
      amount: isMetric(stock.amount) ? stock.amount : null,
      mv: isMetric(stock.mv) ? stock.mv : null,
      tradeDate: EVIDENCE.tradeDate, membershipAsOf: EVIDENCE.membershipAsOf,
    };
    const desc = `${stock.code} · ${dateText(EVIDENCE.tradeDate)} · 总市值 ${moneyText(stock.mv)}，` +
      `成交额 ${moneyText(stock.amount)}，涨跌 ${isMetric(stock.pct) ? metricText(stock.pct) + '%' : '暂无数据'}，` +
      `换手率 ${isMetric(stock.turnover) ? metricText(stock.turnover) + '%' : '暂无数据'}；` +
      `公司行业（基础资料）：${stock.industry || '暂无分类'}。` +
      `同花顺行业归属：${(stock.thsIndustries || []).map(item => `${item.name}（${kindLabel(item.level)}）`).join('、') || '暂无数据'}。` +
      `概念归属（${dateText(EVIDENCE.membershipAsOf)}）：${(stock.concepts || []).join('、') || '暂无数据'}。`;
    return [stock.name, 's' + clusterIndex(stock), weight, desc, stock.code];
  });
  const edgesArr = getStockEdges(selectedStocks.map(s => s.code)).map(edge => [
    edge.a, edge.b, 'rel', {...edge, selectionRule: 'shared-concepts'},
  ]);
  return buildGraph({mode: 'stock', conceptName: board.name, boardName: board.name,
    boardKind: kind, boardCode: board.code, system, totalMembers: members.length,
    clusters, nodesArr, edgesArr, metaByName,
    seed: (META.seed + hashStr(`${system}:${kind}:${board.code}`)) % 100000 || 1});
}

export function edgeRelation(graph, edge) {
  const stock = graph.mode === 'stock';
  const boardKind = graph.boardKind || 'concept';
  const relationType = edge.evidence.relationType || (edge.kind === 'pre' ? 'classification' : edge.kind === 'supply' ? 'supply-chain' : 'overlap');
  const endpoint = node => ({i: node.i, key: node.key, name: node.name, code: node.meta?.code,
    kind: node.meta?.boardKind || boardKind, boardKind: node.meta?.boardKind || boardKind,
    system: node.meta?.system || graph.system});
  if (relationType === 'business' || relationType === 'theme') {
    const evidence = edge.evidence, sourceRefs = evidence.sourceRefs || [], sharedThemes = evidence.sharedThemes || [];
    return {...evidence, edgeId: edge.i, relationId: evidence.relationId || evidence.id,
      kind: boardKind, boardKind, type: relationType, relationType, directed: edge.directed,
      a: endpoint(edge.s), b: endpoint(edge.t), from: evidence.from, to: evidence.to,
      statement: evidence.statement || '', boundary: evidence.boundary || null, sourceRefs, sharedThemes,
      source: [...new Set(sourceRefs.map(source => source.title || source.url).filter(Boolean))].join('；'),
      sharedConcepts: [], sharedStocks: [], sharedCount: null, unionCount: null, overlapPct: null,
      hierarchyVerified: false,
      reason: relationType === 'business' ?
        `${evidence.statement || ''} ${edge.directed ? '箭头按已核实来源的业务方向绘制。' : '此线只说明来源记载的业务联系。'}不表示双方所有成员公司之间都有直接交易。` :
        `${evidence.statement || ''}双方不同公司的概念归属构成共同产业主题；这是可复核的数据推导，不是已核实供货关系，也不表示上下级分类。`};
  }
  if (relationType !== 'overlap') {
    const evidence = edge.evidence, sourceRefs = evidence.sourceRefs || [];
    return {...evidence, edgeId: edge.i, relationId: evidence.relationId || evidence.id,
      kind: boardKind, boardKind, relationType, type: relationType, directed: true,
      a: endpoint(edge.s), b: endpoint(edge.t), from: evidence.from, to: evidence.to,
      statement: evidence.statement || '', boundary: evidence.boundary || null, sourceRefs, verificationStatus: evidence.verificationStatus,
      source: sourceRefs.map(source => source.title || source.url).join('；'), asOf: evidence.asOf,
      sharedConcepts: [], sharedStocks: [], sharedCount: null, unionCount: null, overlapPct: null,
      hierarchyVerified: relationType === 'classification',
      reason: `${evidence.statement || ''}${relationType === 'classification' ?
        ' 箭头由上级分类指向下级分类，不表示供货或资金方向。' :
        ' 箭头表示证据中的产业投入或服务方向，不表示所有成员公司之间都有直接交易。'}`};
  }
  const relation = stock ? getStockRelation(edge.s.meta.code, edge.t.meta.code) :
    getBoardRelation(edge.s.meta.code, edge.t.meta.code, boardKind, graph.system);
  const selectedNames = (edge.evidence.selectedBy || []).map(code => getStockEvidence(code)?.name || code);
  const selectedBoards = (edge.evidence.selectedBy || []).map(code => getBoardEvidence(code, boardKind, graph.system)?.name || code);
  const reason = stock ?
    `共同所属概念至少 3 个；每只图中股票按共同概念数取前 2 个邻居，再将双方选择取并集。本边由${selectedNames.join('、') || '其中一端'}选入。同数按股票代码排序。` :
    `成分共现连线：共同成分股至少 1 只；每个${kindLabel(boardKind)}按成员重合比例（Jaccard：交集数 ÷ 并集数）取前 2 个邻居，双方选择取并集。` +
      `本边由${selectedBoards.join('、') || '其中一端'}选入，比例相同先比共同成分数，再按板块代码排序。此线不表示上下级分类或产业上下游。`;
  return {
    edgeId: edge.i, kind: stock ? 'stock' : boardKind, boardKind, relationType: 'overlap', type: 'overlap', directed: false,
    a: endpoint(edge.s), b: endpoint(edge.t),
    sharedConcepts: [], sharedStocks: [], ...relation, reason,
    selectionRule: edge.evidence.selectionRule,
    rankingRule: edge.evidence.rankingRule,
  };
}

function drawerPayload(graph, node) {
  if (!node) return null;
  const relations = graph.edges.filter(edge => edge.s === node || edge.t === node).map(edge => {
    const neighbor = edge.s === node ? edge.t : edge.s;
    const evidence = edgeRelation(graph, edge);
    const outgoing = edge.s === node;
    return {edgeId: edge.i, relationId: evidence.relationId, relationType: evidence.relationType, type: evidence.relationType,
      directed: edge.directed, outgoing, i: neighbor.i, key: neighbor.key,
      name: neighbor.name, color: neighbor.cluster.color, boardKind: neighbor.meta?.boardKind, system: neighbor.meta?.system,
      code: neighbor.meta?.code, sharedCount: evidence.sharedCount,
      sharedThemes: evidence.sharedThemes || [], statement: evidence.statement, boundary: evidence.boundary,
      sourceRefs: evidence.sourceRefs || [], verificationStatus: evidence.verificationStatus,
      summary: evidence.relationType === 'business' ? (edge.directed ? (outgoing ? '业务方向 →' : '业务方向 ←') : '已核业务联系') :
        evidence.relationType === 'theme' ? `共同主题 · ${evidence.sharedThemes?.slice(0, 2).map(theme => theme.name).join('、') || '查看依据'}${evidence.sharedThemes?.length > 2 ? ' 等' : ''}` :
        evidence.relationType === 'classification' ? (outgoing ? '下级分类' : '上级分类') :
        evidence.relationType === 'supply-chain' ? (outgoing ? '流向下游' : '来自上游') :
        graph.mode === 'stock' ? `共属 ${evidence.sharedCount} 个概念` :
        `共同 ${evidence.sharedCount} 只成分股`};
  });
  if (graph.relationMode === 'network') relations.sort((a, b) =>
    Number(b.relationType === 'business') - Number(a.relationType === 'business') || compareText(a.code, b.code));
  return {
    i: node.i, name: node.name, desc: node.desc, cname: node.cluster.name, color: node.cluster.color,
    deg: graph.deg(node), depth: graph.depth[node.i], meta: node.meta, marketVisual: node.marketVisual,
    relations, relatedConcepts: relations,
    groups: [...new Set(relations.map(relation => relation.relationType))].map(type => ({
      title: type === 'business' ? '已核业务关系' : type === 'theme' ? '共同产业主题（数据推导）' :
        type === 'classification' ? '分类关系' : type === 'supply-chain' ? '产业链关系' : '成员重合',
      tag: type, items: relations.filter(relation => relation.relationType === type),
    })),
  };
}

function edgeCaption(graph, edge) {
  const relation = edgeRelation(graph, edge);
  const label = relation.relationType === 'business' ? '已核业务关系' :
    relation.relationType === 'theme' ? '共同产业主题 · 数据推导' :
    relation.relationType === 'classification' ? '分类包含' :
    relation.relationType === 'supply-chain' ? '产业链方向' :
    `${graph.mode === 'stock' ? '共属' : '共有'} ${relation.sharedCount} ${graph.mode === 'stock' ? '概念' : '成分股'}`;
  return `${edge.s.name} ${edge.directed ? '→' : '↔'} ${edge.t.name} · ${label}`;
}

function directedEdgeColor(edge, theme = getTheme()) {
  if (edge.kind === 'pre') return theme === 'light' ? '#147d94' : '#63c9df';
  if (edge.kind === 'supply' || edge.kind === 'business') return theme === 'light' ? '#aa6200' : '#ffb340';
  if (edge.kind === 'theme') return theme === 'light' ? '#3577a0' : '#74b7d4';
  return null;
}

export function edgeArrowPlacement(edge) {
  if (!edge.directed) return null;
  const direction = new THREE.Vector3(edge.t.x - edge.s.x, edge.t.y - edge.s.y, edge.t.z - edge.s.z);
  const distance = direction.length();
  if (!Number.isFinite(distance) || distance < 1e-6) return null;
  const targetRadius = (edge.t.size || 0.95 + edge.t.w * 0.4) * Math.max(1, edge.t.scale || 1) * 0.65;
  const length = Math.max(distance * 0.3, distance - targetRadius);
  return {origin: new THREE.Vector3(edge.s.x, edge.s.y, edge.s.z), direction: direction.divideScalar(distance),
    length, headLength: Math.min(2.8, length * 0.22), headWidth: Math.min(1.8, length * 0.14)};
}

/* ═══════════════════════════════════════════════════════════════════════
   三维
   ═══════════════════════════════════════════════════════════════════════ */

/* 星图引擎。三维、每帧的标签投影、力导向都在 React 之外；
   React 只画左栏、抽屉和工具条，靠 emit.* 拿到列表、选中项和开关状态。
   HUD、面包屑、底部读数这几处纯读数，仍旧由引擎直接写进 React 给的壳里。 */
export function resizeCameraFit(cameraState, previousFit, nextFit) {
  // Preserve both the requested zoom and its in-flight damping. Resizing must
  // not reset a user's close-up, selected center, or viewing direction.
  const ratio = nextFit / previousFit;
  cameraState.dist *= ratio;
  cameraState.tDist *= ratio;
}

export function createAtlas({els, emit, graph}) {
  /* 图实例解构为同名局部量 —— 引擎主体对概念图与个股图一视同仁。 */
  const {CLUSTERS, nodes, edges, deg, adj, depth, anchors, fitDist} = graph;
  const industryNetwork = graph.mode === 'industry' && graph.relationMode === 'network';
  const ac = new AbortController();
  const {signal} = ac;
  const bind = (t, ev, fn, o) => t.addEventListener(ev, fn, {...o, signal});
  let raf = 0, active = true;
  let unsubscribeTheme = () => {};
  for (const c of CLUSTERS) c.color = c[getTheme()];
  emit.relation?.(null);
  for (const node of nodes) { node.vis = true; node.alpha = 1; node.scale = 1 }
  for (const edge of edges) edge.alpha = 1;

  function refreshMarketVisuals() {
    const visuals = marketVisualsForNodes(nodes);
    nodes.forEach((node, i) => { node.marketVisual = visuals[i]; node.size = visuals[i].size });
  }
  refreshMarketVisuals();

  const {stage} = els;
  let renderer, scene, camera, glowPts, corePts, lineSeg;
  let ok = true;
  try {
    renderer = new THREE.WebGLRenderer({antialias: true, alpha: false, powerPreference: 'high-performance'});
  } catch (err) { ok = false }
  if (!renderer) ok = false;

  /* 无 3D 的降级实现：左栏检索、图例开关、右栏详情照常工作。
     WebGL 完全不可用、以及渲染中途崩溃，都走这一条。 */
  const off = new Set();
  function makeFallback() {
    emit.gate(true);
    let fallbackSelected = null, fallbackEdge = null, fallbackQuery = '';
    const fbClearRelation = () => {
      fallbackEdge = null; emit.relation?.(null);
      els.hudSel.textContent = fallbackSelected?.name || '未选中';
      fbList();
    };
    const fbList = v => {
      if (typeof v === 'string') fallbackQuery = v.trim().toLowerCase();
      const q = fallbackQuery;
      const rows = nodes
        .filter(n => n === fallbackEdge?.s || n === fallbackEdge?.t ||
          (!off.has(n.cid) && (!q || n.name.toLowerCase().includes(q) || n.desc.toLowerCase().includes(q))))
        .sort((a, b) => deg(b) - deg(a));
      emit.list({q, rows: rows.map(n => ({i: n.i, name: n.name, color: n.cluster.color,
        deg: deg(n), on: n === fallbackSelected || n === fallbackEdge?.t}))});
      els.sNode.textContent = rows.length;
      const ec = edges.filter(e => rows.includes(e.s) && rows.includes(e.t)).length;
      els.sEdge.textContent = ec;
      els.sDeg.textContent = rows.length ? (ec * 2 / rows.length).toFixed(1) : '0';
    };
    const fbDrawer = n => emit.drawer(drawerPayload(graph, n));
    const fbSelect = i => {
      fallbackSelected = nodes[i] || null;
      fbClearRelation(); fbDrawer(fallbackSelected); fbList();
      els.hudSel.textContent = fallbackSelected?.name || '未选中';
    };
    const fbSelectEdge = edgeId => {
      const edge = edges[edgeId];
      if (!edge) return null;
      fallbackSelected = edge.s; fallbackEdge = edge;
      fbDrawer(edge.s); fbList();
      const payload = edgeRelation(graph, edge);
      emit.relation?.(payload);
      els.hudSel.textContent = edgeCaption(graph, edge);
      return payload;
    };
    fbClearRelation(); fbDrawer(null);
    emit.tools({flow: false, label: true, spin: false});
    const applyFallbackTheme = () => {
      const theme = getTheme();
      for (const c of CLUSTERS) c.color = c[theme];
      emit.theme?.(theme);
      fbList(); fbDrawer(fallbackSelected);
    };
    unsubscribeTheme = subscribeTheme(applyFallbackTheme);
    applyFallbackTheme();
    const noop = () => {};
    return {
      setQuery: fbList,
      toggleCluster(id) { off.has(id) ? off.delete(id) : off.add(id); fbList() },
      selectAt: fbSelect, selectEdge: fbSelectEdge, clearRelation: fbClearRelation,
      hoverAt: noop, clearPath: noop, centerOn: noop, startPath: noop,
      setView: noop, toggleFlow: noop, toggleLabel: noop, toggleSpin: noop,
      toggleTheme,
      reset() { fbSelect(null) }, dolly: noop, zoomReset: noop,
      setActive(value) { active = !!value },
      updateMarketMetrics() { refreshMarketVisuals(); fbList(); fbDrawer(fallbackSelected) },
      dispose() { unsubscribeTheme(); ac.abort() },
    };
  }

  if (!ok) return makeFallback();
  emit.gate(false);
  {
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  stage.appendChild(renderer.domElement);

  scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x050507, 0.0068);
  camera = new THREE.PerspectiveCamera(FOV, 1, 1, 1400);

  const hex = h => {const c = new THREE.Color(h); return [c.r, c.g, c.b]};

  /* ── 节点：两层 Points，都用加性混合。
        glow 层大而弱负责气氛，core 层小而亮负责「这是一个球」。 ── */
  const N = nodes.length;
  const pos = new Float32Array(N * 3), col = new Float32Array(N * 3);
  const siz = new Float32Array(N), alp = new Float32Array(N), scl = new Float32Array(N);
  const brightness = new Float32Array(N), strength = new Float32Array(N);
  nodes.forEach((n, i) => {
    const c = hex(n.cluster.color);
    col[i * 3] = c[0]; col[i * 3 + 1] = c[1]; col[i * 3 + 2] = c[2];
    // 世界单位下的直径，不是像素。像素尺寸交给 shader 按透视算，
    // 这样缩放时节点的大小关系才是真的，而不是缩放后全部一样大。
    siz[i] = n.size;
    brightness[i] = n.marketVisual.brightness; strength[i] = n.marketVisual.strength;
    alp[i] = 1; scl[i] = 1;
  });

  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  geo.setAttribute('aColor', new THREE.BufferAttribute(col, 3));
  geo.setAttribute('aSize', new THREE.BufferAttribute(siz, 1));
  geo.setAttribute('aAlpha', new THREE.BufferAttribute(alp, 1));
  geo.setAttribute('aScale', new THREE.BufferAttribute(scl, 1));
  geo.setAttribute('aBrightness', new THREE.BufferAttribute(brightness, 1));
  geo.setAttribute('aStrength', new THREE.BufferAttribute(strength, 1));

  const NODE_VERT = /* glsl */`
    attribute vec3 aColor; attribute float aSize; attribute float aAlpha; attribute float aScale;
    attribute float aBrightness; attribute float aStrength;
    varying vec3 vColor; varying float vAlpha, vPhase, vProminence, vBrightness;
    uniform float uPx, uMul, uHalo;
    void main(){
      vColor = aColor; vAlpha = aAlpha; vBrightness = aBrightness;
      vPhase = dot(position, vec3(0.31, 0.53, 0.71));
      vProminence = smoothstep(0.2, 1.0, aStrength);
      vec4 mv = modelViewMatrix * vec4(position, 1.0);
      gl_PointSize = aSize * aScale * uMul * mix(1.0, 0.7 + 0.85 * vProminence, uHalo) * uPx / max(-mv.z, 1.0);
      gl_Position = projectionMatrix * mv;
    }`;

  // uPx = h / (2·tan(fov/2))，即「一个世界单位在单位距离上占多少像素」。
  // 把它算对，节点大小就跟真实球体一致，近大远小不用手调。
  const glowMat = new THREE.ShaderMaterial({
    uniforms: {uPx: {value: 300}, uMul: {value: 4.2}, uHalo: {value: 1}, uLight: {value: 0},
      uStrength: {value: 0.72}, uTime: {value: 0}, uFlow: {value: 0}},
    vertexShader: NODE_VERT,
    fragmentShader: /* glsl */`
      varying vec3 vColor; varying float vAlpha, vPhase, vProminence, vBrightness;
      uniform float uLight, uStrength, uTime, uFlow;
      void main(){
        float d = length(gl_PointCoord - 0.5) * 2.0;
        if (d > 1.0) discard;
        // 三次衰减而不是高斯：边缘落得更干净，不会在近处糊成一片方块。
        float halo = pow(1.0 - d, 2.2);
        vec2 p = abs((gl_PointCoord - 0.5) * 2.0);
        vec3 tint = pow(max(vColor, vec3(0.0)), vec3(0.454545));
        float rays = (exp(-p.x * 38.0) + exp(-p.y * 38.0)) * pow(1.0 - d, 1.8);
        if (uLight > 0.5) {
          // On a light surface, colored light around a white core supplies
          // contrast. No extra stars: every sparkle belongs to a real node.
          float breathe = 0.5 + 0.5 * sin(uTime * 1.1 + vPhase);
          float sparkle = (0.25 + 0.75 * pow(breathe, 3.0)) * uFlow;
          float aura = halo * (0.32 + sparkle * 0.08);
          float flare = rays * (0.15 + sparkle * 0.28) * vProminence * vProminence;
          gl_FragColor = vec4(tint, min(0.85, (aura + flare) * vBrightness) * vAlpha);
        } else {
          // A broad colored aura and a steady bright-star cross survive even
          // with animation disabled. Low-cap stars keep a clean, dim core.
          float flare = rays * 0.32 * vProminence * vProminence;
          gl_FragColor = vec4(mix(tint, vec3(1.0), 0.2 * vProminence),
            min(0.88, (halo * uStrength + flare) * vBrightness) * vAlpha);
        }
      }`,
    transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
  });
  const coreMat = new THREE.ShaderMaterial({
    uniforms: {uPx: {value: 300}, uMul: {value: 1.0}, uHalo: {value: 0}, uLight: {value: 0}},
    vertexShader: NODE_VERT,
    fragmentShader: /* glsl */`
      varying vec3 vColor; varying float vAlpha, vBrightness, vProminence;
      uniform float uLight;
      void main(){
        float d = length(gl_PointCoord - 0.5) * 2.0;
        if (d > 1.0) discard;
        if (uLight > 0.5) {
          vec2 p = (gl_PointCoord - 0.5) * 2.0;
          vec3 tint = pow(max(vColor, vec3(0.0)), vec3(0.454545));
          float disc = 1.0 - smoothstep(0.80, 1.0, d);
          float rim = smoothstep(0.58, 0.88, d);
          float core = 1.0 - smoothstep(0.06, 0.60, d);
          float glint = pow(max(0.0, 1.0 - length(p + vec2(0.22, 0.24)) / 0.7), 2.0);
          vec3 body = mix(vec3(0.46), mix(tint, tint * 0.64, rim), 0.3 + 0.7 * vProminence);
          body = mix(body, vec3(1.0), min(0.98, core * 0.88 + glint * 0.9) * (0.08 + 0.9 * vProminence));
          gl_FragColor = vec4(body, disc * (0.62 + 0.38 * vProminence) * vAlpha);
        } else {
          float core = 1.0 - smoothstep(0.12, 0.85, d);
          float disc = 1.0 - smoothstep(0.76, 1.0, d);
          vec3 tint = pow(max(vColor, vec3(0.0)), vec3(0.454545));
          vec3 c = mix(tint, vec3(1.0), core * 0.9 * vProminence);
          gl_FragColor = vec4(c * vBrightness, disc * (0.35 + 0.65 * core) * vAlpha);
        }
      }`,
    transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
  });

  glowPts = new THREE.Points(geo, glowMat);
  corePts = new THREE.Points(geo, coreMat);
  glowPts.frustumCulled = false; corePts.frustumCulled = false;
  scene.add(glowPts, corePts);

  /* 可选动效只做明暗呼吸；有向关系另绘真实箭头，不借动效暗示方向。 */
  const E = edges.length;
  const epos = new Float32Array(E * 6), ecol = new Float32Array(E * 6);
  const et = new Float32Array(E * 2), eseed = new Float32Array(E * 2);
  const ealp = new Float32Array(E * 2);
  edges.forEach((e, i) => {
    const typeColor = directedEdgeColor(e);
    const a = hex(typeColor || e.s.cluster.color), b = hex(typeColor || e.t.cluster.color);
    ecol.set(a, i * 6); ecol.set(b, i * 6 + 3);
    et[i * 2] = 0; et[i * 2 + 1] = 1;
    const sd = (i * 0.6180339887) % 1;
    eseed[i * 2] = sd; eseed[i * 2 + 1] = sd;
    ealp[i * 2] = ealp[i * 2 + 1] = 1;
  });
  const egeo = new THREE.BufferGeometry();
  egeo.setAttribute('position', new THREE.BufferAttribute(epos, 3));
  egeo.setAttribute('aColor', new THREE.BufferAttribute(ecol, 3));
  egeo.setAttribute('aT', new THREE.BufferAttribute(et, 1));
  egeo.setAttribute('aSeed', new THREE.BufferAttribute(eseed, 1));
  egeo.setAttribute('aAlpha', new THREE.BufferAttribute(ealp, 1));

  const lineMat = new THREE.ShaderMaterial({
    uniforms: {uTime: {value: 0}, uFlow: {value: 0}, uLight: {value: 0}},
    vertexShader: /* glsl */`
      attribute vec3 aColor; attribute float aT, aSeed, aAlpha;
      varying vec3 vColor; varying float vT, vSeed, vAlpha;
      void main(){
        vColor = aColor; vT = aT; vSeed = aSeed; vAlpha = aAlpha;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }`,
    fragmentShader: /* glsl */`
      precision mediump float;
      varying vec3 vColor; varying float vT, vSeed, vAlpha;
      uniform float uTime, uFlow, uLight;
      void main(){
        float pulse = (0.5 + 0.5 * sin(uTime * 1.6 + vSeed * 6.2831853)) * uFlow;
        if (uLight > 0.5) {
          vec3 tint = pow(max(vColor, vec3(0.0)), vec3(0.454545));
          // Symmetric highlights breathe in place; they imply no flow direction.
          float gleam = pow(0.5 + 0.5 * cos((vT - 0.5) * 25.132741), 10.0) * pulse;
          vec3 light = mix(tint * 0.78, mix(tint, vec3(1.0), 0.32), gleam);
          gl_FragColor = vec4(light, vAlpha * (0.28 + 0.25 * pulse + 0.30 * gleam));
        } else {
          gl_FragColor = vec4(vColor * (0.55 + 1.10 * pulse), vAlpha * (0.13 + 0.80 * pulse));
        }
      }`,
    transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
  });
  lineSeg = new THREE.LineSegments(egeo, lineMat);
  lineSeg.frustumCulled = false;
  scene.add(lineSeg);

  const arrowHeads = edges.filter(edge => edge.directed).map(edge => {
    const arrow = new THREE.ArrowHelper(new THREE.Vector3(0, 1, 0), new THREE.Vector3(), 1, directedEdgeColor(edge));
    arrow.line.visible = false; // The existing line buffer draws the complete shaft.
    arrow.cone.material.transparent = true; arrow.cone.material.depthWrite = false;
    arrow.cone.frustumCulled = false;
    scene.add(arrow);
    return {edge, arrow};
  });
  function updateArrowHeads() {
    for (const {edge, arrow} of arrowHeads) {
      const placement = edgeArrowPlacement(edge);
      arrow.visible = !!placement && edge.s.vis && edge.t.vis && edge.alpha > 0.02;
      if (!placement) continue;
      arrow.position.copy(placement.origin); arrow.setDirection(placement.direction);
      arrow.setLength(placement.length, placement.headLength, placement.headWidth);
      arrow.cone.material.opacity = Math.min(1, edge.alpha * 0.95);
    }
  }
  updateArrowHeads();

  /* ── 相机控制：自己写，省一个 vendor 文件。
        阻尼是唯一让手感从「玩具」变成「仪器」的东西，所以它不是可选项。 ── */
  let D0 = fitDist(stage.clientWidth / stage.clientHeight);
  const cam = {
    theta: 0.7, phi: 1.15, dist: D0,
    tTheta: 0.7, tPhi: 1.15, tDist: D0,
    tx: 0, ty: 0, tz: 0, cx: 0, cy: 0, cz: 0,
  };
  let dragging = false, lastX = 0, lastY = 0, moved = 0;
  const el = renderer.domElement;
  /* 触摸：记录每根手指。第二根落下就进入捏合 —— 两指间距的变化走和滚轮同一条 dolly 路径，
     并且这一次手势不再算拖拽也不算点击；任一手指抬起后要重新按下才恢复单指旋转，免得视角跳一下。 */
  const pointers = new Map();
  let pinchDist = 0;
  const pinchDistance = () => { const [a, b] = [...pointers.values()]; return Math.hypot(a.x - b.x, a.y - b.y) };

  bind(el, 'pointerdown', e => {
    pointers.set(e.pointerId, {x: e.clientX, y: e.clientY});
    el.setPointerCapture(e.pointerId);
    if (pointers.size >= 2) { pinchDist = pinchDistance(); dragging = false; moved = 99; return }
    dragging = true; moved = 0; lastX = e.clientX; lastY = e.clientY;
  });
  const release = e => {
    pointers.delete(e.pointerId); dragging = false;
    if (pointers.size < 2) pinchDist = 0;
    if (el.hasPointerCapture(e.pointerId)) el.releasePointerCapture(e.pointerId);
  };
  bind(el, 'pointerup', release);
  bind(el, 'pointercancel', e => { release(e); mouse.live = false });
  bind(el, 'pointermove', e => {
    const r = el.getBoundingClientRect();
    mouse.x = e.clientX - r.left; mouse.y = e.clientY - r.top; mouse.live = true;
    if (pointers.has(e.pointerId)) pointers.set(e.pointerId, {x: e.clientX, y: e.clientY});
    if (pointers.size >= 2) {
      const d = pinchDistance();
      if (pinchDist > 0 && d > 0) dolly(pinchDist / d);   // 两指张开 → 间距变大 → 因子 < 1 → 拉近
      pinchDist = d;
      return;
    }
    if (!dragging) return;
    const dx = e.clientX - lastX, dy = e.clientY - lastY;
    moved += Math.abs(dx) + Math.abs(dy);
    lastX = e.clientX; lastY = e.clientY;
    cam.tTheta -= dx * 0.0052;
    cam.tPhi = Math.max(0.12, Math.min(Math.PI - 0.12, cam.tPhi - dy * 0.0052));
    spin = false; syncTools();
  });
  bind(el, 'pointerleave', () => { mouse.live = false; hover = null; hoverEdge = null; syncHud() });
  // 拉近 = 距离变小，所以按钮上的「＋」对应的是 dolly(1/1.18)。
  const zlvl = els.zlvl;
  const syncZoom = () => { zlvl.textContent = Math.round(D0 / cam.tDist * 100) + '%' };
  const dolly = f => {
    cam.tDist = Math.max(D0 * 0.22, Math.min(D0 * 2.6, cam.tDist * f));
    syncZoom();
  };
  bind(el, 'wheel', e => {
    e.preventDefault();
    dolly(1 + Math.sign(e.deltaY) * 0.11);
  }, {passive: false});
  const zoomReset = () => {
    D0 = fitDist(stage.clientWidth / stage.clientHeight);
    cam.tDist = D0; syncZoom();
  };
  syncZoom();

  /* ── 拾取：不用 Raycaster。
        每帧本来就要把全部节点投影到屏幕上画标签，顺手拿这份屏幕坐标找最近的那个，
        比给可变大小的 Points 调 raycaster threshold 稳得多。 ── */
  const mouse = {x: -1, y: -1, live: false};
  let hover = null, hoverEdge = null, selected = null, selectedEdge = null, pathSet = null, pathEdges = null;
  // 每次打开概念或板块星图，默认开启连线动效、标签与自转；
  // 系统要求减少动态时，自转与沿边光点默认关掉，工具条上仍可手动打开。
  const reducedMotion = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  let spin = !reducedMotion, showLabels = true, flow = !reducedMotion;
  const off = new Set();                 // 被图例关掉的聚类
  const DIM = 0.12;

  const v3 = new THREE.Vector3();
  function project(w, h) {
    const px = coreMat.uniforms.uPx.value;
    for (const n of nodes) {
      v3.set(n.x, n.y, n.z);
      const dist = camera.position.distanceTo(v3);
      v3.project(camera);
      n.sx = (v3.x * 0.5 + 0.5) * w;
      n.sy = (-v3.y * 0.5 + 0.5) * h;
      n.sz = v3.z;
      // 拾取半径直接由渲染尺寸推出来，而不是另猜一个常数 ——
      // 猜的那个总会在某次调大小之后和眼睛看到的对不上。
      n.sr = n.size * n.scale * coreMat.uniforms.uMul.value * px / Math.max(dist, 1) * 0.5;
    }
  }

  bind(el, 'click', e => {
    if (moved > 5) return;               // 拖拽结束不该被当成一次点击
    const bounds = el.getBoundingClientRect();
    const hit = pick(e.clientX - bounds.left, e.clientY - bounds.top);
    if (hit.node) {
      if (e.shiftKey && selected && hit.node !== selected) { makePath(selected, hit.node); return }
      select(hit.node);
    } else if (hit.edge) selectEdge(hit.edge.i);
    else if (!e.shiftKey) clearSel();
  });

  /* ── 状态：选中 / 邻域 / 路径 决定每个节点与每条边的目标 alpha。
        真正的动画交给每帧的指数逼近，所以状态切换永远是渐变的。 ── */
  // 每帧都要算的三个数组，建一次用到底 —— 每帧新建会让 GC 在一分钟后开始打嗝。
  const nT = new Float32Array(nodes.length), sT = new Float32Array(nodes.length), eT = new Float32Array(edges.length);
  let query = '';
  function targets() {
    nT.fill(1); sT.fill(1); eT.fill(1);
    if (industryNetwork) for (const edge of edges) {
      eT[edge.i] = edge.kind === 'business' ? .8 : edge.s.cid === edge.t.cid ? .58 : .3;
    }
    const q = query;
    const hit = n => !q || n.name.toLowerCase().includes(q) || n.desc.toLowerCase().includes(q);

    for (const n of nodes) {
      // 显式查看某条关系时，两端暂时越过检索过滤；关闭关系后恢复原过滤。
      n.vis = n === selectedEdge?.s || n === selectedEdge?.t || (!off.has(n.cid) && hit(n));
      if (!n.vis) { nT[n.i] = 0; sT[n.i] = 0.6 }
    }
    for (const e of edges) if (!e.s.vis || !e.t.vis) eT[e.i] = 0;

    if (selectedEdge) {
      const pair = new Set([selectedEdge.s.i, selectedEdge.t.i]);
      for (const n of nodes) if (n.vis) { nT[n.i] = pair.has(n.i) ? 1 : DIM; sT[n.i] = pair.has(n.i) ? 1.65 : .75 }
      for (const e of edges) if (eT[e.i]) eT[e.i] = e === selectedEdge ? 2.4 : DIM * .35;
    } else if (pathSet) {
      for (const n of nodes) if (n.vis) { nT[n.i] = pathSet.has(n.i) ? 1 : DIM; sT[n.i] = pathSet.has(n.i) ? 1.25 : 0.8 }
      for (const e of edges) if (eT[e.i]) eT[e.i] = pathEdges?.has(e.i) ? 1.35 : DIM * 0.5;
    } else if (selected) {
      const near = new Set([selected.i, ...adj[selected.i]]);
      for (const n of nodes) if (n.vis) { nT[n.i] = near.has(n.i) ? 1 : DIM; sT[n.i] = n === selected ? 1.75 : near.has(n.i) ? 1.15 : 0.75 }
      for (const e of edges) if (eT[e.i]) eT[e.i] = (e.s === selected || e.t === selected) ? 1.4 : DIM * 0.45;
    }
    if (hover && hover.vis && (!selectedEdge || hover === selectedEdge.s || hover === selectedEdge.t)) {
      nT[hover.i] = 1; sT[hover.i] = Math.max(sT[hover.i], 1.6);
    }
    if (hoverEdge && eT[hoverEdge.i] >= .25) eT[hoverEdge.i] = Math.max(eT[hoverEdge.i], 1.8);
    return {nT, sT, eT};
  }

  function pick(x, y) {
    let node = null, edge = null, nearest = 6;
    for (const candidate of nodes) {
      if (!candidate.vis || candidate.sz > 1 || candidate.sz < -1) continue;
      if (Math.hypot(candidate.sx - x, candidate.sy - y) > candidate.sr + 7) continue;
      if (!node || candidate.sz < node.sz) node = candidate;
    }
    if (node) return {node, edge: null};
    for (const candidate of edges) {
      if (!candidate.s.vis || !candidate.t.vis || candidate.alpha < .2 || eT[candidate.i] < .25) continue;
      if (candidate.s.sz > 1 || candidate.t.sz > 1 || candidate.s.sz < -1 || candidate.t.sz < -1) continue;
      const dx = candidate.t.sx - candidate.s.sx, dy = candidate.t.sy - candidate.s.sy;
      const length2 = dx * dx + dy * dy;
      if (length2 < 1) continue;
      const t = Math.max(0, Math.min(1, ((x - candidate.s.sx) * dx + (y - candidate.s.sy) * dy) / length2));
      const distance = Math.hypot(x - candidate.s.sx - t * dx, y - candidate.s.sy - t * dy);
      if (distance < nearest) { nearest = distance; edge = candidate }
    }
    return {node: null, edge};
  }

  function clearRelation() {
    selectedEdge = null; hoverEdge = null;
    emit.relation?.(null); drawList(); syncHud();
  }
  function selectEdge(edgeId) {
    const edge = edges[edgeId];
    if (!edge) return null;
    selected = edge.s; selectedEdge = edge; pathSet = null; pathEdges = null; hover = null; hoverEdge = null;
    spin = false;
    els.pathbar.classList.remove('on');
    // 保持当前取景，使被点中的线停留原位。
    drawDrawer(edge.s); drawList(); syncTools(); syncHud();
    const payload = edgeRelation(graph, edge);
    emit.relation?.(payload);
    return payload;
  }

  function select(n) {
    if (!n) { clearSel(); return }
    clearRelation();
    selected = n; pathSet = null; pathEdges = null;
    els.pathbar.classList.remove('on');
    // 目标点带进相机中心，但不改距离 —— 突然拉近会让人丢失方位。
    cam.tx = n.x; cam.ty = n.y; cam.tz = n.z;
    cam.tDist = Math.min(cam.tDist, D0 * 0.72);
    drawDrawer(n); drawList(); syncHud();
  }
  function clearSel() {
    selected = null; pathSet = null; pathEdges = null;
    clearRelation();
    cam.tx = cam.ty = cam.tz = 0;
    els.pathbar.classList.remove('on');
    drawDrawer(null); drawList(); syncHud();
  }

  function makePath(a, b) {
    clearRelation();
    pathSet = null; pathEdges = null;
    const chain = graph.findPath(a.i, b.i, true);
    if (!chain) { els.chain.textContent = '当前关系方向下，两点之间没有通路'; els.pathbar.classList.add('on'); return }
    pathSet = new Set(chain);
    pathEdges = new Set();
    for (let index = 0; index < chain.length - 1; index++) {
      const from = chain[index], to = chain[index + 1];
      for (const edge of edges) if ((edge.s.i === from && edge.t.i === to) ||
        (!edge.directed && edge.s.i === to && edge.t.i === from)) pathEdges.add(edge.i);
    }
    els.chain.textContent = chain.map((i, index) => {
      if (!index) return nodes[i].name;
      const previous = chain[index - 1];
      const step = edges.find(edge => (edge.s.i === previous && edge.t.i === i) ||
        (!edge.directed && edge.s.i === i && edge.t.i === previous));
      return `${step?.directed ? ' → ' : ' — '}${nodes[i].name}`;
    }).join('');
    els.pathbar.classList.add('on');
    syncHud();
  }
  function clearPath() { pathSet = null; pathEdges = null; els.pathbar.classList.remove('on'); syncHud() }

  /* ── 标签池：固定数量的 div 循环使用。
        每帧新建节点会让 GC 在四十秒后开始打嗝。 ── */
  const labelHost = els.labels;
  const LABEL_BUDGET = industryNetwork ? 20 : 14;
  const pool = Array.from({length: 44}, () => {
    const d = document.createElement('div');
    d.className = 'lab'; d.style.opacity = 0;
    labelHost.appendChild(d); return d;
  });
  const topDeg = [...nodes].sort((a, b) => deg(b) - deg(a)).slice(0, LABEL_BUDGET).map(n => n.i);
  const representatives = industryNetwork ? CLUSTERS.filter(cluster => !cluster.evidenceGap).map(cluster =>
    nodes.filter(node => node.cid === cluster.id).sort((a, b) => deg(b) - deg(a) || a.i - b.i)[0]?.i
  ).filter(index => index !== undefined) : [];

  function drawLabels(w, h) {
    let k = 0;
    const want = new Set();
    if (showLabels && !selectedEdge) [...new Set([...representatives, ...topDeg])].slice(0, LABEL_BUDGET).forEach(i => want.add(i));
    if (selectedEdge) { want.add(selectedEdge.s.i); want.add(selectedEdge.t.i) }
    else if (selected) { want.add(selected.i); adj[selected.i].forEach(i => want.add(i)) }
    if (pathSet) pathSet.forEach(i => want.add(i));
    if (hover) want.add(hover.i);

    const priority = n => n === hover || n === selected || n === selectedEdge?.t || n === selectedEdge?.s ? 4 :
      pathSet?.has(n.i) ? 3 : representatives.includes(n.i) ? 2 : 1;
    const list = [...want].map(i => nodes[i])
      .filter(n => n.vis && n.sz < 1 && n.sx > -60 && n.sx < w + 60 && n.sy > -20 && n.sy < h + 20)
      .sort((a, b) => industryNetwork ? priority(b) - priority(a) || a.sz - b.sz : a.sz - b.sz);

    const taken = [];
    for (const n of list) {
      if (k >= pool.length) break;
      // 粗暴但足够的避让：占位矩形重叠就跳过。中文标签宽，宁可少画。
      const emphasized = n === hover || n === selected || selectedEdge?.t === n || selectedEdge?.s === n;
      const wpx = n.name.length * (industryNetwork ? emphasized ? 14 : 12.5 : 11.5) + (industryNetwork ? 12 : 8);
      const offsets = industryNetwork ? [[0, -20], [0, 20], [wpx / 2 + 12, 0], [-wpx / 2 - 12, 0]] : [[0, -17]];
      const placement = offsets.map(([dx, dy]) => industryNetwork ? [n.sx + dx - wpx / 2, n.sy + dy - 10, wpx, 20] :
        [n.sx - wpx / 2, n.sy - 18, wpx, 16])
        .find(box => (!industryNetwork || box[0] > 5 && box[0] + box[2] < w - 5 && box[1] > 8 && box[1] + box[3] < h - 60) &&
          !taken.some(t => box[0] < t[0] + t[2] && box[0] + box[2] > t[0] && box[1] < t[1] + t[3] && box[1] + box[3] > t[1]));
      if (!placement) continue;
      const box = placement;
      taken.push(box);
      const d = pool[k++];
      d.textContent = n.name;
      d.className = 'lab' + (emphasized ? '' : ' sm') + (industryNetwork ? ' industry-lab' : '');
      d.style.transform = `translate(-50%,-50%) translate(${(industryNetwork ? box[0] + box[2] / 2 : n.sx).toFixed(1)}px,${(industryNetwork ? box[1] + box[3] / 2 : n.sy - 17).toFixed(1)}px)`;
      d.style.opacity = Math.min(1, n.alpha * 1.3);
      d.style.color = emphasized ? n.cluster.color : '';
    }
    for (; k < pool.length; k++) pool[k].style.opacity = 0;
  }

  /* ── 主循环 ────────────────────────────────────────────────────── */
  let last = performance.now(), fpsAcc = 0, fpsN = 0;
  const posAttr = geo.getAttribute('position'), alpAttr = geo.getAttribute('aAlpha'), sclAttr = geo.getAttribute('aScale');
  const eposAttr = egeo.getAttribute('position'), ealpAttr = egeo.getAttribute('aAlpha');

  /* 渲染循环里任何一步抛异常（上下文丢失、shader 编译失败、驱动问题），
     都不能让它冒出去变成整页黑屏 —— 就地降级：关画布、左栏照常。 */
  let dead = false;
  function die(err) {
    if (dead) return; dead = true;
    console.error('[atlas] 渲染异常，已降级为列表模式：', err);
    cancelAnimationFrame(raf);
    unsubscribeTheme();
    ac.abort();
    geo.dispose(); egeo.dispose(); glowMat.dispose(); coreMat.dispose(); lineMat.dispose();
    arrowHeads.forEach(({arrow}) => arrow.dispose());
    try { renderer.dispose(); } catch (_) {}
    try { el.remove(); } catch (_) {}
    pool.forEach(d => d.remove());
    // 接管后续交互：把返回的 api 换成降级实现，左栏/详情继续可用
    const fb = makeFallback();
    for (const k of Object.keys(fb)) api[k] = fb[k];
  }
  el.addEventListener('webglcontextlost', e => { e.preventDefault(); die(e) }, {signal});

  function frame(now) {
    if (dead || !active) return;
    raf = requestAnimationFrame(frame);
    try { tick(now) } catch (err) { die(err) }
  }
  function tick(now) {
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const w = stage.clientWidth, h = stage.clientHeight;
    if (!w || !h) return;
    if (renderer.domElement.width !== Math.floor(w * renderer.getPixelRatio()) ||
        renderer.domElement.height !== Math.floor(h * renderer.getPixelRatio())) {
      renderer.setSize(w, h, false);
      camera.aspect = w / h; camera.updateProjectionMatrix();
      const nextFit = fitDist(camera.aspect);
      resizeCameraFit(cam, D0, nextFit);
      D0 = nextFit;
      syncZoom();
      glowMat.uniforms.uPx.value = coreMat.uniforms.uPx.value =
        h / (2 * Math.tan(camera.fov * Math.PI / 360));
    }

    graph.layout();

    if (spin) cam.tTheta += dt * 0.09;
    const k = 1 - Math.pow(0.0016, dt);      // 帧率无关的指数逼近
    cam.theta += (cam.tTheta - cam.theta) * k;
    cam.phi   += (cam.tPhi   - cam.phi)   * k;
    cam.dist  += (cam.tDist  - cam.dist)  * k;
    cam.cx += (cam.tx - cam.cx) * k; cam.cy += (cam.ty - cam.cy) * k; cam.cz += (cam.tz - cam.cz) * k;
    camera.position.set(
      cam.cx + cam.dist * Math.sin(cam.phi) * Math.cos(cam.theta),
      cam.cy + cam.dist * Math.cos(cam.phi),
      cam.cz + cam.dist * Math.sin(cam.phi) * Math.sin(cam.theta),
    );
    camera.lookAt(cam.cx, cam.cy, cam.cz);
    camera.updateMatrixWorld();

    project(w, h);
    const {nT, sT, eT} = targets();

    // 拾取：屏幕距离最近且在阈值内。深度用来在重叠时优先取近的。
    if (mouse.live && !dragging) {
      const hit = pick(mouse.x, mouse.y);
      if (hit.node !== hover || hit.edge !== hoverEdge) {
        hover = hit.node; hoverEdge = hit.edge;
        el.style.cursor = hover || hoverEdge ? 'pointer' : 'grab'; syncHud();
      }
    }

    const ka = 1 - Math.pow(0.002, dt);
    for (const n of nodes) {
      n.alpha += (nT[n.i] - n.alpha) * ka;
      n.scale += (sT[n.i] - n.scale) * ka;
      posAttr.array[n.i * 3] = n.x; posAttr.array[n.i * 3 + 1] = n.y; posAttr.array[n.i * 3 + 2] = n.z;
      alpAttr.array[n.i] = n.alpha; sclAttr.array[n.i] = n.scale;
    }
    posAttr.needsUpdate = alpAttr.needsUpdate = sclAttr.needsUpdate = true;

    for (const e of edges) {
      e.alpha += (eT[e.i] - e.alpha) * ka;
      const o = e.i * 6;
      eposAttr.array[o] = e.s.x; eposAttr.array[o + 1] = e.s.y; eposAttr.array[o + 2] = e.s.z;
      eposAttr.array[o + 3] = e.t.x; eposAttr.array[o + 4] = e.t.y; eposAttr.array[o + 5] = e.t.z;
      ealpAttr.array[e.i * 2] = ealpAttr.array[e.i * 2 + 1] = e.alpha;
    }
    eposAttr.needsUpdate = ealpAttr.needsUpdate = true;
    updateArrowHeads();

    lineMat.uniforms.uTime.value = now / 1000;
    lineMat.uniforms.uFlow.value += ((flow ? 1 : 0) - lineMat.uniforms.uFlow.value) * ka;
    glowMat.uniforms.uTime.value = now / 1000;
    glowMat.uniforms.uFlow.value = lineMat.uniforms.uFlow.value;

    drawLabels(w, h);
    renderer.render(scene, camera);

    fpsAcc += 1 / Math.max(dt, 1e-4); fpsN++;
    if (fpsN >= 30) { els.sFps.textContent = Math.round(fpsAcc / fpsN); fpsAcc = fpsN = 0 }
  }
  raf = requestAnimationFrame(frame);

  /* ── 控件 ──────────────────────────────────────────────────────── */
  const reheat = t => graph.reheat(t);

  function setView(v) {
    graph.setView(v);
    els.hudMode.textContent =
      ({atlas: '星图视图', shell: '球面视图', tier: graph.relationMode === 'classification' && edges.length ? '分类层级视图' : '平面视图'})[v];
    reheat(1);
  }
  const toggleFlow = () => { flow = !flow; syncTools() };
  const toggleLabel = () => { showLabels = !showLabels; syncTools() };
  const toggleSpin = () => { spin = !spin; syncTools() };
  function reset() {
    D0 = fitDist(stage.clientWidth / stage.clientHeight);
    cam.tTheta = 0.7; cam.tPhi = 1.15; cam.tDist = D0; clearSel(); reheat(0.8); syncZoom();
  }
  function syncTools() { emit.tools({flow, label: showLabels, spin}) }

  /* ── 主题 ──────────────────────────────────────────────────────────
     切主题要动四处，少一处就穿帮：CSS 令牌、聚类色、GPU 里的颜色缓冲、
     以及混合模式。混合模式是最容易忘的那个 —— 加性混合在白纸上会把
     所有节点烧成一片灰白，看着像渲染坏了。 */
  function applyTheme(mode) {
    emit.theme?.(mode);
    const light = mode === 'light';

    for (const c of CLUSTERS) c.color = c[mode];
    nodes.forEach((n, i) => {
      const c = hex(n.cluster.color);
      col[i * 3] = c[0]; col[i * 3 + 1] = c[1]; col[i * 3 + 2] = c[2];
    });
    geo.getAttribute('aColor').needsUpdate = true;
    edges.forEach((e, i) => {
      const typeColor = directedEdgeColor(e, mode);
      ecol.set(hex(typeColor || e.s.cluster.color), i * 6);
      ecol.set(hex(typeColor || e.t.cluster.color), i * 6 + 3);
    });
    egeo.getAttribute('aColor').needsUpdate = true;
    arrowHeads.forEach(({edge, arrow}) => arrow.setColor(directedEdgeColor(edge, mode)));

    const blend = light ? THREE.NormalBlending : THREE.AdditiveBlending;
    for (const m of [glowMat, coreMat, lineMat]) {
      m.uniforms.uLight.value = light ? 1 : 0;
      m.blending = blend;
      m.needsUpdate = true;
    }
    glowMat.uniforms.uMul.value = light ? 4.5 : 4.2;
    coreMat.uniforms.uMul.value = light ? 1.35 : 1.0;
    const bg = light ? 0xeff3fb : 0x050507;
    renderer.setClearColor(bg, 1);
    scene.fog.color.setHex(bg);
    scene.fog.density = light ? 0.0042 : 0.0068;   // 白底上雾走得太快会把远处洗成一片白

    drawList();
    if (selected) drawDrawer(selected);
  }

  bind(window, 'keydown', e => {
    if (!active) return;
    if (/^(INPUT|TEXTAREA)$/.test(e.target.tagName)) { if (e.key === 'Escape') e.target.blur(); return }
    if (e.key === 'Escape') clearSel();
    else if (e.key === 'l' || e.key === 'L') { showLabels = !showLabels; syncTools() }
    else if (e.key === 'r' || e.key === 'R') reset();
    else if (e.key === ' ') { e.preventDefault(); spin = !spin; syncTools() }
    else if (e.key === '/') { e.preventDefault(); els.q.focus() }
    else if (e.key === '=' || e.key === '+') dolly(1 / 1.18);
    else if (e.key === '-' || e.key === '_') dolly(1.18);
  });

  function syncHud() {
    const edge = hoverEdge || selectedEdge;
    const relationLabel = edge ? edgeCaption(graph, edge) : '';
    els.hudSel.textContent = relationLabel ||
      (pathSet ? `路径 ${Math.max(0, pathSet.size - 1)} 跳` : selected ? selected.name : hover ? hover.name : '未选中');
    el.title = hoverEdge ? relationLabel : hover?.name || '拖动旋转，滚轮缩放；点击节点或连线查看证据';
  }

  /* ── 左栏与抽屉 ────────────────────────────────────────────────── */
  function toggleCluster(id) {
    off.has(id) ? off.delete(id) : off.add(id);
    drawList(); reheat(0.4);
  }

  function drawList() {
    const q = query;
    const rows = nodes
      .filter(n => n === selectedEdge?.s || n === selectedEdge?.t ||
        (!off.has(n.cid) && (!q || n.name.toLowerCase().includes(q) || n.desc.toLowerCase().includes(q))))
      .sort((a, b) => deg(b) - deg(a));
    emit.list({
      q,
      rows: rows.map(n => ({i: n.i, name: n.name, color: n.cluster.color, deg: deg(n), on: n === selected || n === selectedEdge?.t})),
    });
    els.sNode.textContent = rows.length;
    const ec = edges.filter(e => rows.includes(e.s) && rows.includes(e.t)).length;
    els.sEdge.textContent = ec;
    els.sDeg.textContent = rows.length ? (ec * 2 / rows.length).toFixed(1) : '0';
  }
  const selectAt = i => select(nodes[i]);
  const hoverAt = i => { hover = i === null ? null : nodes[i]; hoverEdge = null; syncHud() };

  function setQuery(v) {
    query = v.trim().toLowerCase();
    drawList(); reheat(0.25);
  }

  function drawDrawer(n) {
    emit.drawer(drawerPayload(graph, n));
  }
  /* 「以此为中心」：把这个节点的锚点挪到原点，其余重新收敛。 */
  function centerOn(i) {
    const n = nodes[i], a = anchors[graph.getView()], base = a[n.i].slice();
    for (let k = 0; k < a.length; k++) { a[k][0] -= base[0]; a[k][1] -= base[1]; a[k][2] -= base[2] }
    cam.tx = cam.ty = cam.tz = 0; reheat(1);
  }
  function startPath(i) {
    const n = nodes[i];
    els.chain.innerHTML = `以 <b style="color:${n.cluster.color}">${n.name}</b> 为起点 —— 按住 Shift 点另一个节点`;
    els.pathbar.classList.add('on');
  }

  unsubscribeTheme = subscribeTheme(() => applyTheme(getTheme()));
  applyTheme(getTheme());
  drawList(); drawDrawer(null); syncTools(); syncHud();

  const api = {
    setView, toggleFlow, toggleLabel, toggleSpin, reset, toggleTheme,
    dolly, zoomReset, toggleCluster, selectAt, hoverAt, setQuery,
    selectEdge, clearRelation, clearPath, centerOn, startPath,
    updateMarketMetrics() {
      refreshMarketVisuals();
      nodes.forEach((node, i) => {
        siz[i] = node.size;
        brightness[i] = node.marketVisual.brightness;
        strength[i] = node.marketVisual.strength;
      });
      for (const name of ['aSize', 'aBrightness', 'aStrength']) geo.getAttribute(name).needsUpdate = true;
      drawList(); drawDrawer(selected);
    },
    setActive(value) {
      const next = !!value;
      if (next === active || dead) return;
      active = next;
      cancelAnimationFrame(raf);
      mouse.live = false; hover = null; hoverEdge = null;
      if (active) { last = performance.now(); raf = requestAnimationFrame(frame) }
    },
    dispose() {
      dead = true; unsubscribeTheme(); ac.abort(); cancelAnimationFrame(raf);
      geo.dispose(); egeo.dispose(); glowMat.dispose(); coreMat.dispose(); lineMat.dispose();
      arrowHeads.forEach(({arrow}) => arrow.dispose());
      try { renderer.dispose(); } catch (_) {} try { el.remove(); } catch (_) {}
      pool.forEach(d => d.remove());
    },
  };
  return api;
  }
}

export { conceptGraph, buildStockGraph, META };
