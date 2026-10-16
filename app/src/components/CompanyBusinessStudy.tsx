import { useId, useState } from 'react'
import type { CompanySource } from '../lib/company'
import type { BusinessStudy, Fact } from '../lib/company-business-study'
import { SourceRefs } from './CompanyDetailParts'
import '../styles/company-business-study.css'

type StudyProps = { study: BusinessStudy; sources: CompanySource[] }
type CashRow = BusinessStudy['cashBridge']['rows'][number]
type Spending = BusinessStudy['spending'][number]

function FactCopy({ fact, sources }: { fact: Fact; sources: CompanySource[] }) {
  return <p>{fact.text}<SourceRefs ids={fact.sourceIds} sources={sources} /></p>
}

const spendingKinds = {
  cost: '营业成本',
  expense: '期间费用',
  investment: '长期资产现金支出',
  inventory: '期末资产存量',
}

function CostComposition({ composition, sources }: {
  composition: NonNullable<NonNullable<Spending['reader']>['composition']>
  sources: CompanySource[]
}) {
  const { basis, segments } = composition
  // Only explicit, complete percentages can become a composition graphic.
  const valid = segments.length > 1
    && segments.every(segment => Number.isFinite(segment.ratio) && segment.ratio >= 0 && segment.ratio <= 100)
    && Math.abs(segments.reduce((sum, segment) => sum + segment.ratio, 0) - 100) < 0.01
  if (!valid) return null

  const percent = (ratio: number) => `${ratio.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}%`
  return <div className="cbs-composition">
    <p className="cbs-composition-basis">{basis}</p>
    <div className="cbs-composition-bar" role="img" aria-label={`${basis}：${segments.map(segment => `${segment.label} ${percent(segment.ratio)}`).join('，')}`}>
      {segments.map((segment, index) => <span key={`${index}-${segment.label}`} style={{ width: `${segment.ratio}%` }} />)}
    </div>
    <ul className="cbs-composition-legend">
      {segments.map((segment, index) => <li key={`${index}-${segment.label}`}>
        <span className="cbs-composition-dot" aria-hidden="true" />
        <span>{segment.label}<SourceRefs ids={segment.sourceIds} sources={sources} /></span>
        <strong>{percent(segment.ratio)}</strong>
      </li>)}
    </ul>
  </div>
}

function SpendingItem({ item, sources }: { item: Spending; sources: CompanySource[] }) {
  const reader = item.reader
  return <article className={`cbs-spending${reader?.kind === 'cost' ? ' cbs-spending-main' : ''}`}>
    {reader && <span className="cbs-category">{spendingKinds[reader.kind]}</span>}
    <header><h4>{item.title}</h4><span className="cbs-meta">{item.period}</span></header>
    <div className="cbs-metric"><strong>{item.metric}</strong><span>{item.metricLabel}</span></div>
    <FactCopy fact={reader?.answer || item} sources={sources} />
    {reader?.composition && <CostComposition composition={reader.composition} sources={sources} />}
    {(reader || item.rows.length > 0 || item.note) && <details className="cbs-details">
      <summary>查看财报说明与明细{item.rows.length > 0 && <span>{item.rows.length} 项</span>}</summary>
      {reader && <FactCopy fact={item} sources={sources} />}
      {item.rows.length > 0 && <dl className="cbs-detail-rows">
        {item.rows.map((row, rowIndex) => <div key={`${rowIndex}-${row.label}`}>
          <dt>{row.label}<SourceRefs ids={row.sourceIds} sources={sources} /></dt>
          <dd>{row.value}</dd>
        </div>)}
      </dl>}
      {item.note && <p className="cbs-note">{item.note}</p>}
    </details>}
  </article>
}

