import catalogue from 'virtual:company-content-catalogue'
import { parseBoundIndex } from './content-catalogue'
export type EvidenceStatus = 'available' | 'partial' | 'missing' | 'review'
// Link availability recorded by the release's link check: an HTTP 200 that served HTML,
// a permanent 404 and a refused redirect are NOT usable originals.
export type SourceAccessStatus = 'ok' | 'unchecked' | 'permanently_unavailable' | 'transient_failure'
  | 'html_instead_of_pdf' | 'not_a_pdf' | 'refused_unsafe_redirect'
export type CompanySource = {
  candidate?: boolean
  id: string; title: string; url?: string; document?: string; locator?: string
  asOf?: string; publishedAt?: string; localRef?: string; sourceType?: 'provider' | 'filing' | 'company'
  // Provenance status carried through from the filing release. `pending: true` marks an
  // explicit gap ("原文待补") rather than a located original, and `available: false`
  // means the link is known not to be usable, so the page must not offer a button that
  // pretends otherwise. Local archive paths are never public addresses.
  accessStatus?: SourceAccessStatus; available?: boolean; pending?: boolean; gapReason?: string
  reportPeriod?: string; reportKind?: string; verificationLevel?: 1 | 2 | 3; versionRelation?: string
  issuer?: string; platform?: string
}
export type CompanyClaim = {
  title: string; text: string; kind: 'fact' | 'company_statement' | 'interpretation'
  sourceIds: string[]; status?: EvidenceStatus
}
export type CompanyEvent = CompanyClaim & { date: string }
export type FinancialPoint = {
  period: string; annDate: string | null; revenue: number | null; revenueField: string | null
  netProfit: number | null; totalNetProfit?: number | null; operatingCashFlow: number | null
  totalAssets: number | null; totalLiabilities: number | null; rdExpense: number | null; capex: number | null
  sourceIds: string[]; currency?: string; reportType?: string; profitReviewPeriods?: string[]
}
export type SegmentGroup = {
  period: string; dimension: string; currency: string
  items: { name: string; revenue: number | null; cost: number | null; profit: number | null; share: number | null; sourceIds: string[] }[]
  notes: string[]
}
export type CompanyIndexEntry = {
  code: string; name: string; industry: string; summary: string; hasHistory: boolean
  depth: 'basic' | 'deep'; updatedAt: string
}
export type CompanyIndex = {
  schemaVersion: number; generatedAt: string; asOf: string; snapshotId: string
  coverage: { total: number; basic: number; financialHistory: number; deep: number; missingProfiles: number }
  companies: CompanyIndexEntry[]
}
export type CompanyDossier = {
  schemaVersion: number; code: string; name: string; industry: string
  companyType: 'industrial' | 'bank' | 'insurance' | 'securities' | 'financial'
  asOf: string; profileAsOf: string; updatedAt: string
  summary: { text: string; products: string; customers: string; revenue: string; sourceIds: string[] }
  profile: { founded: string | null; listed: string | null; website: string | null; intro: string; mainBusiness: string; businessScope: string }
  timeline: CompanyEvent[]; businessModel: CompanyClaim[]; competitive: CompanyClaim[]; risks: CompanyClaim[]
  finance: { currency: string; unit: '元'; annual: FinancialPoint[]; quarterly: FinancialPoint[]; latest: FinancialPoint | null; notes: string[]; profitReconciliation?: { period: string; status: EvidenceStatus; note: string; sourceIds: string[] }[] }
  segments: SegmentGroup[]
  sources: CompanySource[]
  coverage: Record<string, { status: EvidenceStatus; note: string }>
}

export type CompanySearchState = { query: string; industry: string; limit: number }

let indexPromise: Promise<CompanyIndex> | undefined
const dossiers = new Map<string, Promise<CompanyDossier>>()
const root = `${import.meta.env.BASE_URL}data/companies/`
async function readJson<T>(url: string, revalidate = false, bindIndex = false): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 15_000)
  try {
    const response = await fetch(url, { signal: controller.signal, cache: revalidate ? 'no-cache' : 'default' })
    if (!response.ok) throw new Error(response.status === 404 ? '这份公司资料暂未生成。' : '公司资料加载失败，请稍后重试。')
    const body = bindIndex ? await parseBoundIndex(await response.text(), catalogue.index) : await response.json()
    if (!body || body.schemaVersion !== 1) throw new Error('公司资料版本不兼容，请重新读取。')
    return body as T
  } catch (error) {
    if (controller.signal.aborted) throw new Error('读取超过 15 秒，请检查网络后重试，也可以先返回目录。')
    if (error instanceof SyntaxError) throw new Error('收到的资料不完整，请重新读取。')
    if (error instanceof TypeError) throw new Error('暂时无法连接资料服务，请检查网络后重试。')
    throw error
  } finally {
    window.clearTimeout(timeout)
  }
}
export function loadCompanyIndex(refresh = false): Promise<CompanyIndex> {
  if (refresh) { indexPromise = undefined; dossiers.clear() }
  if (!indexPromise) {
    const pending = readJson<CompanyIndex>(`${root}index.json`, true, true).then(index => {
      if (!Array.isArray(index.companies) || !index.coverage || !/^[\w-]+$/.test(index.snapshotId || '')) throw new Error('公司目录不完整，请重新读取。')
      return index
    }).catch(error => { if (indexPromise === pending) indexPromise = undefined; throw error })
    indexPromise = pending
  }
  return indexPromise
}
export async function loadCompany(code: string): Promise<CompanyDossier> {
  if (!/^\d{6}\.(SH|SZ|BJ)$/.test(code)) throw new Error('公司代码格式不正确。')
  const index = await loadCompanyIndex()
  if (!index.companies.some(company => company.code === code)) throw new Error('未找到这家公司的当前上市档案。')
  const key = `${index.snapshotId}/${code}`
  if (!dossiers.has(key)) {
    const pending = readJson<CompanyDossier>(`${root}snapshots/${encodeURIComponent(index.snapshotId)}/${code}.json`).then(company => {
      if (company.code !== code || company.name !== index.companies.find(item => item.code === code)?.name || !company.summary || !company.profile || !company.coverage || !company.finance ||
        ![company.timeline, company.businessModel, company.competitive, company.risks, company.segments, company.sources, company.finance.annual, company.finance.quarterly].every(Array.isArray)) {
        throw new Error('这份公司档案不完整，请重新读取。')
      }
      return company
    }).catch(error => { if (dossiers.get(key) === pending) dossiers.delete(key); throw error })
    dossiers.set(key, pending)
  }
  return dossiers.get(key)!
}
