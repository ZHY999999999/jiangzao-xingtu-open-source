declare module 'virtual:company-memberships' {
  const memberships: ReturnType<typeof import('./lib/related-companies.js').compactCompanyMemberships>
  export default memberships
}

declare module 'virtual:company-content-catalogue' {
  const catalogue: import('./lib/content-catalogue').ContentCatalogue
  export default catalogue
}

declare module 'virtual:editorial-catalog' {
  const catalog: import('./lib/content-catalogue').ContentEntry[]
  export default catalog
}

declare module 'virtual:site-coverage' {
  const coverage: { asOf: string; total: number; financialHistory: number; editorial: number; reviewedSeven: number; reviewedOverview?: number; industries: number }
  export default coverage
}

declare module 'virtual:company-industries' {
  const industries: {code: string; name: string; members: string[]; membershipAsOf: string | null}[]
  export default industries
}
