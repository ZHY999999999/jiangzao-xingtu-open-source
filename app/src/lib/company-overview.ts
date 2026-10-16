import { QUESTION_IDS, sevenQuestionSourceUrl } from './company-seven-questions'
import type { SevenQuestionClaim, SevenQuestionSource } from './company-seven-questions'

export type OverviewStatement = { text: string; claimIds: string[] }
export type CompanyOverviewContent = {
  schema: 'atlas-company-overview'; schemaVersion: 1; contentTier: 'L'
  code: string; name: string; asOf: string; tagline: string; introduction: string
  answers: (OverviewStatement & { questionId: 'Q1' | 'Q2' })[]
  businessModel: {
    flows: { id: string; buyer: OverviewStatement; work: OverviewStatement; income: OverviewStatement }[]
    notes?: OverviewStatement[]
  }
  claims: SevenQuestionClaim[]; sources: SevenQuestionSource[]
}

function need(ok: unknown, message: string): asserts ok {
  if (!ok) throw new Error(`生意概览不可用：${message}`)
}
function object(value: unknown, required: string[], optional: string[] = []): Record<string, unknown> {
  need(value && typeof value === 'object' && !Array.isArray(value), '格式错误')
  const row = value as Record<string, unknown>
  need(required.every(key => Object.hasOwn(row, key)) && Object.keys(row).every(key => [...required, ...optional].includes(key)), '字段不匹配')
  return row
}
function text(value: unknown): asserts value is string {
  need(typeof value === 'string' && Boolean(value.trim()), '文字为空')
}
function texts(value: unknown, nonempty = true): asserts value is string[] {
  need(Array.isArray(value) && (!nonempty || value.length > 0), '引用为空或格式错误')
  value.forEach(text)
  need(new Set(value.map(id => id.trim())).size === value.length, '重复引用')
}
function sameSet(a: Set<string>, b: Set<string>) { return a.size === b.size && [...a].every(id => b.has(id)) }
function date(value: unknown): string {
  text(value)
  const clean = value.trim().replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3')
  need(/^\d{4}-\d{2}-\d{2}$/.test(clean), '日期格式错误')
  const parsed = new Date(`${clean}T00:00:00Z`)
  need(Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === clean, '日期不存在')
  return clean
}

/** Independent L contract. Neither missing answers nor invented Q3–Q7 are accepted. */
export function validateCompanyOverview(value: unknown, code: string): CompanyOverviewContent {
  const row = object(value, ['schema', 'schemaVersion', 'contentTier', 'code', 'name', 'asOf', 'tagline', 'introduction', 'answers', 'businessModel', 'claims', 'sources'])
  need(row.schema === 'atlas-company-overview' && row.schemaVersion === 1 && row.contentTier === 'L', '版本不匹配')
  need(row.code === code && /^\d{6}\.(SH|SZ|BJ)$/.test(code), '公司不匹配')
  for (const field of ['name', 'tagline', 'introduction']) text(row[field])
  const asOf = date(row.asOf), sourceIds = new Set<string>()
  need(Array.isArray(row.sources) && row.sources.length > 0, '来源为空')
  for (const source of row.sources) {
    const s = object(source, ['id', 'title', 'publisher', 'publishedAt', 'reportPeriod', 'url'])
    Object.values(s).forEach(text)
    const id = (s.id as string).trim()
    need(!sourceIds.has(id), '来源编号重复'); sourceIds.add(id)
    need(date(s.publishedAt) <= asOf, '来源日期错误'); date(s.reportPeriod)
    need(sevenQuestionSourceUrl(s.url as string), '来源网址不安全')
  }
  const claims = new Map<string, string>(), usedSources = new Set<string>()
  need(Array.isArray(row.claims) && row.claims.length > 0, '依据为空')
  for (const claim of row.claims) {
    const c = object(claim, ['id', 'questionId', 'claim', 'claimType', 'sourceIds', 'citations'], ['limitations'])
    text(c.id); text(c.claim)
    const id = c.id.trim()
    need(!claims.has(id), '依据编号重复')
    need(QUESTION_IDS.includes(c.questionId as typeof QUESTION_IDS[number]), '依据所属问题错误')
    need(['fact', 'company_statement', 'calculation', 'interpretation'].includes(c.claimType as string), '依据类型错误')
    claims.set(id, c.questionId as string)
    texts(c.sourceIds)
    const refs = new Set(c.sourceIds.map(id => id.trim())), cited = new Set<string>()
    need([...refs].every(id => sourceIds.has(id)), '来源引用缺失')
    refs.forEach(id => usedSources.add(id))
    need(Array.isArray(c.citations) && c.citations.length > 0, '原文定位为空')
    for (const citation of c.citations) {
      const cite = object(citation, ['sourceId', 'section', 'excerpt'], ['pdfPage'])
      text(cite.sourceId); text(cite.section); text(cite.excerpt); cited.add(cite.sourceId.trim())
      if (Object.hasOwn(cite, 'pdfPage')) need(Number.isInteger(cite.pdfPage) && (cite.pdfPage as number) > 0, 'PDF 页序错误')
    }
    need(sameSet(refs, cited), '来源与原文引用不一致')
    if (Object.hasOwn(c, 'limitations')) { if (Array.isArray(c.limitations)) texts(c.limitations, false); else text(c.limitations) }
  }
  need(sameSet(usedSources, sourceIds), '包含未引用来源')
  const usedClaims = new Set<string>()
  function statement(value: unknown, question?: string) {
    const s = object(value, ['text', 'claimIds'], question ? ['questionId'] : [])
    text(s.text); texts(s.claimIds)
    for (const raw of s.claimIds) {
      const id = raw.trim()
      need(claims.has(id) && (!question || claims.get(id) === question), '正文引用缺失或问题不匹配')
      usedClaims.add(id)
    }
  }
  need(Array.isArray(row.answers) && row.answers.length === 2, '必须包含产品与收入两问')
  row.answers.forEach((answer, index) => {
    const a = object(answer, ['questionId', 'text', 'claimIds'])
    need(a.questionId === ['Q1', 'Q2'][index], '两问顺序错误'); statement(a, a.questionId as string)
  })
  const model = object(row.businessModel, ['flows'], ['notes'])
  need(Array.isArray(model.flows) && model.flows.length > 0, '生意模式图为空')
  const flowIds = new Set<string>()
  for (const flow of model.flows) {
    const f = object(flow, ['id', 'buyer', 'work', 'income']); text(f.id)
    need(!flowIds.has(f.id.trim()), '图中路线编号重复'); flowIds.add(f.id.trim())
    statement(f.buyer); statement(f.work); statement(f.income)
  }
  if (Object.hasOwn(model, 'notes')) { need(Array.isArray(model.notes), '图注格式错误'); model.notes.forEach(note => statement(note)) }
  need(sameSet(usedClaims, new Set(claims.keys())), '正文与图必须完整引用公开依据')
  return value as CompanyOverviewContent
}
