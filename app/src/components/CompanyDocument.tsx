import { useEffect, useMemo, useRef, useState } from 'react'
import { IconArrowDown, IconArrowUpRight, IconArrowRight, IconBuildingFactory2, IconDatabase, IconDeviceDesktop, IconExternalLink, IconNetwork, IconPackage, IconSearch, IconSettings, IconX } from '@tabler/icons-react'
import type { CompanyDossier, CompanySource, CompanyClaim } from '../lib/company'
import { loadEditorial } from '../lib/company-editorial'
import type { CompanyEditorial, EditorialSource } from '../lib/company-editorial'
import { BusinessSegments, Claims, EmptyNote, FinancialHistory, LongText, SourcePanelContext, SourceRefs, Status, date, money, safeUrl, sourceAction, sourceLink, sourceStatus, reportName, jumpTo } from './CompanyDetailParts'
import CompanyAudio from './CompanyAudio'
import CompanyBusinessStudy, { CompanyCashExplanation } from './CompanyBusinessStudy'
import InformationNotice from './InformationNotice'
import CompanyQuickRead from './CompanyQuickRead'
import CompanySevenQuestions, { SevenQuestionSources, SevenQuestionIntroduction } from './CompanySevenQuestions'
import { loadSevenQuestions } from '../lib/company-seven-questions-loader'
import type { SevenQuestionContent } from '../lib/company-seven-questions'
import CompanyOverview, { CompanyOverviewSources } from './CompanyOverview'
import { loadCompanyOverview } from '../lib/company-overview-loader'
import type { CompanyOverviewContent } from '../lib/company-overview'
import catalog from 'virtual:editorial-catalog'
import { audioLabel } from '../lib/audio-label'
import { selectHomeSamples, nextHomeSample } from '../lib/content-catalogue'
import { sevenQuestionAudio, sevenQuestionAudioSources } from '../lib/seven-question-audio'
import { baseHistoryReaderText, baseCoverageReaderNote, baseCoverageReaderLabel, baseCoverageVisible } from '../lib/base-dossier-reader-copy'

function SectionTitle({ number, title, children }: { number: string; title: string; children?: React.ReactNode }) {
  return <header className="cr-section-title"><span>{number}</span><div><h2>{title}</h2>{children && <p>{children}</p>}</div></header>
}

const versionLabel = (value: string) => ({original: '采用原始披露版本', revised: '采用修订版本', corrected: '采用更正版本'}[value] || value)
const sameCopy = (a: string, b: string) => a.replace(/\s/g,'') === b.replace(/\s/g,'')

const CN_COUNT = ['零','一','两','三','四','五','六','七','八','九']
// Title follows the reviewed mix instead of assuming a company shape.
function revenueHeadline(items: { share: number }[]) {
  const major = items.filter(item => item.share >= 0.05).length
  const top = Math.max(0, ...items.map(item => item.share))
  if (top >= 0.8) return '收入高度集中在一项业务'
  if (major >= 1 && major < CN_COUNT.length) return `主要靠${CN_COUNT[major]}项生意`
  return '收入来自多项业务'
}
function financeReadingTitle(notes: { period: string }[]) {
  const years = [...new Set(notes.map(note => /^\d{8}$/.test(note.period) ? `${note.period.slice(0,4)}${note.period.endsWith('1231') ? '年度' : note.period.endsWith('0630') ? '年半年度' : '年'}` : note.period))]
  return `${years.join('、') || '经营变化'} · 阅读解读`
}

function SourceCard({ source }: { source: EditorialSource }) {
  const link = sourceLink(source)
  return <article className="cr-source-card"><div className="cr-source-meta"><span>{source.reportPeriod ? reportName(source.reportPeriod) : '公开资料'}</span><span>{sourceStatus(source) || (source.verificationLevel === 3 ? '已核对相关内容' : source.verificationLevel === 2 ? '已找到对应报告，尚未逐项核对数据' : '公开资料 · 相关内容尚未核对')}</span></div><h3>{source.title}</h3>{(source.pageSection || source.locator) && <p className="cr-source-locator">{source.pageSection || source.locator}</p>}{source.excerpt && <p>{source.excerpt}</p>}{source.versionRelation && <p>{versionLabel(source.versionRelation)}</p>}<footer><span>{source.publishedAt ? `披露 ${date(source.publishedAt)}` : '披露日期待补'}</span>{link ? <a href={link} target="_blank" rel="noreferrer">{sourceAction(source)}<IconExternalLink size={15} /></a> : <span>{sourceStatus(source) || '公开链接待补'}</span>}</footer></article>
}

