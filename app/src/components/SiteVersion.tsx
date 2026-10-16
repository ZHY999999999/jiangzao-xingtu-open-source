import { useId, useRef } from 'react'
import { siteEnvironment, siteRelease } from '../lib/site-release'

export default function SiteVersion() {
  const dialog = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  const environment = siteEnvironment()
  return <>
    <button type="button" className="site-version" aria-label={`网站版本 v${siteRelease.version}，查看更新记录`} onClick={() => dialog.current?.showModal()}>
      {environment !== '正式网站' && <span>{environment} · </span>}v{siteRelease.version}
    </button>
    <dialog ref={dialog} className="information-dialog site-version-dialog" aria-labelledby={titleId} onClick={event => {
      if (event.target === event.currentTarget) dialog.current?.close()
    }}>
      <div className="information-dialog-content">
        <p className="site-version-context">降噪星图 · {environment}</p>
        <h2 id={titleId}>版本与更新</h2>
        <p>当前页面 v{siteRelease.version}<span className="site-version-date">{siteRelease.date}</span></p>
        <ol className="site-version-history">
          {siteRelease.history.map(entry => <li key={entry.version}>
            <div><strong>v{entry.version}</strong><time dateTime={entry.date}>{entry.date}</time></div>
            <ul>{entry.changes.map(change => <li key={change}>{change}</li>)}</ul>
          </li>)}
        </ol>
        <p className="site-version-note">网站从 v1.0.0 开始统一编号。市值、财报及资料的更新日期，仍以各页面标注为准。</p>
        {!import.meta.env.DEV && <details className="site-version-details"><summary>版本识别信息</summary><code>v{siteRelease.version} · {siteRelease.revision}</code></details>}
        <button type="button" className="information-dialog-close" onClick={() => dialog.current?.close()}>关闭</button>
      </div>
    </dialog>
  </>
}
