import { IconArrowDown, IconArrowUpRight, IconCircleFilled, IconFileText } from '@tabler/icons-react'
import { useTheme } from '../lib/theme'
import '../styles/home.css'
import InformationNotice from './InformationNotice'
import HomeValue from './HomeValue'
import SiteHeader from './SiteHeader'

type Props = { atlasHash: string; preloadAtlas: () => void; preloadCompanies: () => void }

export default function BrandHome({ atlasHash, preloadAtlas, preloadCompanies }: Props) {
  const theme = useTheme()
  return <main className="brand-home" tabIndex={-1} aria-label="降噪星图首页">
    <div className="home-stage">
      <div className="home-art" aria-hidden="true">
        <img src={theme === 'dark' ? '/images/brand/home-constellation-night.png' : '/images/brand/home-constellation.png'} alt="" width="1586" height="992" fetchPriority="high" draggable={false} />
      </div>
      <SiteHeader current="home" variant="home" atlasHash={atlasHash} />
      <div className="home-content">
        <div className="home-intro">
          <h1>降噪星图</h1>
          <p className="home-description"><span className="home-description-lead">你的第一个</span><span className="home-description-line">把公司生意讲明白的</span><span className="home-description-line">市场观察工具</span></p>
        </div>
        <nav className="home-entries" aria-label="探索内容">
          <a href={atlasHash} onPointerEnter={preloadAtlas} onFocus={preloadAtlas}>
            <IconCircleFilled className="home-entry-icon home-star-icon" size={15} aria-hidden="true" />
            <div className="home-entry-copy">
              <h2>市场星图</h2><p>行业、概念与公司之间的联系</p>
              <span className="home-entry-action">进入星图 <IconArrowUpRight size={23} stroke={1.6} aria-hidden="true" /></span>
            </div>
          </a>
          <a href="#/companies" onPointerEnter={preloadCompanies} onFocus={preloadCompanies}>
            <IconFileText className="home-entry-icon" size={27} stroke={1.5} aria-hidden="true" />
            <div className="home-entry-copy">
              <h2>公司档案</h2><p>发展历史、主营业务与经营财报</p>
              <span className="home-entry-action">查找公司 <IconArrowUpRight size={23} stroke={1.6} aria-hidden="true" /></span>
            </div>
          </a>
        </nav>
        <a className="home-scroll-cue" href="#home-value" onClick={event => { event.preventDefault(); document.getElementById('home-value')?.scrollIntoView({ behavior: 'smooth' }) }}>它解决什么问题 <IconArrowDown size={16} stroke={1.6} aria-hidden="true" /></a>
      </div>
    </div>
    <div id="home-value"><HomeValue preloadCompanies={preloadCompanies} /></div>
    <div className="home-notice-end"><InformationNotice variant="home" /></div>
  </main>
}

