import { useId, useRef } from 'react'
import '../styles/notice.css'
import SiteVersion from './SiteVersion'

export default function InformationNotice({ variant = 'reading' }: { variant?: 'home' | 'atlas' | 'reading' }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const titleId = useId()
  return <div className={`information-notice information-notice--${variant}`}>
    <span>公开资料整理 · 不构成投资建议</span>
    <button type="button" onClick={() => dialog.current?.showModal()}>使用说明</button>
    <SiteVersion />
    <dialog ref={dialog} className="information-dialog" aria-labelledby={titleId} onClick={event => {
      if (event.target === event.currentTarget) dialog.current?.close()
    }}>
      <div className="information-dialog-content">
        <h2 id={titleId}>关于本站资料</h2>
        <p>降噪星图基于公司公告、定期报告等公开资料进行整理与可视化，供学习和信息查阅，不构成投资建议、投资咨询服务或任何证券买卖推荐。</p>
        <p>星点大小、亮度、排序及连线用于展示规模与资料中的关系，不代表投资价值、收益预测或交易信号。</p>
        <p>内容可能存在更新延迟、遗漏或整理误差。事实资料与经营解读分别标注，资料日期和核验状态以页面说明为准，请以公司、交易所等机构的最新原始披露为准。</p>
        <p>请独立核实信息并审慎决策，勿将本站内容作为投资决策的唯一依据。</p>
        <button type="button" className="information-dialog-close" onClick={() => dialog.current?.close()}>关闭说明</button>
      </div>
    </dialog>
  </div>
}
