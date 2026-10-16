import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
import ts from 'typescript'

const root = resolve(import.meta.dirname, '..')
const source = readFileSync(resolve(root, 'src/lib/company-reading.ts'), 'utf8')
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText
const mod = { exports: {} }
new Function('exports', 'require', 'module', output)(mod.exports, createRequire(import.meta.url), mod)
const { segmentDisplay, usableSourceUrl, segmentNeedsReview, segmentDimensionLabel, orderSegments } = mod.exports
const base = { id:'test', title:'报告', url:'https://static.cninfo.com.cn/example.pdf' }
for (const status of ['permanently_unavailable','transient_failure','html_instead_of_pdf','not_a_pdf','refused_unsafe_redirect']) assert.equal(usableSourceUrl({...base,accessStatus:status}),undefined)
assert.equal(usableSourceUrl({...base,available:false}),undefined)
assert.equal(usableSourceUrl({...base,pending:true}),undefined)
assert.equal(usableSourceUrl({...base,pending:true,candidate:true}),base.url)
assert.equal(usableSourceUrl({...base,accessStatus:'unchecked'}),base.url)
assert.equal(usableSourceUrl({...base,url:'file:///private.pdf'}),undefined)
assert.equal(usableSourceUrl({...base,url:'javascript:alert(1)'}),undefined)
const group = values => ({items:values.map(([name,revenue])=>({name,revenue,sourceIds:[]}))})
assert.deepEqual(segmentDisplay(group([['合计',100],['A',70],['B',30]])).items.map(i=>i.name),['A','B'])
assert.equal(segmentDisplay(group([['合计',100],['A',70],['B',null]])).removedAggregate,false)
assert.equal(segmentDisplay(group([['合计',100],['A',70],['A别名',70],['B',30]])).removedAggregate,false)
assert.equal(segmentDisplay(group([['A',120],['抵消',-20]])).items[1].revenue,-20)
assert.equal(segmentDisplay(group([['总计',0],['A',0],['B',0]])).removedAggregate,false)
const editorial = JSON.parse(readFileSync(resolve(root,'content/company-editorial/601138.SH.json'),'utf8'))
assert.equal(editorial.revenueMix.period,'20251231')
assert.equal(editorial.revenueMix.items.reduce((n,i)=>n+i.revenue,0),editorial.revenueMix.denominator)
assert.ok(Math.abs(editorial.revenueMix.items.reduce((n,i)=>n+i.share,0)-1)<1e-10)
assert.ok(editorial.audio.durationSeconds>=120&&editorial.audio.durationSeconds<=180)
const ids = new Set(editorial.sources.map(s=>s.id))
assert.equal(ids.size,editorial.sources.length)
function walk(node) { if(!node || typeof node!=='object') return; for(const [k,v] of Object.entries(node)) {if(k==='sourceIds'||k==='introductionSourceIds'||k==='paymentSourceIds')for(const id of v)assert.ok(ids.has(id),`Unresolved ${id}`);else walk(v)} }
walk(editorial)
const index = JSON.parse(readFileSync(resolve(process.env.ATLAS_PUBLIC_ROOT || resolve(root,'public'),'data/companies/index.json'),'utf8'))
for(const code of ['601138.SH','600519.SH','000333.SZ','688981.SH','600588.SH','600036.SH','601318.SH']) {
  const c = JSON.parse(readFileSync(resolve(process.env.ATLAS_PUBLIC_ROOT || resolve(root,'public'),`data/companies/snapshots/${index.snapshotId}/${code}.json`),'utf8'))
  assert.ok(c.finance.quarterly.every(p=>p.totalAssets===null&&p.totalLiabilities===null))
  const q4=c.finance.quarterly.find(p=>p.period==='20251231')
  const periods=q4.sourceIds.map(id=>c.sources.find(s=>s.id===id)?.reportPeriod)
  assert.ok(periods.includes('20250930')&&periods.includes('20251231'))
}
console.log('PASS: source availability, aggregate/alias/negative/null handling, editorial identities and audio, seven real company quarter-source contracts.')

assert.equal(segmentNeedsReview({notes:['含汇总项或父子层级，原行保留但不可直接加总。']}),true)
assert.equal(segmentNeedsReview({notes:['本次按产品分别列示']}),false)
assert.equal(segmentDimensionLabel('455006000'),'分类待核')
assert.equal(segmentDimensionLabel('销售模式'),'销售模式')
const unclassified={period:'20260630',dimension:'455006000'}, product={period:'20260630',dimension:'产品'}, region={period:'20260630',dimension:'地区'}
assert.deepEqual(orderSegments([unclassified,region,product]),[product,region,unclassified])
console.log('PASS: unresolved segment hierarchy and anomalous dimensions remain explicit.')
