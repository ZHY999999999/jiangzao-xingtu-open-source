import { createContext, useContext, useEffect, useId, useMemo, useRef, useState } from 'react'
import type { CompanyClaim, CompanyDossier, CompanySource, EvidenceStatus, FinancialPoint, SegmentGroup } from '../lib/company'
import '../styles/company-detail-parts.css'
import CompanyCashChart from './CompanyCashChart'
import { segmentDisplay, usableSourceUrl, segmentNeedsReview, segmentDimensionLabel, orderSegments } from '../lib/company-reading'
import { baseFinanceReaderNote } from '../lib/base-dossier-reader-copy'
export const SourcePanelContext = createContext<((ids: string[]) => void) | null>(null)

type Metric = 'revenue' | 'netProfit' | 'operatingCashFlow' | 'totalAssets' | 'totalLiabilities'
const METRICS: { key: Metric; label: string; explanation: string }[] = [
  { key: 'revenue', label: '营收', explanation: '公司在这段时间确认的营业收入；具体字段见下方明细。' },
  { key: 'netProfit', label: '归母净利润', explanation: '扣除成本费用后，归属于母公司股东的净利润。负值表示亏损。' },
  { key: 'operatingCashFlow', label: '经营现金流', explanation: '经营活动现金流入减去流出；负值表示本期经营现金净流出。' },
  { key: 'totalAssets', label: '总资产', explanation: '报告期末公司控制的资产总额，是时点数。' },
  { key: 'totalLiabilities', label: '总负债', explanation: '报告期末承担的负债总额，是时点数。' },
]
const STATUS: Record<EvidenceStatus, string> = { available: '有资料', partial: '资料不全', missing: '未收录', review: '尚需核对' }
const finite = (value: number | null | undefined): value is number => typeof value === 'number' && Number.isFinite(value)
const date = (value?: string | null) => !value ? '待补' : /^\d{8}$/.test(value) ? value.replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3') : /^\d{4}-\d{2}-\d{2}T/.test(value) ? value.slice(0, 10) : value
const money = (value: number | null | undefined, digits = 2) => finite(value) ? (value / 1e8).toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits }) : '—'
const rawNumber = (value: number | null | undefined) => finite(value) ? value.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : '—'
const currency = (value: string) => ({ CNY: '人民币', RMB: '人民币', USD: '美元', HKD: '港元' }[value] || value || '币种待补')
const safeUrl = (value?: string | null) => value && /^https?:\/\//i.test(value) ? value : undefined
const sourceDescription = (value?: string) => value?.replace(/\[来源根:[^\]]*\]\s*/g, '').trim() || ''
// Why a link must not be offered as "打开原始公告".
const SOURCE_UNUSABLE: Record<string, string> = {
  permanently_unavailable: '原文已永久失效',
  html_instead_of_pdf: '原链接返回网页而非 PDF 文件',
  not_a_pdf: '原链接不是 PDF 文件',
  refused_unsafe_redirect: '原链接跳转到非披露站点，已拒绝',
  transient_failure: '原链接暂时无法访问',
}
// An openable original: not a gap placeholder, and the release did not record the link
// as unusable. Everything else is presented as a status, never as a button.
const sourceUnusable = (source: CompanySource) => source.available === false || Boolean(SOURCE_UNUSABLE[source.accessStatus || ''])
const sourceLink = usableSourceUrl
const sourceStatus = (source: CompanySource) => sourceUnusable(source)
  ? SOURCE_UNUSABLE[source.accessStatus || ''] || '原文暂不可用'
  : source.candidate ? `原文待核${source.accessStatus === 'unchecked' ? ' · 链接未核验' : ''}`
    : source.pending ? '原文待补'
      : source.accessStatus === 'unchecked' ? '链接未核验' : undefined
const sourceAction = (source: CompanySource) => source.candidate ? '查看相关报告（待核）'
  : source.accessStatus === 'unchecked' ? '查看原文（链接未核验）'
    : source.sourceType === 'filing' ? '打开原始公告'
      : source.sourceType === 'company' ? '打开公司资料' : '打开资料'
