/** Explainable THS industry links. This module never changes catalog membership.
 * A theme edge records different companies in a common concept, not suppliers,
 * customers, hierarchy, causality, or an official industry-chain classification.
 */
const NEIGHBORS = 3;
const MIN_COMPANIES = 2;
const MIN_COVERAGE = 0.15;
const MIN_LIFT = 1.8;
const MEMBER_DOC = 'https://tushare.pro/document/2?doc_id=261';
const cmp = (a, b) => a < b ? -1 : a > b ? 1 : 0;
const sortedUnique = items => [...new Set(items || [])].sort(cmp);
const records = input => Array.isArray(input) ? input : Object.values(input || {});
const endpoint = value => typeof value === 'string' ? value : value?.code;
const pairKey = (a, b) => [a, b].sort(cmp).join('|');
const round = value => Number(value.toFixed(10));
const clone = value => JSON.parse(JSON.stringify(value));

// These labels describe trading eligibility, ownership, geography, finances,
// broad policy, or a whole ecosystem. They remain searchable concept nodes.
const EXCLUSION_RULES = [
  ['market_or_index_label', /融资融券|沪股通|深股通|样本股|成[份分]股|次新股|^ST板块$|^摘帽$|^同花顺|指数|^中国AI\s*50$/i],
  ['ownership_or_capital_label', /参股|持股|国企|央企|股权转让|并购重组|举牌|中字头|中船系|兵装重组|^创投$|独角兽|专精特新|超级品牌|^供销社$/],
  ['geographic_or_trade_policy_label', /自贸|自由贸易港|大湾区|京津冀|长三角|雄安|新疆振兴|横琴|西部大开发|海峡两岸|中韩|中俄|一带一路|共同富裕|特色小镇|俄乌冲突/],
  ['financial_or_property_policy_label', /人民币贬值|预增|高股息|化债|AMC|租售同权|土地流转|^PPP概念$/i],
  ['broad_umbrella_theme', /^(人工智能|AI应用|新能源汽车|机器人概念|高端装备|军工|军民融合|智慧城市|数字经济|新型工业化|新型城镇化|低空经济|乡村振兴|三胎概念|统一大市场|碳中和|养老概念)$/],
  ['broad_brand_ecosystem', /^(苹果概念|特斯拉概念|阿里巴巴概念|蚂蚁集团概念|腾讯概念|小米概念|富士康概念|宁德时代概念|百度概念|华为概念|拼多多概念|抖音概念\(字节概念\)|快手概念|比亚迪概念|英伟达概念|长安汽车概念|小红书概念|DeepSeek概念|智谱AI)$/i],
];

const STATISTICAL_METHOD = '双方代码分别与同花顺概念成员求交，先从双方同时剔除属于两个行业的同一公司；以完整行业成员数为覆盖率分母。仅使用双方各至少2家公司、覆盖率至少15%、相对全行业股票基准集中度至少1.8倍的主题。';
const THEME_BOUNDARY = '这是根据同花顺成员数据推导的共同主题关联，来自两行业的不同公司；不是官方产业链、上下游、供货关系或行业父子关系，也不代表两行业的所有公司均经营该业务。';

function normalize(input, kind) {
  const seen = new Set();
  return records(input).filter(row => {
    if (!row || !row.code || !row.name || !Array.isArray(row.members)) return false;
    if (kind === 'industry' && (row.level !== 'industry' || !/^881\d{3}\.TI$/.test(row.code))) return false;
    if (seen.has(row.code)) throw new Error('Duplicate ' + kind + ' code: ' + row.code);
    seen.add(row.code);
    return true;
  }).map(row => ({...row, members: sortedUnique(row.members)})).sort((a, b) => cmp(a.code, b.code));
}

function memberRef(board, role) {
  return {url: board.provenance?.membershipUrl || MEMBER_DOC,
    title: '同花顺板块成员 · Tushare Pro',
    locator: `ths_member ts_code=${board.code}; ${role}; membershipAsOf=${board.membershipAsOf || 'unknown'}`,
    excerpt: `${board.name}（${board.code}）成员快照；公司代码见本关系的 sharedThemes。`};
}

function orientedTheme(theme, reverse) {
  const a = reverse ? theme.b : theme.a, b = reverse ? theme.a : theme.b;
  return {...theme, a, b, fromCodes: a.codes, fromCount: a.count, fromTotal: a.total, fromCoverage: a.coverage,
    toCodes: b.codes, toCount: b.count, toTotal: b.total, toCoverage: b.coverage};
}

/** Inputs may be arrays or code/name keyed record objects. No input is mutated.
 * from/to are industry code strings; a/b in each sharedTheme follow that order.
 * Local top-3 choices are unioned, so incoming choices can produce degree >3.
 */
