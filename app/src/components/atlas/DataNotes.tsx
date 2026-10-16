import type { ReactNode } from 'react'

/* 抽屉头部唯一的「数据说明」：日期、口径、覆盖率、来源差异都收在这一处，
   摘要行只露最要紧的一句和待核条数，正文不再逐段重复边界声明。 */
export default function DataNotes({ summary, warnings = [], children }: { summary: string; warnings?: (string | false | null | undefined)[]; children: ReactNode }) {
  const alerts = warnings.filter((text): text is string => Boolean(text))
  return <details className="data-notes">
    <summary><span>数据说明</span><small>{summary}</small>{alerts.length > 0 && <b>{alerts.length} 项待核</b>}</summary>
    <div className="data-notes-body">
      {alerts.map(text => <p className="source-discrepancy" key={text}>{text}</p>)}
      {children}
    </div>
  </details>
}
