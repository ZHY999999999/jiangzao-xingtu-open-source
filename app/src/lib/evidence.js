import data from './evidence-data.json';
import industryData from './industry-relations.json';
import supplyData from './supply-chain-relations.json';
import { buildIndustryNetwork } from './industry-network.js';
import { buildBoardIndex } from './board-index.js';
import { aggregateMarketCap, validateMarketSnapshot } from './market-cap.js';

export const EVIDENCE = data;
export const INDUSTRY_DATA = industryData;
const initialMarketDate = String(data.tradeDate).replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3');
export const MARKET_CAP = {tradeDate: initialMarketDate, status: 'bundled', revision: 0};
let marketRequest;
export function refreshMarketSnapshot() {
  if (marketRequest) return marketRequest;
  marketRequest = (async () => {
    try {
      const response = await fetch(`${import.meta.env.BASE_URL}data/market/latest.json`, {cache:'no-store', signal:AbortSignal.timeout(12000)});
      if (!response.ok) throw new Error('Market snapshot unavailable');
      const snapshot = await response.json();
      if (!validateMarketSnapshot(snapshot, MARKET_CAP.tradeDate)) throw new Error('Invalid market snapshot');
      const revision = `${snapshot.tradeDate}:${snapshot.snapshotId || snapshot.contentHash || JSON.stringify(snapshot.stocks)}`;
      if (revision === lastMarketRevision) { MARKET_CAP.status = 'current'; return false; }
      // Clear missing values; never silently mix a past valuation with today's.
      for (const [code, stock] of Object.entries(EVIDENCE.stocks)) stock.mv = snapshot.stocks[code]?.mv ?? null;
      for (const boards of [EVIDENCE.boards, EVIDENCE.industries]) {
        for (const board of Object.values(boards || {})) Object.assign(board, aggregateMarketCap(board.members, EVIDENCE.stocks));
      }
      adaptedBoards.clear(); boardIndexes.clear();
      MARKET_CAP.tradeDate = snapshot.tradeDate; MARKET_CAP.status = 'current'; MARKET_CAP.revision++;
      lastMarketRevision = revision;
      return true;
    } catch { MARKET_CAP.status = 'retained'; return false; }
    finally { marketRequest = null; }
  })();
  return marketRequest;
}
let lastMarketRevision;
// Revalue existing graph objects in place: saved camera, anchors and selection survive.
export function refreshGraphMarketCaps(graph) {
  for (const node of new Set([...(graph.nodes || []), ...(graph.directoryNodes || [])])) {
    if (!node.meta) continue;
    if (graph.mode === 'stock') node.meta.mv = getStockEvidence(node.meta.code)?.mv ?? null;
    else Object.assign(node.meta, aggregateMarketCap(node.meta.members || getBoardMembers(node.meta.code, node.meta.boardKind, node.meta.system), EVIDENCE.stocks));
    node.meta.marketCapDate = MARKET_CAP.tradeDate;
  }
}
const source = 'Tushare · 同花顺概念成分';
const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const finite = value => typeof value === 'number' && Number.isFinite(value);
const financialIndustries = new Set(['银行', '证券', '保险', '多元金融']);
const conceptSets = new Map();
const memberSets = new Map();
const relationCache = new Map();
const boardIndexes = new Map();
const adaptedBoards = new Map();
let industryNetwork;

export const BOARD_KINDS = ['concept', 'industry', 'subindustry'];

/** Native catalog levels stay separate; a layout group is never a taxonomy. */
export function getBoardRecords(kind = 'concept', system = 'ths') {
  if (system === 'sw2021' && kind !== 'concept') {
    if (!adaptedBoards.has(kind)) adaptedBoards.set(kind, industryData.boards.filter(board => board.level === kind).map(board => {
      const stocks = board.members.map(code => EVIDENCE.stocks[code]).filter(Boolean);
      const quoted = stocks.filter(stock => finite(stock.amount)), valued = stocks.filter(stock => finite(stock.mv));
      return {...board, system, count:board.members.length, pct:null, weightedPct:null,
        amount:quoted.length ? quoted.reduce((sum, stock) => sum + stock.amount, 0) : null,
        mv:valued.length ? valued.reduce((sum, stock) => sum + stock.mv, 0) : null,
        amountCount:quoted.length, quotedCount:quoted.length, mvCount:valued.length,
        provenance:{hierarchyVerified:true, sourceUrl:'https://tushare.pro/document/2?doc_id=181', membershipUrl:'https://tushare.pro/document/2?doc_id=335'},
      };
    }));
    return adaptedBoards.get(kind);
  }
  if (kind === 'concept') return Object.values(EVIDENCE.boards || {});
  if (kind === 'industry' || kind === 'subindustry') {
    return Object.values(EVIDENCE.industries || {}).filter(board => board.level === kind);
  }
  return [];
}