export default function CompanyBusinessStudy({ study, sources }: StudyProps) {
  const [selectedLane, setSelectedLane] = useState('')
  const panelId = useId()
  const currentLane = study.lanes.find(lane => lane.id === selectedLane) || study.lanes[0]
  const hasTradeAnswers = study.trade.steps.some(step => step.reader) || !!study.reader?.tradeIntro

  return <div className="cbs-study">
    <header className={`cbs-intro${study.reader ? ' cbs-intro-compact' : ''}`}>
      {study.reader ? <details className="cbs-details cbs-scope">
        <summary><span className="cbs-meta">资料截至 {study.asOf}</span><span className="cbs-scope-toggle">资料范围</span></summary>
        {study.reader.intro && study.reader.intro !== study.intro && <p>{study.reader.intro}</p>}
        <p>{study.intro}</p>
      </details> : <>
        <p>{study.intro}</p>
        <span className="cbs-meta">资料截至 {study.asOf}</span>
      </>}
    </header>

    {currentLane && <section className="cbs-block" aria-labelledby={`${panelId}-business-title`}>
      <h3 id={`${panelId}-business-title`} className={currentLane.reader ? 'cbs-visually-hidden' : undefined}>把业务分开看</h3>
      <div className="cbs-lane-switch" role="group" aria-label="选择要阅读的业务">
        {study.lanes.map(lane => <button
          type="button"
          key={lane.id}
          aria-pressed={currentLane.id === lane.id}
          aria-controls={panelId}
          onClick={() => setSelectedLane(lane.id)}
        >{lane.title}</button>)}
      </div>
      <div key={currentLane.id} id={panelId} className="cbs-lane-panel" aria-labelledby={`${panelId}-lane-title`}>
        <header className="cbs-lane-heading">
          <h4 id={`${panelId}-lane-title`}>{currentLane.reader ? currentLane.reader.headline || currentLane.headline : currentLane.title}</h4>
          <span className="cbs-meta">{currentLane.period}</span>
        </header>
        {!currentLane.reader && <p className="cbs-headline">{currentLane.headline}</p>}
        {currentLane.reader ? <>
          <dl className="cbs-quick-answers">
            {([
              ['谁来买', currentLane.reader.customer],
              ['交付什么', currentLane.reader.delivery],
              ['公司做什么', currentLane.reader.work],
            ] as const).map(([label, fact], index) => <div key={label}>
              <dt><span aria-hidden="true">0{index + 1}</span>{label}</dt>
              <dd>{fact.text}<SourceRefs ids={fact.sourceIds} sources={sources} /></dd>
            </div>)}
          </dl>
          <details className="cbs-details cbs-lane-evidence">
            <summary>查看业务事实与判断边界</summary>
            {currentLane.reader.headline && currentLane.reader.headline !== currentLane.headline && <p>{currentLane.headline}</p>}
            <dl className="cbs-fact-grid">
              {currentLane.facts.map((fact, index) => <div key={`${currentLane.id}-${index}`}>
                <dt>{fact.label}</dt>
                <dd>{fact.text}<SourceRefs ids={fact.sourceIds} sources={sources} /></dd>
              </div>)}
            </dl>
          </details>
        </> : <dl className="cbs-fact-grid">
          {currentLane.facts.map((fact, index) => <div key={`${currentLane.id}-${index}`}>
            <dt>{fact.label}</dt>
            <dd>{fact.text}<SourceRefs ids={fact.sourceIds} sources={sources} /></dd>
          </div>)}
        </dl>}
      </div>
    </section>}

    <section className="cbs-block cbs-products" aria-labelledby={`${panelId}-products-title`}>
      <h3 id={`${panelId}-products-title`}>产品清单与生产材料</h3>
      <details className="cbs-details cbs-catalogue">
        <summary>展开产品与材料清单<span>{study.catalogue.items.length} 类产品</span></summary>
        <ol>{study.catalogue.items.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ol>
        <p>{study.catalogue.note}<SourceRefs ids={study.catalogue.sourceIds} sources={sources} /></p>
        <div className="cbs-materials">
          <h4>公司整体使用哪些材料</h4>
          <FactCopy fact={study.materials} sources={sources} />
        </div>
      </details>
    </section>

    <section className="cbs-block" aria-labelledby={`${panelId}-trade-title`}>
      <h3 id={`${panelId}-trade-title`}>交付、收入与收款，分别看</h3>
      <p className="cbs-section-intro">{study.reader?.tradeIntro || study.trade.intro}</p>
      <ol className="cbs-trade">
        {study.trade.steps.map((step, index) => <li key={`${index}-${step.title}`}>
          <span className="cbs-step-number" aria-hidden="true">{String(index + 1).padStart(2, '0')}</span>
          <h4>{step.title}</h4>
          <FactCopy fact={step.reader || step} sources={sources} />
        </li>)}
      </ol>
      {(hasTradeAnswers || study.trade.gap) && <details className="cbs-details cbs-trade-evidence">
        <summary>查看合同、收入确认与收款说明</summary>
        {study.reader?.tradeIntro && <p>{study.trade.intro}</p>}
        {study.trade.steps.filter(step => step.reader).map((step, index) => <div className="cbs-evidence-section" key={`${index}-${step.title}`}>
          <h4>{step.title}</h4><FactCopy fact={step} sources={sources} />
        </div>)}
        {study.trade.gap && <p className="cbs-boundary"><strong>还需了解的细节</strong>{study.trade.gap}</p>}
      </details>}
    </section>

    <section className="cbs-block" aria-labelledby={`${panelId}-spending-title`}>
      <h3 id={`${panelId}-spending-title`}>钱投在哪里</h3>
      {study.reader?.spendingNote && <p className="cbs-section-intro cbs-spending-intro">{study.reader.spendingNote}</p>}
      <div className={`cbs-spending-grid${study.spending.some(item => item.reader?.kind === 'cost') ? ' cbs-spending-classified' : ''}`}>
        {study.spending.map((item, index) => <SpendingItem key={`${index}-${item.title}`} item={item} sources={sources} />)}
      </div>
    </section>

    <section className="cbs-block" aria-labelledby={`${panelId}-conditions-title`}>
      <h3 id={`${panelId}-conditions-title`}>行业要求，公司做到哪一步</h3>
      {(study.reader?.position || study.reader?.positionStatus) && <div className="cbs-position">
        {study.reader.position && <><h4>产业链中的位置</h4><FactCopy fact={study.reader.position} sources={sources} /></>}
        {study.reader.positionStatus && <span className="cbs-status">{study.reader.positionStatus}</span>}
      </div>}
      <div className="cbs-conditions">
        {study.conditions.map((condition, index) => <article key={`${index}-${condition.title}`}>
          <h4>{condition.title}</h4>
          {condition.reader && <>
            <FactCopy fact={condition.reader.answer} sources={sources} />
            {condition.reader.status && <span className="cbs-status">{condition.reader.status}</span>}
          </>}
          {condition.reader ? <details className="cbs-details cbs-condition-evidence">
            <summary>查看行业要求、公司披露与判断边界</summary>
            <div className="cbs-condition-grid">
              <div><h5 className="cbs-condition-label">行业要求</h5><FactCopy fact={condition.need} sources={sources} /></div>
              <div><h5 className="cbs-condition-label">公司披露</h5><FactCopy fact={condition.company} sources={sources} /></div>
              <div><h5 className="cbs-condition-label">判断边界</h5><p>{condition.boundary}</p></div>
            </div>
          </details> : <div className="cbs-condition-grid">
            <div><h5 className="cbs-condition-label">行业要求</h5><FactCopy fact={condition.need} sources={sources} /></div>
            <div><h5 className="cbs-condition-label">公司披露</h5><FactCopy fact={condition.company} sources={sources} /></div>
            <div><h5 className="cbs-condition-label">判断边界</h5><p>{condition.boundary}</p></div>
          </div>}
        </article>)}
      </div>
    </section>
  </div>
}

const billionYuan = (amount: number) => Math.abs(amount / 1e8).toLocaleString('zh-CN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})
const amountSign = (amount: number) => amount < 0 ? '−' : amount > 0 ? '+' : ''

function BridgeRow({ row, sources, first = false, result = false }: {
  row: CashRow
  sources: CompanySource[]
  first?: boolean
  result?: boolean
}) {
  return <div className={`cbs-bridge-row${result ? ' cbs-bridge-result' : ''}`}>
    <dt>
      <span>{row.label}<SourceRefs ids={row.sourceIds} sources={sources} /></span>
      {first && <small>合并净利润，含少数股东损益</small>}
    </dt>
    <dd title={`${row.amount.toLocaleString('zh-CN')} 元`}>
      <span className="cbs-bridge-symbol">{first || result ? row.amount < 0 ? '−' : '' : amountSign(row.amount)}</span>
      <strong>{billionYuan(row.amount)}</strong>
    </dd>
  </div>
}

export function CompanyCashExplanation({ study, sources }: StudyProps) {
  const headingId = useId()
  const bridge = study.cashBridge
  const netProfit = bridge.rows[0]

  return <section className="cbs-cash" aria-labelledby={headingId}>
    <header className="cbs-cash-heading"><h3 id={headingId}>利润与经营现金对照</h3><span className="cbs-meta">{bridge.period} · 人民币亿元</span></header>
    {bridge.reader ? <FactCopy fact={bridge.reader.answer} sources={sources} /> : <p className="cbs-section-intro">{bridge.intro}</p>}
    <dl className="cbs-cash-comparison">
      {netProfit && <div>
        <dt>{netProfit.label}<SourceRefs ids={netProfit.sourceIds} sources={sources} /></dt>
        <dd title={`${netProfit.amount.toLocaleString('zh-CN')} 元`}>{netProfit.amount < 0 ? '−' : ''}{billionYuan(netProfit.amount)}<span>亿元</span></dd>
        <small>合并口径，含少数股东损益</small>
      </div>}
      <div>
        <dt>{bridge.result.label}<SourceRefs ids={bridge.result.sourceIds} sources={sources} /></dt>
        <dd title={`${bridge.result.amount.toLocaleString('zh-CN')} 元`}>{bridge.result.amount < 0 ? '−' : ''}{billionYuan(bridge.result.amount)}<span>亿元</span></dd>
        <small>经营活动现金流量净额</small>
      </div>
    </dl>
    <details className="cbs-details cbs-cash-evidence">
      <summary>展开利润到经营现金的完整调节表</summary>
      {bridge.reader && <p className="cbs-section-intro">{bridge.intro}</p>}
      <p className="cbs-note">从合并净利润出发；“＋”增加经营现金流，“−”减少经营现金流。</p>
      <div className="cbs-bridge">
        <dl>
          {bridge.rows.map((row, index) => <BridgeRow key={`${index}-${row.label}`} row={row} first={index === 0} sources={sources} />)}
          <BridgeRow row={bridge.result} sources={sources} result />
        </dl>
      </div>
      <p className="cbs-note">金额按亿元四舍五入，合计以原始元值为准。</p>
      <div className="cbs-cash-reading">
        <div><h4>公司如何解释</h4><FactCopy fact={bridge.companyExplanation} sources={sources} /></div>
        <div><h4>怎样理解这组数字</h4><p>{bridge.reading}</p></div>
      </div>
      {bridge.boundary && <p className="cbs-boundary"><strong>判断边界</strong>{bridge.boundary}</p>}
    </details>
  </section>
}