function Sources({ sources, onOpen }: { sources: EditorialSource[]; onOpen: (ids: string[]) => void }) {
  const [query, setQuery] = useState(''), [limit, setLimit] = useState(8)
  const filtered = useMemo(() => sources.filter(s => `${s.title} ${s.reportPeriod || ''} ${s.pageSection || s.locator || ''}`.includes(query.trim())).sort((a,b) => Number(Boolean(sourceLink(b) && !b.candidate)) - Number(Boolean(sourceLink(a) && !a.candidate)) || (b.reportPeriod || '').localeCompare(a.reportPeriod || '') || Number(b.verificationLevel || 0) - Number(a.verificationLevel || 0)), [query, sources])
  return <><div className="cr-sources-search"><label><IconSearch size={18} /><input type="search" aria-label="查找资料出处" placeholder="查找报告年份、标题或章节" value={query} onChange={e => { setQuery(e.target.value); setLimit(8) }} /></label><span>{filtered.length} 条资料记录</span></div><div className="cr-source-list">{filtered.slice(0,limit).map(s => <button type="button" key={s.id} onClick={() => onOpen([s.id])}><div><strong>{s.title}</strong><span>{s.pageSection || (s.reportPeriod ? reportName(s.reportPeriod) : s.document || '定位信息待补')}</span></div><span>{sourceStatus(s) || (s.verificationLevel === 3 ? '已核对相关内容' : s.verificationLevel === 2 ? '已匹配报告' : '公开资料')}</span><IconArrowRight size={18} /></button>)}</div>{!filtered.length && <p className="cr-muted">没有匹配的资料。</p>}{filtered.length > limit && <button type="button" className="cr-text-button" onClick={() => setLimit(n => n + 16)}>继续查看 · 已显示 {limit} / {filtered.length}</button>}</>
}

function BusinessMap({ editorial, sources }: { editorial: CompanyEditorial; sources: CompanySource[] }) {
  const map = editorial.businessMap
  const buyers = map?.customers || editorial.customers.slice(0,2).map(c => ({title:c.name,text:c.purpose}))
  const products = map?.products || editorial.products.slice(0,2).map(p => ({title:p.name,text:p.purpose}))
  return <div className="cr-business-map">
    <div className="cr-map-side"><span className="cr-eyebrow">谁来买</span>{buyers.map((item,i)=><a key={item.title} href="#company-business" onClick={e=>jumpTo(e,'company-business')}>{i===0?<IconDatabase size={28}/>:<IconNetwork size={28}/>}<div><h3>{item.title}</h3><p>{item.text}</p></div></a>)}</div>
    <div className="cr-map-center"><div className="cr-map-caption"><strong>{editorial.name}</strong><span>{map?.caption || editorial.readerTakeaway}</span></div>{editorial.code==='601138.SH' && <><img src={`${import.meta.env.BASE_URL}images/company/server-network.png`} alt="服务器机柜与网络交换机的通用产品示意" width="1586" height="992" fetchPriority="high"/><span className="cr-illustration-note">通用产品示意</span></>}<div className="cr-map-process">{editorial.process.slice(0,3).map((step,i)=><span key={step.title} className="cr-map-step">{i>0 && <IconArrowRight size={16} aria-hidden="true"/>}<span>{[<IconSettings key="s" size={22}/>,<IconBuildingFactory2 key="f" size={22}/>,<IconPackage key="p" size={22}/>][i]}{step.title}</span></span>)}</div></div>
    <div className="cr-map-side"><span className="cr-eyebrow">买回去做什么</span>{products.map((item,i)=><a key={item.title} href="#company-business" onClick={e=>jumpTo(e,'company-business')}>{i===0?<IconDeviceDesktop size={28}/>:<IconNetwork size={28}/>}<div><h3>{item.title}</h3><p>{item.text}</p></div></a>)}</div>
    <div className="cr-map-evidence">依据公司披露整理 · 图解为业务归纳<SourceRefs ids={editorial.introductionSourceIds} sources={sources}/></div>
  </div>
}

