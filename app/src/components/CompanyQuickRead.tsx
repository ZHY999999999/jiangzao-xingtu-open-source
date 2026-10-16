import { IconArrowDown } from '@tabler/icons-react'
import type { CompanyDossier, FinancialPoint } from '../lib/company'
import type { CompanyEditorial } from '../lib/company-editorial'
import { audioKind, audioLabel } from '../lib/audio-label'
import { orderSegments, segmentDisplay, segmentNeedsReview, segmentDimensionLabel } from '../lib/company-reading'
import { SourceRefs, jumpTo, money, reportName } from './CompanyDetailParts'
import type { CompanySource } from '../lib/company'
import '../styles/company-quickread.css'

/**
 * The fixed seven questions every dossier answers first. Answers are drawn only from
 * reviewed editorial fields or structured records; an unanswered question stays visibly
 * open instead of being filled with generic industry prose.
 */
type Kind = 'editorial' | 'statement' | 'computed' | 'board' | 'gap'
type Row = { q: string; a?: string; ids: string[]; target: string; kind: Kind; note?: string }
const KIND_LABEL: Record<Kind, string> = { editorial: '经营解读', statement: '公司自述', computed: '财报计算', board: '板块归属', gap: '待整理' }
const finite = (v: number | null | undefined): v is number => typeof v === 'number' && Number.isFinite(v)
const pct = (share: number) => `${(share * 100).toLocaleString('zh-CN', { maximumFractionDigits: 1 })}%`
const clip = (text: string, n = 90) => text.length > n ? `${text.slice(0, n).replace(/[，、；,;\s]+$/, '')}…` : text
const uniq = (ids: string[]) => [...new Set(ids)]

function editorialRows(e: CompanyEditorial): Row[] {
  const mix = e.revenueMix
  const major = mix.items.filter(i => i.share >= 0.05)
  const spend = e.businessStudy?.spending[0]
  const position = e.businessStudy?.reader?.position
  const summary = e.readingSummary
  return [
    { q: '它提供什么', a: e.products.map(p => p.name).join('、'), ids: e.products.flatMap(p => p.sourceIds), target: 'company-business', kind: 'editorial' },
    { q: '收入主要来自哪', a: major.length ? `${major.map(i => `${i.readerLabel || i.name} ${pct(i.share)}`).join('，')}` : undefined, ids: mix.items.flatMap(i => i.sourceIds), target: 'company-overview', kind: 'editorial', note: `${mix.period.slice(0, 4)} 年度 · 占全部营业收入` },
    { q: '谁在付钱', a: e.customers.map(c => c.name).join('、'), ids: e.customers.flatMap(c => c.sourceIds), target: 'company-business', kind: 'editorial' },
    { q: '一笔生意怎样做成', a: e.process.map(p => p.title).join(' → '), ids: e.process.flatMap(p => p.sourceIds), target: 'company-business', kind: 'editorial' },
    spend
      ? { q: '钱主要花在哪里', a: `${spend.title}：${spend.metric}`, ids: spend.sourceIds, target: 'company-business', kind: 'editorial', note: `${spend.metricLabel} · ${spend.period}` }
      : { q: '钱主要花在哪里', a: e.costs[0] ? `${e.costs[0].title}${e.costs[0].metric ? `：${e.costs[0].metric}` : ''}` : undefined, ids: e.costs[0]?.sourceIds || [], target: 'company-business', kind: 'editorial' },
    { q: '在产业链里做哪一环', a: position?.text, ids: position?.sourceIds || [], target: 'company-business', kind: position ? 'editorial' : 'gap' },
    { q: '赚不赚钱，在怎样变化', a: summary?.headline, ids: uniq(summary?.sourceIds?.length ? summary.sourceIds : (summary?.metrics || []).flatMap(m => (m as { sourceIds?: string[] }).sourceIds || [])), target: 'company-finance', kind: summary ? 'editorial' : 'gap', note: summary?.period ? (/^\d{8}$/.test(summary.period) ? `资料至 ${reportName(summary.period)}` : summary.period) : undefined },
  ]
}

function latestAnnualPair(points: FinancialPoint[]) {
  const sorted = [...points].filter(p => p.period.endsWith('1231')).sort((a, b) => a.period.localeCompare(b.period))
  const latest = [...sorted].reverse().find(p => finite(p.revenue))
  if (!latest) return { latest: undefined, previous: undefined }
  const previous = sorted.find(p => p.period === `${Number(latest.period.slice(0, 4)) - 1}1231`)
  return { latest, previous }
}

