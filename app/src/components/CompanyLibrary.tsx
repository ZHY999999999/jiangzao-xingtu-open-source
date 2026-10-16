import { IconUsersGroup } from '@tabler/icons-react'
import { useEffect, useId, useMemo, useRef, useState } from 'react'
import type { Dispatch, SetStateAction, RefObject } from 'react'
import { loadCompany, loadCompanyIndex } from '../lib/company'
import SiteHeader from './SiteHeader'
import type { CompanyClaim, CompanyDossier, CompanyIndex, CompanyIndexEntry, CompanySource, CompanySearchState, EvidenceStatus, FinancialPoint, SegmentGroup } from '../lib/company'
import '../styles/company.css'
import InformationNotice from './InformationNotice'
import RelatedCompanies from './RelatedCompanies'
import CompanyDocument from './CompanyDocument'
import catalogue from 'virtual:company-content-catalogue'
import { audioLabel } from '../lib/audio-label'
import { contentFirst, contentLabel, selectContent } from '../lib/content-catalogue'
import { date, jumpTo } from './CompanyDetailParts'
import '../styles/company-reading.css'

type Props = { code?: string; atlasHash: string; onBack: () => void; onHome: () => void; onOpenCompany: (code: string) => void; directorySearch: CompanySearchState; setDirectorySearch: Dispatch<SetStateAction<CompanySearchState>>; directoryScroll: RefObject<number> }
type DirectoryIndex = Omit<CompanyIndex, 'companies'> & { companies: (CompanyIndexEntry & { industryBoards?: string[] })[] }
const readingPositions = new Map<string, number>()
const CHAPTERS = [['company-overview','公司概览'],['company-business','业务与市场'],['company-history','发展历程'],['company-finance','经营变化'],['company-sources','资料出处']] as const
export function CompanySearch({ index, activeCode, onOpen, compact = false, state, setState }: { index: DirectoryIndex; activeCode?: string; onOpen: (code: string) => void; compact?: boolean; state: CompanySearchState; setState: Dispatch<SetStateAction<CompanySearchState>> }) {
  const { query, industry, limit } = state
  const setQuery = (query: string) => setState(previous => ({ ...previous, query, limit: compact ? 40 : 60 }))
  const setIndustry = (industry: string) => setState(previous => ({ ...previous, industry, limit: compact ? 40 : 60 }))
  const searchId = useId()
  const industries = useMemo(() => [...new Set(index.companies.flatMap(company => company.industryBoards || []).filter(Boolean))].sort(), [index])
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return index.companies.filter(company => (!industry || company.industryBoards?.includes(industry)) &&
      (!q || `${company.name} ${company.code} ${company.industry} ${company.summary}`.toLowerCase().includes(q)))
      .sort((a, b) => contentFirst(catalogue, a, b))
  }, [index, query, industry])
  return <div className={`cl-company-search${compact ? ' cl-search-compact' : ''}`}>
    <label className="cl-field-label" htmlFor={searchId}>查找一家公司</label>
    <div className="cl-search-input"><span aria-hidden="true">⌕</span><input id={searchId} type="search" placeholder="公司名称、代码或行业" value={query} onChange={event => setQuery(event.target.value)} autoComplete="off" />{query && <button type="button" onClick={() => setQuery('')} aria-label="清空公司搜索">×</button>}</div>
    <div className="cl-search-filters"><select aria-label="按行业板块筛选公司" value={industry} onChange={event => setIndustry(event.target.value)}><option value="">全部行业板块</option>{industries.map(name => <option key={name} value={name}>{name}</option>)}</select><span aria-live="polite">{filtered.length.toLocaleString('zh-CN')} 家</span></div>
    <div className="cl-company-results">{filtered.slice(0, limit).map(company => <CompanyResult key={company.code} company={company} selected={company.code === activeCode} compact={compact} onOpen={onOpen} />)}</div>
    {!filtered.length && <p className="cl-no-results">没有匹配的公司。可以换用六位代码或更短的名称。</p>}
    {filtered.length > limit && <button className="cl-load-more" type="button" onClick={() => setState(previous => ({ ...previous, limit: previous.limit + (compact ? 40 : 60) }))}>查看更多公司 <span>{Math.min(limit, filtered.length)} / {filtered.length}</span></button>}
  </div>
}