export function getBoardEvidence(nameOrCode, kind = 'concept', system = 'ths') {
  const cacheKey = `${system}:${kind}`;
  if (!boardIndexes.has(cacheKey)) boardIndexes.set(cacheKey, buildBoardIndex(getBoardRecords(kind, system)));
  return boardIndexes.get(cacheKey).get(nameOrCode) || null;
}

export function getBoardMembers(nameOrCode, kind = 'concept', system = 'ths') {
  return [...new Set(getBoardEvidence(nameOrCode, kind, system)?.members || [])];
}

export function getIndustryRelations(type = 'classification', system = 'sw2021') {
  return [...industryData.relations, ...supplyData.relations].filter(relation => relation.type === type
    && relation.verificationStatus === 'verified' && relation.from.system === system && relation.to.system === system);
}

/** A separate derived view: no changes to catalogs or stock memberships. */
export function getIndustryNetwork() {
  if (!industryNetwork) industryNetwork = buildIndustryNetwork({
    industries: getBoardRecords('industry', 'ths'),
    concepts: getBoardRecords('concept', 'ths'),
    supplyRelations: getIndustryRelations('supply-chain', 'ths'),
  });
  return industryNetwork;
}

export function getBoardHierarchy(code, kind, system = 'sw2021') {
  const relations = getIndustryRelations('classification', system);
  const resolve = ref => getBoardEvidence(ref.code, ref.kind, system);
  return {
    parents: relations.filter(r => r.to.code === code && r.to.kind === kind).map(r => ({...resolve(r.from), relation:r})),
    children: relations.filter(r => r.from.code === code && r.from.kind === kind).map(r => ({...resolve(r.to), relation:r})),
  };
}

export function getStockClassification(code, system = 'sw2021') {
  return ['sector','industry','subindustry'].flatMap(kind => getBoardRecords(kind, system)
    .filter(board => board.members.includes(code)).map(board => ({code:board.code,name:board.name,level:kind,system})));
}

export function getConceptEvidence(nameOrCode) { return getBoardEvidence(nameOrCode); }
export function getStockEvidence(code) {
  return EVIDENCE.stocks[code] || (industryData.stockNames?.[code] ? {
    code, name:industryData.stockNames[code], concepts:[], thsIndustries:[], listStatus:null,
    pct:null,amount:null,mv:null,mainBusiness:null,revenue:null,profit:null,
    ...industryData.stockStatuses?.[code],
  } : null);
}

/** Compatibility API. Activity/strength remain empty when their evidence was not fetched. */
export function getLeaderboards(name, kind = 'concept', system = 'ths') {
  const members = getBoardMembers(name, kind, system);
  const rank = (field, filter = () => true) => members
    .filter(code => finite(EVIDENCE.stocks[code]?.[field]) && filter(EVIDENCE.stocks[code]))
    .sort((a, b) => EVIDENCE.stocks[b][field] - EVIDENCE.stocks[a][field] || compare(a, b))
    .slice(0, 5);
  return {
    scale: rank('mv'),
    activity: rank('amount5'),
    strength: rank('return5', s => s.return5 > 0 && !s.isST),
  };
}

/** Company-wide fiscal revenue, never a conclusion about concept revenue or industry standing. */
export function getBoardCandidates(boardNameOrCode, industry, kind = 'concept', system = 'ths') {
  return getBoardMembers(boardNameOrCode, kind, system)
    .filter(code => {
      const s = getStockEvidence(code);
      return s && s.industry && finite(s.revenue) && s.revenue > 0
        && s.reportPeriod === EVIDENCE.financialPeriod
        && (industry ? s.industry === industry : !s.isFinancial && !financialIndustries.has(s.industry));
    })
    .sort((a, b) => EVIDENCE.stocks[b].revenue - EVIDENCE.stocks[a].revenue || compare(a, b))
    .slice(0, 5);
}

