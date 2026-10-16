/** Lightweight membership evidence for company reading; no graph or quote dependencies. */
/** @typedef {{code:string, name:string, members:string[], membershipAsOf:string|null}} MembershipBoard */
/** @typedef {{industries:MembershipBoard[], concepts:MembershipBoard[], membershipAsOf:string|null, excludedConceptCount:number}} CompanyMemberships */
/** @typedef {{code:string, industryNames:string[], conceptNames:string[], score:number}} RelatedCompany */

const compare = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const unique = values => [...new Set(values)];
const stockCode = /^\d{6}\.(SH|SZ|BJ)$/;
// Keep aligned with industry-network.js: these labels do not establish business similarity.
const excludedLabels = [
  /融资融券|沪股通|深股通|样本股|成[份分]股|次新股|^ST板块$|^摘帽$|^同花顺|指数|^中国AI\s*50$/i,
  /参股|持股|国企|央企|股权转让|并购重组|举牌|中字头|中船系|兵装重组|^创投$|独角兽|专精特新|超级品牌|^供销社$/,
  /自贸|自由贸易港|大湾区|京津冀|长三角|雄安|新疆振兴|横琴|西部大开发|海峡两岸|中韩|中俄|一带一路|共同富裕|特色小镇|俄乌冲突/,
  /人民币贬值|预增|高股息|化债|AMC|租售同权|土地流转|^PPP概念$/i,
  /^(人工智能|AI应用|新能源汽车|机器人概念|高端装备|军工|军民融合|智慧城市|数字经济|新型工业化|新型城镇化|低空经济|乡村振兴|三胎概念|统一大市场|碳中和|养老概念)$/,
  /^(苹果概念|特斯拉概念|阿里巴巴概念|蚂蚁集团概念|腾讯概念|小米概念|富士康概念|宁德时代概念|百度概念|华为概念|拼多多概念|抖音概念\(字节概念\)|快手概念|比亚迪概念|英伟达概念|长安汽车概念|小红书概念|DeepSeek概念|智谱AI)$/i,
];

/** Build-time projection: discard quotes, graph metadata and broad labels; never mutate input.
 * @param {any} evidence
 * @returns {CompanyMemberships}
 */
export function compactCompanyMemberships(evidence) {
  const date = evidence?.membershipAsOf || evidence?.industryMembershipAsOf || null;
  const compact = (input, level) => {
    const seen = new Set();
    return Object.values(input || {}).filter(board => board?.level === level && board.code && board.name && !seen.has(board.code) && seen.add(board.code))
      .map(board => ({code: board.code, name: board.name,
        members: unique((board.members || []).filter(code => typeof code === 'string' && stockCode.test(code))).sort(compare),
        membershipAsOf: board.membershipAsOf || date})).sort((a, b) => compare(a.code, b.code));
  };
  const industries = compact(evidence?.industries, 'industry');
  const universe = new Set(industries.flatMap(board => board.members));
  const allConcepts = compact(evidence?.boards, 'concept');
  const concepts = allConcepts.filter(board => !board.code.startsWith('883') && !excludedLabels.some(rule => rule.test(board.name))
    && (!universe.size || board.members.filter(code => universe.has(code)).length / universe.size <= 0.35));
  return {industries, concepts, membershipAsOf: date, excludedConceptCount: allConcepts.length - concepts.length};
}

const prepared = new WeakMap();
/** @param {CompanyMemberships} membership */
function prepare(membership) {
  if (prepared.has(membership)) return prepared.get(membership);
  const industries = new Map(), concepts = new Map();
  for (const [boards, lookup] of [[membership.industries, industries], [membership.concepts, concepts]]) {
    for (const board of boards) for (const code of board.members) {
      if (!lookup.has(code)) lookup.set(code, []);
      lookup.get(code).push(board);
    }
  }
  const result = {industries, concepts};
  prepared.set(membership, result);
  return result;
}

/** Exact THS industry peers, then other companies sharing eligible concepts.
 * industryNames contains shared THS industries only; conceptNames is symmetric shared evidence.
 * Score = inverse-member support × concept Jaccard, for ordering rather than a confidence claim.
 * Membership is immutable for the lifetime of this module's WeakMap cache. No result budget.
 * @param {CompanyMemberships} membership
 * @param {Array<{code:string}>} indexCompanies Current listed-company directory is authoritative.
 * @param {string} code
 * @returns {{industries:Array<{code:string,name:string}>, peers:RelatedCompany[], concepts:RelatedCompany[], membershipAsOf:string|null, excludedConceptCount:number}}
 */
export function getRelatedCompanies(membership, indexCompanies, code) {
  const empty = {industries: [], peers: [], concepts: [], membershipAsOf: membership.membershipAsOf,
    excludedConceptCount: membership.excludedConceptCount};
  const allowed = new Set(indexCompanies.map(company => company.code));
  if (!allowed.has(code)) return empty;
  const lookup = prepare(membership);
  const ownIndustries = lookup.industries.get(code) || [], ownConcepts = lookup.concepts.get(code) || [];
  const ownIndustryCodes = new Set(ownIndustries.map(board => board.code));
  const ownConceptCodes = new Set(ownConcepts.map(board => board.code));
  const candidates = new Set([...ownIndustries, ...ownConcepts].flatMap(board => board.members));
  /** @type {RelatedCompany[]} */
  const peers = [], concepts = [];
  for (const candidate of candidates) {
    if (candidate === code || !allowed.has(candidate)) continue;
    const sharedIndustries = (lookup.industries.get(candidate) || []).filter(board => ownIndustryCodes.has(board.code));
    const otherConcepts = lookup.concepts.get(candidate) || [];
    const sharedConcepts = otherConcepts.filter(board => ownConceptCodes.has(board.code))
      .sort((a, b) => a.members.length - b.members.length || compare(a.code, b.code));
    const unionSize = ownConcepts.length + otherConcepts.length - sharedConcepts.length;
    const support = sharedConcepts.reduce((sum, board) => sum + 1 / Math.max(1, board.members.length), 0);
    const row = {code: candidate, industryNames: unique(sharedIndustries.map(board => board.name)),
      conceptNames: unique(sharedConcepts.map(board => board.name)), score: unionSize ? support * sharedConcepts.length / unionSize : 0};
    if (sharedIndustries.length) peers.push(row);
    else if (sharedConcepts.length) concepts.push(row);
  }
  const rank = (a, b) => b.score - a.score || compare(a.code, b.code);
  return {...empty, industries: ownIndustries.map(({code: boardCode, name}) => ({code: boardCode, name})),
    peers: peers.sort(rank), concepts: concepts.sort(rank)};
}
