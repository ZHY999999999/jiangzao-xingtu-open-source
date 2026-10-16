export type SiteRoute = { kind: 'home' | 'atlas' | 'directory' | 'company'; code?: string }

export function readSiteRoute(hash: string): SiteRoute {
  if (!hash || hash === '#' || /^#\/home(?:[/?]|$)/.test(hash)) return { kind: 'home' }
  const company = /^#\/company\/([^/?]+)/.exec(hash)
  if (company) {
    let code = company[1]
    try { code = decodeURIComponent(code) } catch { /* The dossier page explains malformed codes. */ }
    return { kind: 'company', code }
  }
  if (hash.startsWith('#/companies')) return { kind: 'directory' }
  // Keep #/ and all historic board/stock deep links as atlas entry points.
  return { kind: 'atlas' }
}

export const isAtlasRouteHash = (hash: string) => readSiteRoute(hash).kind === 'atlas'
