import { Component, useDeferredValue, useEffect, useMemo, useRef, useState } from 'react'
import { getBoardGraph, buildStockGraph, META } from './lib/atlas.js'
import { EVIDENCE, getBoardEvidence, getStockEvidence, getBoardCandidates } from './lib/evidence.js'
import { compareMarketCap } from './lib/market-cap.js'
import { readBoardRoute } from './lib/board-route.js'
import { useMediaQuery } from './lib/media'
import { isAtlasRouteHash } from './lib/site-route'
import { useAtlasEngine } from './components/atlas/useAtlasEngine'
import { SidebarTop, DirectorySheet, type SheetState } from './components/atlas/Sidebar'
import Toolbar from './components/atlas/Toolbar'
import RelationCard from './components/atlas/RelationCard'
import BoardDrawer from './components/atlas/BoardDrawer'
import StockDrawer from './components/atlas/StockDrawer'
import { listingLabel, type BoardKind, type BoardSystem, type DirectoryRow, type Drawer, type Graph } from './components/atlas/types'

/* 渲染期异常的最后一道网：任何 React 子树崩溃都不许把整页拉黑，
   至少保住一个可读的降级界面。 */
class ErrorBoundary extends Component<{ children: React.ReactNode }, { err: string | null }> {
  state = { err: null as string | null }
  static getDerivedStateFromError(e: Error) { return { err: e?.message || String(e) } }
  componentDidCatch(e: Error) {
    console.error('[atlas] React 渲染异常：', e)
    ;(window as unknown as { __atlasFail?: (title: string, msg: string) => void })
      .__atlasFail?.('星图启动失败', e?.stack || e?.message || String(e))
  }
  render() {
    if (this.state.err) return (
      <div style={{ position: 'fixed', inset: 0, display: 'grid', placeContent: 'center',
        background: '#050507', color: '#9a9aa3', fontSize: 13, lineHeight: 2.2, padding: 40, textAlign: 'center' }}>
        <div style={{ fontSize: 15, color: '#e8e8ec', fontWeight: 600 }}>页面渲染时出了点问题</div>
        <div>刷新一次通常能恢复；若反复出现，请把下面的信息反馈给我：</div>
        <code style={{ fontSize: 11, opacity: .7, wordBreak: 'break-all' }}>{this.state.err}</code>
        <button onClick={() => location.reload()}
          style={{ margin: '18px auto 0', padding: '8px 22px', font: 'inherit', cursor: 'pointer',
            background: '#7d9bff', color: '#0a0c14', border: 0, borderRadius: 8 }}>刷新页面</button>
      </div>)
    return this.props.children
  }
}

const routeFor = (hash: string) => readBoardRoute(hash, (target: string, kind: string) => getBoardEvidence(target, kind, 'ths'))
const conceptSearchHints: Record<string, string[]> = { '共封装光学(CPO)': ['光模块', '光通信', 'cpo'] }
const industrySearchHints: Record<string, string[]> = { '通信设备': ['光模块', '光通信'], '通信网络设备及器件': ['光模块', '光通信'], '半导体': ['光芯片'], '分立器件': ['光芯片'] }
const CANDIDATE_PREVIEW = 3

type AtlasProps = { active?: boolean; initialHash?: string; onOpenCompany?: (code: string) => void; onOpenHome?: () => void }
export default function Root(props: AtlasProps) {
  return <ErrorBoundary><App {...props} /></ErrorBoundary>
}

/* 星图页的编排：路由与图的切换（drill / back）、目录筛选、抽屉里的候选与筛选状态。
   three.js 的生命周期在 useAtlasEngine，各区块的版式在 components/atlas 下。 */