const sourceGaps = (sources: CompanySource[]) => sources.filter(source => source.pending || source.candidate || sourceUnusable(source)).length
const reportName = (period: string) => `${period.slice(0, 4)} 年${({ '0331': '一季报', '0630': '中报', '0930': '三季报', '1231': '年报' } as Record<string, string>)[period.slice(4)] || '报告'}`
const periodLabel = (period: string, quarterly = false) => quarterly ? `${period.slice(0, 4)} Q${({ '0331': 1, '0630': 2, '0930': 3, '1231': 4 } as Record<string, number>)[period.slice(4)] || '?'}` : period.slice(0, 4)
const revenueName = (field?: string | null) => field === 'total_revenue' ? '营业总收入' : field === 'revenue' ? '营业收入' : '营收（口径待补）'

function jumpTo(event: React.MouseEvent<HTMLAnchorElement>, id: string) {
  event.preventDefault()
  const target = document.getElementById(id)
  let parent = target?.parentElement
  while (parent) {
    if (parent instanceof HTMLDetailsElement) parent.open = true
    parent = parent.parentElement
  }
  target?.scrollIntoView({ block: 'start' })
  if (target instanceof HTMLElement && target.hasAttribute('tabindex')) target.focus({ preventScroll: true })
}

function Status({ status }: { status: EvidenceStatus }) {
  return <span className={`cl-status cl-status-${status}`}><i />{STATUS[status]}</span>
}

function SourceRefs({ ids, sources }: { ids: string[]; sources: CompanySource[] }) {
  const openSources = useContext(SourcePanelContext)
  const unique = [...new Set(ids)]
  if (!unique.length) return <span className="cl-source-missing">出处待补</span>
  return <span className="cl-source-refs" aria-label="本段出处">{unique.map(id => {
    const index = sources.findIndex(source => source.id === id)
    if (index < 0) return <span key={id} className="cl-source-missing">出处待复核</span>
    const status = sourceStatus(sources[index])
    return status
      ? <a key={id} className="cl-source-missing" href={`#company-source-${index + 1}`} onClick={event => { if (openSources) { event.preventDefault(); openSources([id]) } else jumpTo(event, `company-source-${index + 1}`) }} title={`${sources[index].title} · ${status}`} aria-label={`第 ${index + 1} 条资料：${status}`}>[{index + 1}]</a>
      : <a key={id} href={`#company-source-${index + 1}`} onClick={event => { if (openSources) { event.preventDefault(); openSources([id]) } else jumpTo(event, `company-source-${index + 1}`) }} title={sources[index].title}>[{index + 1}]</a>
  })}</span>
}

function LongText({ text, limit = 250 }: { text: string; limit?: number }) {
  const [expanded, setExpanded] = useState(false)
  const id = useId()
  if (!text) return <p className="cl-empty-copy">本站尚未收录这部分说明。</p>
  return <div className="cl-long-copy">
    <p id={id} className={!expanded && text.length > limit ? 'cl-copy-collapsed' : ''}>{text}</p>
    {text.length > limit && <button type="button" className="cl-text-action" aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded(!expanded)}>{expanded ? '收起全文 ↑' : '展开全文 ↓'}</button>}
  </div>
}

function Claims({ claims, sources, empty }: { claims: CompanyClaim[]; sources: CompanySource[]; empty: string }) {
  if (!claims.length) return <EmptyNote>{empty}</EmptyNote>
  return <div className="cl-claims">{claims.map((claim, index) => <article className="cl-claim" key={`${claim.title}-${index}`}>
    <div className="cl-claim-heading"><h3>{claim.title}</h3><span className={`cl-claim-kind cl-kind-${claim.kind}`}>{claim.kind === 'fact' ? '事实' : claim.kind === 'company_statement' ? '公司披露' : '解读'}</span>{claim.status && claim.status !== 'available' && <Status status={claim.status} />}</div>
    <LongText text={claim.text} limit={360} />
    <SourceRefs ids={claim.sourceIds} sources={sources} />
  </article>)}</div>
}

function EmptyNote({ children }: { children: React.ReactNode }) {
  return <div className="cl-empty-note"><span>资料说明</span><p>{children}</p></div>
}