function basicRows(c: CompanyDossier, industryLabel: string): Row[] {
  const rows: Row[] = []
  const offer = c.summary.products || c.profile.mainBusiness
  rows.push(offer
    ? { q: '它提供什么', a: clip(offer), ids: c.summary.sourceIds, target: 'company-business', kind: 'statement' }
    : { q: '它提供什么', ids: [], target: 'company-business', kind: 'gap' })

  // Largest disclosed item in the most recent readable segment group; unresolved hierarchies are skipped.
  const group = orderSegments(c.segments).find(g => segmentDimensionLabel(g.dimension) !== '分类待核' && !segmentNeedsReview(g))
  const top = group ? [...segmentDisplay(group).items].filter(i => finite(i.revenue) && finite(i.share)).sort((a, b) => b.revenue! - a.revenue!)[0] : undefined
  rows.push(top && group
    ? { q: '收入主要来自哪', a: `最大一项是「${top.name}」，占 ${top.share!.toFixed(1)}%`, ids: top.sourceIds, target: 'company-business', kind: 'computed', note: `${reportName(group.period)} · 按${segmentDimensionLabel(group.dimension)}披露` }
    : c.summary.revenue ? { q: '收入主要来自哪', a: clip(c.summary.revenue), ids: c.summary.sourceIds, target: 'company-business', kind: 'statement' }
      : { q: '收入主要来自哪', ids: [], target: 'company-business', kind: 'gap' })

  rows.push(c.summary.customers
    ? { q: '谁在付钱', a: clip(c.summary.customers), ids: c.summary.sourceIds, target: 'company-business', kind: 'statement' }
    : { q: '谁在付钱', ids: [], target: 'company-business', kind: 'gap' })
  rows.push({ q: '一笔生意怎样做成', ids: [], target: 'company-business', kind: 'gap' })

  const { latest, previous } = latestAnnualPair(c.finance.annual)
  const spendParts = latest ? [finite(latest.rdExpense) && `研发费用 ${money(latest.rdExpense)} 亿元`, finite(latest.capex) && `资本开支 ${money(latest.capex)} 亿元`].filter(Boolean) : []
  rows.push(latest && spendParts.length
    ? { q: '钱主要花在哪里', a: spendParts.join('，'), ids: latest.sourceIds, target: 'company-finance', kind: 'computed', note: `${latest.period.slice(0, 4)} 年度 · ${c.code === '601138.SH' ? '仅两项结构化字段，成本构成待整理' : '所列项目不代表全部成本与支出'}` }
    : { q: '钱主要花在哪里', ids: [], target: 'company-finance', kind: 'gap' })

  rows.push(industryLabel && !/待补|读取中|不可用/.test(industryLabel)
    ? { q: '在产业链里做哪一环', a: `所属行业板块：${industryLabel}`, ids: [], target: 'company-overview', kind: 'board', note: '板块归属不等于产业链位置判断' }
    : { q: '在产业链里做哪一环', ids: [], target: 'company-overview', kind: 'gap' })

  if (latest) {
    const growth = previous && finite(previous.revenue) && previous.revenue !== 0 ? (latest.revenue! - previous.revenue) / Math.abs(previous.revenue) : undefined
    const profit = finite(latest.netProfit) ? `，归母净利润 ${money(latest.netProfit)} 亿元${latest.netProfit < 0 ? '（亏损）' : ''}` : ''
    rows.push({ q: '赚不赚钱，在怎样变化', a: `营收 ${money(latest.revenue)} 亿元${growth === undefined ? '' : `（比上年${growth >= 0 ? '增长' : '下降'} ${Math.abs(growth * 100).toFixed(1)}%）`}${profit}`, ids: latest.sourceIds, target: 'company-finance', kind: 'computed', note: `${latest.period.slice(0, 4)} 年度 · ${c.code === '601138.SH' ? '按结构化财报计算' : '根据财报数据计算'}` })
  } else rows.push({ q: '赚不赚钱，在怎样变化', ids: [], target: 'company-finance', kind: 'gap' })
  return rows
}

export default function CompanyQuickRead({ company, editorial, industryLabel, sources }: { company: CompanyDossier; editorial: CompanyEditorial | null; industryLabel: string; sources: CompanySource[] }) {
  const rows = (editorial ? editorialRows(editorial) : basicRows(company, industryLabel)).map(r => r.a ? r : { ...r, kind: 'gap' as Kind, a: undefined }).filter(row => editorial || row.a)
  const answered = rows.filter(r => r.a).length
  const kind = audioKind(editorial?.audio)
  const layers = [
    { label: '基础档案', on: true, detail: `${company.finance.annual.length} 年财报` },
    ...(editorial ? [{ label: '经营解读', on: true, detail: editorial.reportBasis }] : []),
    { label: '语音讲解', on: kind !== 'none', detail: audioLabel(kind, editorial?.audio?.durationSeconds, 'long') || '暂无' },
    { label: '资料出处', on: sources.length > 0, detail: `${sources.length} 条` },
  ]
  return <section className="cq-quickread" aria-labelledby="cq-title">
    <header>
      <div><span className="cr-eyebrow">{editorial ? '经营解读' : '业务与财报'}</span><h2 id="cq-title" tabIndex={-1}>{editorial ? '读懂这门生意的七个答案' : '从公开资料看这家公司'}</h2></div>
      {editorial && <p className="cq-progress" aria-label={`七个问题可阅读 ${answered} 个`}><strong>{answered}</strong><span>/ 7 个答案</span></p>}
    </header>
    <ol className="cq-list">{rows.map((row, i) => <li key={row.q} className={row.a ? '' : 'is-gap'}>
      <span className="cq-num" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span>
      <h3>{row.q}</h3>
      <div className="cq-answer">
        {row.a ? <p>{row.a}{row.ids.length > 0 && <SourceRefs ids={uniq(row.ids)} sources={sources} />}</p> : <p className="cq-missing">本站尚未整理这部分说明，可查看相关报告。</p>}
        {row.note && row.a && <small>{row.note}</small>}
      </div>
      <span className={`cq-kind cq-kind-${row.kind}`}>{KIND_LABEL[row.kind]}</span>
      <a href={`#${row.target}`} onClick={event => jumpTo(event, row.target)} aria-label={`展开「${row.q}」的详细内容`}><IconArrowDown size={15} /></a>
    </li>)}</ol>
    <footer className="cq-layers" aria-label="这份档案的阅读深度">
      {layers.map(layer => <span key={layer.label} className={layer.on ? 'is-on' : ''}><i aria-hidden="true" />{layer.label}<small>{layer.detail}</small></span>)}
    </footer>
  </section>
}
