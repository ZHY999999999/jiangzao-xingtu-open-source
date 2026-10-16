import { IconArrowRight, IconBriefcase, IconReceipt, IconUsers } from '@tabler/icons-react'
import type { CompanyOverviewContent } from '../lib/company-overview'
import { sevenQuestionSourceUrl } from '../lib/company-seven-questions'
import { ContentEvidence } from './CompanySevenQuestions'
import { jumpTo } from './CompanyDetailParts'
import '../styles/company-overview.css'

export default function CompanyOverview({ content, deepTarget }: { content: CompanyOverviewContent; deepTarget?: string }) {
  const graphClaims = [...new Set([...content.businessModel.flows.flatMap(flow => [...flow.buyer.claimIds, ...flow.work.claimIds, ...flow.income.claimIds]), ...(content.businessModel.notes || []).flatMap(note => note.claimIds)])]
  return <div className="co-overview" data-content-tier="L">
    <section className="cq-quickread sq-reading co-reading" aria-labelledby="co-title">
      <header><div><span className="cr-eyebrow">产品与收入</span><h2 id="co-title" tabIndex={-1}>{content.name}做什么生意？</h2></div><p className="cr-reading-date">资料截止 {content.asOf}</p></header>
      <ol className="cq-list">{content.answers.map((answer, index) => <li key={answer.questionId}><span className="cq-num" aria-hidden="true">0{index + 1}</span><h3>{index === 0 ? '卖什么，解决什么问题？' : '主要靠什么获得收入？'}</h3><div className="cq-answer"><p className="sq-answer-text" data-question-id={answer.questionId}>{answer.text}</p><ContentEvidence content={content} claimIds={answer.claimIds} title={index === 0 ? '产品介绍与报告原文' : '收入数据与报告原文'} /></div></li>)}</ol>
    </section>
    <section className="co-business" id="company-business-model" aria-labelledby="co-business-title">
      <header><span className="cr-eyebrow">生意模式图</span><h2 id="co-business-title">这门生意是怎么做的？</h2></header>
      <div className="co-flow-legend" aria-hidden="true"><span><IconUsers size={20} />买方与需求</span><span><IconBriefcase size={20} />公司做什么</span><span><IconReceipt size={20} />收入从哪来</span></div>
      <ol className="co-flows">{content.businessModel.flows.map(flow => <li className="co-flow" key={flow.id} data-flow-id={flow.id}>
        <div className="co-flow-cell"><h3>买方与需求</h3><p>{flow.buyer.text}</p></div><IconArrowRight className="co-flow-arrow" size={22} aria-hidden="true" />
        <div className="co-flow-cell"><h3>公司做什么</h3><p>{flow.work.text}</p></div><IconArrowRight className="co-flow-arrow" size={22} aria-hidden="true" />
        <div className="co-flow-cell co-flow-income"><h3>收入从哪来</h3><p>{flow.income.text}</p></div>
      </li>)}</ol>
      {content.businessModel.notes?.map((note, index) => <p className="co-model-note sq-preserve" key={index}>{note.text}</p>)}
      <ContentEvidence content={content} claimIds={graphClaims} title="客户、交付与收入的报告说明" />
    </section>
    <section className="co-continue" aria-label="继续阅读"><div><span className="cr-eyebrow">继续了解</span><h2>{deepTarget ? '收入之后，还要看成本和利润' : '从财报和历史中了解经营变化'}</h2><p>{deepTarget ? '钱花在哪里？公司在产业链里做什么？利润为什么变化？' : '比较不同年份的经营数据，也可以查看公司的发展历史与原始报告。'}</p></div><div className="co-continue-actions">{deepTarget && <a className="co-primary-action" href={`#${deepTarget}`} onClick={event => jumpTo(event, deepTarget)}>继续看经营情况 <IconArrowRight size={17} /></a>}<a href="#company-finance" onClick={event => jumpTo(event, 'company-finance')}>查看财报与公司历史 <IconArrowRight size={17} /></a></div></section>
  </div>
}

export function CompanyOverviewSources({ content }: { content: CompanyOverviewContent }) {
  return <div className="sq-sources"><h3 className="cr-subtitle">生意概览的报告来源</h3><p className="cr-muted">资料截止 {content.asOf}。产品、收入和生意模式图下可展开对应原文。</p>{content.sources.map(source => <article className="cr-source-card" key={source.id}><h4>{source.title}</h4><p>{source.publisher}</p><p>报告期间：{source.reportPeriod} · 披露日期：{source.publishedAt}</p><a href={sevenQuestionSourceUrl(source.url)} target="_blank" rel="noreferrer">打开原始报告 ↗</a></article>)}</div>
}
