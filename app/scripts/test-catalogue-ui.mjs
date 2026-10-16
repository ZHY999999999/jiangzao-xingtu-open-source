import assert from 'node:assert/strict'
import { readFileSync, writeFileSync, mkdirSync, mkdtempSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'
import { buildSync, build } from 'esbuild'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

const app = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const evidence = resolve(app, '.catalogue-evidence'); mkdirSync(evidence, {recursive:true})
const output = mkdtempSync(resolve(evidence, 'ui-'))
const require = createRequire(import.meta.url)
const sha = value => createHash('sha256').update(value).digest('hex')
const json = name => JSON.parse(readFileSync(resolve(app, name), 'utf8'))
const frozenPublic = resolve(process.env.ATLAS_PUBLIC_ROOT || resolve(app, 'public'))
const rawIndex = readFileSync(resolve(frozenPublic, 'data/companies/index.json'), 'utf8')
const realIndex = JSON.parse(rawIndex)
// Display fixtures only, not approval receipts. Production uses verify_catalogue.py.
// Read the actual selected format: the batch intentionally replaced the old Inspur editorial.
const selection = json('content-selection.json')
const selectedFormats = new Map([
  ...selection.legacy.map(row => [row.code, false]),
  ...selection.sevenQuestions.map(row => [row.code, true]),
])
function displayEntry(code) {
  assert.ok(selectedFormats.has(code), `Display fixture must be actually selected: ${code}`)
  const seven = selectedFormats.get(code)
  const item = json(`content/${seven ? 'company-seven-questions' : 'company-editorial'}/${code}.json`)
  return {code,name:item.name,tagline:item.tagline,kind:seven?'seven-questions':'legacy-editorial',status:seven?'release-reviewed-seven':'legacy-content',
    headline:'',reportBasis:'TEST DISPLAY FIXTURE',audio:'none',...(seven?{asOf:'2026-10-02'}:{createdAt:'2026-10-02',gaps:0}),
    contentSha256:sha(readFileSync(resolve(app,`content/${seven ? 'company-seven-questions' : 'company-editorial'}/${code}.json`)))}
}
const entries = ['000977.SZ','601138.SH','600588.SH'].map(displayEntry).sort((a,b)=>a.code.localeCompare(b.code))
const allEntries = [...selectedFormats.keys()].map(displayEntry).sort((a,b)=>a.code.localeCompare(b.code))
const displayCatalogue = rows => ({schemaVersion:1,catalogueSha256:'f'.repeat(64),index:{sha256:sha(rawIndex),snapshotId:realIndex.snapshotId,asOf:realIndex.asOf},
  counts:{readable:rows.length,legacy:rows.filter(row=>row.kind==='legacy-editorial').length,reviewedSeven:rows.filter(row=>row.kind==='seven-questions').length},
  coverage:{total:realIndex.coverage.total,financialHistory:realIndex.coverage.financialHistory},entries:rows})
const catalogue = displayCatalogue(entries)
const fullCatalogue = displayCatalogue(allEntries)

function compile(name,path) {
  const outfile=resolve(output,name+'.cjs')
  buildSync({entryPoints:[resolve(app,path)],outfile,bundle:true,platform:'node',format:'cjs',external:['react','react-dom/server'],logLevel:'silent'})
  return require(outfile)
}
const selectors=compile('selectors','src/lib/content-catalogue.ts')
const buildLogic=compile('build-logic','scripts/catalogue-build.ts')
const checks=[]
async function test(name,callback) {
  try {await callback(); checks.push({name,status:'passed'});console.log('PASS',name)}
  catch(error) {checks.push({name,status:'failed',error:String(error)});console.error('FAIL',name,error)}
}
const plugin=fixture=>({name:'isolated-display-fixture',setup(b) {
  b.onResolve({filter:/^virtual:/},args=>({path:args.path,namespace:'fixture'}))
  b.onLoad({filter:/.*/,namespace:'fixture'},args=>({contents:'export default '+JSON.stringify(args.path==='virtual:editorial-catalog'?fixture.entries:args.path==='virtual:site-coverage'?{
    asOf:fixture.index.asOf,...fixture.coverage,editorial:fixture.counts.readable,reviewedSeven:fixture.counts.reviewedSeven,industries:90}:fixture),loader:'js'}))
  b.onResolve({filter:/(?:\/CompanyDocument|\/RelatedCompanies|\/SiteHeader|\/InformationNotice|\/lib\/company)$/},args=>({path:args.path,namespace:'unused'}))
  b.onResolve({filter:/\/CompanyDetailParts$/},args=>({path:args.path,namespace:'unused'}))
  b.onLoad({filter:/.*/,namespace:'unused'},()=>({contents:'export default function Unused(){return null}; export const loadCompany=()=>{},loadCompanyIndex=()=>{},date=x=>x,jumpTo=()=>{}',loader:'js'}))
}})
async function component(name,path,fixture=catalogue) {
  const outfile=resolve(output,name+'.cjs')
  await build({entryPoints:[resolve(app,path)],outfile,bundle:true,platform:'node',format:'cjs',external:['react','react-dom/server'],loader:{'.css':'empty'},jsx:'automatic',plugins:[plugin(fixture)],logLevel:'silent'})
  return require(outfile)
}
await test('same selector: 3 readable / 2 seven-question entries, old deep union 8 is not adopted',()=>{
  assert.deepEqual(catalogue.counts,{readable:3,legacy:1,reviewedSeven:2})
  const deep=realIndex.companies.filter(x=>x.depth==='deep').map(x=>x.code)
  assert.equal(new Set([...deep,...entries.map(x=>x.code)]).size,8)
  for(const code of deep.filter(code=>!entries.some(x=>x.code===code))) assert.equal(selectors.selectContent(catalogue,code),undefined)
  assert.equal(selectors.countMemberContent(catalogue,[...deep,...entries.map(x=>x.code),...entries.map(x=>x.code)]),3)
  assert.equal(selectors.selectContent(catalogue,'600588.SH').status,'release-reviewed-seven')
  assert.equal(selectors.selectContent(catalogue,'601138.SH').status,'legacy-content')
  assert.equal(selectors.selectContent(catalogue,'600588.SZ'),undefined)
})
await test('directory ordering uses only actual selected content, deep-only follows',()=>{
  const sorted=realIndex.companies.slice().sort((a,b)=>selectors.contentFirst(catalogue,a,b))
  assert.deepEqual(sorted.slice(0,3).map(x=>x.code),entries.map(x=>x.code))
})
await test('actual HomeValue SSR reports 3 and subset 2, neutral sample titles',async()=>{
  const Home=(await component('home','src/components/HomeValue.tsx')).default
  const html=renderToStaticMarkup(React.createElement(Home,{preloadCompanies:()=>{}}))
  assert.match(html,/家有经营解读/);assert.match(html,/<dd>3<\/dd>/)
  assert.match(html,/其中 2 家为已核对来源的七问解读/);assert.match(html,/从这些公司开始读/)
  assert.doesNotMatch(html,/已核读的公司|批准链|队列|reviewer|manifest/)
})
await test('actual directory SSR has exactly 3 badges; deep-only has no reviewed badge',async()=>{
  const Search=(await component('directory','src/components/CompanyLibrary.tsx')).CompanySearch
  const codes=new Set([...entries.map(x=>x.code),...realIndex.companies.filter(x=>x.depth==='deep').map(x=>x.code)])
  const index={...realIndex,companies:realIndex.companies.filter(x=>codes.has(x.code))}
  const html=renderToStaticMarkup(React.createElement(Search,{index,onOpen:()=>{},state:{query:'',industry:'',limit:60},setState:()=>{}}))
  assert.equal((html.match(/<em>/g)||[]).length,3)
  assert.equal((html.match(/七问解读 · 已核对来源/g)||[]).length,2)
  assert.equal((html.match(/既有经营解读/g)||[]).length,1)
})
const priority = ['601138.SH','000977.SZ','603019.SH','600588.SH','600036.SH','000333.SZ']
const codes = rows => rows.map(row=>row.code)
const sampleCodes = html => [...(html.match(/<section class="hv-samples"[\s\S]*?<\/section>/)?.[0] || '').matchAll(/href="#\/company\/([^"]+)"/g)].map(match=>match[1])
const syntheticEntry = code => ({...allEntries.find(row=>row.kind==='seven-questions'),code,name:`TEST FIXTURE ${code}`,tagline:`SYNTHETIC DISPLAY ${code}`})
await test('six actual samples have fixed priority, retain benchmark, and do not mutate inputs',()=>{
  assert.deepEqual(fullCatalogue.counts,{readable:15,legacy:1,reviewedSeven:14})
  const input=Object.freeze(allEntries.map(row=>Object.freeze({...row})))
  const before=JSON.stringify(input), samples=selectors.selectHomeSamples(input)
  assert.deepEqual(codes(samples),priority)
  assert.equal(JSON.stringify(input),before)
  assert.ok(samples.every(row=>input.includes(row)))
  assert.equal(samples[0].kind,'legacy-editorial')
})
await test('new entries and input ordering cannot displace present priority samples',()=>{
  const input=[syntheticEntry('000000.SZ'),...allEntries.slice().reverse(),syntheticEntry('999999.SZ')]
  assert.deepEqual(codes(selectors.selectHomeSamples(input)),priority)
})
await test('missing priority entries use deterministic remaining codes without inventing benchmark',()=>{
  const input=allEntries.filter(row=>!['601138.SH','603019.SH'].includes(row.code)).reverse()
  assert.deepEqual(codes(selectors.selectHomeSamples(input)),['000977.SZ','600588.SH','600036.SH','000333.SZ','000001.SZ','000002.SZ'])
  const fallback=[syntheticEntry('800003.SZ'),syntheticEntry('800001.SZ'),syntheticEntry('800002.SZ')]
  assert.deepEqual(codes(selectors.selectHomeSamples(fallback)),['800001.SZ','800002.SZ','800003.SZ'])
})
await test('empty, sparse and duplicate entries produce only unique actual samples',()=>{
  assert.deepEqual(selectors.selectHomeSamples([]),[])
  const first=allEntries.find(row=>row.code==='601138.SH'),other=syntheticEntry('800000.SZ')
  const result=selectors.selectHomeSamples([other,first,{...first,tagline:'DUPLICATE MUST NOT REPLACE FIRST'},other])
  assert.deepEqual(codes(result),['601138.SH','800000.SZ'])
  assert.equal(result[0],first);assert.equal(result[1],other)
})
await test('actual HomeValue SSR renders six samples but retains full 15/14 totals and legacy badge',async()=>{
  const Home=(await component('home-full','src/components/HomeValue.tsx',fullCatalogue)).default
  const html=renderToStaticMarkup(React.createElement(Home,{preloadCompanies:()=>{}}))
  assert.deepEqual(sampleCodes(html),priority)
  assert.match(html,/当前收录 15 家经营解读，其中 14 家为已核对来源的七问解读/)
  assert.match(html,/<dd>15<\/dd>/)
  assert.equal((html.match(/既有经营解读/g)||[]).length,1)
  assert.equal((html.match(/七问解读 · 已核对来源/g)||[]).length,5)
  assert.match(html,/<a class="hv-directory-link" href="#\/companies">打开公司目录 /)
  assert.doesNotMatch(html,/批准链|队列|manifest|reviewer/)
})
await test('actual directory link preserves normal navigation and pointer/focus preloading',async()=>{
  const Home=(await component('home-link','src/components/HomeValue.tsx',fullCatalogue)).default
  let calls=0
  const tree=Home({preloadCompanies:()=>{calls++}}), found=[]
  function visit(node){if(!React.isValidElement(node))return;if(node.type==='a'&&node.props.className==='hv-directory-link')found.push(node);React.Children.forEach(node.props.children,visit)}
  visit(tree);assert.equal(found.length,1)
  const link=found[0];assert.equal(link.props.href,'#/companies');assert.equal(link.props.onClick,undefined)
  link.props.onPointerEnter();link.props.onFocus();assert.equal(calls,2)
  const icon=React.Children.toArray(link.props.children).find(React.isValidElement)
  assert.equal(icon.props['aria-hidden'],'true')
})
await test('actual HomeValue empty/sparse SSR retains directory access without fabricated cards',async()=>{
  for(const size of [0,2]){
    const fixture=displayCatalogue(allEntries.slice(0,size))
    const Home=(await component(`home-sparse-${size}`,'src/components/HomeValue.tsx',fixture)).default
    const html=renderToStaticMarkup(React.createElement(Home,{preloadCompanies:()=>{}}))
    assert.equal(sampleCodes(html).length,size);assert.match(html,/href="#\/companies"/)
    if(!size)assert.doesNotMatch(html,/class="hv-samples"/)
  }
})
await test('actual directory row uses adopted tagline verbatim with React escaping, not base summary',async()=>{
  const fixture=displayCatalogue([{...allEntries[0],tagline:'TAGLINE <safe> & adopted'}])
  const Result=(await component('directory-summary','src/components/CompanyLibrary.tsx',fixture)).CompanyResult
  const company={...realIndex.companies.find(row=>row.code===fixture.entries[0].code),summary:'BASE SUMMARY MUST NOT WIN'}
  const html=renderToStaticMarkup(React.createElement(Result,{company,selected:false,compact:false,onOpen:()=>{}}))
  assert.match(html,/class="cl-result-summary">TAGLINE &lt;safe&gt; &amp; adopted<\/span>/)
  assert.doesNotMatch(html,/BASE SUMMARY MUST NOT WIN|<safe>/)
  assert.match(html,/七问解读 · 已核对来源/)
})
await test('unadopted directory row retains base summary/fallback and no adopted badge',async()=>{
  const Result=(await component('directory-unadopted','src/components/CompanyLibrary.tsx',fullCatalogue)).CompanyResult
  const base=realIndex.companies.find(row=>!allEntries.some(entry=>entry.code===row.code))
  for(const summary of ['BASE ONLY','']){
    const html=renderToStaticMarkup(React.createElement(Result,{company:{...base,summary},selected:false,compact:false,onOpen:()=>{}}))
    assert.ok(html.includes(summary||'基础资料已收录，经营说明待补充。'))
    assert.doesNotMatch(html,/<em>|七问解读 · 已核对来源|既有经营解读/)
  }
})
await test('compact actual directory rows omit adopted and base summaries',async()=>{
  const Result=(await component('directory-compact','src/components/CompanyLibrary.tsx',fullCatalogue)).CompanyResult
  for(const code of [allEntries[0].code,realIndex.companies.find(row=>!allEntries.some(entry=>entry.code===row.code)).code]){
    const company={...realIndex.companies.find(row=>row.code===code),summary:'HIDDEN BASE'}
    const html=renderToStaticMarkup(React.createElement(Result,{company,selected:false,compact:true,onOpen:()=>{}}))
    assert.doesNotMatch(html,/cl-result-summary|HIDDEN BASE/)
  }
})
for(const size of [100,10000])await test(`actual HomeValue SSR remains six cards with ${size} synthetic metadata entries`,async()=>{
  const fixture=displayCatalogue([...allEntries,...Array.from({length:size-allEntries.length},(_,i)=>syntheticEntry(`${200000+i}.SZ`))])
  fixture.coverage={total:size,financialHistory:0}
  const Home=(await component(`home-large-${size}`,'src/components/HomeValue.tsx',fixture)).default
  const html=renderToStaticMarkup(React.createElement(Home,{preloadCompanies:()=>{}}))
  assert.deepEqual(sampleCodes(html),priority)
  assert.ok(html.includes(`当前收录 ${size} 家经营解读，其中 ${size-1} 家为已核对来源的七问解读`))
})
await test('actual CompanySearch bounds 10000 input rows by current 60/40 and explicit raised limits',async()=>{
  const Search=(await component('directory-large','src/components/CompanyLibrary.tsx',fullCatalogue)).CompanySearch
  const base=realIndex.companies[0]
  const index={...realIndex,companies:Array.from({length:10000},(_,i)=>({...base,code:`${200000+i}.SZ`,name:`TEST COMPANY ${i}`,industry:'TEST INDUSTRY',summary:'TEST BASE'}))}
  for(const [compact,limit] of [[false,60],[true,40],[false,120],[true,80]]){
    const html=renderToStaticMarkup(React.createElement(Search,{index,compact,onOpen:()=>{},state:{query:'',industry:'',limit},setState:()=>{}}))
    assert.equal((html.match(/class="cl-company-result(?: is-current)?"/g)||[]).length,limit)
    assert.match(html,/10,000 家/);assert.match(html,/cl-load-more/)
  }
  const small=renderToStaticMarkup(React.createElement(Search,{index:{...index,companies:index.companies.slice(0,3)},onOpen:()=>{},state:{query:'',industry:'',limit:60},setState:()=>{}}))
  assert.equal((small.match(/class="cl-company-result"/g)||[]).length,3);assert.doesNotMatch(small,/cl-load-more/)
})
await test('runtime accepts exact index bytes and rejects same snapshot with changed data',async()=>{
  assert.equal((await selectors.parseBoundIndex(rawIndex,catalogue.index)).snapshotId,realIndex.snapshotId)
  await assert.rejects(()=>selectors.parseBoundIndex(rawIndex+' ',catalogue.index),/版本不一致/)
  await assert.rejects(()=>selectors.parseBoundIndex(rawIndex,{...catalogue.index,snapshotId:'other'}),/快照/)
})
await test('product revision deterministic; queue changes excluded; JSON and index bytes included',()=>{
  const root=resolve(output,'revision');mkdirSync(root);mkdirSync(resolve(root,'content'));mkdirSync(resolve(root,'public/data/companies'),{recursive:true})
  writeFileSync(resolve(root,'content/a.json'),'one');writeFileSync(resolve(root,'public/data/companies/index.json'),'index')
  const receipt={applicationInputs:{'content/a.json':'x','public/data/companies/index.json':'y'},catalogue,approvalBindingId:'old'}
  const first=buildLogic.productRevision(root,receipt)
  assert.equal(first,buildLogic.productRevision(root,{...receipt,approvalBindingId:'unrelated-new'}))
  writeFileSync(resolve(root,'content/a.json'),'two');assert.notEqual(first,buildLogic.productRevision(root,receipt))
  writeFileSync(resolve(root,'content/a.json'),'one');writeFileSync(resolve(root,'public/data/companies/index.json'),'new-index');assert.notEqual(first,buildLogic.productRevision(root,receipt))
})
await test('same-build binding drift refused even if public catalogue is unchanged',()=>{
  const receipt={catalogue,approvalBindingId:'a',applicationInputs:{}}
  assert.doesNotThrow(()=>buildLogic.sameAssembly(receipt,structuredClone(receipt)))
  assert.throws(()=>buildLogic.sameAssembly(receipt,{...receipt,approvalBindingId:'b'}),/changed during build/)
})
await test('actual Vite bundle hook rejects missing, static and eagerly imported selected modules',async()=>{
  // Only this bundle-hook fixture substitutes the already-tested approval gate.
  // It cannot be used by the production CLI or make a semantic approval claim.
  const outfile=resolve(output,'bundle-hook.cjs')
  const receipt={status:'verified_local_assembly_inputs',catalogue,applicationInputs:{},approvalBindingId:'DISPLAY-FIXTURE'}
  await build({entryPoints:[resolve(app,'vite.config.ts')],outfile,bundle:true,platform:'node',format:'cjs',
    define:{'import.meta.url':JSON.stringify(pathToFileURL(resolve(app,'vite.config.ts')).href)},logLevel:'silent',
    plugins:[{name:'bundle-boundary-fixture',setup(b){
      b.onResolve({filter:/^(vite|@vitejs\/plugin-react)$|\.\/scripts\/catalogue-build$/},args=>({path:args.path,namespace:'build-fixture'}))
      b.onLoad({filter:/.*/,namespace:'build-fixture'},args=>({loader:'js',contents:args.path==='vite'?'export const defineConfig=x=>x':args.path==='@vitejs/plugin-react'?'export default ()=>({name:"react-fixture"})':
        `import {createHash} from 'node:crypto'; export const sha=x=>createHash('sha256').update(x).digest('hex'); export const verifyAssembly=()=>(${JSON.stringify(receipt)}); export const sameAssembly=()=>{}; export const productRevision=()=>"fixture";`}))
    }}]})
  const config=require(outfile).default
  const make=()=>config().plugins.find(p=>p.name==='single-content-catalogue')
  const modulePaths=entries.map(row=>resolve(app,`content/${row.kind==='seven-questions'?'company-seven-questions':'company-editorial'}/${row.code}.json`).replaceAll('\\','/'))
  const bundle=()=>Object.fromEntries([{fileName:'main.js',type:'chunk',isEntry:true,isDynamicEntry:false,imports:[],modules:{},code:'main'},
    ...modulePaths.map((name,i)=>({fileName:`content-${i}.js`,type:'chunk',isEntry:false,isDynamicEntry:true,imports:[],modules:{[name]:{}},code:'content'}))].map(row=>[row.fileName,row]))
  const context={emitFile:()=>{}}
  assert.throws(()=>make().generateBundle.call(context,{},bundle()),/actual loaded modules/)
  const hook=make();modulePaths.forEach(name=>hook.transform('',name))
  assert.doesNotThrow(()=>hook.generateBundle.call(context,{},bundle()))
  const missing=bundle();delete missing['content-0.js'];assert.throws(()=>hook.generateBundle.call(context,{},missing),/lazy content chunk/)
  const staticChunk=bundle();staticChunk['content-0.js'].isDynamicEntry=false;assert.throws(()=>hook.generateBundle.call(context,{},staticChunk),/lazy content chunk/)
  const eager=bundle();eager['main.js'].imports=['content-0.js'];assert.throws(()=>hook.generateBundle.call(context,{},eager),/lazy content chunk/)
})
const result={scope:'synthetic display, pure helpers and actual SSR; no semantic approval',tests:checks,total:checks.length,passed:checks.filter(x=>x.status==='passed').length,failed:checks.filter(x=>x.status==='failed').length,noDeploy:true}
writeFileSync(resolve(evidence,'ui-tests.json'),JSON.stringify(result,null,2)+'\n')
if(result.failed)process.exitCode=1
