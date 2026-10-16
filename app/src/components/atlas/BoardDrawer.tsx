import type { ReactNode } from 'react'
import { MARKET_CAP } from '../../lib/evidence.js'
import { boardCodeInfo } from '../../lib/board-codes.js'
import DataNotes from './DataNotes'
import { boardLabels, fmtDate, fmtMv, hasNumber, pctColor, pctText, reportLabel, revenueLabel, type BoardKind, type Drawer } from './types'

type Props = {
  drawer: Drawer
  board: any                         // getBoardEvidence 的结果：成员、目录数量、成员警告
  selectedKind: BoardKind
  boardKind: BoardKind
  dateText: string
  industries: [string, number][]
  industryFilter: string
  onIndustryFilter: (value: string) => void
  candidates: any[]
  candidateLimit: number
  onShowAllCandidates: () => void
  relationSection: ReactNode
  relationsSection: ReactNode
  onClose: () => void
  onShowMembers: () => void
  onDrillStock: (code: string) => void
  onCenter: () => void
  onCopyLink: () => void
}

/* 板块抽屉：头部是行情四宫格 + 主行动 + 数据说明，正文是关系与产业龙头候选。 */
export default function BoardDrawer({ drawer, board, selectedKind, boardKind, dateText, industries, industryFilter, onIndustryFilter, candidates, candidateLimit, onShowAllCandidates, relationSection, relationsSection, onClose, onShowMembers, onDrillStock, onCenter, onCopyLink }: Props) {
  return <>
    <div className="dr-head">
      <button className="drawer-close" aria-label="关闭详情" onClick={onClose}>×</button>
      <div className="kind"><i style={{ background: drawer.color }}></i>同花顺{boardLabels[selectedKind]} · {drawer.deg} 条关系</div>
      <h2>{drawer.name}</h2>
      <div className="dr-stats">
        <div><b>{fmtMv(drawer.meta.amount)}</b><span>成分成交额</span></div>
        <div><b style={{ color: pctColor(drawer.meta.pct) }}>{pctText(drawer.meta.pct)}</b><span>指数涨跌</span></div>
        <div><b>{fmtMv(drawer.meta.mv)}</b><span>成分总市值</span></div>
        <div><b>{drawer.meta.count}<small>只</small></b><span>成分股</span></div>
      </div>
      <button className="drillbtn" type="button" onClick={onShowMembers}>
        展开个股星图
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M6 3l5 5-5 5" /></svg>
      </button>
      <p className="drill-note">共 {drawer.meta.count} 家成员 · 星图展示部分公司，展开后可在目录里搜索完整名单</p>
      <DataNotes summary={`行情 ${dateText} · 市值覆盖 ${drawer.meta.mvCount ?? '—'} / ${drawer.meta.count} 家`}
        warnings={[hasNumber(board?.catalogCount) && board.catalogCount !== drawer.meta.count && `两份来源的公司数量不同：目录统计 ${board.catalogCount} 家，成员接口返回 ${drawer.meta.count} 家。此处展示成员名单返回的公司。`, board?.membershipWarning]}>
        <p className="data-source">同花顺 · {boardCodeInfo(drawer.meta.code, selectedKind).indexCode} · 行情 {dateText}<br />成员查询 {fmtDate(board?.membershipAsOf)}{boardCodeInfo(drawer.meta.code, selectedKind).officialUrl && <> · <a href={boardCodeInfo(drawer.meta.code, selectedKind).officialUrl!} target="_blank" rel="noreferrer">同花顺 ↗</a></>}</p>
        <p className="data-source">市值 {MARKET_CAP.tradeDate} · 覆盖 {drawer.meta.mvCount ?? '—'} / {drawer.meta.count} 家<br />成交额覆盖 {drawer.meta.amountCount ?? '—'} / {drawer.meta.count} 家</p>
        <p className="data-source">连线表示{boardKind === 'industry' ? '业务联系或共同产业主题' : '共同成分股'}。板块归属与连线都来自公开名单，不构成供应链、客户、股权或资金流关系，也不代表业务占比。</p>
      </DataNotes>
    </div>
    <div className="dr-body">
      {relationSection}
      {boardKind === 'industry' && relationsSection}
      {boardKind === 'concept' && drawer.name === '共封装光学(CPO)' && <p className="definition-note">CPO 是同花顺的相关技术概念，不等于“全部光模块公司”。行业归属请同时查看通信设备、半导体及各公司的主营披露。</p>}
      <section className="dr-sec industry-research">
        <h3>公司经营规模 <span className="status-tag">同报告期比较</span></h3>
        <p className="section-note">按同一报告期的公司整体营收比较规模。整体营收不等于细分业务收入，排名也不代表产业龙头地位。</p>
        <label className="industry-filter">按基础资料行业比较经营规模
          <select value={industryFilter} onChange={e => onIndustryFilter(e.target.value)} aria-label="候选行业筛选">
            <option value="">非金融企业 · 公司营收前五</option>
            {industries.map(([name, count]) => <option key={name} value={name}>{name}（{count}家）</option>)}
          </select>
        </label>
        <div className="candidate-list">{candidates.slice(0, candidateLimit).map((stock: any, index: number) => <button type="button" className="candidate-card" key={stock.code}
          onClick={() => onDrillStock(stock.code)} aria-label={`查看${stock.name}主营与关联`}>
          <div className="candidate-heading"><span className="candidate-number">{String(index + 1).padStart(2, '0')}</span><strong>{stock.name}</strong><span>{stock.code.slice(0, 6)}</span></div>
        <div className="candidate-industry">基础资料行业：{stock.industry || '待补'} · {hasNumber(stock.revenueRank) ? `同口径营收 ${stock.revenueRank} / ${stock.industryPeerCount} 家` : '同业排名待补'}</div>
          <div className="candidate-metrics"><span>{revenueLabel(stock.revenueField)} <b>{fmtMv(stock.revenue)}</b></span><span>归母净利润 <b>{fmtMv(stock.profit)}</b></span></div>
          <p className="candidate-business">{stock.mainBusiness || '主营业务暂缺，需查公司披露。'}</p>
          <div className="candidate-bottom"><span>{reportLabel(stock.reportPeriod)}</span><span>查看主营与财报 ↗</span></div>
        </button>)}</div>
        {candidates.length > candidateLimit && <button type="button" className="directory-more candidate-more" onClick={onShowAllCandidates}>查看其余 {candidates.length - candidateLimit} 个候选</button>}
        {!candidates.length && <p className="empty-note">当前筛选没有可比较的财报样本，无法按营收排序。</p>}
        <details className="section-method"><summary>判断口径</summary><p>产业龙头需要同时核对主营匹配、同业经营规模、细分产业地位：主营业务是否直接参与该细分产业；同一报告期的营收和利润是否具备同业规模优势；是否有市场份额、核心产品排名或客户认证等来源支持。市值和概念标签本身不构成产业龙头结论。排序用公司整体营收而不是某项业务收入；比较行业沿用基础资料口径，与当前板块分类分别标注。</p></details>
      </section>
      {boardKind !== 'industry' && relationsSection}
    </div>
    <div className="dr-act">
      <button className="btn" id="a-center" type="button" onClick={onCenter}>以此为中心</button>
      <button className="btn primary" type="button" onClick={onCopyLink}>复制板块链接</button>
    </div>
  </>
}
