import type { RefObject } from 'react'
import type { Tools } from './types'

type Props = {
  view: string
  tools: Tools
  zlvlRef: RefObject<HTMLButtonElement | null>
  onView: (view: string) => void
  onToggleFlow: () => void
  onToggleLabel: () => void
  onToggleSpin: () => void
  onDolly: (factor: number) => void
  onZoomReset: () => void
  onReset: () => void
}

/* 舞台底部工具条：视图、动效开关、缩放、复位。明暗切换在全站页头。连线动效 / 标签 / 自转三个开关在触摸设备与窄屏上由 CSS 隐藏。 */
export default function Toolbar({ view, tools, zlvlRef, onView, onToggleFlow, onToggleLabel, onToggleSpin, onDolly, onZoomReset, onReset }: Props) {
  return <div id="tools">
    {[['atlas', '星图'], ['shell', '球面'], ['tier', '平面']].map(([v, label]) => (
      <button key={v} className={'tb' + (view === v ? ' on' : '')} data-view={v} type="button"
        onClick={() => onView(v)}>{label}</button>
    ))}
    <span className="sep"></span>
    <button className={'tb' + (tools.flow ? ' on' : '')} id="t-flow" type="button" onClick={onToggleFlow}>连线动效</button>
    <button className={'tb' + (tools.label ? ' on' : '')} id="t-label" type="button" onClick={onToggleLabel}>标签</button>
    <button className={'tb' + (tools.spin ? ' on' : '')} id="t-spin" type="button" onClick={onToggleSpin}>自转</button>
    <span className="sep"></span>
    <button className="tb" id="zout" type="button" title="拉远" onClick={() => onDolly(1.18)}>−</button>
    <button className="tb" id="zlvl" type="button" title="点一下回到默认视距" ref={zlvlRef} onClick={onZoomReset}>100%</button>
    <button className="tb" id="zin" type="button" title="拉近" onClick={() => onDolly(1 / 1.18)}>＋</button>
    <span className="sep"></span>
    <button className="tb" id="t-reset" type="button" onClick={onReset}>复位</button>
  </div>
}
