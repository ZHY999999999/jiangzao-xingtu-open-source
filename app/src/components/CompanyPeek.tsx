import { useEffect, useState } from 'react'
import { loadCompany, type CompanyDossier } from '../lib/company'

export default function CompanyPeek({code, onOpen, showAction = true}: {code: string; onOpen: (code:string) => void; showAction?: boolean}) {
  const [company, setCompany] = useState<CompanyDossier | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let alive = true; setCompany(null); setFailed(false)
    loadCompany(code).then(value => { if(alive) setCompany(value) }).catch(() => { if(alive) setFailed(true) })
    return () => { alive = false }
  }, [code])
  return <section className="company-peek">
    <div className="eyebrow">认识这家公司</div>
    <p className="company-peek-intro">{company?.summary.text || (failed ? '公司简介未能加载，可进入档案重试。' : company ? '本站尚未收录公司简介，可打开档案查看业务披露与财报。' : '正在读取公司简介…')}</p>
    {company && [company.summary.products, company.summary.customers, company.summary.revenue].some(Boolean) && <dl>{[['产品与服务', company.summary.products], ['客户', company.summary.customers], ['收入来源', company.summary.revenue]].filter(([, value]) => Boolean(value)).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>}
    {showAction && <button type="button" className="company-read-button" onClick={() => onOpen(code)}>读懂这家公司 <span>→</span></button>}
    {company && <small>资料截至 {company.asOf} · 基础资料查询 {company.profileAsOf}</small>}
  </section>
}