function OperatingSummary({ editorial, sources }: { editorial: CompanyEditorial; sources: CompanySource[] }) {
  const summary = editorial.readingSummary
  if (!summary) return null
  return <section className="cr-operating-summary" aria-label="经营概况">
    <header><h3>{summary.headline}</h3><span>{summary.period}</span></header>
    <dl>{summary.metrics.map(metric=><div key={metric.label}><dt>{metric.label}</dt><dd>{metric.value}</dd><p>{metric.detail}</p></div>)}</dl>
    <p>{summary.note}<SourceRefs ids={summary.sourceIds} sources={sources}/></p>
    <a href="#company-finance" onClick={e=>jumpTo(e,'company-finance')}>查看多年经营变化<IconArrowDown size={15}/></a>
  </section>
}

function RevenueOverview({ editorial, sources }: { editorial: CompanyEditorial; sources: CompanySource[] }) {
  const mix = editorial.revenueMix
  return <div className="cr-revenue-overview"><div><div className="cr-inline-title"><h3>收入来自哪里</h3><span>{mix.period.slice(0,4)} 年度 · 全部营业收入</span></div><div className="cr-revenue-stack" role="img" aria-label={mix.items.map(i => `${i.name}${(i.share*100).toFixed(2)}%`).join('，')}>{mix.items.map((item,i) => <span key={item.name} className={`cr-mix-${i}`} style={{width:`${item.share*100}%`}} />)}</div><div className="cr-revenue-legend">{mix.items.map((item,i) => <div key={item.name}><span className={`cr-legend-dot cr-mix-${i}`} /><strong>{(item.share*100).toFixed(2)}<small>%</small></strong><span>{item.readerLabel || item.name}<small className="cr-revenue-official">{item.readerLabel ? `报告分类：${item.name}` : ''}</small></span></div>)}</div><SourceRefs ids={[...new Set(mix.items.flatMap(i=>i.sourceIds))]} sources={sources} /></div><aside><h3>{revenueHeadline(mix.items)}</h3><p>{mix.explanation}</p>{mix.periodNote && <small className="cr-revenue-period-note">{mix.periodNote}</small>}<a href="#company-business" onClick={e=>jumpTo(e,'company-business')}>展开业务与市场<IconArrowRight size={17} /></a></aside></div>
}

function Glossary() {
  return <div className="cr-glossary"><h3>把术语翻成白话</h3>{[
    ['收入 ≠ 收款','收入按会计规则确认；客户的付款时间可能不同。营业总收入和营业收入也不是同一个字段，请结合财报明细阅读。'],
    ['利润 ≠ 现金','归母净利润是归属于母公司股东的会计利润。经营现金流是经营活动现金流入减去流出，并非账上的现金余额。'],
    ['累计、单季与期末','中报和三季报通常给出年内累计值。单季流量由同年相邻累计值相减；资产、负债是期末存量，不能这样相减。'],
    ['业务收入占比','产品、地区、行业可能描述同一笔收入，不跨维度相加。分部的合计行也不能与子项重复计入。'],
  ].map(([term,text])=><details key={term}><summary>{term}</summary><p>{text}</p></details>)}</div>
}

