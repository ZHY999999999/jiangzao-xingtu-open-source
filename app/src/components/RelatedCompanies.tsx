import { useEffect, useId, useMemo, useState } from 'react'
import type { CompanyIndex, CompanyIndexEntry } from '../lib/company'
import { getRelatedCompanies, compactCompanyMemberships } from '../lib/related-companies.js'

type Memberships = ReturnType<typeof compactCompanyMemberships>
type Props = { index: CompanyIndex; company: Pick<CompanyIndexEntry, 'code' | 'name'>; onOpen: (code: string) => void }

export default function RelatedCompanies({ index, company, onOpen }: Props) {
  const [memberships, setMemberships] = useState<Memberships | null>(null)
  const [error, setError] = useState(false), [retry, setRetry] = useState(0)
  const [query, setQuery] = useState(''), [group, setGroup] = useState<'peers' | 'concepts'>('peers')
  const [limit, setLimit] = useState(20)
  const searchId = useId()
  useEffect(() => {
    let cancelled = false
    setError(false)
    import('virtual:company-memberships').then(module => {
      if (!cancelled) setMemberships(module.default)
    }).catch(() => { if (!cancelled) setError(true) })
    return () => { cancelled = true }
  }, [retry])
  const related = useMemo(() => memberships ? getRelatedCompanies(memberships, index.companies, company.code) : null, [memberships, index, company.code])
  const companies = useMemo(() => new Map(index.companies.map(item => [item.code, item])), [index])
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (related?.[group] || []).filter(item => {
      const entry = companies.get(item.code)
      return entry && (!q || `${entry.name} ${entry.code} ${item.industryNames.join(' ')} ${item.conceptNames.join(' ')}`.toLowerCase().includes(q))
    })
  }, [related, group, query, companies])
  return <div className="cl-related cl-search-compact">
    <div className="cl-related-anchor"><span>正在阅读</span><strong>{company.name}</strong><small>{company.code.slice(0, 6)}{related?.industries.length ? ` · ${related.industries.map(item => item.name).join(' / ')}` : ''}</small></div>
    <a className="cl-all-companies" href="#/companies">全部公司目录 <span aria-hidden="true">↗</span></a>
    {error ? <div className="cl-related-message" role="status"><p>关联目录暂时无法读取，仍可继续阅读档案。</p><button type="button" className="cl-text-action" onClick={() => setRetry(value => value + 1)}>重新读取关联</button></div>
      : !related ? <p className="cl-related-message" role="status">正在查找相关公司…</p>
        : <>
          <div className="cl-related-groups" role="group" aria-label="公司关联类型">
            <button type="button" aria-pressed={group === 'peers'} onClick={() => { setGroup('peers'); setLimit(20) }}>同行业 <small>{related.peers.length}</small></button>
            <button type="button" aria-pressed={group === 'concepts'} onClick={() => { setGroup('concepts'); setLimit(20) }}>共同概念 <small>{related.concepts.length}</small></button>
          </div>
          <label className="cl-visually-hidden" htmlFor={searchId}>筛选相关公司</label>
          <div className="cl-search-input"><span aria-hidden="true">⌕</span><input id={searchId} type="search" placeholder="筛选相关公司" value={query} onChange={event => { setQuery(event.target.value); setLimit(20) }} autoComplete="off" />{query && <button type="button" onClick={() => { setQuery(''); setLimit(20) }} aria-label="清空关联搜索">×</button>}</div>
          <p className="cl-related-context" aria-live="polite">{group === 'peers' ? '同花顺同行业公司' : '其他行业的共同概念公司'} · {filtered.length} 家</p>
          <div className="cl-company-results">{filtered.slice(0, limit).map(item => {
            const entry = companies.get(item.code)!
            const reasons = group === 'peers' ? item.industryNames : item.conceptNames
            const reason = `${group === 'peers' ? '同行业' : '共同概念'}：${reasons.join('、')}`
            return <button key={entry.code} type="button" className="cl-company-result cl-related-result" onClick={() => onOpen(entry.code)} title={reason}>
              <span className="cl-company-result-top"><strong>{entry.name}</strong><span className="cl-company-code">{entry.code.slice(0, 6)}</span></span>
              <span className="cl-related-reason">{reasons.slice(0, 2).join(' · ')}{reasons.length > 2 && ` 等 ${reasons.length} 个${group === 'peers' ? '行业' : '概念'}`}</span>
            </button>
          })}</div>
          {!filtered.length && <p className="cl-related-message">{query ? '没有匹配的相关公司，可清空搜索或查看全部公司目录。' : group === 'peers' ? '暂无同行业公司结果，可切换共同概念或查看全部公司。' : '暂无共同概念公司结果，可查看全部公司目录。'}</p>}
          {filtered.length > limit && <button type="button" className="cl-load-more" onClick={() => setLimit(value => value + 20)}>查看更多 <span>{limit} / {filtered.length}</span></button>}
          <details className="cl-related-basis"><summary>关联依据</summary><p>按同花顺板块成员识别同行业与共同概念。同行业公司不在共同概念列表重复展示；共同概念越集中，排列越靠前。</p><p>融资融券、沪深通、指数样本等宽泛标签不参与关联排序。共同概念不等于供需、合作或竞争关系。</p><p>成员资料：{related.membershipAsOf?.replace(/^(\d{4})(\d{2})(\d{2})$/, '$1-$2-$3') || '日期待补'}</p></details>
        </>}
  </div>
}