function BusinessSegments({ groups, sources }: { groups: SegmentGroup[]; sources: CompanySource[] }) {
  const ordered = useMemo(() => orderSegments(groups), [groups])
  const [expanded, setExpanded] = useState(false)
  const [selected, setSelected] = useState(0)
  if (!ordered.length) return <EmptyNote>尚未补齐按产品、行业或地区披露的业务构成。公司总营收不能替代细分业务收入。</EmptyNote>
  const group = ordered[Math.min(selected, ordered.length - 1)]
  const display = segmentDisplay(group)
  const hierarchyUnclear = segmentNeedsReview(group)
  const visibleItems = expanded ? display.items : display.items.slice(0,8)
  const maxRevenue = Math.max(0, ...display.items.map(item => finite(item.revenue) ? Math.abs(item.revenue) : 0))
  const hasNegative = group.items.some(item => finite(item.revenue) && item.revenue < 0)
  const totalShare = display.items.reduce((sum, item) => sum + (finite(item.share) ? item.share : 0), 0)
  return <div className="cl-segments">
    <div className="cl-subsection-toolbar"><label>披露维度<select value={selected} onChange={event => { setSelected(Number(event.target.value)); setExpanded(false) }}>{ordered.map((item, i) => <option key={`${item.period}-${item.dimension}-${i}`} value={i}>{reportName(item.period)} · {segmentDimensionLabel(item.dimension)}</option>)}</select></label><span>金额：{currency(group.currency)}亿元</span></div>
    <p className="cl-small-note">{hierarchyUnclear ? "原记录含汇总、层级或口径差异，以下逐项列示，不作为可相加的收入结构。" : "同一披露维度内比较收入规模；各维度不相加。"}</p><div className={`cl-segment-list${hierarchyUnclear ? " is-unresolved" : ""}`}>{visibleItems.map((item, index) => <div className="cl-segment-row" key={`${item.name}-${index}`}>
      <div className="cl-segment-label"><strong>{item.name}</strong><SourceRefs ids={item.sourceIds} sources={sources} /></div>
      {!hierarchyUnclear && <div className={`cl-segment-bar${hasNegative ? ' has-negative' : ''}`} aria-hidden="true">{hasNegative && <i />}<span style={{ width: `${finite(item.revenue) && maxRevenue ? Math.abs(item.revenue) / maxRevenue * (hasNegative ? 50 : 100) : 0}%`, left: hasNegative ? `${finite(item.revenue) && item.revenue < 0 && maxRevenue ? 50 - Math.abs(item.revenue) / maxRevenue * 50 : 50}%` : undefined }} className={finite(item.revenue) && item.revenue < 0 ? 'is-negative' : ''} /></div>}
      <div className="cl-segment-value"><strong>{money(item.revenue)}</strong><span>{finite(item.share) ? `占比 ${item.share.toFixed(1)}%` : '占比待核'}</span></div>
    </div>)}</div>
    {display.items.length > 8 && <button type="button" className="cr-text-button" aria-expanded={expanded} onClick={()=>setExpanded(v=>!v)}>{expanded ? "收起披露项目" : `查看全部 ${display.items.length} 个披露项目`}</button>}
    {!hierarchyUnclear && <p className="cl-small-note">{display.removedAggregate && '合计已与子项核对，图中仅展示子项；原始合计保留在明细。'}条形比较本维度已披露项目的收入规模。{hasNegative && '中线为零，暖褐色负值向左延伸。'}{totalShare > 100.5 ? '当前项目可能包含重叠或汇总项，占比不能相加。' : '占比按该披露维度口径理解，不跨维度相加。'}</p>}
    <details className="cl-data-details"><summary>披露口径与核验说明</summary>{group.notes.map((note, i) => <p className="cl-small-note" key={i}>{note}</p>)}</details>
    <details className="cl-data-details"><summary>查看业务构成原始明细</summary><div className="cl-table-scroll"><table><caption>{reportName(group.period)} · {group.dimension} · 原始金额单位：{currency(group.currency)}元</caption><thead><tr><th>项目</th><th>收入</th><th>成本</th><th>披露利润</th><th>占比</th><th>出处</th></tr></thead><tbody>{group.items.map((item, i) => <tr key={`${item.name}-${i}`}><th scope="row">{item.name}</th><td>{rawNumber(item.revenue)}</td><td>{rawNumber(item.cost)}</td><td>{rawNumber(item.profit)}</td><td>{finite(item.share) ? `${item.share.toFixed(2)}%` : '—'}</td><td><SourceRefs ids={item.sourceIds} sources={sources} /></td></tr>)}</tbody></table></div></details>
  </div>
}

