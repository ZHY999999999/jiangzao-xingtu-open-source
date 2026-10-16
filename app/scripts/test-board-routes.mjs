import assert from 'node:assert/strict';
import fs from 'node:fs';
import { readBoardRoute } from '../src/lib/board-route.js';
import { buildBoardIndex } from '../src/lib/board-index.js';

const evidence = JSON.parse(fs.readFileSync(new URL('../src/lib/evidence-data.json', import.meta.url), 'utf8'));
const catalogs = {
  industry: Object.values(evidence.industries).filter(board => board.level === 'industry'),
  concept: Object.values(evidence.boards),
};
// Same resolver the application uses, so the route test covers code, name and bare-index-code lookups.
const indexes = { industry: buildBoardIndex(catalogs.industry), concept: buildBoardIndex(catalogs.concept) };
const find = (target, kind) => indexes[kind]?.get(target) || null;
assert.equal(catalogs.industry.length, 90);
assert.equal(catalogs.concept.length, 395);
let checked = 0;
for (const [kind, boards] of Object.entries(catalogs)) {
  for (const board of boards) {
    const codeRoute = readBoardRoute(`#kind=${kind}&n=${board.code}`, find);
    assert.equal(codeRoute.board, board.code);
    assert.equal(codeRoute.kind, kind);
    const legacyName = readBoardRoute(`#kind=${kind}&c=${encodeURIComponent(board.name)}&s=000333.SZ`, find);
    assert.equal(legacyName.board, board.code);
    assert.equal(legacyName.drill, true);
    assert.equal(legacyName.stock, '000333.SZ');
    checked++;
  }
}
for (const hash of [
  '#kind=industry&sys=sw2021&n=农产品加工',
  '#kind=subindustry&sys=sw2021&c=半导体',
  '#kind=industry&n=801012.SI',
  '#kind=subindustry&sys=ths&n=884188.TI',
  '#n=884188.TI', '#kind=sector', '#kind=industry&nk=sector&n=半导体',
]) {
  const route = readBoardRoute(hash, find);
  assert.equal(route.kind, 'industry');
  assert.equal(route.board, '');
  assert.equal(route.drill, false);
  assert(route.notice);
}
assert.equal(readBoardRoute('#n=芯片概念', find).board, '885756.TI');
assert.equal(readBoardRoute('#n=881121.TI', find).kind, 'industry');
assert.equal(readBoardRoute('#kind=industry&r=supply-chain&n=881121.TI', find).board, '881121.TI');
// The interface shows bare index codes; a link typed from one resolves to the same board as the .TI form.
assert.equal(readBoardRoute('#kind=industry&n=881121', find).board, '881121.TI');
assert.equal(readBoardRoute('#kind=industry&c=881121&s=688981.SH', find).drill, true);
assert.equal(readBoardRoute('#n=885756', find).board, '885756.TI');
assert.equal(readBoardRoute('#kind=industry&c=missing', find).drill, false);
assert.equal(readBoardRoute('#/', find).kind, 'industry');
console.log(JSON.stringify({status:'PASS',catalogs:checked,legacyRoutes:7,default:'industry',system:'ths'}));
