import { Component, lazy, Suspense, useEffect, useRef, useState } from 'react'
import type { CompanySearchState } from './lib/company'
import { readSiteRoute } from './lib/site-route'
import BrandHome from './components/BrandHome'
const loadAtlas = () => import('./App')
const loadLibrary = () => import('./components/CompanyLibrary')
const Atlas = lazy(loadAtlas)
const CompanyLibrary = lazy(loadLibrary)

function PageReady({ children, active = true, selector }: { children: React.ReactNode; active?: boolean; selector: string }) {
  useEffect(() => {
    if (!active) return
    const page = document.querySelector<HTMLElement>(selector)
    if (page) { page.tabIndex = -1; page.focus({ preventScroll: true }) }
  }, [active, selector])
  return children
}
class PageBoundary extends Component<{children: React.ReactNode}, {failed: boolean}> {
  state = {failed: false}
  static getDerivedStateFromError() { return {failed:true} }
  render() { return this.state.failed ? <div className="page-loading" role="alert"><h2>页面加载失败</h2><p>可以重新加载，或从公司目录继续阅读。</p><button onClick={() => location.reload()}>重新加载</button><a href="#/companies" onClick={() => { location.hash = '/companies'; location.reload() }}>打开公司目录</a></div> : this.props.children }
}
function PageLoading({ title }: { title: string }) {
  const [slow, setSlow] = useState(false)
  useEffect(() => { const timer = window.setTimeout(() => setSlow(true), 15_000); return () => window.clearTimeout(timer) }, [])
  return <div className="page-loading" role="status"><p>{title}</p>{slow && <><p>页面文件读取较慢，请检查网络后重试。</p><button onClick={() => location.reload()}>重新加载</button><a href="#/companies" onClick={() => { location.hash = '/companies'; location.reload() }}>打开公司目录</a></>}</div>
}
export default function KnowledgeApp() {
  const [route, setRoute] = useState(() => readSiteRoute(location.hash))
  const [atlasVisited, setAtlasVisited] = useState(route.kind === 'atlas')
  const atlasHash = useRef(route.kind === 'atlas' ? location.hash : '#kind=industry')
  const targetRoute = useRef(route)
  const [directorySearch, setDirectorySearch] = useState<CompanySearchState>({ query: '', industry: '', limit: 60 })
  const directoryScroll = useRef(0)
  useEffect(() => {
    const sync = () => {
      const next = readSiteRoute(location.hash)
      if (next.kind === 'atlas') atlasHash.current = location.hash
      // Board selection and camera state belong to the retained atlas, not this page transition.
      if (next.kind === targetRoute.current.kind && next.code === targetRoute.current.code) return
      targetRoute.current = next
      if (next.kind === 'atlas') setAtlasVisited(true)
      setRoute(next)
    }
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])
  useEffect(() => {
    if (route.kind !== 'atlas') {
      ;(window as unknown as {__atlasBooted?:boolean}).__atlasBooted = true
      document.getElementById('boot')?.remove()
    }
  }, [route.kind])
  useEffect(() => {
    if (route.kind === 'home') document.title = '降噪星图 · A股市场与公司知识库'
    if (route.kind === 'atlas') document.title = '市场星图 · 降噪星图'
  }, [route.kind])
  const openCompany = (code: string) => { location.hash = `/company/${encodeURIComponent(code)}` }
  const openHome = () => { location.hash = '/home' }
  return <PageBoundary>
    {route.kind === 'home' && <PageReady selector=".brand-home"><BrandHome atlasHash={atlasHash.current} preloadAtlas={() => { void loadAtlas().catch(() => {}) }} preloadCompanies={() => { void loadLibrary().catch(() => {}) }} /></PageReady>}
    {atlasVisited && <div className="atlas-host" hidden={route.kind !== 'atlas'}><Suspense fallback={<PageLoading title="正在打开市场星图…" />}>
      <PageReady active={route.kind === 'atlas'} selector="#app"><Atlas active={route.kind === 'atlas'} initialHash={atlasHash.current} onOpenCompany={openCompany} onOpenHome={openHome} /></PageReady>
    </Suspense></div>}
    {(route.kind === 'directory' || route.kind === 'company') && <Suspense fallback={<PageLoading title="正在打开公司档案…" />}>
      <PageReady selector=".company-library"><CompanyLibrary code={route.code} atlasHash={atlasHash.current} onBack={() => { location.hash = atlasHash.current }} onHome={openHome} onOpenCompany={openCompany} directorySearch={directorySearch} setDirectorySearch={setDirectorySearch} directoryScroll={directoryScroll} /></PageReady>
    </Suspense>}
  </PageBoundary>
}
