export type SiteReleaseEntry = { version: string; date: string; changes: string[] }
export type SiteRelease = SiteReleaseEntry & { revision: string; experimental?: boolean; releaseStatus?: string; history: SiteReleaseEntry[] }
declare const __SITE_RELEASE__: SiteRelease

// Embedded in this page's bundle: an old open tab must retain its own version.
export const siteRelease = __SITE_RELEASE__
export function siteEnvironment(hostname = location.hostname) {
  if (siteRelease.releaseStatus === 'public-snapshot-unpublished') return '公开快照重建 · 未发布'
  if (siteRelease.experimental) return '本地实验 · 未发布'
  if (hostname === 'atlas.thinkpair.cn') return '正式网站'
  if (hostname === 'localhost' || hostname === '[::1]' || /^127\./.test(hostname)) return '本地预览'
  return '预览环境'
}
