import type { ReactNode } from 'react'
import { IconMoon, IconSun } from '@tabler/icons-react'
import { toggleTheme, useTheme } from '../lib/theme'
import '../styles/site-header.css'

export type SitePage = 'home' | 'atlas' | 'companies'
type Props = {
  current: SitePage
  /** bar = 公司档案顶栏；home = 首页首屏；sidebar = 星图左栏顶部（手机上变成顶栏一行） */
  variant?: 'bar' | 'home' | 'sidebar'
  /** 星图链接：公司档案页回星图要带上离开时的板块与视角 */
  atlasHash?: string
  /** 页面自己的动作，放在主题按钮左边（如公司档案的「相关公司」） */
  actions?: ReactNode
  onHome?: () => void
}

/* 三个页面共用的页头：左品牌、中产品切换、右动作与主题。位置固定，页面只决定变体和自己的动作。 */
export default function SiteHeader({ current, variant = 'bar', atlasHash = '#kind=industry', actions, onHome }: Props) {
  const theme = useTheme()
  const logo = `${import.meta.env.BASE_URL}images/brand/noise-lab-logo${theme === 'dark' ? '-night' : ''}.png`
  const brand = variant === 'home'
    ? <span className="site-brand"><img src={logo} alt="" width="84" height="48" draggable={false} />降噪实验室</span>
    : <a className="site-brand" href="#/home" onClick={onHome && (event => { event.preventDefault(); onHome() })} aria-label="降噪星图，返回首页" title="返回首页"><img src={logo} alt="" width="40" height="30" draggable={false} /><span>降噪星图<small>A股市场与公司知识库</small></span></a>
  return <header className={`site-header site-header--${variant}`}>
    {brand}
    <nav className="site-nav" aria-label="产品切换">
      <a href={atlasHash} aria-current={current === 'atlas' ? 'page' : undefined}>市场星图</a>
      <a href="#/companies" aria-current={current === 'companies' ? 'page' : undefined}>公司目录</a>
    </nav>
    <div className="site-actions">
      {actions}
      <button type="button" className="site-theme" onClick={toggleTheme} aria-label={theme === 'dark' ? '切换到白天主题' : '切换到夜间主题'} title="全站共用明暗主题">
        {theme === 'dark' ? <IconSun size={17} stroke={1.6} aria-hidden="true" /> : <IconMoon size={17} stroke={1.6} aria-hidden="true" />}
        <span>{theme === 'dark' ? '白天' : '夜间'}</span>
      </button>
    </div>
  </header>
}
