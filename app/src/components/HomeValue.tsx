import { IconArrowUpRight } from '@tabler/icons-react'
import coverage from 'virtual:site-coverage'
import catalog from 'virtual:editorial-catalog'
import { audioLabel } from '../lib/audio-label'
import { contentLabel, selectHomeSamples } from '../lib/content-catalogue'

const fmt = (n: number) => n.toLocaleString('zh-CN')
const day = (v: string) => /^\d{8}$/.test(v) ? `${v.slice(0, 4)}-${v.slice(4, 6)}-${v.slice(6)}` : v

/** Below-the-fold value story. Every number is read at build time from the shipped data. */
export default function HomeValue({ preloadCompanies }: { preloadCompanies: () => void }) {
  const samples = selectHomeSamples(catalog)
  return <div className="home-value">
    <section className="hv-problem" aria-labelledby="hv-problem-title">
      <span className="hv-kicker">认识公司，也看见行业</span>
      <h2 id="hv-problem-title">行情软件告诉你涨跌，<br />很少告诉你这家公司靠什么赚钱。</h2>
      <div className="hv-noise">
        <div><strong>消息很多</strong><p>题材、传闻、观点混在一起，分不清哪句是公司披露，哪句是别人的推测。</p></div>
        <div><strong>数字很碎</strong><p>营收、利润、现金流散落在几十页财报里，口径不同还常被直接比较。</p></div>
        <div><strong>来源很远</strong><p>看到一个结论，很难回到原始公告，确认它说的到底是哪一年、哪一项。</p></div>
      </div>
    </section>

    <section className="hv-method" aria-labelledby="hv-method-title">
      <span className="hv-kicker">从生意开始</span>
      <h2 id="hv-method-title">先认识生意，再深入经营</h2>
      <ol className="hv-questions">
        {['它提供什么', '收入主要来自哪', '谁在付钱', '一笔生意怎样做成', '钱主要花在哪里', '在产业链里做哪一环', '赚不赚钱，在怎样变化'].map((q, i) => <li key={q}><span>{String(i + 1).padStart(2, '0')}</span>{q}</li>)}
      </ol>
      <ul className="hv-rules">
        <li><strong>分层</strong>事实、公司自述、计算和解读分开标注</li>
        <li><strong>溯源</strong>每个答案都能点开，回到原始报告和章节</li>
        <li><strong>看范围</strong>报告期间、数据口径和缺失项都可查看，缺失值不记零</li>
      </ul>
    </section>

    <section className="hv-coverage" aria-labelledby="hv-coverage-title">
      <h2 id="hv-coverage-title" className="hv-visually-hidden">当前覆盖</h2>
      <dl>
        <div><dt>家 A 股公司可查</dt><dd>{fmt(coverage.total)}</dd></div>
        <div><dt>家已有多年财报记录</dt><dd>{fmt(coverage.financialHistory)}</dd></div>
        <div><dt>个行业板块可浏览</dt><dd>{fmt(coverage.industries)}</dd></div>
        <div className="is-deep"><dt>家有公司解读</dt><dd>{fmt(coverage.editorial)}</dd></div>
      </dl>
      <p>公司目录截至 {day(coverage.asOf)}。{coverage.reviewedOverview || 0} 家可读生意概览，{coverage.reviewedSeven} 家可读完整七问解读。两类内容可属于同一家公司；报告期间与来源见各公司页面。</p>
    </section>

    {samples.length > 0 && <section className="hv-samples" aria-labelledby="hv-samples-title">
      <div className="hv-samples-head"><span className="hv-kicker">公司阅读</span><h2 id="hv-samples-title">从这些公司开始读</h2><a className="hv-directory-link" href="#/companies" onPointerEnter={preloadCompanies} onFocus={preloadCompanies}>打开公司目录 <IconArrowUpRight size={16} aria-hidden="true" /></a></div>
      <div className="hv-sample-list">{samples.map(item => <a key={item.code} href={`#/company/${item.code}`} onPointerEnter={preloadCompanies} onFocus={preloadCompanies}>
        <span className="hv-sample-code">{item.code.slice(0, 6)}{item.audio !== 'none' && <em>{audioLabel(item.audio, item.durationSeconds, 'long')}</em>}</span>
        <h3>{item.name}</h3>
        <p className="hv-sample-tagline">{item.overview?.tagline || item.tagline}</p>
        {item.headline && <p className="hv-sample-headline">{item.headline}</p>}
        <span className="hv-sample-foot"><span>{contentLabel(item)}</span><span>阅读档案 <IconArrowUpRight size={16} aria-hidden="true" /></span></span>
      </a>)}</div>
    </section>}

    <section className="hv-layers" aria-labelledby="hv-layers-title">
      <span className="hv-kicker">阅读深度</span>
      <h2 id="hv-layers-title">从产品和收入，读到财报与历史</h2>
      <div className="hv-layer-grid">
        <div className="is-free"><span className="hv-layer-tag">生意概览</span><h3>产品、收入与生意模式</h3><p>公司卖什么，客户为什么需要，公司完成哪些工作，又从哪里获得收入。</p></div>
        <div><span className="hv-layer-tag">经营解读</span><h3>客户、成本与利润</h3><p>进一步看经营依赖与利润变化。完整七问可朗读正文；录音与浏览器朗读在播放入口分别标注。</p></div>
        <div><span className="hv-layer-tag">财报与历史</span><h3>沿时间理解经营变化</h3><p>查看各期财报、发展历史与原始报告。不同公司的可用内容和资料期间以页面为准。</p></div>
      </div>
    </section>

    <footer className="hv-end">
      <a href="#/companies" onPointerEnter={preloadCompanies} onFocus={preloadCompanies}>查找一家公司 <IconArrowUpRight size={20} aria-hidden="true" /></a>
      <span>降噪星图 · 由「降噪实验室」维护</span>
    </footer>
  </div>
}
