import type { CompanySource, SegmentGroup } from './company'

const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n)
// Remove only an explicitly named aggregate whose children reproduce its amount.
// Aliases, nested subtotals and financial-industry offsets remain untouched.
export function segmentDisplay(group: SegmentGroup) {
  const rows = group.items
  const aggregate = rows.filter(r => /^(合计|总计|营业收入合计|营业收入总计|收入合计|营业总收入)$/.test(r.name.trim()))
  if (aggregate.length !== 1) return { items: rows, removedAggregate: false }
  const total = aggregate[0], children = rows.filter(r => r !== total)
  if (!finite(total.revenue) || total.revenue <= 0 || children.length < 2 || children.some(r => !finite(r.revenue))) return { items: rows, removedAggregate: false }
  const sum = children.reduce((n,r)=>n+r.revenue!,0)
  if (Math.abs(sum-total.revenue) > Math.max(1,Math.abs(total.revenue)*1e-8)) return { items: rows, removedAggregate: false }
  return { items: children, removedAggregate: true }
}

export function usableSourceUrl(source: CompanySource) {
  const blocked = ['permanently_unavailable','transient_failure','html_instead_of_pdf','not_a_pdf','refused_unsafe_redirect']
  if (source.available === false || blocked.includes(source.accessStatus || '') || (source.pending && !source.candidate)) return undefined
  return source.url && /^https?:\/\//i.test(source.url) ? source.url : undefined
}

// Unresolved hierarchy is not a set of parallel businesses. Preserve every source row.
export function segmentNeedsReview(group: SegmentGroup) {
  return group.notes.some(note => /父子|重叠|不可直接汇总|口径不同/.test(note))
}
export function segmentDimensionLabel(dimension: string) {
  return /^\d+$/.test(dimension.trim()) ? '分类待核' : dimension
}
export function orderSegments(groups: SegmentGroup[]) {
  const rank = (dimension: string) => ({产品:0,行业:1,地区:2,销售模式:3}[dimension] ?? 4)
  return [...groups].sort((a,b) => Number(segmentDimensionLabel(a.dimension)==='分类待核')-Number(segmentDimensionLabel(b.dimension)==='分类待核') || b.period.localeCompare(a.period) || rank(a.dimension)-rank(b.dimension) || a.dimension.localeCompare(b.dimension))
}
