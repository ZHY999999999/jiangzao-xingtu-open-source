/** Public projection only. Approval records and local source paths never belong here. */
export const QUESTION_IDS = ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6', 'Q7'] as const
export type QuestionId = typeof QUESTION_IDS[number]
export type SevenQuestionSource = { id: string; title: string; publisher: string; publishedAt: string; reportPeriod: string; url: string }
export type SevenQuestionClaim = {
  id: string; questionId: QuestionId; claim: string
  claimType: 'fact' | 'company_statement' | 'calculation' | 'interpretation'
  sourceIds: string[]
  citations: { sourceId: string; section: string; excerpt: string; pdfPage?: number }[]
  limitations?: string | string[]
}
export type SevenQuestionContent = {
  schema: 'atlas-company-seven-questions'; schemaVersion: 1
  code: string; name: string; asOf: string; tagline: string; introduction: string
  answers: { questionId: QuestionId; text: string; claimIds: string[] }[]
  claims: SevenQuestionClaim[]; sources: SevenQuestionSource[]
}

function requireValue(ok: unknown, message: string): asserts ok {
  if (!ok) throw new Error(`七问内容不可用：${message}`)
}
function object(value: unknown, required: string[], optional: string[] = []): Record<string, unknown> {
  requireValue(value && typeof value === 'object' && !Array.isArray(value), '格式错误')
  const row = value as Record<string, unknown>
  requireValue(required.every(key => Object.hasOwn(row, key)) && Object.keys(row).every(key => [...required, ...optional].includes(key)), '字段不匹配')
  return row
}
function text(value: unknown): asserts value is string {
  requireValue(typeof value === 'string' && Boolean(value.trim()), '文字为空')
}
function texts(value: unknown, nonempty = false): asserts value is string[] {
  requireValue(Array.isArray(value) && (!nonempty || value.length), '引用格式错误')
  value.forEach(text)
  requireValue(new Set(value.map(id => id.trim())).size === value.length, '重复引用')
}
function sameSet(left: Set<string>, right: Set<string>) {
  return left.size === right.size && [...left].every(key => right.has(key))
}
function dateValue(value: string) {
  const clean = value.trim().replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3')
  requireValue(/^\d{4}-\d{2}-\d{2}$/.test(clean), '日期格式错误')
  const parsed = new Date(`${clean}T00:00:00Z`)
  requireValue(Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === clean, '日期不存在')
  return clean
}

/** No network reachability claim: this only validates public HTTPS link syntax. */
export function sevenQuestionSourceUrl(value: string): string | undefined {
  try {
    const url = new URL(value)
    if (url.protocol !== 'https:' || url.username || url.password || !url.hostname.includes('.') ||
      /(?:^|\.)(?:localhost|local|internal)$|^\[|^[\d.]+$/i.test(url.hostname)) return undefined
    let decoded = value
    for (let i = 0; i < 2; i++) decoded = decodeURIComponent(decoded)
    if (/file:\/|[a-z]:[\\/]|\\\\/i.test(decoded.replace(/^https:\/\//i, ''))) return undefined
    return value
  } catch { return undefined }
}

/** Validate without changing any copied text, whitespace, IDs, dates or amounts. */
export function validateSevenQuestions(value: unknown, code: string): SevenQuestionContent {
  const row = object(value, ['schema', 'schemaVersion', 'code', 'name', 'asOf', 'tagline', 'introduction', 'answers', 'claims', 'sources'])
  requireValue(row.schema === 'atlas-company-seven-questions' && row.schemaVersion === 1, '版本不匹配')
  requireValue(row.code === code && /^\d{6}\.(SH|SZ|BJ)$/.test(code), '公司不匹配')
  for (const field of ['name', 'asOf', 'tagline', 'introduction']) text(row[field])
  const asOf = dateValue(row.asOf as string)
  requireValue(Array.isArray(row.sources) && row.sources.length, '来源为空')
  const sourceIds = new Set<string>()
  for (const source of row.sources) {
    const s = object(source, ['id', 'title', 'publisher', 'publishedAt', 'reportPeriod', 'url'])
    Object.values(s).forEach(text)
    const id = (s.id as string).trim()
    requireValue(!sourceIds.has(id), '来源编号重复')
    sourceIds.add(id)
    requireValue(dateValue(s.publishedAt as string) <= asOf, '来源日期错误')
    dateValue(s.reportPeriod as string)
    requireValue(sevenQuestionSourceUrl(s.url as string), '来源网址不安全')
  }
  requireValue(Array.isArray(row.claims) && row.claims.length, '主张为空')
  const claims = new Map<string, QuestionId>(), usedSources = new Set<string>()
  for (const claim of row.claims) {
    const c = object(claim, ['id', 'questionId', 'claim', 'claimType', 'sourceIds', 'citations'], ['limitations'])
    text(c.id); text(c.claim)
    const id = c.id.trim()
    requireValue(!claims.has(id), '主张编号重复')
    requireValue(QUESTION_IDS.includes(c.questionId as QuestionId), '主张所属问题错误')
    requireValue(['fact', 'company_statement', 'calculation', 'interpretation'].includes(c.claimType as string), '主张类型错误')
    claims.set(id, c.questionId as QuestionId)
    texts(c.sourceIds, true)
    const refs = new Set(c.sourceIds.map(id => id.trim()))
    requireValue([...refs].every(id => sourceIds.has(id)), '来源引用缺失')
    refs.forEach(id => usedSources.add(id))
    requireValue(Array.isArray(c.citations) && c.citations.length, '原文定位为空')
    const cited = new Set<string>()
    for (const citation of c.citations) {
      const cite = object(citation, ['sourceId', 'section', 'excerpt'], ['pdfPage'])
      text(cite.sourceId); text(cite.section); text(cite.excerpt)
      cited.add(cite.sourceId.trim())
      if (Object.hasOwn(cite, 'pdfPage')) requireValue(Number.isInteger(cite.pdfPage) && (cite.pdfPage as number) > 0, 'PDF 页序错误')
    }
    requireValue(sameSet(refs, cited), '来源与原文引用不一致')
    if (Object.hasOwn(c, 'limitations')) {
      if (Array.isArray(c.limitations)) texts(c.limitations)
      else text(c.limitations)
    }
  }
  requireValue(sameSet(usedSources, sourceIds), '包含未引用来源')
  requireValue(Array.isArray(row.answers) && row.answers.length === 7, '必须完整保留七问')
  const used = new Set<string>()
  row.answers.forEach((answer, i) => {
    const a = object(answer, ['questionId', 'text', 'claimIds'])
    requireValue(a.questionId === QUESTION_IDS[i], '七问顺序错误')
    text(a.text); texts(a.claimIds)
    for (const raw of a.claimIds) {
      const id = raw.trim()
      requireValue(claims.get(id) === a.questionId, '答案引用缺失或问题不匹配')
      used.add(id)
    }
  })
  requireValue(sameSet(used, new Set(claims.keys())), '包含未采用主张')
  return value as SevenQuestionContent
}