function FinancialChart({ points, metric, quarterly, denomination }: { points: FinancialPoint[]; metric: Metric; quarterly: boolean; denomination: string }) {
  const titleId = useId()
  const viewport = useRef<HTMLDivElement>(null)
  const [availableWidth, setAvailableWidth] = useState(640)
  useEffect(() => {
    const element = viewport.current
    if (!element) return
    const update = () => setAvailableWidth(Math.max(280, Math.floor(element.clientWidth)))
    update()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(update)
    observer.observe(element)
    return () => observer.disconnect()
  }, [metric, points.length])
  const values = points.map(point => finite(point[metric]) ? point[metric]! / 1e8 : null)
  if (!values.some(finite)) return <EmptyNote>这一指标在当前时间范围内没有可用数据，缺失值保留为空。</EmptyNote>
  const min = Math.min(0, ...values.filter(finite)), max = Math.max(0, ...values.filter(finite))
  const extent = max - min || 1
  const lower = min < 0 ? min - extent * .14 : 0, upper = max > 0 ? max + extent * .14 : min === 0 ? 1 : 0
  const width = Math.max(availableWidth, points.length * 47 + 84), height = 282, left = 67, right = 17, top = 26, bottom = 54
  const plotHeight = height - top - bottom, plotWidth = width - left - right
  const y = (value: number) => top + (upper - value) / (upper - lower) * plotHeight
  const zero = y(0), step = plotWidth / points.length, barWidth = Math.min(44, step * .57)
  const ticks = [lower, lower + (upper - lower) / 2, upper]
  return <figure className="cl-chart">
    <div className="cl-chart-scroll" ref={viewport}><svg viewBox={`0 0 ${width} ${height}`} style={{ minWidth: width }} role="img" aria-labelledby={titleId}>
      <title id={titleId}>{METRICS.find(item => item.key === metric)?.label}，{quarterly ? '单季披露' : '年度披露'}，单位为{denomination}亿元；负值在零线下方，缺失值不作零处理。</title>
      {ticks.map((tick, index) => <g key={index}><line x1={left} x2={width - right} y1={y(tick)} y2={y(tick)} className="cl-chart-grid" /><text x={left - 10} y={y(tick) + 4} textAnchor="end" className="cl-chart-axis">{tick.toLocaleString('zh-CN', { maximumFractionDigits: 1 })}</text></g>)}
      <line x1={left} x2={width - right} y1={zero} y2={zero} className="cl-chart-zero" />
      {points.map((point, index) => {
        const value = values[index], x = left + step * (index + .5)
        return <g key={point.period}>
          {value === null ? <text x={x} y={zero - 9} textAnchor="middle" className="cl-chart-missing">—</text> : <>
            <rect x={x - barWidth / 2} y={Math.min(y(value), zero)} width={barWidth} height={Math.max(1, Math.abs(y(value) - zero))} rx="2" className={value < 0 ? 'cl-chart-bar is-negative' : 'cl-chart-bar'}><title>{periodLabel(point.period, quarterly)}：{money(point[metric])} 亿元{metric === 'netProfit' && point.profitReviewPeriods?.length ? '，利润归属待复核' : ''}</title></rect>
            {points.length <= 12 && <text x={x} y={value < 0 ? y(value) + 15 : y(value) - 8} textAnchor="middle" className="cl-chart-value">{value.toLocaleString('zh-CN', { maximumFractionDigits: 1 })}{metric === 'netProfit' && Boolean(point.profitReviewPeriods?.length) && '*'}</text>}
          </>}
          <text x={x} y={height - 25} textAnchor="middle" className="cl-chart-axis">{periodLabel(point.period, quarterly)}</text>
        </g>
      })}
    </svg></div>
    <figcaption>实线为零。暖褐色表示负值；“—”表示资料缺失。{points.length > 12 && '展开全部后可横向滚动查看。'}</figcaption>
  </figure>
}