function App({active = true, initialHash, onOpenCompany = code => { location.hash = `/company/${code}` }, onOpenHome = () => { location.hash = '/home' }}: AtlasProps) {
  const initialRoute = useRef(routeFor(initialHash ?? location.hash))
  const initialKind = useRef<BoardKind>(initialRoute.current.kind as BoardKind)
  const handledHash = useRef(initialHash ?? location.hash)
  const navigateHash = useRef<(hash: string) => void>(() => {})

  /* 下钻状态：concept = 概念星图；stock = 某概念的个股星图 */
  const [mode, setMode] = useState<'concept' | 'stock'>('concept')
  const [concept, setConcept] = useState('')
  const [boardKind, setBoardKind] = useState<BoardKind>(initialKind.current)
  const boardSystem: BoardSystem = 'ths'
  const [graph, setGraph] = useState<Graph>(() => getBoardGraph(initialKind.current, initialKind.current === 'industry' ? 'network' : 'overlap', 'ths'))
  const engine = useAtlasEngine({ active, graph })
  const { api, drawer, relation } = engine

  const [industryFilter, setIndustryFilter] = useState('')
  const [candidateLimit, setCandidateLimit] = useState(CANDIDATE_PREVIEW)
  const [query, setQuery] = useState('')
  /* 输入框立即回显，5,000 多只股票的扫描按低优先级跟上；高亮与计数都用延后的值，和结果一致。 */
  const deferredQuery = useDeferredValue(query)
  const stockIndex = useMemo(() => Object.values(EVIDENCE.stocks).map((s: any) => ({ code: s.code, name: s.name.toLowerCase(), lower: s.code.toLowerCase() })), [])
  const coarsePointer = useMediaQuery('(pointer: coarse)')
  const [listLimit, setListLimit] = useState(100)
  const [routeNotice, setRouteNotice] = useState('')

  /* 手机上目录是底部面板：peek 只露出手柄和计数，open 升到 62vh。桌面不读这个状态。 */
  const [sheet, setSheet] = useState<SheetState>('peek')
  const sheetDrag = useRef<{ y: number; moved: boolean } | null>(null)
  const sheetClickSuppressedUntil = useRef(0)
  const sheetHandlers = {
    onPointerDown: (e: React.PointerEvent<HTMLButtonElement>) => { sheetDrag.current = { y: e.clientY, moved: false }; e.currentTarget.setPointerCapture(e.pointerId) },
    onPointerMove: (e: React.PointerEvent<HTMLButtonElement>) => {
      const drag = sheetDrag.current
      if (!drag) return
      const dy = e.clientY - drag.y
      if (Math.abs(dy) > 24) { drag.moved = true; setSheet(dy < 0 ? 'open' : 'peek') }
    },
    // A drag already chose the state; the click the browser fires right after it must not toggle back.
    onPointerEnd: () => { if (sheetDrag.current?.moved) sheetClickSuppressedUntil.current = performance.now() + 400; sheetDrag.current = null },
    onClick: () => { if (performance.now() < sheetClickSuppressedUntil.current) return; setSheet(value => value === 'open' ? 'peek' : 'open') },
  }

  const clusterCounts = useMemo(() => Object.fromEntries(
    graph.CLUSTERS.map((c: { id: string }) => [c.id, graph.nodes.filter((n: { cid: string }) => n.cid === c.id).length])), [graph])

  const rememberRoute = (g: Graph, selected?: Drawer | null) => {
    if (!isAtlasRouteHash(location.hash)) return
    const kind = (g.boardKind || (g.mode === 'stock' ? boardKind : g.mode)) as BoardKind
    const params = new URLSearchParams({kind})
    if (g.mode === 'stock') {
      params.set('c', g.boardCode || g.conceptName || '')
      if (selected?.meta.code) params.set('s', selected.meta.code)
    } else if (selected) { params.set('n', selected.meta.code || selected.name) }
    const hash = '#' + params.toString()
    handledHash.current = hash
    if (location.hash !== hash) {
      history.replaceState(null, '', hash)
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    }
  }

  /* 换图：引擎重建 + 目录与提示复位 */
  const mount = (g: Graph) => {
    engine.mount(g, value => rememberRoute(g, value))
    setIndustryFilter(''); setQuery(''); setListLimit(100); setRouteNotice('')
  }

  /* 展开个股星图：市值参照用于布局；可顺带定位某只个股 */
  const drill = (name: string, stock?: string, kind: BoardKind = boardKind) => {
    const g = buildStockGraph(name, stock, kind, 'ths')
    if (!g) { setRouteNotice('该板块暂时没有可展示的成员，请查看其他板块。'); return }
    const targetBoard = getBoardEvidence(name, kind, 'ths')
    setBoardKind(kind); setConcept(targetBoard?.name || g.conceptName || name); setGraph(g); setMode('stock')
    mount(g)
    rememberRoute(g)
    if (stock) {
      const t = g.nodes.find((n: any) => n.name === stock || n.meta?.code === stock)
      if (t) api.current?.selectAt(t.i)
    }
  }

  /* 返回概念星图；可顺带定位某个概念（从个股详情的概念芯片点回来） */
  const back = (selectConcept?: string, kind: BoardKind = boardKind) => {
    const nextGraph = getBoardGraph(kind, kind === 'industry' ? 'network' : 'overlap', 'ths')
    setBoardKind(kind); setMode('concept'); setGraph(nextGraph); setConcept('')
    mount(nextGraph)
    rememberRoute(nextGraph)
    if (selectConcept) {
      const t = nextGraph.nodes.find((n: any) => n.name === selectConcept || n.meta?.code === selectConcept)
      if (t) api.current?.selectAt(t.i)
      else setRouteNotice('链接指向的板块已更名或暂不在当前目录中，可以搜索名称或代码。')
    }
  }

  navigateHash.current = (hash: string) => {
    if (!isAtlasRouteHash(hash) || hash === handledHash.current) return
    handledHash.current = hash
    const route = routeFor(hash)
    if (route.drill) drill(route.board, route.stock || undefined, route.kind as BoardKind)
    else back(route.board || undefined, route.kind as BoardKind)
    if (route.notice) setRouteNotice(route.notice)
  }

  useEffect(() => {
    mount(graph)
    // 挂载成功：通知启动探针并收起加载屏
    ;(window as unknown as { __atlasBooted?: boolean }).__atlasBooted = true
    document.getElementById('boot')?.remove()
    // 深链：#n=概念 定位概念；#c=概念 直接展开个股星图；&s=个股 再定位个股
    const route = initialRoute.current
    if (route.drill) drill(route.board, route.stock || undefined, initialKind.current)
    else if (route.board) {
      const t = graph.nodes.find((x: any) => x.meta?.code === route.board)
      if (t) api.current?.selectAt(t.i)
      else setRouteNotice('链接指向的板块已更名或暂不在当前目录中，可以搜索名称或代码。')
    } else rememberRoute(graph)
    if (route.notice) setRouteNotice(route.notice)
    const onHash = () => navigateHash.current(location.hash)
    window.addEventListener('hashchange', onHash)
    return () => { window.removeEventListener('hashchange', onHash) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => { setIndustryFilter(''); setCandidateLimit(CANDIDATE_PREVIEW) }, [drawer?.name])
  useEffect(() => {
    if (relation) document.getElementById('relation-card')?.scrollIntoView({ block: 'nearest' })
  }, [relation])

  const selectedKind = drawer?.meta.boardKind || boardKind
  const selectedSystem: BoardSystem = 'ths'
  const board = mode === 'concept' && drawer ? getBoardEvidence(drawer.meta.code || drawer.name, selectedKind, selectedSystem) : null
  const industries = useMemo(() => {
    const counts = new Map<string, number>()
    for (const code of board?.members || []) {
      const industry = getStockEvidence(code)?.industry
      if (industry) counts.set(industry, (counts.get(industry) || 0) + 1)
    }
    return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'zh-CN'))
  }, [board])
  const candidates = mode === 'concept' && drawer
    ? getBoardCandidates(drawer.meta.code || drawer.name, industryFilter || undefined, selectedKind, selectedSystem).map((code: string) => getStockEvidence(code)).filter(Boolean)
    : []

  const shownCodes = useMemo(() => new Map(graph.nodes.map((n: any) => [n.meta?.code, n])), [graph])
  const directoryRows = useMemo<DirectoryRow[]>(() => {
    const term = deferredQuery.trim().toLowerCase()
    if (mode === 'stock') {
      const members = getBoardEvidence(concept, boardKind, boardSystem)?.members || []
      return [...new Set(members)].map((code: any) => getStockEvidence(code)).filter(Boolean)
        .filter((s: any) => !term || s.name.toLowerCase().includes(term) || s.code.toLowerCase().includes(term))
        .sort(compareMarketCap)
        .map((s: any) => ({key: s.code, name: s.name, code: s.code, node: shownCodes.get(s.code) as any, count: 0, hint: false, mv:s.mv, listing:listingLabel(s.listStatus)}))
    }
    const stockMatches = new Set(term ? stockIndex.filter(s => s.name.includes(term) || s.lower.includes(term)).map(s => s.code) : [])
    return (term ? graph.nodes : graph.directoryNodes || graph.nodes).filter((n: any) => {
      if (engine.off.includes(n.cid) && !term) return false
      const hints = (boardKind === 'concept' ? conceptSearchHints : industrySearchHints)[n.name] || []
      return !term || n.name.toLowerCase().includes(term) || n.meta?.code?.toLowerCase().includes(term) || hints.some(h => h.includes(term)) || (n.meta?.members || []).some((code: string) => stockMatches.has(code))
    }).sort((a: any, b: any) => compareMarketCap(a.meta, b.meta)).map((n: any) => ({key:n.meta?.code || n.name, name:n.name, code:n.meta?.code || '', node:n, count:n.meta?.count || 0, mv:n.meta?.mv ?? null, mvCount:n.meta?.mvCount, hint:!!term && !n.name.toLowerCase().includes(term) && ((boardKind === 'concept' ? conceptSearchHints : industrySearchHints)[n.name] || []).some(h => h.includes(term))}))
  }, [graph, mode, concept, boardKind, boardSystem, deferredQuery, stockIndex, shownCodes, engine.off, engine.marketRevision])
  const selectDirectoryRow = (row: DirectoryRow) => {
    setSheet('peek')
    if (!row.node && mode === 'stock') { drill(concept, row.code); return }
    if (row.node) {
      if (engine.off.includes(row.node.cid)) engine.toggleCluster(row.node.cid)
      // Search is a directory filter. Clear the canvas filter so a matched company cannot hide its board.
      api.current?.setQuery('')
      api.current?.selectAt(row.node.i)
    }
  }
  const changeQuery = (value: string) => { setQuery(value); setListLimit(100) }
  const showMembers = () => { if (drawer) drill(drawer.meta.code || drawer.name, undefined, selectedKind) }
  const copyBoardLink = async () => {
    const params = new URLSearchParams({kind: boardKind, ...(mode === 'stock' ? {c:graph.boardCode || concept} : {n:drawer?.meta.code || drawer?.name || ''})})
    if (mode === 'stock' && drawer?.meta.code) params.set('s', drawer.meta.code)
    try { await navigator.clipboard.writeText(`${location.origin}${location.pathname}#${params}`); setRouteNotice('已复制当前板块链接。') }
    catch { setRouteNotice('当前浏览器无法复制，请使用地址栏或重新打开页面。') }
  }

  const relationsSection = drawer && <section className="dr-sec related-section">
    <h3>与谁相连 <b>{drawer.relations?.length || 0} 条直接连线</b></h3>
    <p className="section-note">点名称后的“关系依据”，或直接点图上的连线。当前网络只展示部分关联。</p>
    <div className="relation-list">{drawer.relations?.map(item => <button type="button" key={item.edgeId}
      className={'relation-row' + (relation?.edgeId === item.edgeId ? ' active' : '')}
      onClick={() => api.current?.selectEdge(item.edgeId)} aria-label={`查看${drawer.name}与${item.name}的关系依据`}>
      <i style={{ background: item.color }} /><span><strong>{item.name}</strong><small>{item.summary}</small></span><b>关系依据 ↗</b>
    </button>)}</div>
    {!drawer.relations?.length && <p className="section-note">{mode === 'concept' && boardKind === 'industry' ? '当前资料不足以形成达到展示条件的关系，业务联系待补证；不代表这个行业与其他行业无关。' : '当前未展示共同成分关系；不代表没有其他业务联系。'}</p>}
  </section>
  const relationSection = relation && <RelationCard relation={relation} onClear={() => api.current?.clearRelation()} onStock={i => api.current?.selectAt(i)} onCompany={onOpenCompany} onTheme={code => back(code, 'concept')} />

  const dateText = `${META.tradeDate.slice(0, 4)}-${META.tradeDate.slice(4, 6)}-${META.tradeDate.slice(6)}`

  return (
    <div id="app" className={drawer ? 'open' : ''}>
      <aside>
        {/* 桌面上两个容器都是 display:contents，侧栏仍是一列；手机上 side-top 是顶栏，side-list 是底部面板 */}
        <SidebarTop mode={mode} boardKind={boardKind} boardSystem={boardSystem} concept={concept} graph={graph} dateText={dateText} routeNotice={routeNotice}
          query={query} inputRef={engine.refs.q} onOpenHome={onOpenHome} onBack={kind => back(undefined, kind)} onQuery={changeQuery} />
        <DirectorySheet sheet={sheet} sheetHandlers={sheetHandlers} graph={graph} off={engine.off} clusterCounts={clusterCounts} onToggleCluster={engine.toggleCluster}
          mode={mode} boardKind={boardKind} deferredQuery={deferredQuery} rows={directoryRows} listLimit={listLimit} onMore={() => setListLimit(limit => limit + 100)}
          litRows={engine.list.rows} coarsePointer={coarsePointer} onSelectRow={selectDirectoryRow} onHoverRow={i => api.current?.hoverAt(i)}
          statRefs={{ node: engine.refs.sNode, edge: engine.refs.sEdge, deg: engine.refs.sDeg, fps: engine.refs.sFps }} />
      </aside>

      <div id="stage" ref={engine.refs.stage}>
        {/* 标签是每帧投影出来的，走的是固定的 div 池，React 不参与 */}
        <div id="labels" ref={engine.refs.labels}></div>

        <div id="hud">
          <div><b id="hud-mode" ref={engine.refs.hudMode}>星图视图</b></div>
          <div id="hud-sel" ref={engine.refs.hudSel}>未选中</div>
        </div>

        <div id="pathbar" ref={engine.refs.pathbar}>
          <span className="chain" id="chain" ref={engine.refs.chain}></span>
          <button className="x" id="path-x" type="button" onClick={() => api.current?.clearPath()}>✕</button>
        </div>

        <Toolbar view={engine.view} tools={engine.tools} zlvlRef={engine.refs.zlvl} onView={engine.changeView}
          onToggleFlow={() => api.current?.toggleFlow()} onToggleLabel={() => api.current?.toggleLabel()} onToggleSpin={() => api.current?.toggleSpin()}
          onDolly={f => api.current?.dolly(f)} onZoomReset={() => api.current?.zoomReset()} onReset={() => api.current?.reset()} />

        <div id="hint">
          拖拽旋转 · 滚轮缩放 · 点节点看公司 · 点连线看关系<br />{' '}
          {mode === 'concept'
            ? boardKind === 'industry' ? <>行业间的业务与主题联系 · 点线查看原因与来源</> : <>连线表示共同成分股 · 点击线查看依据</>
            : <>连线表示共同概念，来源和具体清单在右侧展开 · <kbd>Esc</kbd> 清除</>}
        </div>

        <div id="gate" style={engine.gate ? { display: 'grid' } : undefined}>这台设备没有可用的 WebGL。<br />星图的其余部分（左栏检索、右侧详情）仍然可用。</div>
      </div>

      <div id="drawer"><div className="dr" id="dr">
        {drawer && mode === 'concept' && <BoardDrawer drawer={drawer} board={board} selectedKind={selectedKind} boardKind={boardKind} dateText={dateText}
          industries={industries} industryFilter={industryFilter} onIndustryFilter={value => { setIndustryFilter(value); setCandidateLimit(CANDIDATE_PREVIEW) }}
          candidates={candidates} candidateLimit={candidateLimit} onShowAllCandidates={() => setCandidateLimit(candidates.length)}
          relationSection={relationSection} relationsSection={relationsSection}
          onClose={engine.closeDrawer} onShowMembers={showMembers} onDrillStock={code => drill(drawer.meta.code || drawer.name, code, selectedKind)}
          onCenter={() => api.current?.centerOn(drawer.i)} onCopyLink={copyBoardLink} />}
        {drawer && mode === 'stock' && <StockDrawer drawer={drawer} dateText={dateText} concept={concept}
          relationSection={relationSection} relationsSection={relationsSection}
          onClose={engine.closeDrawer} onOpenCompany={onOpenCompany} onBack={back}
          onCenter={() => api.current?.centerOn(drawer.i)} onStartPath={() => api.current?.startPath(drawer.i)} />}
      </div></div>
    </div>
  )
}
