import type { ReactNode, RefObject } from 'react'
import { EVIDENCE, MARKET_CAP } from '../../lib/evidence.js'
import { boardCodeInfo } from '../../lib/board-codes.js'
import InformationNotice from '../InformationNotice'
import SiteHeader from '../SiteHeader'
import { boardLabels, fmtDate, fmtMv, systemLabels, type BoardKind, type BoardSystem, type DirectoryRow, type Graph, type Row } from './types'

/* 转义正则元字符后，把命中搜索词的片段包成 <mark> */
export function mark(name: string, q: string): ReactNode {
  if (!q) return name
  const re = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'ig')
  return name.split(re).map((part, i) => i % 2 ? <mark key={i}>{part}</mark> : part)
}

type TopProps = {
  mode: 'concept' | 'stock'
  boardKind: BoardKind
  boardSystem: BoardSystem
  concept: string
  graph: Graph
  dateText: string
  routeNotice: string
  query: string
  inputRef: RefObject<HTMLInputElement | null>
  onOpenHome: () => void
  onBack: (kind?: BoardKind) => void
  onQuery: (value: string) => void
}

/* 侧栏上半部：全站页头、当前星图的范围与日期、板块切换、面包屑与搜索。手机上它就是顶栏。 */
export function SidebarTop({ mode, boardKind, boardSystem, concept, graph, dateText, routeNotice, query, inputRef, onOpenHome, onBack, onQuery }: TopProps) {
  return <div className="side-top">
    <SiteHeader current="atlas" variant="sidebar" onHome={onOpenHome} />
    <div className="atlas-context">
      <p>{mode === 'concept'
        ? `${systemLabels[boardSystem]}${boardLabels[boardKind]} · ${(graph.directoryNodes || graph.nodes).length} 个`
        : `${concept} · 显示 ${graph.nodes.length} / ${graph.totalMembers || graph.nodes.length} 只`}</p>
      <div className="snapshot-note">市值 {MARKET_CAP.tradeDate}{MARKET_CAP.status === 'retained' ? ' · 最近有效数据' : ''}<br />行情 {dateText} · 成分 {fmtDate(EVIDENCE.membershipAsOf)}</div>
    </div>

    <div className="classification-tabs" role="group" aria-label="板块星图">
      {(['industry', 'concept'] as BoardKind[]).map(kind => <button type="button" key={kind} aria-pressed={boardKind === kind} onClick={() => onBack(kind)}>{boardLabels[kind]}</button>)}
    </div>
    <p className="classification-note">{mode === 'stock' ? <>个股连线表示共同概念，点击查看依据。</> : boardKind === 'industry' ? <>连线表示业务联系或共同产业主题。<br />点击查看原因、涉及公司与来源。</> : <>连线表示共同成分股，点击查看依据。</>}</p>
    {routeNotice && <p className="classification-notice" role="status">{routeNotice}</p>}

    {mode === 'stock' && (
      <button className="crumb" type="button" onClick={() => onBack()}>
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M10 3 5 8l5 5" /></svg>
        {boardLabels[boardKind]}星图<i>/</i><b>{concept}</b>
      </button>
    )}

    <div className="searchbox">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6">
        <circle cx="7" cy="7" r="4.5" /><path d="M10.5 10.5 14 14" /></svg>
      <input id="q" type="search" autoComplete="off" spellCheck={false} ref={inputRef}
        value={query} aria-label={mode === 'concept' ? `搜索全部${boardLabels[boardKind]}或成员公司` : '搜索板块全部成员'}
        placeholder={mode === 'concept' ? `搜${boardLabels[boardKind]} / 公司 / 代码…` : '搜全部成员 / 代码…'}
        onChange={e => onQuery(e.target.value)} />
    </div>
  </div>
}

export type SheetState = 'peek' | 'open'
type SheetHandlers = {
  onClick: () => void
  onPointerDown: (e: React.PointerEvent<HTMLButtonElement>) => void
  onPointerMove: (e: React.PointerEvent<HTMLButtonElement>) => void
  onPointerEnd: () => void
}
type StatRefs = { node: RefObject<HTMLDivElement | null>; edge: RefObject<HTMLDivElement | null>; deg: RefObject<HTMLDivElement | null>; fps: RefObject<HTMLDivElement | null> }
type SheetProps = {
  sheet: SheetState
  sheetHandlers: SheetHandlers
  graph: Graph
  off: string[]
  clusterCounts: Record<string, number>
  onToggleCluster: (id: string) => void
  mode: 'concept' | 'stock'
  boardKind: BoardKind
  deferredQuery: string
  rows: DirectoryRow[]
  listLimit: number
  onMore: () => void
  litRows: Row[]
  coarsePointer: boolean
  onSelectRow: (row: DirectoryRow) => void
  onHoverRow: (i: number | null) => void
  statRefs: StatRefs
}

