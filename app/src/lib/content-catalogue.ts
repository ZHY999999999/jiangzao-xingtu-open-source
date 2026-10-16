/** Absence preserves the historical individual-review contract. Sampling flags
 * describe actual per-company checks; batch eligibility does not imply them. */
export type OverviewReviewMetadata =
  | { reviewScope?: never; contentSampled?: never; browserObserved?: never; batchId?: never;
      batchEnvelopeSha256?: never; batchReviewSha256?: never; batchPageReviewSha256?: never }
  | { reviewScope: 'individual'; contentSampled: true; browserObserved: true; batchId?: never;
      batchEnvelopeSha256?: never; batchReviewSha256?: never; batchPageReviewSha256?: never }
  | { reviewScope: 'sampled_batch'; contentSampled: boolean; browserObserved: boolean; batchId: string;
      batchEnvelopeSha256: string; batchReviewSha256: string; batchPageReviewSha256: string }

export type ContentEntry = {
  code: string; name: string; tagline: string; contentSha256: string
  headline: string; reportBasis: string
  audio: 'recording' | 'script' | 'none'
  durationSeconds?: number | null
  overview?: { asOf: string; contentSha256: string; tagline: string } & OverviewReviewMetadata
} & (
  { kind: 'legacy-editorial'; status: 'legacy-content'; createdAt: string; gaps: number }
  | { kind: 'seven-questions'; status: 'release-reviewed-seven'; asOf: string }
  | { kind: 'business-overview'; status: 'release-reviewed-overview'; asOf: string }
)
export type ContentCatalogue = {
  schemaVersion: 1; catalogueSha256: string
  index: { sha256: string; snapshotId: string; asOf: string }
  counts: { readable: number; legacy: number; reviewedSeven: number; reviewedOverview?: number }
  coverage: { total: number; financialHistory: number }
  entries: ContentEntry[]
}

/** Shared by every public status consumer; deep is deliberately not an input. */
export function selectContent(catalogue: ContentCatalogue, code: string): ContentEntry | undefined {
  return catalogue.entries.find(entry => entry.code === code)
}

const HOME_SAMPLE_CODES = ['601138.SH', '000977.SZ', '603019.SH', '600588.SH', '600036.SH', '000333.SZ'] as const

/** Display a bounded sample of actual entries; this does not change content status or totals. */
export function selectHomeSamples(entries: readonly ContentEntry[]): ContentEntry[] {
  const remaining = new Map<string, ContentEntry>()
  for (const entry of entries) if (!remaining.has(entry.code)) remaining.set(entry.code, entry)
  const samples: ContentEntry[] = []
  for (const code of HOME_SAMPLE_CODES) {
    const entry = remaining.get(code)
    if (entry) { samples.push(entry); remaining.delete(code) }
  }
  if (samples.length < 6) {
    samples.push(...[...remaining.values()].sort((a, b) => a.code.localeCompare(b.code)).slice(0, 6 - samples.length))
  }
  return samples
}

/** Homepage, after-listening navigation and the plain-company bridge share this order. */
export function nextHomeSample(entries: readonly ContentEntry[], currentCode: string): ContentEntry | undefined {
  const samples = selectHomeSamples(entries)
  const index = samples.findIndex(entry => entry.code === currentCode)
  return [...samples.slice(index + 1), ...samples.slice(0, Math.max(0, index))].find(entry => entry.code !== currentCode)
}

export function contentLabel(entry: ContentEntry | undefined): string | undefined {
  if (!entry) return undefined
  if (entry.kind === 'business-overview') return '生意概览'
  return entry.overview ? '生意概览 · 经营解读' : '经营解读'
}
export function contentFirst(catalogue: ContentCatalogue, a: {code: string}, b: {code: string}): number {
  return Number(Boolean(selectContent(catalogue, b.code))) - Number(Boolean(selectContent(catalogue, a.code))) || a.code.localeCompare(b.code)
}
export function countMemberContent(catalogue: ContentCatalogue, codes: string[]): number {
  return [...new Set(codes)].filter(code => selectContent(catalogue, code)).length
}

/** Validate exact served bytes before mixing fetched data with this compiled release. */
export async function parseBoundIndex(raw: string, expected: ContentCatalogue['index']): Promise<unknown> {
  if (!globalThis.crypto?.subtle) throw new Error('当前环境无法核对资料版本，请在安全连接中重新打开。')
  const digest = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw))
  const sha = [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('')
  if (sha !== expected.sha256) throw new Error('公司目录与当前页面版本不一致，请刷新整个页面后重试。')
  const index = JSON.parse(raw)
  if (index.snapshotId !== expected.snapshotId || index.asOf !== expected.asOf) throw new Error('公司资料快照与当前页面不一致，请刷新整个页面后重试。')
  return index
}
