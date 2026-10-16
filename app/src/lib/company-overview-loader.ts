import { validateCompanyOverview } from './company-overview'
import type { CompanyOverviewContent } from './company-overview'

const modules = import.meta.glob<{ default: unknown }>('../../content/company-overview/*.json')
export const OVERVIEW_CODES = new Set(Object.keys(modules).map(path => path.split('/').pop()!.replace(/\.json$/, '')))
export async function loadCompanyOverview(code: string): Promise<CompanyOverviewContent | null> {
  const loader = modules[`../../content/company-overview/${code}.json`]
  return loader ? validateCompanyOverview((await loader()).default, code) : null
}