export function CompanyResult({ company, selected, compact, onOpen }: { company: CompanyIndexEntry; selected: boolean; compact: boolean; onOpen: (code: string) => void }) {
  const content = selectContent(catalogue, company.code)
  return <button type="button" className={`cl-company-result${selected ? ' is-current' : ''}`} aria-current={selected ? 'page' : undefined} onClick={() => onOpen(company.code)}>
    <span className="cl-company-result-top"><strong>{company.name}</strong><span className="cl-company-code">{company.code.slice(0, 6)}</span></span>
    <span className="cl-result-industry" title="与市场星图一致的同花顺行业板块">{company.industry || '行业板块待补'}{content && <em>{contentLabel(content)}</em>}{content && content.audio !== 'none' && <em className="cl-audio-badge">{audioLabel(content.audio, content.durationSeconds)}</em>}</span>
    {!compact && <span className="cl-result-summary">{content ? content.overview?.tagline || content.tagline : company.summary || '查看登记资料、业务披露与财报。'}</span>}
    {!compact && <span className="cl-result-bottom"><span>{company.hasHistory ? '可查看财报' : '本站尚未收录财报'}</span><span aria-hidden="true">阅读档案 ↗</span></span>}
  </button>
}

export default function CompanyLibrary({ code, atlasHash, onBack, onHome, onOpenCompany, directorySearch, setDirectorySearch, directoryScroll }: Props) {
  const [industryBoards, setIndustryBoards] = useState<typeof import('virtual:company-industries').default | null>(null)
  const [industryError, setIndustryError] = useState(false)
  const [index, setIndex] = useState<CompanyIndex | null>(null)
  const [company, setCompany] = useState<CompanyDossier | null>(null)
  const [indexError, setIndexError] = useState(''), [companyError, setCompanyError] = useState('')
  const [retry, setRetry] = useState(0), [directoryOpen, setDirectoryOpen] = useState(false)
  const [activeChapter, setActiveChapter] = useState<string>(CHAPTERS[0][0])
  const root = useRef<HTMLElement>(null)
  const relatedDialog = useRef<HTMLDialogElement>(null)
  const restoring = useRef(true)
  const targetScroll = useRef(0)
  const restoreReading = () => { requestAnimationFrame(() => requestAnimationFrame(() => { root.current?.scrollTo({ top: targetScroll.current, behavior: 'instant' }); root.current?.focus({ preventScroll: true }); restoring.current = false })) }
  useEffect(() => { const dialog = relatedDialog.current; if (!dialog) return; if (directoryOpen && !dialog.open) dialog.showModal(); else if (!directoryOpen && dialog.open) dialog.close() }, [directoryOpen, company])
  useEffect(() => {
    let cancelled = false
    setIndexError('')
    loadCompanyIndex(retry > 0).then(value => { if (!cancelled) setIndex(value) }).catch(error => { if (!cancelled) setIndexError(error instanceof Error ? error.message : '公司目录暂时无法读取。') })
    return () => { cancelled = true }
  }, [retry])
  useEffect(() => {
    let cancelled = false
    restoring.current = true; targetScroll.current = code ? readingPositions.get(code) || 0 : 0
    setCompanyError(''); setCompany(null); setDirectoryOpen(false); setActiveChapter(CHAPTERS[0][0])
    if (code) root.current?.scrollTo({ top: 0 })
    if (code) loadCompany(code).then(value => { if (!cancelled) setCompany(value) }).catch(error => { if (!cancelled) setCompanyError(error instanceof Error ? error.message : '公司档案暂时无法读取。') })
    return () => { cancelled = true }
  }, [code, retry])
  useEffect(() => {
    if (code || !index || indexError) return
    const frame = requestAnimationFrame(() => root.current?.scrollTo({ top: directoryScroll.current, behavior: 'instant' }))
    return () => cancelAnimationFrame(frame)
  }, [code, index, indexError, directoryScroll])
  useEffect(() => {
    let cancelled = false
    setIndustryError(false)
    import('virtual:company-industries').then(module => { if (!cancelled) setIndustryBoards(module.default) }).catch(() => { if (!cancelled) setIndustryError(true) })
    return () => { cancelled = true }
  }, [retry])
  const industryByCode = useMemo(() => {
    const lookup = new Map<string, string[]>()
    for (const board of industryBoards || []) for (const member of board.members) lookup.set(member, [...(lookup.get(member) || []), board.name])
    return lookup
  }, [industryBoards])
  const displayIndex: DirectoryIndex | null = useMemo(() => index ? { ...index, companies: index.companies.map(item => ({...item, industry: (industryByCode.get(item.code) || []).join(' / '), industryBoards: industryByCode.get(item.code) || []})) } : null, [index, industryByCode])
  const dossier = company?.code === code ? company : null
  useEffect(() => {
    document.title = dossier ? `${dossier.name} · 公司档案 | 降噪星图` : code ? '公司档案 | 降噪星图' : '公司目录 | 降噪星图'
  }, [code, dossier])
  useEffect(() => {
    const element = root.current
    if (!dossier || !element) return
    let frame = 0
    const update = () => {
      frame = 0
      const top = (element.querySelector('.site-header')?.getBoundingClientRect().height || 76) + (element.querySelector('.cr-chapter-nav')?.getBoundingClientRect().height || 64) + 36
      let active: string = CHAPTERS[0][0]
      CHAPTERS.forEach(([id]) => { const section = element.querySelector(`#${id}`); if (section && section.getBoundingClientRect().top <= top + 2) active = id })
      if(element.scrollTop + element.clientHeight >= element.scrollHeight - 5) active = 'company-sources'
      setActiveChapter(active)
    }
    const schedule = () => { if(!frame) frame=requestAnimationFrame(update) }
    element.addEventListener('scroll', schedule, {passive:true}); window.addEventListener('resize',schedule); schedule()
    return () => { element.removeEventListener('scroll',schedule); window.removeEventListener('resize',schedule); cancelAnimationFrame(frame) }
  }, [dossier])
  useEffect(() => {
    const header = root.current?.querySelector('.site-header')
    if (!header) return
    const update = () => root.current?.style.setProperty('--cr-header-height', `${header.getBoundingClientRect().height}px`)
    const observer = new ResizeObserver(update); observer.observe(header); update()
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    const active = root.current?.querySelector<HTMLElement>('.cr-chapter-nav [aria-current]')
    const strip = active?.parentElement
    if (!active || !strip) return
    const item = active.getBoundingClientRect(), bounds = strip.getBoundingClientRect()
    if (item.left < bounds.left) strip.scrollLeft -= bounds.left - item.left
    else if (item.right > bounds.right) strip.scrollLeft += item.right - bounds.right
  }, [activeChapter])
  const error = code ? companyError || indexError : indexError
  const openCompany = (nextCode: string) => { setDirectoryOpen(false); onOpenCompany(nextCode) }
  const focusDirectory = () => {
    setDirectoryOpen(true)
    // The modal moves focus and restores it on close.
  }
  const closeDirectory = () => {
    setDirectoryOpen(false)
    root.current?.querySelector<HTMLButtonElement>('.cl-directory-toggle')?.focus()
  }
  return <main className="company-library" ref={root} tabIndex={-1} aria-label={dossier ? `${dossier.name}公司档案` : "A股公司目录"} onScroll={event => { if (!code && index && !error) directoryScroll.current = event.currentTarget.scrollTop; if (code && dossier && !restoring.current) readingPositions.set(code,event.currentTarget.scrollTop) }}>
    <SiteHeader current="companies" variant="bar" atlasHash={atlasHash} onHome={onHome}
      actions={code && <button type="button" className="cl-directory-toggle" onClick={focusDirectory} aria-label="相关公司" aria-expanded={directoryOpen} aria-controls="related-company-catalog"><span className="cl-related-label">相关公司</span><IconUsersGroup size={19} aria-hidden="true" /></button>} />
    {error ? <div className="cl-page-message" role="alert"><span className="cl-kicker">资料尚未就绪</span><h1>{code ? '这次没能打开公司档案' : '这次没能打开公司目录'}</h1><p>{error}</p><div className="cl-recovery-actions"><button type="button" className="cl-primary-button" onClick={() => setRetry(value => value + 1)}>重新读取</button>{code && <button type="button" className="cl-secondary-button" onClick={() => { location.hash = "/companies" }}>返回公司目录</button>}<button type="button" className="cl-secondary-button" onClick={onBack}>返回市场星图</button></div></div> : !index || (code && !dossier) ? <div className="cl-page-message" role="status"><span className="cl-loading-mark" /><h1>{code ? '正在翻开公司档案' : '正在准备公司目录'}</h1><p>首次打开需要读取目录和公司资料。单次读取超过 15 秒会提示重试。</p></div> : !code ? <div className="cl-directory-page"><header className="cl-directory-hero"><span className="cl-kicker">A股 · 公司阅读室</span><h1>从一家公司，<br />读懂一门生意。</h1><p>查找公司，沿着历史、业务构成和多年财报，建立对经营的理解。</p><div className="cl-directory-counts"><div><strong>{index.coverage.total.toLocaleString('zh-CN')}</strong><span>家公司</span></div><div><strong>{index.coverage.financialHistory.toLocaleString('zh-CN')}</strong><span>已有财报记录</span></div><div><strong>{catalogue.counts.readable.toLocaleString('zh-CN')}</strong><span>有公司解读</span></div><p>生意概览 {catalogue.counts.reviewedOverview || 0} 家 · 完整七问解读 {catalogue.counts.reviewedSeven} 家 · 目录截至 {date(index.asOf)}</p></div></header><CompanySearch index={displayIndex || index} onOpen={openCompany} state={directorySearch} setState={setDirectorySearch} /><footer className="cl-directory-footer">同一家公司可以同时阅读生意概览与经营解读。财报按可用记录统计，具体期间与缺失项见公司页面。</footer><InformationNotice /></div> : dossier && <div className="cr-reading-layout">
      <nav className="cr-chapter-nav" aria-label="公司档案章节"><strong>{dossier.name}</strong><div>{CHAPTERS.map(([id,label]) => <a key={id} href={`#${id}`} onClick={event => jumpTo(event,id)} aria-current={activeChapter === id ? 'location' : undefined}>{label}</a>)}</div></nav>
      <CompanyDocument key={dossier.code} company={dossier} industryLabel={(industryByCode.get(dossier.code) || []).join(" / ") || (industryError ? "行业板块暂不可用" : industryBoards ? "行业板块待补" : "行业板块读取中")} onReady={restoreReading} />
      <dialog ref={relatedDialog} id="related-company-catalog" className="cr-drawer cr-related-drawer" aria-labelledby="cr-related-title" onClose={() => setDirectoryOpen(false)} onClick={event => { if(event.target === event.currentTarget) closeDirectory() }}><div className="cr-drawer-inner"><header><div><span className="cr-eyebrow">从一家公司延伸</span><h2 id="cr-related-title">相关公司</h2></div><button type="button" onClick={closeDirectory} aria-label="关闭相关公司">×</button></header>{directoryOpen && <RelatedCompanies key={code} index={index} company={dossier} onOpen={openCompany} />}</div></dialog>
    </div>}
  </main>
}
