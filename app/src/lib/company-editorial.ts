import type { CompanySource } from './company'
import { SEVEN_QUESTION_CODES } from './company-seven-questions-loader'
import type { BusinessStudy } from './company-business-study'

type Note = { title: string; text: string; sourceIds: string[]; metric?: string }
export type EditorialSource = CompanySource & { pageSection?: string; excerpt?: string; verifiedAt?: string }
export type CompanyEditorial = {
  code: string; name: string; createdAt: string; reportBasis: string
  tagline: string; introduction: string; introductionSourceIds: string[]; readerTakeaway: string
  customers: { name: string; purpose: string; sourceIds: string[] }[]
  products: { name: string; purpose: string; business: string; sourceIds: string[] }[]
  process: Note[]; paymentExplanation: string; paymentSourceIds: string[]
  costs: Note[]; dependencies: Note[]
  readingSummary?: {
    period: string; headline: string; note: string; sourceIds: string[]
    metrics: { label: string; value: string; detail: string }[]
  }
  businessMap?: {
    caption: string
    customers: { title: string; text: string }[]
    products: { title: string; text: string }[]
  }
  businessStudy?: BusinessStudy
  history: (Note & { date: string })[]
  revenueMix: { period: string; currency: string; denominator: number; denominatorLabel: string;
    items: { name: string; readerLabel?: string; revenue: number; share: number; sourceIds: string[] }[];
    explanation: string; calculationNote: string; periodNote?: string }
  financeNotes: (Note & { period: string; meaning: string; boundary: string })[]
  sources: EditorialSource[]; evidenceGaps: string[]
  audio?: { url: string; transcript: string; sourceIds: string[]; contentVersion: string; durationSeconds: number }
}
// Editorial content is reviewed independently from the financial snapshot and loaded per company.
const modules = import.meta.glob<{ default: CompanyEditorial }>('../../content/company-editorial/*.json')
export const EDITORIAL_CODES = new Set([...Object.keys(modules).map(path => path.split('/').pop()!.replace(/\.json$/, '')), ...SEVEN_QUESTION_CODES])
export async function loadEditorial(code: string): Promise<CompanyEditorial | null> {
  const loader = modules[`../../content/company-editorial/${code}.json`]
  if (!loader) return null
  const result = (await loader()).default
  if (result.code !== code || !Array.isArray(result.sources)) throw new Error('经营说明版本不匹配')
  return result
}
