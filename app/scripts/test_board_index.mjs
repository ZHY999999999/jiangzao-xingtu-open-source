import assert from 'node:assert/strict';
import { buildBoardIndex } from '../src/lib/board-index.js';

// Pure resolver rules; no runtime data needed.
const index = buildBoardIndex([
  { code: '881121.TI', name: '半导体' },
  { code: '885756.TI', name: '芯片概念' },
  { code: '886001.TI', name: '重名' },
  { code: '886002.TI', name: '重名' },
]);
assert.equal(index.get('881121.TI')?.name, '半导体', 'full code resolves');
assert.equal(index.get('半导体')?.code, '881121.TI', 'display name resolves');
assert.equal(index.get('881121')?.code, '881121.TI', 'bare index code resolves');
assert.equal(index.get('885756')?.code, '885756.TI');
assert.equal(index.get('重名'), null, 'duplicated display name is not silently selected');
assert.equal(index.get('886001')?.code, '886001.TI', 'bare codes of the duplicates still resolve');
assert.equal(index.get('000001'), undefined, 'unknown code stays unresolved');
console.log(JSON.stringify({ status: 'PASS', checks: 7 }));
