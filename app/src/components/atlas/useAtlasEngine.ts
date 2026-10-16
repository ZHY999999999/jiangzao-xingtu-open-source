import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createAtlas } from '../../lib/atlas.js'
import { refreshMarketSnapshot, refreshGraphMarketCaps } from '../../lib/evidence.js'
import type { Drawer, Graph, Relation, Row, Tools } from './types'

/* three.js 星图的生命周期：挂载、释放、前后台切换、每五分钟的市值回填，
   以及 atlas.js 通过 emit 回传的那几份状态。路由与目录逻辑不在这里。 */
export function useAtlasEngine({ active, graph }: { active: boolean; graph: Graph }) {
  const activeRef = useRef(active)
  activeRef.current = active
  const refs = {
    stage: useRef<HTMLDivElement>(null),
    labels: useRef<HTMLDivElement>(null),
    hudMode: useRef<HTMLElement>(null),
    hudSel: useRef<HTMLDivElement>(null),
    pathbar: useRef<HTMLDivElement>(null),
    chain: useRef<HTMLSpanElement>(null),
    zlvl: useRef<HTMLButtonElement>(null),
    sNode: useRef<HTMLDivElement>(null),
    sEdge: useRef<HTMLDivElement>(null),
    sDeg: useRef<HTMLDivElement>(null),
    sFps: useRef<HTMLDivElement>(null),
    q: useRef<HTMLInputElement>(null),
  }
  const api = useRef<ReturnType<typeof createAtlas> | null>(null)

  const [gate, setGate] = useState(false)
  const [list, setList] = useState<{ q: string; rows: Row[] }>({ q: '', rows: [] })
  const [drawer, setDrawer] = useState<Drawer | null>(null)
  const [relation, setRelation] = useState<Relation | null>(null)
  const [tools, setTools] = useState<Tools>({ flow: true, label: true, spin: true })
  const [view, setView] = useState('atlas')
  const [off, setOff] = useState<string[]>([])
  const [marketRevision, setMarketRevision] = useState(0)

  /* 换一张图：释放旧实例，复位引擎侧状态与 HUD，再创建新实例。onDrawer 在抽屉打开时回调，用来记录路由。 */
  const mount = (g: Graph, onDrawer: (value: Drawer) => void) => {
    api.current?.dispose()
    g.setView('atlas')          // 概念图是共享单例：返回时把视图复位，HUD 与布局才一致
    setDrawer(null); setRelation(null); setOff([]); setView('atlas')
    if (refs.q.current) refs.q.current.value = ''
    if (refs.hudMode.current) refs.hudMode.current.textContent = '星图视图'
    if (refs.hudSel.current) refs.hudSel.current.textContent = '未选中'
    refreshGraphMarketCaps(g)
    api.current = createAtlas({
      els: {
        stage: refs.stage.current!, labels: refs.labels.current!, hudMode: refs.hudMode.current!,
        hudSel: refs.hudSel.current!, pathbar: refs.pathbar.current!, chain: refs.chain.current!,
        zlvl: refs.zlvl.current!, sNode: refs.sNode.current!, sEdge: refs.sEdge.current!,
        sDeg: refs.sDeg.current!, sFps: refs.sFps.current!, q: refs.q.current!,
      },
      emit: { gate: setGate, list: setList, drawer: (value: Drawer | null) => { setDrawer(value); if (value) onDrawer(value) }, relation: setRelation, tools: setTools },
      graph: g,
    })
    api.current.setActive(activeRef.current)
  }

  const toggleCluster = (id: string) => {
    setOff(o => o.includes(id) ? o.filter(x => x !== id) : [...o, id])
    api.current?.toggleCluster(id)
  }
  const changeView = (v: string) => { setView(v); api.current?.setView(v) }
  const closeDrawer = () => { api.current?.reset(); setDrawer(null); setRelation(null) }

  useEffect(() => () => { api.current?.dispose(); api.current = null }, [])
  useLayoutEffect(() => { api.current?.setActive(active) }, [active])

  // The compact daily snapshot refreshes independently of the application bundle.
  // Revalue in place so returning from a company file keeps the same star map.
  useEffect(() => {
    let disposed = false
    const refresh = async () => {
      await refreshMarketSnapshot()
      if (!disposed) {
        refreshGraphMarketCaps(graph)
        api.current?.updateMarketMetrics()
        setMarketRevision(value => value + 1)
      }
    }
    void refresh()
    const timer = window.setInterval(() => { if (!document.hidden) void refresh() }, 5 * 60_000)
    const onVisible = () => { if (!document.hidden) void refresh() }
    document.addEventListener('visibilitychange', onVisible)
    return () => { disposed = true; clearInterval(timer); document.removeEventListener('visibilitychange', onVisible) }
  }, [graph])

  return { refs, api, gate, list, drawer, relation, tools, view, off, marketRevision, mount, toggleCluster, changeView, closeDrawer }
}
