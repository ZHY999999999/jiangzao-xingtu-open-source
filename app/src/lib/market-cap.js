// All values are company total market capitalisation, in 亿元.
export const validCap = value => typeof value === 'number' && Number.isFinite(value) && value > 0;
export function aggregateMarketCap(members, stocks) {
  const codes = [...new Set(members || [])];
  const values = codes.map(code => stocks[code]?.mv).filter(validCap);
  return {mv: values.length ? values.reduce((sum, value) => sum + value, 0) : null,
    mvCount: values.length, count: codes.length};
}
export function compareMarketCap(a, b) {
  const av = validCap(a.mv) ? a.mv : -1, bv = validCap(b.mv) ? b.mv : -1;
  return bv - av || String(a.code || '').localeCompare(String(b.code || ''));
}
export function validateMarketSnapshot(snapshot, previousDate = '') {
  if (snapshot?.schemaVersion !== 1 || !/^\d{4}-\d{2}-\d{2}$/.test(snapshot.tradeDate || '')
      || snapshot.tradeDate < previousDate || !snapshot.stocks || Array.isArray(snapshot.stocks)) return false;
  const parsed = new Date(`${snapshot.tradeDate}T00:00:00Z`);
  if (!Number.isFinite(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== snapshot.tradeDate
      || snapshot.tradeDate > new Date(Date.now() + 8 * 3600_000).toISOString().slice(0, 10)) return false;
  const entries = Object.entries(snapshot.stocks);
  if (entries.length < 4000 || entries.some(([code, row]) => !/^\d{6}\.(SH|SZ|BJ)$/.test(code)
      || !row || (row.mv !== null && !validCap(row.mv)))) return false;
  const valued = entries.filter(([, row]) => validCap(row.mv)).length;
  return snapshot.coverage?.listed === entries.length && snapshot.coverage?.valued === valued
    && snapshot.coverage?.missing === entries.length - valued && valued / entries.length >= .9;
}