function FinancialHistory({ company }: { company: CompanyDossier }) {
  const [frequency, setFrequency] = useState<'annual' | 'quarterly'>('annual')
  const [metric, setMetric] = useState<Metric>('revenue')
  const [all, setAll] = useState(false)
  const [compare, setCompare] = useState(company.code === '601138.SH')
  const quarterly = frequency === 'quarterly'
  const ordered = useMemo(() => [...company.finance[frequency]].sort((a, b) => a.period.localeCompare(b.period)), [company, frequency])
  const points = all ? ordered : ordered.slice(quarterly ? -12 : -5)
  const descriptor = METRICS.find(item => item.key === metric)!
  const latest = company.finance.latest
  const stockMeasure = !compare && (metric === 'totalAssets' || metric === 'totalLiabilities')
  const latestCumulative = latest && latest.period.slice(4) !== '1231'
  const metricCoverage = stockMeasure ? company.coverage.balanceSheet : company.coverage.financialHistory
  return <div className="cl-financials">
    {latest && <div className="cl-latest"><div className="cl-latest-heading"><span>最近披露 · {reportName(latest.period)}</span><span>{latestCumulative ? '年内累计' : '全年'} · 公告 {date(latest.annDate)}<SourceRefs ids={latest.sourceIds} sources={company.sources} /></span></div><div className="cl-latest-grid">{([{ key: 'revenue', label: revenueName(latest.revenueField) }, { key: 'netProfit', label: '归母净利润' }, { key: 'operatingCashFlow', label: '经营现金流净额' }] as const).map(item => <div key={item.key}><span>{item.label}{item.key === 'netProfit' && Boolean(latest.profitReviewPeriods?.length) && ' · 待复核'}</span><strong className={finite(latest[item.key]) && latest[item.key]! < 0 ? 'is-negative' : ''}>{money(latest[item.key])}<small>亿元</small></strong></div>)}</div>
      <details className="cl-latest-details"><summary>查看最近一期数据明细</summary><div className="cl-table-scroll"><table><caption>{reportName(latest.period)} · {latestCumulative ? '年内累计，资产与负债为期末数' : '全年，资产与负债为年末数'} · {currency(company.finance.currency)}元</caption><tbody>{([
        ['revenue', revenueName(latest.revenueField)], ['netProfit', '归母净利润'], ['totalNetProfit', '合并净利润（含少数股东）'],
        ['operatingCashFlow', '经营现金流净额'], ['totalAssets', '期末总资产'], ['totalLiabilities', '期末总负债'], ['rdExpense', '研发费用'], ['capex', '资本开支'],
      ] as const).map(([key, label]) => <tr key={key}><th scope="row">{label}</th><td>{rawNumber(latest[key])}</td></tr>)}</tbody></table></div></details>
    </div>}
    <div className="cl-finance-toolbar"><div className="cl-tabs" role="group" aria-label="财报时间口径"><button type="button" aria-pressed={!quarterly} onClick={() => { setFrequency('annual'); setAll(false) }}>年度</button><button type="button" aria-pressed={quarterly} onClick={() => { setFrequency('quarterly'); setAll(false) }}>单季</button></div><span>{all ? `全部 ${ordered.length} 期` : `最近 ${Math.min(quarterly ? 12 : 5, ordered.length)} ${quarterly ? '季' : '年'}`} · {currency(company.finance.currency)}亿元</span></div>
    <div className="cl-metric-tabs" role="group" aria-label="经营指标">{METRICS.map(item => <button key={item.key} type="button" aria-pressed={!compare && metric === item.key} onClick={() => { setMetric(item.key); setCompare(false) }}>{item.label}</button>)}{company.companyType === 'industrial' && <button type="button" aria-pressed={compare} onClick={() => setCompare(true)}>利润与现金</button>}</div>
    <p className="cl-chart-explanation"><strong>{compare ? '利润与现金' : descriptor.label} · {stockMeasure ? '期末数' : quarterly ? '单季数' : '全年数'}</strong>{compare ? '利润按会计规则确认，经营现金流记录现金流入与流出。下图采用同一纵轴对照。' : descriptor.explanation}</p>
    {metricCoverage && metricCoverage.status !== 'available' && <p className="cl-metric-coverage"><Status status={metricCoverage.status} />{stockMeasure ? '资产、负债的披露口径仍需核对；未确认的数据保留为空。' : metricCoverage.note}</p>}
    {(compare || metric === 'netProfit') && points.some(point => point.profitReviewPeriods?.length) && <p className="cl-metric-coverage"><Status status="review" />部分期间的利润归属仍需核对；带“*”的利润数值保留原值，单季值继承参与差分期间的提示。</p>}
    {points.length ? compare ? <CompanyCashChart points={points} denomination={currency(company.finance.currency)} /> : <FinancialChart points={points} metric={metric} quarterly={quarterly} denomination={currency(company.finance.currency)} /> : <EmptyNote>这家公司尚未补齐{quarterly ? '单季' : '年度'}财报历史。</EmptyNote>}
    {ordered.length > (quarterly ? 12 : 5) && <button type="button" className="cl-text-action cl-expand-history" aria-expanded={all} onClick={() => setAll(!all)}>{all ? `收起为最近 ${quarterly ? '12 季' : '5 年'} ↑` : `展开全部 ${ordered.length} 期 ↓`}</button>}
    <p className="cl-small-note">{quarterly ? '单季营收、利润和现金流由同年累计披露差分得到；不能可靠差分的期间留空。资产、负债仍为各季度末的时点数。' : '营收、利润、现金流使用全年口径；资产、负债使用年末时点数。'} 空白不代表零。数字来自结构化财报记录；报告链接尚未逐字段核验。</p>
    {Boolean(company.finance.profitReconciliation?.length) && <details className="cl-data-details"><summary>利润归属核对记录 · {company.finance.profitReconciliation?.length} 期</summary>{company.finance.profitReconciliation?.map(item => <p className="cl-small-note" key={item.period}><strong>{reportName(item.period)} · {item.status === 'available' ? '已解释' : '待复核'}</strong> {item.note}<SourceRefs ids={item.sourceIds} sources={company.sources} /></p>)}</details>}
    {company.finance.notes.map((note, i) => <p className="cl-small-note" key={i}>{baseFinanceReaderNote(company.code, note)}</p>)}
    <details className="cl-data-details"><summary>查看本视图财报数据明细 · {points.length} 期</summary><div className="cl-table-scroll"><table><caption>{quarterly ? '单季口径（期末资产、负债除外）' : '年度口径'} · 原始金额单位：{currency(company.finance.currency)}元</caption><thead><tr><th>报告期</th><th>营收</th><th>营收字段</th><th>归母净利润</th><th>经营现金流</th><th>总资产</th><th>总负债</th><th>研发费用</th><th>资本开支</th><th>公告日期</th><th>出处</th></tr></thead><tbody>{points.map(point => <tr key={point.period}><th scope="row">{quarterly ? periodLabel(point.period, true) : reportName(point.period)}</th><td>{rawNumber(point.revenue)}</td><td className="cl-table-text">{revenueName(point.revenueField)}</td><td>{rawNumber(point.netProfit)}{Boolean(point.profitReviewPeriods?.length) && <span title={`利润归属待复核，涉及累计期：${point.profitReviewPeriods?.join("、")}`}> *待复核</span>}</td><td>{rawNumber(point.operatingCashFlow)}</td><td>{rawNumber(point.totalAssets)}</td><td>{rawNumber(point.totalLiabilities)}</td><td>{rawNumber(point.rdExpense)}</td><td>{rawNumber(point.capex)}</td><td>{date(point.annDate)}</td><td><SourceRefs ids={point.sourceIds} sources={company.sources} /></td></tr>)}</tbody></table></div></details>
  </div>
}


export { SourceRefs, Claims, EmptyNote, LongText, FinancialHistory, BusinessSegments, date, money, currency, safeUrl, sourceLink, sourceStatus, sourceAction, sourceGaps, reportName, jumpTo, Status }