export function buildIndustryNetwork({industries = [], concepts = [], supplyRelations = []} = {}) {
  const industryRows = normalize(industries, 'industry');
  const conceptRows = normalize(concepts, 'concept');
  const byCode = new Map(industryRows.map(row => [row.code, row]));
  const stockIndustries = new Map();
  for (const industry of industryRows) for (const code of industry.members) {
    if (!stockIndustries.has(code)) stockIndustries.set(code, []);
    stockIndustries.get(code).push(industry.code);
  }
  const universeSize = stockIndustries.size;
  const candidates = new Map(), excludedThemes = [], usableThemes = [];
  let rejectedPairSupports = 0;
  for (const concept of conceptRows) {
    const exclusion = EXCLUSION_RULES.find(([, rule]) => rule.test(concept.name));
    if (exclusion || concept.code.startsWith('883')) {
      excludedThemes.push({code: concept.code, name: concept.name, reason: exclusion?.[0] || 'market_or_index_label'});
      continue;
    }
    const cohorts = new Map();
    let knownConceptCount = 0;
    for (const code of concept.members) {
      const industryCodes = stockIndustries.get(code);
      if (!industryCodes) continue;
      knownConceptCount++;
      for (const industryCode of industryCodes) {
        if (!cohorts.has(industryCode)) cohorts.set(industryCode, []);
        cohorts.get(industryCode).push(code);
      }
    }
    const industryCount = cohorts.size;
    const prevalence = universeSize ? knownConceptCount / universeSize : 0;
    // A label shared by most stocks cannot identify an industry connection.
    if (prevalence > 0.35) {
      excludedThemes.push({code: concept.code, name: concept.name, reason: 'too_universal', prevalence: round(prevalence)});
      continue;
    }
    const codes = [...cohorts.keys()].sort(cmp);
    const specificity = Math.log(1 + industryRows.length / Math.max(1, industryCount)) / Math.log(1 + Math.max(1, industryRows.length));
    let supportCount = 0;
    for (let i = 0; i < codes.length; i++) for (let j = i + 1; j < codes.length; j++) {
      const from = codes[i], to = codes[j];
      const fromSet = new Set(cohorts.get(from)), toSet = new Set(cohorts.get(to));
      const excludedSharedCodes = cohorts.get(from).filter(code => toSet.has(code));
      const fromCodes = cohorts.get(from).filter(code => !toSet.has(code));
      const toCodes = cohorts.get(to).filter(code => !fromSet.has(code));
      const fromTotal = byCode.get(from).members.length, toTotal = byCode.get(to).members.length;
      const fromCoverage = fromCodes.length / fromTotal, toCoverage = toCodes.length / toTotal;
      const fromLift = prevalence ? fromCoverage / prevalence : 0, toLift = prevalence ? toCoverage / prevalence : 0;
      if (fromCodes.length < MIN_COMPANIES || toCodes.length < MIN_COMPANIES
          || Math.min(fromCoverage, toCoverage) < MIN_COVERAGE || Math.min(fromLift, toLift) < MIN_LIFT) {
        rejectedPairSupports++;
        continue;
      }
      const reliability = Math.min(1, Math.sqrt(Math.min(fromCodes.length, toCodes.length)) / 3);
      const score = round(100 * Math.sqrt(fromCoverage * toCoverage) * specificity * reliability);
      const a = {codes: fromCodes, count: fromCodes.length, total: fromTotal, coverage: round(fromCoverage), lift: round(fromLift)};
      const b = {codes: toCodes, count: toCodes.length, total: toTotal, coverage: round(toCoverage), lift: round(toLift)};
      const shared = orientedTheme({code: concept.code, name: concept.name, a, b, excludedSharedCodes,
        conceptCount: concept.members.length, knownConceptCount, industryCount, prevalence: round(prevalence),
        specificity: round(specificity), score, membershipAsOf: concept.membershipAsOf || null,
        statisticalMethod: STATISTICAL_METHOD}, false);
      const key = pairKey(from, to);
      if (!candidates.has(key)) candidates.set(key, {from, to, sharedThemes: []});
      candidates.get(key).sharedThemes.push(shared);
      supportCount++;
    }
    usableThemes.push({code: concept.code, name: concept.name, supportingPairCount: supportCount});
  }
  const conceptByCode = new Map(conceptRows.map(row => [row.code, row]));
  for (const pair of candidates.values()) {
    pair.sharedThemes.sort((a, b) => b.score - a.score || cmp(a.code, b.code));
    pair.score = round(pair.sharedThemes.slice(0, 3).reduce((sum, theme, i) => sum + theme.score * [1, 0.35, 0.15][i], 0));
  }
  const business = [], rejectedBusinessRelations = [], businessPairs = new Set(), businessIds = new Set();
  const sourceBusiness = supplyRelations?.relations || supplyRelations;
  for (const row of records(sourceBusiness).slice().sort((a, b) => cmp(a.id || '', b.id || ''))) {
    const from = endpoint(row.from), to = endpoint(row.to);
    const valid = row.verificationStatus === 'verified' && ['supply-chain', 'business'].includes(row.type)
      && row.from?.system === 'ths' && row.to?.system === 'ths'
      && byCode.has(from) && byCode.has(to) && from !== to && row.sourceRefs?.length && row.statement && row.boundary;
    if (!valid) {
      rejectedBusinessRelations.push({id: row.id || null, reason: 'not_verified_ths_business_between_available_industries'});
      continue;
    }
    const id = row.id || `business:ths:${from}>${to}`;
    if (businessIds.has(id)) continue;
    businessIds.add(id);
    const key = pairKey(from, to), support = candidates.get(key);
    businessPairs.add(key);
    business.push({...clone(row), id, from, to, type: 'business', directed: true, score: support?.score || 0,
      sharedThemes: (support?.sharedThemes || []).map(theme => orientedTheme(theme, support.from !== from))});
  }
  const businessNeighbors = new Map(industryRows.map(row => [row.code, new Set()]));
  for (const edge of business) {
    businessNeighbors.get(edge.from).add(edge.to);
    businessNeighbors.get(edge.to).add(edge.from);
  }
  const themeCandidates = [...candidates.values()].filter(pair => !businessPairs.has(pairKey(pair.from, pair.to)));
  const chosen = new Set(), selectedNeighbors = {};
  for (const industry of industryRows) {
    const ranked = themeCandidates.filter(pair => pair.from === industry.code || pair.to === industry.code)
      .sort((a, b) => b.score - a.score || cmp(pairKey(a.from, a.to), pairKey(b.from, b.to)));
    const budget = Math.max(0, NEIGHBORS - businessNeighbors.get(industry.code).size);
    const picks = ranked.slice(0, budget);
    selectedNeighbors[industry.code] = {business: [...businessNeighbors.get(industry.code)].sort(cmp),
      themes: picks.map(pair => pair.from === industry.code ? pair.to : pair.from)};
    picks.forEach(pair => chosen.add(pairKey(pair.from, pair.to)));
  }
  const themes = themeCandidates.filter(pair => chosen.has(pairKey(pair.from, pair.to)))
    .map(pair => {
      const a = byCode.get(pair.from), b = byCode.get(pair.to), top = pair.sharedThemes[0];
      const dates = sortedUnique([a.membershipAsOf, b.membershipAsOf, ...pair.sharedThemes.map(theme => theme.membershipAsOf)].filter(Boolean));
      return {id: `theme:ths:${pair.from}|${pair.to}`, from: pair.from, to: pair.to, type: 'theme', directed: false,
        score: pair.score, label: top.name, verificationStatus: 'derived', asOf: dates.length === 1 ? dates[0] : null,
        membershipDates: dates, sharedThemes: pair.sharedThemes,
        statement: `${a.name}与${b.name}的不同公司共同涉及“${top.name}”：分别${top.a.count}家、${top.b.count}家进入该概念。`,
        boundary: THEME_BOUNDARY,
        sourceRefs: [memberRef(a, 'from industry'), memberRef(b, 'to industry'),
          ...pair.sharedThemes.map(theme => memberRef(conceptByCode.get(theme.code), 'shared concept'))]};
    }).sort((a, b) => b.score - a.score || cmp(a.id, b.id));
  const relations = [...business, ...themes];
  const neighbors = new Map(industryRows.map(row => [row.code, []]));
  for (const edge of relations) {
    neighbors.get(edge.from).push({code: edge.to, type: edge.type, score: edge.score, id: edge.id,
      themes: edge.sharedThemes.map(theme => theme.name)});
    neighbors.get(edge.to).push({code: edge.from, type: edge.type, score: edge.score, id: edge.id,
      themes: edge.sharedThemes.map(theme => theme.name)});
  }
  const isolatedIndustryCodes = industryRows.filter(row => !neighbors.get(row.code).length).map(row => row.code);
  return {relations, coverage: {
    industryCount: industryRows.length, industryCodes: industryRows.map(row => row.code), conceptCount: conceptRows.length,
    businessRelationCount: business.length, themeRelationCount: themes.length,
    connectedIndustryCount: industryRows.length - isolatedIndustryCodes.length, isolatedIndustryCodes,
    candidateThemeRelationCount: themeCandidates.length, eligibleThemeCount: usableThemes.length,
    usedThemeCount: new Set(relations.flatMap(edge => edge.sharedThemes.map(theme => theme.code))).size,
    excludedThemes, usableThemes, rejectedPairSupports, rejectedBusinessRelations, selectedNeighbors,
    neighborLimit: NEIGHBORS, minCompaniesPerSide: MIN_COMPANIES, minCoveragePerSide: MIN_COVERAGE, minLiftPerSide: MIN_LIFT,
    neighborSummary: industryRows.map(row => ({code: row.code, name: row.name,
      neighbors: neighbors.get(row.code).sort((a, b) => (a.type === 'business' ? 0 : 1) - (b.type === 'business' ? 0 : 1)
        || b.score - a.score || cmp(a.code, b.code))})),
    method: '业务边沿用有来源的已核验关系并优先保留。主题评分=100×双方覆盖率几何均值×概念行业专属性×样本量权重；边分取最强三个主题按1/0.35/0.15加权。每行业优先计入业务邻居，再选最强主题邻居补到3，最终取双方选择的并集，故部分节点度数可超过3；不为孤点补边。',
    statisticalMethod: STATISTICAL_METHOD, boundary: THEME_BOUNDARY,
    universeStockCount: universeSize, source: '同花顺 ths_index/ths_member 成员快照；关系为本地数据推导',
  }};
}
