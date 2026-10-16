export type MembershipBoard = { code: string; name: string; members: string[]; membershipAsOf: string | null }
export type CompanyMemberships = { industries: MembershipBoard[]; concepts: MembershipBoard[]; membershipAsOf: string | null; excludedConceptCount: number }
export type RelatedCompany = { code: string; industryNames: string[]; conceptNames: string[]; score: number }
export function compactCompanyMemberships(evidence: unknown): CompanyMemberships
export function getRelatedCompanies(membership: CompanyMemberships, indexCompanies: { code: string }[], code: string): {
  industries: { code: string; name: string }[]; peers: RelatedCompany[]; concepts: RelatedCompany[]
  membershipAsOf: string | null; excludedConceptCount: number
}
