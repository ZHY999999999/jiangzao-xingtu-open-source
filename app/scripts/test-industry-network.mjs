import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import {buildIndustryNetwork} from '../src/lib/industry-network.js';

const fixture = () => Array.from({length: 12}, (_, i) => ({code: `881${String(100 + i)}.TI`,
  name: `行业${i}`, level: 'industry', membershipAsOf: '20260922',
  members: Array.from({length: 20}, (_, j) => `${i}_${j}.SH`)}));
const concept = (industries, a = 0, b = 1, count = 4, name = '共封装光学(CPO)', code = '886033.TI') =>
  ({code, name, level: 'concept', membershipAsOf: '20260922',
    members: [...industries[a].members.slice(0, count), ...industries[b].members.slice(0, count)]});
const freeze = object => {
  if (object && typeof object === 'object') {Object.values(object).forEach(freeze); Object.freeze(object);}
  return object;
};
const business = (from, to, id = 'supply:ths:test') => ({id, type: 'supply-chain',
  from: {system: 'ths', kind: 'industry', code: from}, to: {system: 'ths', kind: 'industry', code: to},
  statement: '已有来源限定的产品应用关系', boundary: '不证明具体公司供货', verificationStatus: 'verified',
  asOf: '2026-09-22', sourceRefs: [{url: 'https://www.miit.gov.cn/', title: 'Fixture evidence'}]});

test('keeps all industries, identifies isolates and never connects them by force', () => {
  const industries = fixture(), result = buildIndustryNetwork({industries, concepts: [concept(industries)]});
  assert.equal(result.coverage.industryCount, 12);
  assert.equal(result.coverage.connectedIndustryCount, 2);
  assert.equal(result.coverage.isolatedIndustryCodes.length, 10);
  assert.equal(result.relations.length, 1);
  const edge = result.relations[0], support = edge.sharedThemes[0];
  assert.equal(edge.type, 'theme'); assert.equal(edge.directed, false);
  assert.equal(edge.verificationStatus, 'derived'); assert.match(edge.boundary, /不是官方产业链/);
  assert.equal(edge.label, '共封装光学(CPO)');
  assert.deepEqual(support.a.codes, industries[0].members.slice(0, 4));
  assert.equal(support.a.count, 4); assert.equal(support.a.coverage, 0.2);
});

test('filters market, ownership, regional, financial and umbrella labels only from inference', () => {
  const industries = fixture();
  const names = ['融资融券', '沪深300样本股', '国企改革', '参股银行', '上海自贸区', '2026中报预增',
    '人民币贬值受益', '人工智能', 'AI应用', '新能源汽车', 'DeepSeek概念'];
  const concepts = names.map((name, i) => concept(industries, 0, 1, 8, name, `886${String(i).padStart(3, '0')}.TI`));
  const before = JSON.stringify(concepts);
  const result = buildIndustryNetwork({industries, concepts: freeze(concepts)});
  assert.equal(result.relations.length, 0);
  assert.equal(result.coverage.excludedThemes.length, names.length);
  assert.equal(JSON.stringify(concepts), before);
});

test('one common company or even multiple identical companies cannot bridge two industries', () => {
  const industries = fixture();
  industries[1].members = [...industries[0].members.slice(0, 4), ...industries[1].members.slice(4)];
  const theme = {...concept(industries), members: industries[0].members.slice(0, 4)};
  assert.equal(buildIndustryNetwork({industries, concepts: [theme]}).relations.length, 0);
});

test('shared companies are removed from both sides while remaining different companies are auditable', () => {
  const industries = fixture();
  industries[1].members.push(industries[0].members[0]);
  const result = buildIndustryNetwork({industries, concepts: [concept(industries)]});
  const t = result.relations[0].sharedThemes[0];
  assert.deepEqual(t.excludedSharedCodes, [industries[0].members[0]]);
  assert.equal(t.a.count, 3); assert.equal(t.b.count, 4);
  assert.equal(t.a.codes.some(code => t.b.codes.includes(code)), false);
});

