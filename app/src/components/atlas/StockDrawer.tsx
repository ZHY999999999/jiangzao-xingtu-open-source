import type { ReactNode } from 'react'
import { EVIDENCE, MARKET_CAP } from '../../lib/evidence.js'
import { boardCodeInfo } from '../../lib/board-codes.js'
import CompanyPeek from '../CompanyPeek'
import DataNotes from './DataNotes'
import { fmtDate, fmtMv, hasNumber, listingLabel, pctColor, pctText, reportLabel, revenueLabel, type BoardKind, type Drawer } from './types'

type Props = {
  drawer: Drawer
  dateText: string
  concept: string
  relationSection: ReactNode
  relationsSection: ReactNode
  onClose: () => void
  onOpenCompany: (code: string) => void
  onBack: (board: string, kind: BoardKind) => void
  onCenter: () => void
  onStartPath: () => void
}

/* 个股抽屉：行情四宫格 + 打开公司档案 + 数据说明，正文是公司速览、归属、关系与主营规模。 */
export default function StockDrawer({ drawer, dateText, concept, relationSection, relationsSection, onClose, onOpenCompany, onBack, onCenter, onStartPath }: Props) {
  return <>
    <div className="dr-head">
      <button className="drawer-close" aria-label="关闭详情" onClick={onClose}>×</button>
      <div className="kind"><i style={{ background: drawer.color }}></i>{drawer.meta.code} · {(drawer.meta.thsIndustries || []).find(item => item.level === 'industry')?.name || '同花顺行业待补'}</div>
      <h2>{drawer.name}</h2>
      <div className="dr-stats">
        <div><b>{fmtMv(drawer.meta.amount)}</b><span>成交额</span></div>
        <div><b style={{ color: pctColor(drawer.meta.pct) }}>{pctText(drawer.meta.pct)}</b><span>涨跌幅</span></div>
        <div><b>{fmtMv(drawer.meta.mv)}</b><span>总市值</span></div>
        <div><b>{hasNumber(drawer.meta.to) ? drawer.meta.to.toFixed(2) + '%' : '—'}</b><span>换手率</span></div>
      </div>
      <button className="drillbtn" type="button" onClick={() => onOpenCompany(drawer.meta.code)}>
        打开公司档案
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M6 3l5 5-5 5" /></svg>
      </button>
      <DataNotes summary={`行情 ${dateText} · 市值 ${MARKET_CAP.tradeDate} · ${drawer.relations?.length || 0} 条直接连线`}
        warnings={[listingLabel(drawer.meta.listStatus) && `${listingLabel(drawer.meta.listStatus)}。该公司仍出现在板块成员接口中，保留来源记录，这一记录不代表它目前正常上市。`, !hasNumber(drawer.meta.pct) && '当日行情缺失，横线表示未知。']}>
        <p className="data-source">市值 {MARKET_CAP.tradeDate} · 行情 {dateText} · {drawer.relations?.length || 0} 条直接连线均可展开依据。</p>
        <p className="data-source">行业与概念归属来自同花顺板块成员 · 成分查询 {fmtDate(EVIDENCE.membershipAsOf)}。此处可查的概念共 {Object.keys(EVIDENCE.boards).length} 个，基于完整成分清单，不受图中显示数量影响。</p>
        <p className="data-source">主营与行业信息对应资料查询日期；财报只包含截至行情日已披露的报告，出处见公司档案「资料出处」。板块归属不证明业务占比、市场份额或行业排名；连线表示共同概念，不构成供应链、客户、股权或资金流关系。</p>
      </DataNotes>
    </div>
    <div className="dr-body">
      {relationSection}
      <CompanyPeek code={drawer.meta.code} onOpen={onOpenCompany} showAction={false} />
      <section className="dr-sec"><h3>所属行业板块</h3><div className="chips">{(drawer.meta.thsIndustries || []).filter(item => item.level === 'industry').map(item => <button className="chip" type="button" key={item.code} onClick={() => onBack(item.code, 'industry')}>{item.name}<small> · {boardCodeInfo(item.code).indexCode}</small></button>)}</div>
        {!drawer.meta.thsIndustries?.some(item => item.level === 'industry') && <p className="section-note">本次查询暂无行业板块成员记录。</p>}
      </section>
      {relationsSection}
      <section className="dr-sec business-section">
        <h3>主营与经营规模 <span className="status-tag">公司整体口径</span></h3>
        <div className="business-copy"><strong>主营业务</strong><p>{drawer.meta.mainBusiness || '暂缺公司主营披露，不能据概念标签推断业务占比。'}</p></div>
        {drawer.meta.businessScope && <details className="business-scope"><summary>查看经营范围</summary><p>{drawer.meta.businessScope}</p></details>}
        <div className="financial-grid"><div><small>{revenueLabel(drawer.meta.revenueField)}</small><strong>{fmtMv(drawer.meta.revenue)}</strong></div><div><small>归母净利润</small><strong>{fmtMv(drawer.meta.profit)}</strong></div></div>
        <p className="evidence-line">{reportLabel(drawer.meta.reportPeriod)} · 披露 {fmtDate(drawer.meta.reportAnnDate)}</p>
        {hasNumber(drawer.meta.revenueRank) && <div className="peer-rank"><span>基础资料行业：{drawer.meta.industry} · 营收排序</span><strong>{drawer.meta.revenueRank}<small> / {drawer.meta.industryPeerCount} 家</small></strong></div>}
        <details className="section-method"><summary>口径与边界</summary><p>营收排序限同一基础资料行业、相同报告期的可用 A 股样本，与同花顺板块成员口径分开。所属板块“{concept}”不直接证明公司的业务占比、产品市场份额或行业排名；公司整体营收与细分业务收入需分别核对。</p></details>
      </section>
      {drawer.meta.concepts?.length > 0 && <div className="dr-sec">
        <h3>所属概念 <b>本站可查共 {drawer.meta.concepts.length} 个</b></h3>
        <div className="chips">
          {drawer.meta.concepts.map(cn => <button className="chip" type="button" key={cn} onClick={() => onBack(cn, 'concept')}>{cn}</button>)}
        </div>
      </div>}
    </div>
    <div className="dr-act">
      <button className="btn" type="button" onClick={onCenter}>以此为中心</button>
      <button className="btn primary" type="button" onClick={onStartPath}>从这里找路径</button>
    </div>
  </>
}
