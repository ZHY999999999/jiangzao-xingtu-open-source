/** Presentation only: retain the source record in the data layer for audits. */
export function presentRelationSource(source) {
  let providerDocumentation = false;
  try {
    const host = new URL(source.url).hostname.toLowerCase();
    providerDocumentation = host === 'tushare.pro' || host.endsWith('.tushare.pro');
  } catch { /* An absent URL remains an unlinked source record. */ }
  if (!providerDocumentation) return source;
  return {
    title: '板块成员记录',
    url: null,
    locator: source.excerpt?.split('；')[0] || null,
  };
}
