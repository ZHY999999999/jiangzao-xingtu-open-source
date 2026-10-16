import { conceptGraph } from '../../lib/atlas.js'

export type Graph = typeof conceptGraph
export type BoardKind = 'concept' | 'industry'
export type BoardSystem = 'ths' | 'sw2021'
export type RelationMode = 'classification' | 'supply-chain' | 'overlap' | 'business' | 'theme' | 'network'
export const boardLabels: Record<BoardKind, string> = { concept: '概念板块', industry: '行业板块' }
export const systemLabels = {ths:'同花顺',sw2021:'申万2021'}

export type Row = { i: number; name: string; color: string; deg: number; on: boolean }
export type Item = { i: number; name: string; color: string }
export type DirectoryRow = { key: string; name: string; code: string; node: any; count: number; hint: boolean; mv: number | null; mvCount?: number; listing?: string }
export type NullableNumber = number | null | undefined
export type ConceptMeta = {
  boardKind?: BoardKind; system?: BoardSystem; context?: boolean
  amount: NullableNumber; pct: NullableNumber; mv: NullableNumber; count: number
  weightedPct?: NullableNumber; code?: string
  relationCounts?: {business: number; theme: number}; evidenceGap?: boolean
  amountCount?: number; mvCount?: number
  leaders: [string, string, number, number][]   // [代码, 名称, 涨跌幅, 总市值(亿)]
}
export type StockMeta = {
  code: string; pct: NullableNumber; amount: NullableNumber; mv: NullableNumber; to: NullableNumber
  concepts: string[]
  industry?: string | null; mainBusiness?: string | null; businessScope?: string | null
  thsIndustries?: {code: string; name: string; level: 'industry' | 'subindustry'}[]
  listStatus?: string | null
  revenue?: NullableNumber; profit?: NullableNumber; reportPeriod?: string | null; reportAnnDate?: string | null
  revenueField?: string | null
  revenueRank?: NullableNumber; industryPeerCount?: number
}
export type RelationRow = { edgeId: number; i: number; name: string; color: string; sharedCount: number; summary: string }
export type Relation = {
  edgeId: number; kind: 'stock' | 'concept' | 'industry' | 'subindustry'
  a: { i: number; name: string; code?: string }; b: { i: number; name: string; code?: string }
  sharedConcepts: string[]; sharedStocks: { code: string; name: string }[]
  sharedCount: number; unionCount: number; overlapPct: number; sameIndustry?: string | null
  source: string; asOf: string; reason: string
  relationType?: RelationMode; directed?: boolean; statement?: string; boundary?: string; mappingBasis?: string
  sourceRefs?: {url:string;title:string;locator?:string;excerpt?:string}[]
  sharedThemes?: {code:string;name:string;a:{codes:string[];count:number;coverage:number};b:{codes:string[];count:number;coverage:number}}[]
}
export type Drawer = {
  i: number; name: string; desc: string; cname: string; color: string
  deg: number; depth: number; meta: ConceptMeta & StockMeta
  groups: { title: string; tag: string; items: Item[] }[]
  relations: RelationRow[]
}
export type Tools = { flow: boolean; label: boolean; spin: boolean }

/* A股惯例：涨红跌绿 */
export const hasNumber = (v: NullableNumber): v is number => typeof v === 'number' && Number.isFinite(v)
export const pctColor = (v: NullableNumber) => hasNumber(v) && v > 0 ? 'var(--up)' : hasNumber(v) && v < 0 ? 'var(--down)' : 'var(--muted)'
export const pctText = (v: NullableNumber) => hasNumber(v) ? (v > 0 ? '+' : '') + v.toFixed(2) + '%' : '—'
export const fmtMv = (v: NullableNumber) => !hasNumber(v) ? '—' : Math.abs(v) >= 10000 ? (v / 10000).toFixed(2) + '万亿' : v.toFixed(1) + '亿'
export const fmtDate = (v?: string | null) => v ? (v.length === 8 ? `${v.slice(0, 4)}-${v.slice(4, 6)}-${v.slice(6)}` : v.slice(0, 10)) : '待补'
export const reportLabel = (v?: string | null) => !v ? '财报待补' : `${v.slice(0, 4)}年${v.slice(4) === '0630' ? '中报' : v.slice(4) === '1231' ? '年报' : v.slice(4) === '0331' ? '一季报' : '三季报'} · 累计口径`
export const revenueLabel = (field?: string | null) => field === 'total_revenue' ? '营业总收入' : field === 'revenue' ? '营业收入' : '营收（口径待补）'
export const listingLabel = (status?: string | null) => status === 'L' ? '' : status === 'D' ? '已退市' : status === 'P' ? '暂停上市' : '上市状态待核'