test('weak coverage and universal themes cannot form bridges', () => {
  const industries = fixture();
  industries[0].members.push(...Array.from({length: 200}, (_, i) => `extra_${i}.SH`));
  assert.equal(buildIndustryNetwork({industries, concepts: [concept(industries)]}).relations.length, 0);
  const all = {code: '886999.TI', name: '宽泛标签', members: industries.flatMap(row => row.members)};
  const result = buildIndustryNetwork({industries, concepts: [all]});
  assert.equal(result.relations.length, 0); assert.equal(result.coverage.excludedThemes[0].reason, 'too_universal');
});

test('specific themes outrank equally covered but widespread themes without member duplication inflation', () => {
  const industries = fixture();
  const narrow = concept(industries, 0, 1, 4, '具体材料', '886001.TI');
  const broad = {...narrow, name: '通用技术', code: '886002.TI',
    members: [...narrow.members, ...industries.slice(2, 6).flatMap(row => row.members.slice(0, 4))]};
  const result = buildIndustryNetwork({industries, concepts: [broad, {...narrow, members: [...narrow.members, ...narrow.members]}]});
  const edge = result.relations.find(row => row.from === industries[0].code && row.to === industries[1].code);
  assert.equal(edge.sharedThemes.length, 2);
  assert.equal(edge.sharedThemes[0].code, narrow.code);
  assert.ok(edge.sharedThemes[0].score > edge.sharedThemes[1].score);
  assert.equal(edge.sharedThemes[0].a.count, 4);
  assert.equal(edge.sharedThemes[0].conceptCount, 8);
});

test('validated business edges remain directed, prioritized and separate from derived claims', () => {
  const industries = fixture();
  const source = business(industries[1].code, industries[0].code);
  const rejected = {...source, id: 'bad', verificationStatus: 'candidate'};
  const result = buildIndustryNetwork({industries, concepts: [concept(industries)], supplyRelations: {relations: [rejected, source]}});
  assert.equal(result.relations.length, 1);
  const edge = result.relations[0];
  assert.equal(edge.from, industries[1].code); assert.equal(edge.type, 'business'); assert.equal(edge.directed, true);
  assert.equal(edge.statement, source.statement); assert.deepEqual(edge.sourceRefs, source.sourceRefs);
  assert.deepEqual(edge.sharedThemes[0].a.codes, industries[1].members.slice(0, 4));
  assert.equal(result.coverage.rejectedBusinessRelations.length, 1);
});

test('local top-three choices union may give a hub more than three neighbors', () => {
  const industries = fixture();
  const concepts = Array.from({length: 6}, (_, i) => concept(industries, 0, i + 1, 4, `具体产品${i}`, `88600${i}.TI`));
  const result = buildIndustryNetwork({industries, concepts});
  assert.equal(result.coverage.selectedNeighbors[industries[0].code].themes.length, 3);
  assert.equal(result.relations.length, 6);
  for (const edge of result.relations) {
    assert.ok(result.coverage.selectedNeighbors[edge.from].themes.includes(edge.to)
      || result.coverage.selectedNeighbors[edge.to].themes.includes(edge.from));
  }
});

test('business neighbors consume local selection slots and cannot be dropped by theme score', () => {
  const industries = fixture();
  const concepts = Array.from({length: 4}, (_, i) => concept(industries, 0, i + 4, 4, `具体产品${i}`, `88600${i}.TI`));
  const supplyRelations = [1, 2, 3].map(i => business(industries[0].code, industries[i].code, 'business' + i));
  const result = buildIndustryNetwork({industries, concepts, supplyRelations});
  assert.equal(result.coverage.businessRelationCount, 3);
  assert.equal(result.coverage.selectedNeighbors[industries[0].code].themes.length, 0);
});

test('input permutations and keyed records give deterministic immutable output', () => {
  const industries = fixture();
  const concepts = [concept(industries), concept(industries, 1, 2, 5, '汽车芯片', '886100.TI')];
  const first = buildIndustryNetwork(freeze({industries, concepts}));
  const second = buildIndustryNetwork({industries: Object.fromEntries([...industries].reverse().map(row =>
    [row.code, {...row, members: [...row.members].reverse()}])),
  concepts: Object.fromEntries([...concepts].reverse().map(row => [row.name, {...row, members: [...row.members].reverse()}]))});
  assert.deepEqual(second, first);
});

