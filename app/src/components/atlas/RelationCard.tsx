import { getStockEvidence } from '../../lib/evidence.js'
import { boardCodeInfo } from '../../lib/board-codes.js'
import { presentRelationSource } from '../../lib/source-presentation.js'
import { fmtDate, type Relation } from './types'

/* 「这条线为什么存在」：三种连线各有一套依据版式 —— 业务联系（有向、有文件）、
   共同产业主题（从成员名单推导）、共同成分/概念（计数与重合比例）。 */
export default function RelationCard({ relation, onClear, onStock, onCompany, onTheme }: { relation: Relation; onClear: () => void; onStock: (i: number) => void; onCompany: (code: string) => void; onTheme: (code: string) => void }) {
  const isStock = relation.kind === 'stock'
  const isBusiness = relation.relationType === 'business'
  const isTheme = relation.relationType === 'theme'
  const themeCard = (theme: NonNullable<Relation['sharedThemes']>[number]) => <details className="theme-evidence" key={theme.code}>
    <summary><strong>{theme.name}</strong><span>{relation.a.name} {theme.a.count} 家 · {relation.b.name} {theme.b.count} 家</span></summary>
    <button type="button" className="theme-open" onClick={() => onTheme(theme.code)}>查看这个概念板块 · {boardCodeInfo(theme.code, 'concept').indexCode} ↗</button>
    {[{node: relation.a, side: theme.a}, {node: relation.b, side: theme.b}].map(({node, side}) => <div className="theme-company-side" key={node.code}>
      <h4>{node.name}<small>与该主题交集 {side.count} 家 · 本行业占比 {(side.coverage * 100).toFixed(1)}%</small></h4>
      <div className="theme-companies">{side.codes.map(code => <button type="button" key={code} onClick={() => onCompany(code)}>{getStockEvidence(code)?.name || code}<small>{code.slice(0, 6)}</small></button>)}</div>
    </div>)}
  </details>
  if (isBusiness || isTheme) return <section className={'relation-card industry-relation ' + (isBusiness ? 'business-relation' : 'theme-relation')} id="relation-card" aria-label="连线关系详情">
    <div className="section-heading"><span className="eyebrow">{isBusiness ? '业务联系 · 有公开文件依据' : '共同产业主题 · 依据成员名单'}</span><button className="text-button" onClick={onClear} aria-label="收起关系详情">收起 ×</button></div>
    <div className="pair-heading"><button onClick={() => onStock(relation.a.i)}>{relation.a.name}</button><span>{isBusiness ? '→' : '↔'}</span><button onClick={() => onStock(relation.b.i)}>{relation.b.name}</button></div>
    <p className="industry-statement">{relation.statement}</p>
    <div className="relation-boundary">{isTheme ? '共同主题不代表供货关系，也不代表行业内所有公司都涉及。' : relation.boundary}</div>
    {relation.sharedThemes?.slice(0, 3).map(themeCard)}
    {(relation.sharedThemes?.length || 0) > 3 && <details className="relation-method more-themes"><summary>更多共同主题 · {(relation.sharedThemes?.length || 0) - 3}</summary>{relation.sharedThemes?.slice(3).map(themeCard)}</details>}
    <details className="relation-method"><summary>来源与连线口径</summary><p>{relation.reason}</p>{isTheme && <p>{relation.boundary}</p>}{relation.mappingBasis && <p>{relation.mappingBasis}</p>}
      <div className="relation-sources">{relation.sourceRefs?.map(presentRelationSource).map((source, i) => <p className="data-source" key={`${source.url}-${i}`}>{source.url ? <a href={source.url} target="_blank" rel="noreferrer">{source.title} ↗</a> : source.title}{source.locator && <><br />{source.url ? '定位：' : ''}{source.locator}</>}</p>)}</div>
    </details>
    <p className="data-source">{isTheme ? '成员资料日期' : '关系资料整理日期'}：{fmtDate(relation.asOf)}</p>
  </section>
  return <section className="relation-card" id="relation-card" aria-label="连线关系详情">
    <div className="section-heading"><span className="eyebrow">这条线为什么存在</span><button className="text-button" onClick={onClear} aria-label="收起关系详情">收起 ×</button></div>
    <div className="pair-heading">
      <button onClick={() => onStock(relation.a.i)}>{relation.a.name}</button><span>↔</span><button onClick={() => onStock(relation.b.i)}>{relation.b.name}</button>
    </div>
    <div className="relationship-fact">共同{isStock ? '所属' : '包含'} <strong>{relation.sharedCount}</strong> 个{isStock ? '概念' : '股票成员'}</div>
    <p className="relation-reason">{relation.reason}</p>
    {relation.sameIndustry && <p className="evidence-line">基础资料行业相同：<strong>{relation.sameIndustry}</strong></p>}
    <details className="shared-evidence" open>
      <summary>{isStock ? '共同概念清单' : '共同股票清单'} · {relation.sharedCount}</summary>
      <div className="evidence-tags">{isStock
        ? relation.sharedConcepts.map(name => <span key={name}>{name}</span>)
        : relation.sharedStocks.map(stock => <span key={stock.code}>{stock.name}<small>{stock.code.slice(0, 6)}</small></span>)}</div>
    </details>
    <p className="evidence-line">{isStock ? '概念' : '成员'}重合比例 <strong>{relation.overlapPct.toFixed(1)}%</strong><br />共同数量 ÷ 两者合并去重后的数量（{relation.unionCount}）</p>
    <div className="relation-boundary">这条线证明的是{isStock ? '概念共属' : '成员重合'}。供应链、客户、股权与资金流关系需要另外的证据。</div>
    <p className="data-source">同花顺板块成员 · 成员查询 {fmtDate(relation.asOf)}</p>
  </section>
}