export function getIndustryCandidates(boardNameOrCode, industry, kind = 'concept') {
  return getBoardCandidates(boardNameOrCode, industry, kind);
}

function concepts(code) {
  if (!conceptSets.has(code)) conceptSets.set(code, new Set(getStockEvidence(code)?.concepts || []));
  return conceptSets.get(code);
}
function members(nameOrCode, kind, system = 'ths') {
  const board = getBoardEvidence(nameOrCode, kind, system), key = `${system}:${kind}:${board?.code || nameOrCode}`;
  if (!memberSets.has(key)) memberSets.set(key, new Set(board?.members || []));
  return memberSets.get(key);
}
function intersection(a, b) { return [...a].filter(x => b.has(x)).sort(compare); }

export function getStockRelation(codeA, codeB) {
  const [a, b] = [codeA, codeB].sort(compare);
  const key = `${a}|${b}`;
  if (!relationCache.has(key)) {
    const as = concepts(a), bs = concepts(b), sharedConcepts = intersection(as, bs);
    const unionCount = as.size + bs.size - sharedConcepts.length;
    const industry = getStockEvidence(a)?.industry;
    relationCache.set(key, {
      sharedConcepts, sharedCount: sharedConcepts.length, unionCount,
      overlapPct: unionCount ? sharedConcepts.length / unionCount * 100 : 0,
      sameIndustry: industry && industry === getStockEvidence(b)?.industry ? industry : null,
      sameIndustrySource: 'Tushare · stock_basic（公司基础资料行业）',
      sameIndustryAsOf: getStockEvidence(a)?.industryAsOf || null,
      source, asOf: EVIDENCE.membershipAsOf,
    });
    // Bound memory when a user visits many distinct drill-downs in one session.
    if (relationCache.size > 25000) relationCache.delete(relationCache.keys().next().value);
  }
  return relationCache.get(key);
}

export function getBoardRelation(nameA, nameB, kind = 'concept', system = 'ths') {
  const boardA = getBoardEvidence(nameA, kind, system), boardB = getBoardEvidence(nameB, kind, system);
  const a = members(nameA, kind, system), b = members(nameB, kind, system), sharedCodes = intersection(a, b);
  const unionCount = a.size + b.size - sharedCodes.length;
  const sources = [...new Set([boardA?.source, boardB?.source].filter(Boolean))];
  const membershipDates = [...new Set([boardA?.membershipAsOf, boardB?.membershipAsOf].filter(Boolean))].sort(compare);
  return {
    sharedStocks: sharedCodes.map(code => ({ code, name: getStockEvidence(code)?.name || code })),
    sharedCount: sharedCodes.length, unionCount,
    overlapPct: unionCount ? sharedCodes.length / unionCount * 100 : 0,
    boardKind: kind,
    source: sources.join('；') || (kind === 'concept' ? source : 'Tushare · 同花顺行业成分'),
    asOf: membershipDates.length ? membershipDates.join(' / ') : EVIDENCE.membershipAsOf,
    hierarchyVerified: false,
  };
}

export function getConceptRelation(nameA, nameB) { return getBoardRelation(nameA, nameB); }

/** Union of each visible stock's two strongest concept overlaps; no inferred direction. */
export function getStockEdges(codes) {
  const unique = [...new Set(codes)].filter(code => getStockEvidence(code)).sort(compare);
  const neighbors = new Map(unique.map(code => [code, []]));
  for (let i = 0; i < unique.length; i++) {
    for (let j = i + 1; j < unique.length; j++) {
      const a = unique[i], b = unique[j], sharedCount = getStockRelation(a, b).sharedCount;
      if (sharedCount < 3) continue;
      neighbors.get(a).push({ code: b, sharedCount });
      neighbors.get(b).push({ code: a, sharedCount });
    }
  }
  const selected = new Map();
  for (const code of unique) {
    const best = neighbors.get(code).sort((a, b) => b.sharedCount - a.sharedCount || compare(a.code, b.code)).slice(0, 2);
    for (const neighbor of best) {
      const [a, b] = [code, neighbor.code].sort(compare), key = `${a}|${b}`;
      if (!selected.has(key)) selected.set(key, { a, b, sharedCount: neighbor.sharedCount, selectedBy: [] });
      selected.get(key).selectedBy.push(code);
    }
  }
  return [...selected.values()].sort((a, b) => compare(a.a, b.a) || compare(a.b, b.b));
}
