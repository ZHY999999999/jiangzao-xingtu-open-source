import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {test} from 'node:test';
import {compactCompanyMemberships, getRelatedCompanies} from '../src/lib/related-companies.js';

const read = name => JSON.parse(readFileSync(new URL(name, import.meta.url), 'utf8'));
const evidence = read('../src/lib/evidence-data.json');
const index = (process.env.ATLAS_PUBLIC_ROOT ? JSON.parse(readFileSync(resolve(process.env.ATLAS_PUBLIC_ROOT,'data/companies/index.json'),'utf8')) : read('../public/data/companies/index.json')).companies;
const membership = compactCompanyMemberships(evidence);
const lookup = code => getRelatedCompanies(membership, index, code);
const allRows = result => [...result.peers, ...result.concepts];
const makeCode = n => `${String(n).padStart(6, '0')}.SZ`;
const board = (code, name, members, level = 'concept') => ({code, name, members, level, membershipAsOf: '20260922'});
const fixture = () => {
  const codes = Array.from({length: 20}, (_, i) => makeCode(i + 1));
  return {codes, data: {membershipAsOf: '20260922', industries: [board('881001.TI', '行业甲', codes.slice(0, 10), 'industry'),
    board('881002.TI', '行业乙', codes.slice(10), 'industry')], boards: []}};
};

test('compact projection keeps 90 THS industries and only membership fields', () => {
  assert.equal(membership.industries.length, 90);
  assert.equal(membership.membershipAsOf, '20260922');
  assert.ok(membership.excludedConceptCount > 0);
  for (const row of [...membership.industries, ...membership.concepts]) {
    assert.deepEqual(Object.keys(row).sort(), ['code', 'members', 'membershipAsOf', 'name']);
    assert.equal(row.members.length, new Set(row.members).size);
  }
});

for (const [code, name, peer] of [['600519.SH', '白酒', '000858.SZ'], ['000333.SZ', '白色家电', '000651.SZ'], ['688981.SH', '半导体', '688347.SH']]) {
  test(`real ${code}: exact ${name} peers and symmetric shared evidence`, () => {
    const result = lookup(code), row = result.peers.find(value => value.code === peer);
    assert.ok(result.industries.some(value => value.name === name));
    assert.ok(row, `missing known peer ${peer}`);
    const reverse = lookup(peer).peers.find(value => value.code === code);
    assert.deepEqual(row.conceptNames, reverse.conceptNames);
    assert.deepEqual(row.industryNames, reverse.industryNames);
    assert.equal(row.score, reverse.score);
    const expected = new Set(membership.industries.filter(value => value.members.includes(code)).flatMap(value => value.members)
      .filter(value => value !== code && index.some(company => company.code === value)));
    assert.deepEqual(new Set(result.peers.map(value => value.code)), expected);
    assert.ok(result.concepts.every(value => !expected.has(value.code) && value.conceptNames.length));
  });
}

test('no self, duplicate, or noncurrent directory company; unknown code is empty', () => {
  const result = lookup('000333.SZ'), rows = allRows(result), valid = new Set(index.map(row => row.code));
  assert.equal(rows.length, new Set(rows.map(row => row.code)).size);
  assert.ok(rows.every(row => row.code !== '000333.SZ' && valid.has(row.code)));
  const removed = rows[0].code;
  const filtered = getRelatedCompanies(membership, index.filter(row => row.code !== removed), '000333.SZ');
  assert.ok(!allRows(filtered).some(row => row.code === removed));
  assert.deepEqual(allRows(lookup('999999.SZ')), []);
  assert.deepEqual(lookup('999999.SZ').industries, []);
});

test('market, index, ownership, ecosystem and >35% concepts cannot create relations', () => {
  const {codes, data} = fixture();
  data.boards = ['融资融券', '沪股通', '深股通', '沪深300样本股', '国企改革', '华为概念', '人工智能'].map((name, i) =>
    board(`88500${i}.TI`, name, [codes[0], codes[10]]));
  data.boards.push(board('883001.TI', '无关键词的指数', [codes[0], codes[10]]), board('885100.TI', '过宽业务主题', codes.slice(0, 8)),
    board('885101.TI', '窄主题', [codes[0], codes[10]]));
  const before = JSON.stringify(data), compact = compactCompanyMemberships(data);
  assert.equal(JSON.stringify(data), before);
  assert.deepEqual(compact.concepts.map(row => row.name), ['窄主题']);
  assert.equal(compact.excludedConceptCount, 9);
  const result = getRelatedCompanies(compact, codes.map(code => ({code})), codes[0]);
  assert.deepEqual(result.concepts.map(row => [row.code, row.conceptNames]), [[codes[10], ['窄主题']]]);
});

test('specific concepts rank first, ties use code, and lack of THS never falls back to stock_basic', () => {
  const {codes, data} = fixture();
  data.boards = [board('885100.TI', '窄主题', [codes[0], codes[11]]), board('885101.TI', '普通主题', [codes[0], ...codes.slice(12, 18)])];
  const compact = compactCompanyMemberships(data), companies = codes.map(code => ({code, industry: '相同基础行业'}));
  const result = getRelatedCompanies(compact, companies, codes[0]);
  assert.equal(result.concepts[0].code, codes[11]);
  assert.deepEqual(result.concepts.slice(1).map(row => row.code), codes.slice(12, 18));
  const withoutIndustry = {...compact, industries: []};
  assert.deepEqual(getRelatedCompanies(withoutIndustry, companies, codes[0]).peers, []);
  const pair = result.concepts[0], reverse = getRelatedCompanies(compact, companies, pair.code).concepts.find(row => row.code === codes[0]);
  assert.deepEqual(pair.conceptNames, reverse.conceptNames); assert.equal(pair.score, reverse.score);
});

test('deduplicates multiple memberships and retains more than the graph 150 budget', () => {
  const codes = Array.from({length: 202}, (_, i) => makeCode(i + 1));
  const compact = compactCompanyMemberships({industries: [board('881001.TI', '行业甲', [...codes, codes[1]], 'industry'),
    board('881002.TI', '行业乙', codes.slice(0, 4), 'industry')], boards: []});
  const result = getRelatedCompanies(compact, [...codes.map(code => ({code})), {code: codes[1]}], codes[0]);
  assert.equal(result.peers.length, 201); assert.equal(result.concepts.length, 0);
  assert.deepEqual(result.peers.map(row => row.code), codes.slice(1));
  assert.deepEqual(result.peers[0].industryNames, ['行业甲', '行业乙']);
});

console.log(JSON.stringify({compactBytes: Buffer.byteLength(JSON.stringify(membership)), industries: membership.industries.length,
  concepts: membership.concepts.length, excludedConceptCount: membership.excludedConceptCount,
  examples: ['600519.SH', '000333.SZ', '688981.SH'].map(code => ({code, peers: lookup(code).peers.length, concepts: lookup(code).concepts.length}))}));