const root = new URL('../', import.meta.url);
const evidence = JSON.parse(readFileSync(new URL('src/lib/evidence-data.json', root), 'utf8'));
const supplyRelations = JSON.parse(readFileSync(new URL('src/lib/supply-chain-relations.json', root), 'utf8'));
const originalConcepts = JSON.stringify(evidence.boards);
const actual = buildIndustryNetwork({industries: evidence.industries, concepts: evidence.boards, supplyRelations});

test('actual snapshot keeps 90 THS industries and all 395 source concepts unchanged', () => {
  assert.equal(actual.coverage.industryCount, 90); assert.equal(actual.coverage.conceptCount, 395);
  assert.equal(actual.coverage.businessRelationCount, 3);
  assert.equal(actual.coverage.themeRelationCount, 182);
  assert.equal(actual.coverage.minCoveragePerSide, 0.15);
  assert.equal(JSON.stringify(evidence.boards), originalConcepts);
  assert.equal(actual.coverage.connectedIndustryCount + actual.coverage.isolatedIndustryCodes.length, 90);
  assert.deepEqual(actual.coverage.isolatedIndustryCodes, ['881109.TI', '881135.TI', '881156.TI', '881264.TI']);
});

test('all real company lists reconcile exactly to both source memberships, with distinct sides', () => {
  const conceptsByCode = Object.fromEntries(Object.values(evidence.boards).map(row => [row.code, row]));
  for (const edge of actual.relations) for (const t of edge.sharedThemes) {
    const cm = new Set(conceptsByCode[t.code].members);
    const fm = new Set(evidence.industries[edge.from].members), tm = new Set(evidence.industries[edge.to].members);
    const expectedFrom = [...fm].filter(code => cm.has(code) && !tm.has(code)).sort();
    const expectedTo = [...tm].filter(code => cm.has(code) && !fm.has(code)).sort();
    assert.deepEqual(t.a.codes, expectedFrom); assert.deepEqual(t.b.codes, expectedTo);
    assert.equal(t.a.count, expectedFrom.length); assert.equal(t.b.count, expectedTo.length);
    assert.ok(t.a.count >= 2 && t.b.count >= 2);
    assert.ok(Math.abs(t.a.coverage - t.a.count / fm.size) < 1e-9);
    assert.ok(Math.abs(t.b.coverage - t.b.count / tm.size) < 1e-9);
    assert.ok(!t.a.codes.some(code => t.b.codes.includes(code)));
  }
});

test('real broad labels do not create misleading agriculture/software bridges', () => {
  const blocked = new Set(actual.coverage.excludedThemes.map(row => row.code));
  assert.ok(actual.relations.every(edge => edge.sharedThemes.every(theme => !blocked.has(theme.code))));
  assert.ok(!actual.relations.some(edge => [edge.from, edge.to].includes('881102.TI')
    && [edge.from, edge.to].includes('881272.TI')));
  for (const weakNeighbor of ['881160.TI', '881177.TI']) assert.ok(!actual.relations.some(edge =>
    [edge.from, edge.to].includes('881273.TI') && [edge.from, edge.to].includes(weakNeighbor)));
  assert.ok(actual.relations.some(edge => [edge.from, edge.to].includes('881273.TI')
    && [edge.from, edge.to].includes('881133.TI')));
  const otherElectronics = actual.coverage.neighborSummary.find(row => row.code === '881123.TI');
  assert.ok(otherElectronics.neighbors.length > 0);
  assert.ok(otherElectronics.neighbors.every(row => actual.relations.find(edge => edge.id === row.id)?.sharedThemes.length));
});

if (process.argv.includes('--summary')) {
  const names = Object.fromEntries(Object.values(evidence.industries).map(row => [row.code, row.name]));
  console.log(JSON.stringify({industryCount: actual.coverage.industryCount, conceptCount: actual.coverage.conceptCount,
    business: actual.coverage.businessRelationCount, theme: actual.coverage.themeRelationCount,
    connected: actual.coverage.connectedIndustryCount, isolated: actual.coverage.isolatedIndustryCodes.map(code => names[code]),
    excludedThemes: actual.coverage.excludedThemes.length}));
  for (const row of actual.coverage.neighborSummary) console.log(`${row.code} ${row.name}: ` +
    (row.neighbors.map(edge => `${names[edge.code]}[${edge.type === 'business' ? '业务' : '主题'}:${edge.themes.slice(0, 3).join('/')}]`).join('；') || '暂无达到门槛的关系'));
}
