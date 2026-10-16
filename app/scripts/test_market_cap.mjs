import assert from 'node:assert/strict';
import {aggregateMarketCap, compareMarketCap, validateMarketSnapshot, validCap} from '../src/lib/market-cap.js';

const cases = [];
const test = (name, run) => cases.push({name, run});
const fixture = (date = '2026-09-24', valued = 4000, size = 4000) => ({
  schemaVersion: 1,
  tradeDate: date,
  stocks: Object.fromEntries(Array.from({length: size}, (_, i) =>
    [`${String(i + 1).padStart(6, '0')}.SZ`, {mv: i < valued ? i + 0.125 : null}])),
  coverage: {listed: size, valued, missing: size - valued},
});

test('only finite positive numeric values represent measured total market cap', () => {
  for (const value of [0.01, 1, 10_000_000]) assert.equal(validCap(value), true);
  for (const value of [null, undefined, 0, -1, NaN, Infinity, -Infinity, '100', true]) {
    assert.equal(validCap(value), false, String(value));
  }
});

test('aggregate sums every unique constituent and reports partial coverage', () => {
  const stocks = Object.freeze({
    a: Object.freeze({mv: 120.125}), b: Object.freeze({mv: 30.875}),
    c: Object.freeze({mv: null}), d: Object.freeze({mv: 0}),
  });
  const members = Object.freeze(['a', 'a', 'b', 'c', 'd', 'absent']);
  assert.deepEqual(aggregateMarketCap(members, stocks), {mv: 151, mvCount: 2, count: 5});
  assert.deepEqual(aggregateMarketCap([...members].reverse(), stocks), {mv: 151, mvCount: 2, count: 5});
});

test('unmeasured and empty boards remain unknown instead of zero', () => {
  assert.deepEqual(aggregateMarketCap(['a', 'a', 'b'], {a: {mv: null}, b: {mv: -10}}),
    {mv: null, mvCount: 0, count: 2});
  assert.deepEqual(aggregateMarketCap([], {}), {mv: null, mvCount: 0, count: 0});
  assert.deepEqual(aggregateMarketCap(undefined, {}), {mv: null, mvCount: 0, count: 0});
});

test('directories rank market cap descending, then code, with unknowns last', () => {
  const entries = [
    {code: '000006.SZ', mv: 0}, {code: '000005.SZ', mv: null},
    {code: '000004.SZ', mv: 200}, {code: '000002.SZ', mv: 200},
    {code: '000003.SZ', mv: 0.125}, {code: '000001.SZ', mv: 2_000},
  ];
  const expected = ['000001.SZ', '000002.SZ', '000004.SZ', '000003.SZ', '000005.SZ', '000006.SZ'];
  assert.deepEqual([...entries].sort(compareMarketCap).map(entry => entry.code), expected);
  assert.deepEqual([...entries].reverse().sort(compareMarketCap).map(entry => entry.code), expected);
});

test('valid snapshots accept the same date so corrected daily data can refresh', () => {
  const snapshot = fixture();
  assert.equal(validateMarketSnapshot(snapshot), true);
  assert.equal(validateMarketSnapshot(snapshot, snapshot.tradeDate), true);
  snapshot.stocks['000001.SZ'].mv = 999;
  assert.equal(validateMarketSnapshot(snapshot, snapshot.tradeDate), true);
  assert.equal(validateMarketSnapshot(snapshot, '2026-09-25'), false);
});

test('all supported exchanges accept the shared numeric unit', () => {
  const snapshot = fixture();
  snapshot.stocks['000001.SH'] = snapshot.stocks['000001.SZ'];
  delete snapshot.stocks['000001.SZ'];
  snapshot.stocks['920001.BJ'] = snapshot.stocks['000002.SZ'];
  delete snapshot.stocks['000002.SZ'];
  assert.equal(validateMarketSnapshot(snapshot), true);
});

test('impossible calendar dates and future dates cannot become current', () => {
  for (const date of ['2026-99-99', '2026-02-30', '2025-02-29',
    new Date(Date.now() + 72 * 3600_000).toISOString().slice(0, 10)]) {
    assert.equal(validateMarketSnapshot(fixture(date)), false, date);
  }
});

test('snapshot coverage has a floor and exact listed/valued/missing accounting', () => {
  assert.equal(validateMarketSnapshot(fixture('2026-09-24', 3600)), true);
  assert.equal(validateMarketSnapshot(fixture('2026-09-24', 3599)), false);
  assert.equal(validateMarketSnapshot(fixture('2026-09-24', 3999, 3999)), false);
  for (const key of ['listed', 'valued', 'missing']) {
    const snapshot = fixture();
    snapshot.coverage[key]++;
    assert.equal(validateMarketSnapshot(snapshot), false, key);
  }
});

test('invalid individual caps, stock codes, and schema shapes cannot replace valid data', () => {
  for (const value of [undefined, 0, -1, NaN, Infinity, '100']) {
    const snapshot = fixture();
    snapshot.stocks['000001.SZ'].mv = value;
    assert.equal(validateMarketSnapshot(snapshot), false, String(value));
  }
  const badCode = fixture();
  badCode.stocks['000001.HK'] = badCode.stocks['000001.SZ'];
  delete badCode.stocks['000001.SZ'];
  assert.equal(validateMarketSnapshot(badCode), false);
  for (const snapshot of [null, undefined, {}, {...fixture(), schemaVersion: 2},
    {...fixture(), stocks: []}, {...fixture(), coverage: undefined},
    {...fixture(), tradeDate: '20260924'}]) {
    assert.equal(validateMarketSnapshot(snapshot), false);
  }
});

let failed = 0;
for (const {name, run} of cases) {
  try { run(); console.log(`PASS ${name}`); }
  catch (error) { failed++; console.error(`FAIL ${name}: ${error.message}`); }
}
if (failed) process.exitCode = 1;
else console.log(`PASS ${cases.length} market-cap contract checks`);