export default function CompanyDocument({ company, industryLabel, onReady }: { company: CompanyDossier; industryLabel: string; onReady: () => void }) {
  const [editorial,setEditorial] = useState<CompanyEditorial|null>(null)
  const [seven,setSeven] = useState<SevenQuestionContent|null>(null)
  const [overview,setOverview] = useState<CompanyOverviewContent|null>(null)
  const [editorialError,setEditorialError] = useState(false), [retry,setRetry] = useState(0)
  const readyCallback = useRef(onReady)
  readyCallback.current = onReady
  const [selectedSources,setSelectedSources] = useState<string[]>([])
  const drawer = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    let cancelled = false
    setEditorialError(false); setEditorial(null); setSeven(null); setOverview(null)
    Promise.allSettled([loadEditorial(company.code), loadSevenQuestions(company.code), loadCompanyOverview(company.code)]).then(([legacy, deep, first]) => {
      if (cancelled) return
      const e = legacy.status === 'fulfilled' ? legacy.value : null
      const s = deep.status === 'fulfilled' ? deep.value : null
      const o = first.status === 'fulfilled' ? first.value : null
      const conflict = Boolean(e && s)
      setEditorial(!conflict && e?.name === company.name ? e : null)
      setSeven(!conflict && s?.name === company.name ? s : null)
      setOverview(o?.name === company.name ? o : null)
      setEditorialError(conflict || [legacy, deep, first].some(result => result.status === 'rejected') || Boolean(e && e.name !== company.name || s && s.name !== company.name || o && o.name !== company.name))
      readyCallback.current()
    })
    return () => { cancelled = true }
  }, [company.code, company.name, retry])
  const sources = useMemo(()=>[...(seven ? sevenQuestionAudioSources(seven) : []),...(editorial?.sources || []),...company.sources], [editorial,seven,company])
  const displayCompany = useMemo(()=>({...company,sources}),[company,sources])
  const openSources = (ids:string[]) => { setSelectedSources(ids); drawer.current?.showModal() }
  const history = editorial?.history || company.timeline
  const intro = company.summary.text || company.profile.intro || ''
  const basics = [['提供什么',company.summary.products],['服务谁',company.summary.customers],['收入从哪来',company.summary.revenue]].filter(([,text]) => text && !sameCopy(text,intro))
  const missingBasics = [['客户类型',company.summary.customers],['收入方式',company.summary.revenue]].filter(([,text]) => !text).map(([label]) => label)
  const distinctBusiness = company.businessModel.filter(claim => !sameCopy(claim.text,intro) && !basics.some(([,text]) => sameCopy(claim.text,text)))
  const introSourceIds = [...new Set([...company.summary.sourceIds, ...company.businessModel.filter(claim => sameCopy(claim.text,intro)).flatMap(claim => claim.sourceIds)])]
  const contentEntry = catalog.find(item => item.code === company.code)
  const nextEntry = nextHomeSample(catalog, company.code)
  const nextCompany = nextEntry ? {...nextEntry, durationSeconds: nextEntry.durationSeconds ?? null} : undefined
  const samples = selectHomeSamples(catalog).filter(item => item.code !== company.code).slice(0, 3)
  const audio = seven && contentEntry ? sevenQuestionAudio(seven, contentEntry.contentSha256) : editorial?.audio
  const financialCompany = company.companyType !== 'industrial'
  const costLabel = editorial?.businessStudy?.spending.find(item => item.reader?.kind === 'cost' || item.metric === editorial.costs[0]?.metric) ? (()=>{const item=editorial!.businessStudy!.spending.find(item => item.reader?.kind === 'cost' || item.metric === editorial!.costs[0]?.metric)!; return `${item.metricLabel} · ${item.period}`})() : ''
  return <SourcePanelContext.Provider value={openSources}><article className="cr-document">
    <section id="company-overview" className="cr-overview" tabIndex={-1}>
      <header className={`cr-company-hero${overview || editorial || seven ? ' has-editorial' : ''}`}><div><span className="cr-eyebrow">公司档案 · {industryLabel}</span><div className="cr-name-audio"><h1>{company.name}</h1><CompanyAudio companyCode={company.code} companyName={company.name} audio={audio} onSources={openSources} nextCompany={nextCompany} quickReadId={seven ? "sq-title" : "cq-title"} /></div><p className="cr-company-code">{company.code}<span>主体注册 {date(company.profile.founded)}</span><span>上市 {date(company.profile.listed)}</span></p></div><div className="cr-hero-intro">{overview ? <><span className="cr-eyebrow">生意概览</span><h2>{overview.tagline}</h2><p className="sq-preserve">{overview.introduction}</p></> : seven ? <SevenQuestionIntroduction content={seven}/> : editorial ? <><h2>{editorial.tagline}</h2><p>{editorial.introduction}</p></> : <p>{intro || '可在下方查看公司登记资料与财报。'}</p>}{!overview && !seven && (editorial || introSourceIds.length > 0 || company.coverage.summary?.status === "available") && <SourceRefs ids={editorial?.introductionSourceIds || introSourceIds} sources={sources} />}{!overview && !editorial && !seven && company.coverage.summary?.status !== "available" && <p className="cr-summary-status">经营说明 · {introSourceIds.length ? "原文依据待核对" : "出处待补"}</p>}</div></header>
      {overview ? <CompanyOverview content={overview} deepTarget={seven ? "company-deep-reading" : editorial ? "company-business" : undefined} /> : seven ? <CompanySevenQuestions content={seven} /> : <CompanyQuickRead company={company} editorial={editorial} industryLabel={industryLabel} sources={sources} />}
      {overview && seven && <div id="company-deep-reading" className="co-deep" tabIndex={-1}><div className="cr-hero-intro"><SevenQuestionIntroduction content={seven}/></div><CompanySevenQuestions content={seven} /></div>}
      {editorialError && <p className="cr-load-warning" role="status">经营解读暂时未能加载，基础资料仍可阅读。<button type="button" onClick={()=>setRetry(v=>v+1)}>重试</button></p>}
      {seven ? <p className="cr-reading-date">经营解读资料截止 {seven.asOf} · 财务数据截至 {date(company.asOf)}。各部分报告期间与核对范围见资料出处。</p> : editorial ? <><BusinessMap editorial={editorial} sources={sources} /><RevenueOverview editorial={editorial} sources={sources} /><OperatingSummary editorial={editorial} sources={sources}/><p className="cr-reading-date">经营解读依据：{editorial.reportBasis} 财务数据截至 {date(company.asOf)}。</p></> : !overview ? <>{basics.length > 0 && <div className="cr-basics" style={{gridTemplateColumns:`repeat(${basics.length},minmax(0,1fr))`}}>{basics.map(([label,text])=><div key={label}><h3>{label}</h3><p>{text}</p></div>)}</div>}{missingBasics.length > 0 && <p className="cr-content-gap">{missingBasics.join("、")}的说明尚未收录，可查看下方业务披露和财报。</p>}</> : null}
      {!overview && !editorial && !seven && samples.length > 0 && <aside className="cr-sample-bridge" aria-labelledby="cr-sample-bridge-title">
        <h2 id="cr-sample-bridge-title">也读读这些公司的生意</h2>
        <p>从产品、客户和收入，了解不同公司的经营方式。</p>
        <div className="cr-sample-grid">{samples.map(item => <a key={item.code} className="cr-sample-card" href={`#/company/${item.code}`}>
          <span className="cr-sample-code">{item.code.slice(0, 6)}</span><h3>{item.name}</h3>
          <p className="cr-sample-tagline">{item.tagline}</p>
          <span className="cr-sample-foot"><span className="cr-sample-label">{audioLabel(item.audio, item.durationSeconds, 'long') || '经营解读'}</span><span>阅读档案 <IconArrowUpRight size={16} aria-hidden="true" /></span></span>
        </a>)}</div>
      </aside>}
    </section>

    <section id="company-business" className="cr-section" tabIndex={-1}><SectionTitle number="01" title={seven || overview ? '公司业务披露' : '业务与市场'}>{seven || overview ? '公司自述、登记范围与各期收入分类。登记范围不等于实际收入来源。' : editorial?.businessStudy ? null : editorial || distinctBusiness.length ? "从产品用途开始，顺着客户、交付和收入，理解这门生意。" : "主营自述与业务披露见下方；公司登记范围不代表每项业务都已产生收入。"}</SectionTitle>
      {seven || (overview && !editorial) ? null : editorial ? (editorial.businessStudy ? <CompanyBusinessStudy study={editorial.businessStudy} sources={sources} /> : <><div className="cr-business-columns"><div><h3 className="cr-subtitle">谁需要它，为什么需要</h3>{editorial.customers.map(c=><div className="cr-text-row" key={c.name}><h4>{c.name}</h4><p>{c.purpose}</p><SourceRefs ids={c.sourceIds} sources={sources} /></div>)}</div><div><h3 className="cr-subtitle">产品在做什么</h3>{editorial.products.map(p=><div className="cr-text-row" key={p.name}><span className="cr-small-label">{p.business}</span><h4>{p.name}</h4><p>{p.purpose}</p><SourceRefs ids={p.sourceIds} sources={sources} /></div>)}</div></div>
      <h3 className="cr-subtitle cr-spaced">一笔生意，怎样完成</h3><ol className="cr-process">{editorial.process.map((p,i)=><li key={p.title}><span>{String(i+1).padStart(2,'0')}</span><h4>{p.title}</h4><p>{p.text}</p><SourceRefs ids={p.sourceIds} sources={sources} /></li>)}</ol><p className="cr-pullquote">{editorial.paymentExplanation}<SourceRefs ids={editorial.paymentSourceIds} sources={sources} /></p>
      <div className="cr-business-columns"><div><h3 className="cr-subtitle">钱主要花在哪里</h3>{editorial.costs.map((c,i)=><div className="cr-text-row" key={c.title}>{c.metric && <strong className="cr-cost-metric">{c.metric}{costLabel && i===0 && <small>{costLabel}</small>}</strong>}<h4>{c.title}</h4><p>{c.text}</p><SourceRefs ids={c.sourceIds} sources={sources} /></div>)}</div><div><h3 className="cr-subtitle">经营依赖什么</h3>{editorial.dependencies.map(d=><div className="cr-text-row" key={d.title}><h4>{d.title}</h4><p>{d.text}</p><SourceRefs ids={d.sourceIds} sources={sources} /></div>)}</div></div></>) : <>{distinctBusiness.length > 0 && <Claims claims={distinctBusiness} sources={sources} empty="" />}{(company.competitive.length>0 || company.risks.length>0) && <div className="cr-business-columns cr-spaced"><div><h3 className="cr-subtitle">怎样获得客户</h3><Claims claims={company.competitive} sources={sources} empty="独立的竞争位置证据待补充。" /></div><div><h3 className="cr-subtitle">经营依赖与待观察问题</h3><Claims claims={company.risks} sources={sources} empty="观察问题待补充。" /></div></div>}</>}
      <details className="cr-profile-details"><summary>公司简介与登记资料</summary><h3>公司简介 · 公司自述</h3><LongText text={company.profile.intro} limit={600}/><h3>主营业务</h3><LongText text={company.profile.mainBusiness}/><h3>登记经营范围</h3><LongText text={company.profile.businessScope}/><p className="cr-muted">登记范围描述可以开展的业务，不代表均已产生收入。基础资料查询日期 {date(company.profileAsOf)}。</p>{safeUrl(company.profile.website)&&<a href={safeUrl(company.profile.website)} target="_blank" rel="noreferrer">公司网站 ↗</a>}</details>
      {overview || editorial || seven ? <details className="cr-profile-details cr-raw-segments"><summary>各期收入构成与原始披露</summary><p className="cr-muted">各期维度和报告范围不同；合计与子项不能重复相加。</p><BusinessSegments groups={company.segments} sources={sources}/></details> : <div className="cr-segment-section"><h3 className="cr-subtitle">收入与业务构成</h3><BusinessSegments groups={company.segments} sources={sources}/></div>}
    </section>

    <section id="company-history" className="cr-section" tabIndex={-1}><SectionTitle number="02" title="怎样成为今天的公司">{'法律主体的设立时间与实际业务起源可能不同，具体变化见各条资料出处。'}</SectionTitle>{history.length ? <ol className="cr-history">{history.map((event,i)=><li key={`${event.date}-${i}`}><time>{date(event.date)}</time><div><h3>{event.title}</h3><p>{editorial ? event.text : baseHistoryReaderText(company.code, event)}</p>{!editorial && <div className="cr-history-status"><span>{(event as CompanyClaim).kind === 'company_statement' ? '公司披露' : (event as CompanyClaim).kind === 'interpretation' ? '解读' : '事实'}</span>{(event as CompanyClaim).status && (event as CompanyClaim).status !== 'available' && <Status status={(event as CompanyClaim).status!}/>}</div>}<SourceRefs ids={event.sourceIds} sources={sources}/></div></li>)}</ol> : <EmptyNote>本站尚未收录业务沿革。页首的主体注册与上市时间不代表完整发展历史。</EmptyNote>}</section>

    <section id="company-finance" className="cr-section" tabIndex={-1}><SectionTitle number="03" title="经营怎样变化">把数字放回生意里，分清规模、利润与现金的不同含义。</SectionTitle>{financialCompany && <p className="cr-industry-note">{company.companyType==='bank'?'银行通过贷款、存款、结算等金融服务开展经营，重点结合利息、非息收入和资产质量阅读。':company.companyType==='insurance'?'保险需区分保险服务与投资等业务，以及对应会计口径。':'金融服务企业需结合各自业务与报表口径理解。'} 不将制造业的材料、存货或单一现金流标准直接套用到这里。</p>}{seven && <p className="cr-muted">历史财务的期间、口径和核对范围见各项说明，与经营解读所引用的报告范围分别列示。</p>}<div className="cr-finance-layout"><FinancialHistory company={displayCompany}/></div>{editorial && <details className="cr-profile-details cr-finance-reading"><summary>{financeReadingTitle(editorial.financeNotes)}</summary><div className="cr-finance-reading-grid">{editorial.financeNotes.map(note=><div className="cr-finance-note" key={note.title}><h3>{note.title}</h3><p>{note.text}</p><p>{note.meaning}</p><p className="cr-muted">{note.boundary}</p><SourceRefs ids={note.sourceIds} sources={sources}/></div>)}</div></details>}{editorial?.businessStudy && <CompanyCashExplanation study={editorial.businessStudy} sources={sources} />}<Glossary/></section>

    <section id="company-sources" className="cr-section" tabIndex={-1}><SectionTitle number="04" title="资料出处">正文下可展开原文。找到对应报告，不代表已经核对报告中的每项数据。</SectionTitle>{overview && <CompanyOverviewSources content={overview}/>} {seven && <SevenQuestionSources content={seven}/>} {(overview || seven) && <h3 className="cr-subtitle">公司档案与财报来源</h3>}<Sources sources={sources} onOpen={openSources}/>{editorial && <details className="cr-profile-details"><summary>这份经营解读还缺什么</summary><ul>{editorial.evidenceGaps.map(g=><li key={g}>{g}</li>)}</ul></details>}<details className="cr-profile-details"><summary>资料范围与缺失项</summary>{editorial && <p className="cr-muted">经营解读的报告范围为 {editorial.reportBasis}。下列状态只说明基础资料、财报和历史记录的可用范围，不代表各部分均已逐项核对。</p>}{(overview || seven) && <p className="cr-muted">生意概览与经营解读的依据见对应原文。下列状态只说明基础资料、财报和历史记录的可用范围，不代表各部分均已逐项核对。</p>}<dl className="cr-coverage">{Object.entries(company.coverage).filter(([key]) => baseCoverageVisible(company.code, key, Boolean(overview || seven))).map(([key,item])=><div key={key}><dt>{{profile:'基础资料',summary:'公司概览',businessModel:'业务解释',timeline:'发展历史',research:'经营研究',segments:'业务构成',latestFinancial:'最近财报',financialHistory:'历年财报',balanceSheet:'资产负债',sources:'原始出处'}[key] || baseCoverageReaderLabel(company.code, key)}<Status status={item.status}/></dt><dd>{baseCoverageReaderNote(company.code, key, item.note)}</dd></div>)}</dl></details></section>
    <footer className="cr-end"><InformationNotice/><p>{company.name} · 公司档案<br/>财务资料截至 {date(company.asOf)}{editorial && ` · 经营解读核读 ${editorial.createdAt}`}{seven && ` · 七问资料截止 ${seven.asOf}`}</p></footer>
    <dialog className="cr-drawer cr-source-drawer" ref={drawer} aria-labelledby="cr-source-title" onClick={event=>{if(event.target===event.currentTarget)drawer.current?.close()}}><div className="cr-drawer-inner"><header><div><span className="cr-eyebrow">沿着证据阅读</span><h2 id="cr-source-title">资料出处</h2></div><button type="button" aria-label="关闭资料出处" onClick={()=>drawer.current?.close()}><IconX size={23}/></button></header>{selectedSources.map(id=>{const source=sources.find(s=>s.id===id);return source?<SourceCard key={id} source={source}/>:<p key={id}>本站尚未收录这项引用的原文记录。</p>})}<p className="cr-source-footnote">“已核对相关内容”仅限所列章节和数字。公司自述与编辑归纳仍按正文说明区分。</p></div></dialog>
  </article></SourcePanelContext.Provider>
}
