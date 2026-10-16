import type { SevenQuestionContent, SevenQuestionClaim } from '../lib/company-seven-questions'
import { sevenQuestionSourceUrl } from '../lib/company-seven-questions'
import { audioLabel } from '../lib/audio-label'
import '../styles/company-quickread.css'
import '../styles/company-seven-questions.css'

export const SEVEN_QUESTION_TITLES = [
  '它提供什么，有什么用', '收入主要来自哪里', '谁在付钱，为什么需要它',
  '怎样完成工作并获得收入', '钱主要花在哪里', '怎样发展，处在行业哪一环', '赚不赚钱，为什么变化',
]
const CLAIM_LABEL: Record<SevenQuestionClaim['claimType'], string> = {
  fact: '报告披露', company_statement: '公司自述', calculation: '计算', interpretation: '星图解读',
}
export function SevenQuestionIntroduction({ content }: { content: SevenQuestionContent }) {
  return <><h2>{content.tagline}</h2><p className="sq-preserve">{content.introduction}</p></>
}

export function ContentEvidence({ content, claimIds, title }: { content: Pick<SevenQuestionContent, 'claims' | 'sources'>; claimIds: string[]; title: string }) {
  const claims = new Map(content.claims.map(claim => [claim.id.trim(), claim]))
  const sources = new Map(content.sources.map(source => [source.id.trim(), source]))
  return <details className="sq-evidence"><summary>{title}</summary>{[...new Set(claimIds.map(id => id.trim()))].map(id => {
    const claim = claims.get(id)!
    const limits = Array.isArray(claim.limitations) ? claim.limitations : claim.limitations ? [claim.limitations] : []
    return <article className="sq-claim" key={id} data-claim-id={claim.id}>
      <header><span className="cq-kind">{CLAIM_LABEL[claim.claimType]}</span></header><p className="sq-preserve">{claim.claim}</p>
      {claim.citations.map((citation, index) => {
        const source = sources.get(citation.sourceId.trim())!
        return <div className="sq-citation" key={`${citation.sourceId.trim()}-${index}`}><h4>{source.title}</h4><p className="sq-preserve">报告原文节选 · {citation.section}{citation.pdfPage !== undefined && <span> · PDF 第 {citation.pdfPage} 页</span>}</p><blockquote className="sq-preserve">{citation.excerpt}</blockquote><a href={sevenQuestionSourceUrl(source.url)} target="_blank" rel="noreferrer">打开原始报告 ↗</a></div>
      })}
      {limits.length > 0 && <div className="sq-limitations"><strong>阅读时还需注意</strong><ul>{limits.map((limit, index) => <li className="sq-preserve" key={index}>{limit}</li>)}</ul></div>}
    </article>
  })}</details>
}

export default function CompanySevenQuestions({ content }: { content: SevenQuestionContent }) {
  return <section className="cq-quickread sq-reading" aria-labelledby="sq-title">
    <header><div><span className="cr-eyebrow">经营解读</span><h2 id="sq-title" tabIndex={-1}>进一步了解{content.name}</h2></div><p className="cr-reading-date">资料截止 {content.asOf}</p></header>
    <ol className="cq-list">{content.answers.map((answer, i) => <li key={answer.questionId}>
      <span className="cq-num" aria-hidden="true">{String(i + 1).padStart(2, '0')}</span>
      <h3>{SEVEN_QUESTION_TITLES[i]}</h3>
      <div className="cq-answer">
        <p className="sq-answer-text" data-question-id={answer.questionId}>{answer.text}</p>
        <ContentEvidence content={content} claimIds={answer.claimIds} title={['产品介绍与报告原文', '收入数据与报告原文', '客户与需求的报告说明', '交付与收入的报告说明', '成本与投入的报告说明', '行业位置与报告原文', '盈利数据与报告原文'][i]} />
      </div>
    </li>)}</ol>
    <div className="cq-layers"><span>语音讲解 · {audioLabel('script', undefined, 'long')} · 朗读本页七问正文</span></div>
  </section>
}

export function SevenQuestionSources({ content }: { content: SevenQuestionContent }) {
  return <div className="sq-sources"><h3 className="cr-subtitle">经营解读的报告来源</h3><p className="cr-muted">各问题下可展开报告原文。资料截止 {content.asOf}。</p>
    {content.sources.map(source => <article className="cr-source-card" key={source.id.trim()}>
      <h4>{source.title}</h4><p>{source.publisher}</p><p>报告期间：{source.reportPeriod} · 披露日期：{source.publishedAt}</p>
      <a href={sevenQuestionSourceUrl(source.url)} target="_blank" rel="noreferrer">打开原始报告 ↗</a>
    </article>)}
  </div>
}
