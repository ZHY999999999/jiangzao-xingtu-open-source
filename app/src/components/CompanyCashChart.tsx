import { useEffect, useId, useRef, useState } from 'react'
import type { FinancialPoint } from '../lib/company'

// Shared axis makes profit/cash differences directly comparable. Nulls break lines.
export default function CompanyCashChart({ points, denomination }: { points: FinancialPoint[]; denomination: string }) {
  const id = useId()
  const container = useRef<HTMLElement>(null)
  const [containerWidth, setContainerWidth] = useState(620)
  useEffect(() => {
    const element = container.current
    if (!element) return
    const observer = new ResizeObserver(entries => setContainerWidth(Math.max(240, Math.floor(entries[0].contentRect.width))))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  const valid = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n)
  const values = points.flatMap(p=>[p.netProfit,p.operatingCashFlow]).filter(valid).map(n=>n/1e8)
  if (!values.length) return <p className="cr-muted">当前期间没有可用的利润与经营现金流数据。缺值保留为空。</p>
  const low = Math.min(0,...values), high = Math.max(0,...values), extent = high-low || 1
  const min = low < 0 ? low-extent*.15 : 0, max = high+extent*.15
  const width = points.length <= 5 ? containerWidth : Math.max(containerWidth,points.length*70+75), height = 280, left=50, right=16, top=30, bottom=48
  const x=(i:number)=>left+(width-left-right)*(i+.5)/points.length
  const y=(v:number)=>top+(max-v)/(max-min)*(height-top-bottom)
  const series = [{key:'netProfit',label:'归母净利润',className:'cr-cash-profit'},{key:'operatingCashFlow',label:'经营现金流净额',className:'cr-cash-operating'}] as const
  return <figure className="cr-cash-chart" ref={container}><figcaption><span className="cr-cash-profit">— 归母净利润</span><span className="cr-cash-operating">┄ 经营现金流净额</span><small>{denomination}亿元 · 同一坐标轴</small></figcaption>{width > containerWidth + 1 && <p className="cr-chart-scroll-hint">左右滑动查看全部 {points.length} 期 →</p>}<div className="cl-chart-scroll" tabIndex={width > containerWidth + 1 ? 0 : undefined} aria-label={width > containerWidth + 1 ? "可左右滚动的财报图表" : undefined}><svg viewBox={`0 0 ${width} ${height}`} style={{minWidth:width}} role="img" aria-labelledby={id}><title id={id}>归母净利润和经营现金流对照；缺值处不连线，负数保留。</title>{[min,(min+max)/2,max].map(t=><g key={t}><line className="cl-chart-grid" x1={left} x2={width-right} y1={y(t)} y2={y(t)}/><text className="cl-chart-axis" x={left-10} y={y(t)+4} textAnchor="end">{t.toFixed(0)}</text></g>)}<line className="cl-chart-zero" x1={left} x2={width-right} y1={y(0)} y2={y(0)}/>{series.map(s=><g key={s.key} className={s.className}>{points.map((p,i)=>{const v=p[s.key],prev=points[i-1]?.[s.key]; if(!valid(v))return <text key={p.period} x={x(i)} y={height-32} className="cl-chart-missing" textAnchor="middle">—</text>;return <g key={p.period} tabIndex={0} role="img" aria-label={`${p.period} ${s.label} ${(v/1e8).toFixed(2)}亿元${s.key==='netProfit'&&p.profitReviewPeriods?.length?'，待复核':''}`}>{i>0&&valid(prev)&&<line x1={x(i-1)} x2={x(i)} y1={y(prev/1e8)} y2={y(v/1e8)} stroke="currentColor" strokeWidth="2" strokeDasharray={s.key==='operatingCashFlow'?'6 4':undefined}/>}<circle cx={x(i)} cy={y(v/1e8)} r="4" fill="var(--bg)" stroke="currentColor" strokeWidth="2"/><title>{s.label}：{(v/1e8).toFixed(2)}亿元</title></g>})}</g>)}{points.map((p,i)=><text className="cl-chart-axis" key={p.period} x={x(i)} y={height-13} textAnchor="middle">{p.period.endsWith('1231')&&points.every(p=>p.period.endsWith('1231'))?p.period.slice(0,4):`${p.period.slice(0,4)}.${p.period.slice(4,6)}`}</text>)}</svg></div><p className="cr-muted">两条线记录不同侧面，差额不直接代表好坏。详细数值与双期出处可在下方数据明细查看。</p></figure>
}