/* 侧栏下半部：图例、目录与读数。手机上是底部面板，收起时只露手柄与计数。 */
export function DirectorySheet({ sheet, sheetHandlers, graph, off, clusterCounts, onToggleCluster, mode, boardKind, deferredQuery, rows, listLimit, onMore, litRows, coarsePointer, onSelectRow, onHoverRow, statRefs }: SheetProps) {
  return <div className={'side-list' + (sheet === 'open' ? ' sheet-open' : '')}>
    <button type="button" className="sheet-handle" aria-expanded={sheet === 'open'} aria-controls="list" aria-label={sheet === 'open' ? '收起目录面板' : '展开目录面板'}
      onClick={sheetHandlers.onClick} onPointerDown={sheetHandlers.onPointerDown} onPointerMove={sheetHandlers.onPointerMove} onPointerUp={sheetHandlers.onPointerEnd} onPointerCancel={sheetHandlers.onPointerEnd}><i aria-hidden="true"></i></button>
    <details className="layout-controls"><summary>颜色分组与显示筛选</summary><div className="legend" id="legend">
      {graph.CLUSTERS.map((c: { id: string; name: string; color: string }) => (
        <button key={c.id} className={'cl' + (off.includes(c.id) ? ' off' : '')} type="button"
          title={`显示分组 · ${c.name}；颜色只用于布局，连线依据可点开查看`}
          onClick={() => onToggleCluster(c.id)}>
          <i style={{ background: c.color }}></i>{c.name}<b>{clusterCounts[c.id]}</b></button>
      ))}
    </div></details>
    {mode === 'stock' && <p className="legend-note">颜色用于分组，连线表示共同概念。<br />点个股或连线查看依据。</p>}
    <div className="directory-count">{deferredQuery ? '搜索结果' : mode === 'stock' ? '完整成员名单' : '板块目录'} <b>{rows.length}</b>{mode === 'concept' ? ' 个' : ' 家'}<small title="板块内成员去重后汇总总市值；缺失值不记为零。大小和亮度为当前星图内的相对规模。">总市值从高到低 · 越大越亮</small></div>
    <div className="listwrap" id="list">
      {rows.length ? rows.slice(0, listLimit).map(row => (
        <button type="button" key={row.key} className={'lrow directory-row' + (row.node && litRows.some(n => n.i === row.node.i && n.on) ? ' on' : '')} data-code={row.code}
          onClick={() => onSelectRow(row)}
          /* 触摸屏没有悬停：模拟出的 mouseover 会一直粘在最后点过的行上，所以只在精确指针下联动画布高亮 */
          onMouseOver={coarsePointer ? undefined : () => row.node && onHoverRow(row.node.i)}
          onMouseLeave={coarsePointer ? undefined : () => onHoverRow(null)}>
          <i style={{ background: row.node?.cluster.color || 'var(--faint)' }}></i><span>{mark(row.name, deferredQuery)}<small>{mode === 'stock' ? `${row.code}${row.listing ? ' · ' + row.listing : row.node ? ' · 已上图' : ' · 点击加入图中'}` : row.hint ? '相关词匹配 · 不代表等同分类' : `${boardCodeInfo(row.code, boardKind).indexCode} · ${row.count} 家`}</small></span><b title={mode === 'concept' ? `市值覆盖 ${row.mvCount ?? 0}/${row.count} 家` : '公司总市值'}>{fmtMv(row.mv)}{mode === 'concept' && (row.mvCount ?? 0) < row.count && <small className="cap-partial">部分</small>}</b>
        </button>
      )) : <div className="directory-empty">
        没有匹配的{mode === 'concept' ? boardLabels[boardKind] : '成员'}。{mode === 'concept' ? '可切换行业板块或概念板块，也可到公司知识库搜索全市场公司。' : '这里只搜索当前板块的完整成员。'}</div>}
      {rows.length > listLimit && <button className="directory-more" onClick={onMore}>继续显示 · 还有 {rows.length - listLimit} 项</button>}
    </div>

    <div className="foot">
      <div><div className="k" id="s-node" ref={statRefs.node}>—</div><div className="l">显示节点</div></div>
      <div><div className="k" id="s-edge" ref={statRefs.edge}>—</div><div className="l">显示边</div></div>
      <div><div className="k" id="s-deg" ref={statRefs.deg}>—</div><div className="l">平均度</div></div>
      <div><div className="k" id="s-fps" ref={statRefs.fps}>—</div><div className="l">FPS</div></div>
    </div>
    <InformationNotice variant="atlas" />
  </div>
}
