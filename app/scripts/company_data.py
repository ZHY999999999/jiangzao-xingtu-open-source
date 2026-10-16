"""Pure company dossier calculations; no network access or credential handling."""
from collections import defaultdict
from datetime import datetime
import json
import math
import re

DATE = re.compile(r'^\d{8}$')
FLOW_FIELDS = ('revenue', 'netProfit', 'totalNetProfit', 'operatingCashFlow', 'rdExpense', 'capex')
INCOME_FIELDS = ('revenue', 'total_revenue', 'n_income_attr_p', 'n_income', 'rd_exp', 'minority_gain')
CASH_FIELDS = ('n_cashflow_act', 'c_pay_acq_const_fiolta')
BALANCE_FIELDS = ('total_assets', 'total_liab')
FINANCIAL = {'银行': 'bank', '保险': 'insurance', '证券': 'securities', '多元金融': 'financial'}
DIMENSIONS = {'P': '产品', 'D': '地区', 'I': '行业'}


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def valid_date(value):
    value = str(value or '')
    if not DATE.fullmatch(value):
        return None
    try:
        datetime.strptime(value, '%Y%m%d')
        return value
    except ValueError:
        return None


def announced(row):
    values = [valid_date(row.get(key)) for key in ('ann_date', 'f_ann_date')]
    return max((x for x in values if x), default=None)


def signature(row, fields):
    return tuple(number(row.get(field)) for field in fields)


def conflicting_values(a, b, fields):
    return any(x is not None and y is not None and not math.isclose(x, y, rel_tol=1e-10, abs_tol=.01)
               for x, y in zip(signature(a, fields), signature(b, fields)))


def select_reports(rows, as_of, fields, require_consolidated=True):
    """Select whole report rows, never fill a revised row from an older version."""
    groups, issues = defaultdict(list), defaultdict(int)
    for original in rows:
        row = dict(original)
        period, ann = valid_date(row.get('end_date')), announced(row)
        if not period or period > as_of:
            issues['invalidOrFuturePeriod'] += 1
            continue
        if not ann:
            issues['missingAnnouncementDate'] += 1
            continue
        if ann > as_of:
            issues['futureAnnouncement'] += 1
            continue
        if require_consolidated and str(row.get('report_type')) not in ('1', '1.0'):
            issues['unverifiedOrNonconsolidatedReport'] += 1
            continue
        row['_ann'] = ann
        groups[period].append(row)
    selected = {}
    for period, versions in groups.items():
        latest_ann = max(row['_ann'] for row in versions)
        latest = [row for row in versions if row['_ann'] == latest_ann]
        updated = [row for row in latest if str(row.get('update_flag')) in ('1', '1.0')]
        if updated:
            latest = updated
        if any(conflicting_values(a, b, fields) for i, a in enumerate(latest) for b in latest[i + 1:]):
            newest_source = max(row.get('_priority', 0) for row in latest)
            latest = [row for row in latest if row.get('_priority', 0) == newest_source]
        if any(conflicting_values(a, b, fields) for i, a in enumerate(latest) for b in latest[i + 1:]):
            # A source which dropped its update flag cannot resolve this conflict.
            issues['ambiguousSameDateRevisions'] += 1
            continue
        latest.sort(key=lambda row: (sum(number(row.get(field)) is not None for field in fields),
                                     row.get('_priority', 0), json.dumps(row, sort_keys=True, ensure_ascii=False)))
        chosen = dict(latest[-1])
        chosen['_revised'] = any(conflicting_values(a, b, fields) for i, a in enumerate(versions) for b in versions[i + 1:])
        chosen['_versionCount'] = len(versions)
        chosen['_firstAnn'] = min(row['_ann'] for row in versions)
        selected[period] = chosen
    return selected, dict(issues)


def row_source(sources, dataset, period, row, source_file):
    identifier = f'{dataset}-{period}-{row["_ann"]}'
    if identifier not in sources:
        sources[identifier] = {
            'id': identifier, 'title': f'Tushare {dataset} {period} 合并报表',
            'publishedAt': row['_ann'], 'localRef': row.get('_sourceRef') or source_file,
            'locator': f'{dataset}: end_date={period}; announcement={row["_ann"]}; report_type=1; whole selected row',
            'sourceType': 'provider',
        }
    return identifier


def revenue_value(row):
    for field in ('total_revenue', 'revenue'):
        value = number(row.get(field))
        if value is not None:
            return value, field
    return None, None


def point(period, income, cash, balance, sources, raw_ref):
    inc, cf, bs = income.get(period), cash.get(period), balance.get(period)
    source_ids = [row_source(sources, dataset, period, row, raw_ref)
                  for dataset, row in (('income', inc), ('cashflow', cf), ('balancesheet', bs)) if row]
    revenue, field = revenue_value(inc or {})
    return {
        'period': period, 'annDate': max((row['_ann'] for row in (inc, cf, bs) if row), default=None),
        'revenue': revenue, 'revenueField': field, 'netProfit': number((inc or {}).get('n_income_attr_p')),
        'totalNetProfit': number((inc or {}).get('n_income')), 'operatingCashFlow': number((cf or {}).get('n_cashflow_act')),
        'totalAssets': number((bs or {}).get('total_assets')), 'totalLiabilities': number((bs or {}).get('total_liab')),
        'rdExpense': number((inc or {}).get('rd_exp')), 'capex': number((cf or {}).get('c_pay_acq_const_fiolta')),
        'sourceIds': source_ids, 'currency': 'CNY', 'reportType': '1',
    }


def comparable_versions(current, previous):
    if not current or not previous:
        return False
    if not current.get('_revised') and not previous.get('_revised'):
        return True
    # Both periods must be explicitly restated together before subtraction.
    return current['_ann'] == previous['_ann']


def derive_quarterly(cumulative, income, cash):
    quarterly, suppressed = [], 0
    previous_end = {'0630': '0331', '0930': '0630', '1231': '0930'}
    for period in sorted(cumulative):
        suffix = period[4:]
        if suffix not in ('0331', '0630', '0930', '1231'):
            continue
        current = cumulative[period]
        output = dict(current)
        output['sourceIds'] = list(current['sourceIds'])
        # A balance sheet is a point-in-time value, never a quarterly cash flow.
        output['totalAssets'] = output['totalLiabilities'] = None
        if suffix == '0331':
            quarterly.append(output)
            continue
        prev_period = period[:4] + previous_end[suffix]
        prior = cumulative.get(prev_period)
        for field in FLOW_FIELDS:
            output[field] = None
        if prior:
            output['sourceIds'] = sorted(set(current['sourceIds'] + prior['sourceIds']))
            output['annDate'] = max(x for x in (current['annDate'], prior['annDate']) if x)
            for mapping, fields in ((income, ('revenue', 'netProfit', 'totalNetProfit', 'rdExpense')),
                                    (cash, ('operatingCashFlow', 'capex'))):
                if not comparable_versions(mapping.get(period), mapping.get(prev_period)):
                    if mapping.get(period) and mapping.get(prev_period):
                        suppressed += 1
                    continue
                if mapping is income and current['revenueField'] != prior['revenueField']:
                    # Revenue labels cannot silently change inside a subtraction.
                    suppressed += 1
                    income_fields = [x for x in fields if x != 'revenue']
                else:
                    income_fields = fields
                for field in income_fields:
                    a, b = current[field], prior[field]
                    if a is not None and b is not None:
                        output[field] = a - b
        quarterly.append(output)
    return [p for p in quarterly if any(p[field] is not None for field in FLOW_FIELDS)], suppressed


def build_finance(raw, evidence, as_of, sources, raw_ref, reviews=None):
    income_rows = list(raw.get('income', []))
    ev_period, ev_ann = valid_date(evidence.get('reportPeriod')), valid_date(evidence.get('reportAnnDate'))
    if ev_period and ev_ann and ev_period <= as_of and ev_ann <= as_of:
        ev_row = {'end_date': ev_period, 'ann_date': ev_ann, 'report_type': '1',
                  'n_income_attr_p': number(evidence.get('profit')) * 1e8 if number(evidence.get('profit')) is not None else None,
                  '_sourceRef': 'src/lib/evidence-data.json', '_priority': 1}
        if evidence.get('revenueField') in ('total_revenue', 'revenue'):
            ev_row[evidence['revenueField']] = number(evidence.get('revenue')) * 1e8 if number(evidence.get('revenue')) is not None else None
        income_rows.append(ev_row)
    income, income_issues = select_reports(income_rows, as_of, INCOME_FIELDS)
    cash, cash_issues = select_reports(raw.get('cashflow', []), as_of, CASH_FIELDS)
    balance, balance_issues = select_reports(raw.get('balancesheet', []), as_of, BALANCE_FIELDS)
    for dataset, dataset_issues in (('income', income_issues), ('cashflow', cash_issues), ('balancesheet', balance_issues)):
        if dataset_issues.get('ambiguousSameDateRevisions'):
            raise ValueError(f'{dataset}: unresolved same-date revised reports; refusing candidate snapshot')
    periods = sorted(set(income) | set(cash) | set(balance))
    cumulative = {period: point(period, income, cash, balance, sources, raw_ref) for period in periods}
    quarterly, suppressed = derive_quarterly(cumulative, income, cash)
    annual = [cumulative[p] for p in periods if p.endswith('1231')]
    latest = cumulative[periods[-1]] if periods else None
    notes = [
        '金额单位为人民币元；年度序列为12月31日累计值，单季序列由同年相邻累计值相减；最新一期可能是半年或前三季累计。',
        '每期采用现有来源中截至档案日期已披露的最新合并报表整行；缺失值保留空值，负值不归零。未声称已穷尽实时披露。',
        '营业总收入与营业收入按字段逐点标明；归母净利润与包含少数股东的净利润分别保留。',
        '资本开支表示购建固定资产、无形资产和其他长期资产支付的现金；未直接采用旧自动计算的自由现金流。',
    ]
    if balance_issues.get('unverifiedOrNonconsolidatedReport'):
        notes.append('旧资产负债表未保留合并报表类型，资产与负债暂不并入已验证序列，待补原始报表类型。')
    if suppressed:
        notes.append(f'{suppressed}组单季差分因财报更正版本或收入字段不一致未计算。')
    if any(x.get('ambiguousSameDateRevisions') for x in (income_issues, cash_issues, balance_issues)):
        notes.append('同一公告日存在数值冲突且缺少可核验更正优先级的期间已排除。')
    if income_issues.get('currentEvidenceConflict'):
        notes.append('当前财报快照与旧原始数据同日数值冲突，最新一期采用当前快照，不拼接旧字段。')
    reconciliation = []
    for period, row in sorted(income.items()):
        total, parent, minority = (number(row.get(k)) for k in ('n_income', 'n_income_attr_p', 'minority_gain'))
        if any(v is None for v in (total, parent, minority)):
            continue
        residual = total - parent - minority
        if not math.isclose(residual, 0, abs_tol=.05, rel_tol=0):
            item = {'period': period, 'totalNetProfit': total, 'parentNetProfit': parent,
                                   'minorityProfit': minority, 'residual': residual,
                                   'status': 'review', 'note': '三字段存在差额，需结合利润归属口径及原报告核对。',
                                   'sourceIds': [row_source(sources, 'income', period, row, raw_ref)]}
            review = (reviews or {}).get(period)
            if review and all(number(review.get(key)) == item[key] for key in ('totalNetProfit', 'parentNetProfit', 'minorityProfit')):
                source = review['source']
                sources[source['id']] = source
                item.update(status=review['status'], note=review['note'])
                item['sourceIds'].append(source['id'])
            reconciliation.append(item)
    if reconciliation:
        notes.append('利润归属核对保留来源数值；差额可能涉及其他权益工具等口径，不能直接当作经营异常或自动改数。具体期间见核对记录。')
    pending = {item['period'] for item in reconciliation if item['status'] == 'review'}
    previous_end = {'0630': '0331', '0930': '0630', '1231': '0930'}
    for p in annual + ([latest] if latest else []):
        p['profitReviewPeriods'] = [p['period']] if p['period'] in pending else []
    for p in quarterly:
        dependencies = {p['period']}
        if p['period'][4:] in previous_end:
            dependencies.add(p['period'][:4] + previous_end[p['period'][4:]])
        p['profitReviewPeriods'] = sorted(pending & dependencies)
    return {'currency': 'CNY', 'unit': '元', 'annual': annual, 'quarterly': quarterly,
            'latest': latest, 'notes': notes, 'profitReconciliation': reconciliation}, income, {
                'income': income_issues, 'cashflow': cash_issues, 'balancesheet': balance_issues,
                'quarterlyRevisionSuppressed': suppressed,
            }


def normalized_segment_name(name):
    return re.sub(r'\s|[（(](产品|地区|行业)[）)]$', '', name).strip()


def build_segments(rows, as_of, income):
    groups = defaultdict(list)
    seen = set()
    for row in rows:
        period = valid_date(row.get('end_date'))
        if not period or period > as_of or not row.get('bz_item'):
            continue
        ann = announced(row)
        if ann and ann > as_of:
            continue
        currency = str(row.get('curr_type') or '未披露').upper()
        currency = {'人民币': 'CNY', 'RMB': 'CNY', '元': 'CNY'}.get(currency, currency)
        dimension = DIMENSIONS.get(str(row.get('bz_code') or '').upper(), str(row.get('bz_code') or '未披露维度'))
        key = (period, dimension, currency)
        fingerprint = (key, row.get('_priority', 0), announced(row), row['bz_item'], signature(row, ('bz_sales', 'bz_cost', 'bz_profit')))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        groups[key].append(row)
    result = []
    for (period, dimension, currency), original in sorted(groups.items(), reverse=True):
        priority = max(row.get('_priority', 0) for row in original)
        original = [row for row in original if row.get('_priority', 0) == priority]
        dated = [announced(row) for row in original if announced(row)]
        if dated:
            latest_ann = max(dated)
            original = [row for row in original if announced(row) == latest_ann]
        notes = ['按查询时点可用分部资料整理；原源未保留披露日时，披露日待核，不代表截至某日的历史回放。']
        names = [normalized_segment_name(str(r['bz_item'])) for r in original]
        parent_present = any(name in ('产品', '地区', '行业', '合计', '总计', '营业收入', '营业总收入', '主营业务收入')
                             or '合计' in name or '总计' in name for name in names)
        hierarchy = any(other.startswith(name + sep) for name in names for other in names if name != other for sep in (':', '：', '/', '—'))
        value_alias = len({signature(r, ('bz_sales', 'bz_cost', 'bz_profit')) for r in original}) < len(original)
        unknown_values = any(number(r.get('bz_sales')) is None for r in original)
        negative_values = any((number(r.get('bz_sales')) or 0) < 0 for r in original)
        total, revenue_field = revenue_value(income.get(period, {}))
        sum_sales = sum(number(r.get('bz_sales')) or 0 for r in original)
        over_total = total is not None and total > 0 and sum_sales > total * 1.01
        ambiguous = parent_present or hierarchy or value_alias or unknown_values or negative_values or over_total
        if parent_present or hierarchy:
            notes.append('含汇总项或父子层级，原行保留但不可直接加总；不计算份额。')
        if value_alias:
            notes.append('存在金额完全相同的不同名称，可能为同项别名，未将它们当作独立收入加总。')
        if over_total:
            notes.append('分部原行合计超过公司同期收入，可能重叠或口径不同，份额留空。')
        if currency != 'CNY':
            notes.append('该组未换算人民币，不与人民币公司收入计算份额。')
        if total is None or total <= 0:
            notes.append('缺少同期间可核对的正值公司收入，份额留空。')
        elif not ambiguous and currency == 'CNY':
            notes.append('份额以公司同期间' + ('营业总收入' if revenue_field == 'total_revenue' else '营业收入') + '为分母，未把分部表自动归一化为100%。')
        items = []
        for row in sorted(original, key=lambda r: (-(number(r.get('bz_sales')) or 0), str(r['bz_item']))):
            sales = number(row.get('bz_sales'))
            share = sales / total * 100 if not ambiguous and currency == 'CNY' and total and total > 0 and sales is not None else None
            if share is not None and not 0 <= share <= 100:
                share = None
            items.append({'name': str(row['bz_item']), 'revenue': sales, 'cost': number(row.get('bz_cost')),
                          'profit': number(row.get('bz_profit')), 'share': share,
                          'sourceIds': ['overlay-segments' if row.get('_priority') == 2 else 'raw-segments']})
        result.append({'period': period, 'dimension': dimension, 'currency': currency, 'items': items, 'notes': notes})
    return result


def company_type(industry, evidence, raw):
    if industry in FINANCIAL:
        return FINANCIAL[industry]
    types = {'2': 'bank', '3': 'insurance', '4': 'securities', '7': 'financial'}
    candidates = raw.get('income', [])
    if candidates and str(candidates[0].get('comp_type')) in types:
        return types[str(candidates[0]['comp_type'])]
    return 'financial' if evidence.get('isFinancial') else 'industrial'


def build_dossier(code, evidence, legacy, raw, as_of, financial_as_of, narrative=None, finance_reviews=None):
    old_company = legacy.get('company') or {}
    profile_as_of = evidence.get('profileAsOf') or 'unknown'
    main_business = evidence.get('mainBusiness') or old_company.get('business') or ''
    business_scope = evidence.get('businessScope') or old_company.get('scope') or ''
    raw_ref = f'data/value/raw/{code}.json'
    old_ref = f'site/data/stocks/{code}.json'
    sources = {
        'current-profile': {'id': 'current-profile', 'title': 'Tushare 上市公司资料（主体业务描述）',
                            'url': 'https://tushare.pro/document/2?doc_id=112', 'asOf': profile_as_of,
                            'localRef': 'src/lib/evidence-data.json', 'sourceType': 'provider'},
        'legacy-profile': {'id': 'legacy-profile', 'title': '旧知识库基础资料（原采集日期未记录）',
                           'localRef': old_ref, 'locator': 'company and base fields; not auto-generated analysis', 'sourceType': 'provider'},
        'current-income': {'id': 'current-income', 'title': 'Tushare income_vip 最新已载入合并利润表',
                           'url': 'https://tushare.pro/document/2?doc_id=33', 'asOf': financial_as_of,
                           'publishedAt': evidence.get('reportAnnDate'), 'localRef': 'src/lib/evidence-data.json',
                           'locator': f'stocks[{code}]; report_type=1', 'sourceType': 'provider'},
    }
    if any(row.get('_priority') != 2 for row in raw.get('mainbz', [])):
        sources['raw-segments'] = {'id': 'raw-segments', 'title': 'Tushare 主营业务构成原始行（披露日待核）',
                                   'url': 'https://tushare.pro/document/2?doc_id=81', 'localRef': raw_ref,
                                   'locator': 'mainbz; group by end_date,bz_code,curr_type', 'sourceType': 'provider'}
    overlay_segments = [row for row in raw.get('mainbz', []) if row.get('_priority') == 2]
    if overlay_segments:
        sources['overlay-segments'] = {'id': 'overlay-segments', 'title': 'Tushare 主营业务构成更新快照（披露日待核）',
            'url': 'https://tushare.pro/document/2?doc_id=81', 'localRef': overlay_segments[0].get('_sourceRef'),
            'locator': 'mainbz; latest input snapshot per period,dimension,currency', 'sourceType': 'provider'}
    finance, selected_income, financial_issues = build_finance(raw, evidence, as_of, sources, raw_ref, finance_reviews)
    industry = evidence.get('industry') or legacy.get('industry_raw') or ''
    comp_type = company_type(industry, evidence, raw)
    if comp_type != 'industrial':
        finance['notes'].append('金融企业收入和现金流结构有行业专属含义；不据此套用工业企业毛利率、自由现金流或优劣评价。')
    segments = build_segments(raw.get('mainbz', []), as_of, selected_income)
    products = main_business
    intro_text = old_company.get('intro') or ''
    promotional = re.compile(r'全球领先|国内领先|世界领先|行业领先|行业龙头|最大[的]?|第一[的]?|唯一[的]?|领军|领导者')
    intro_sentences = [part.strip() for part in re.split(r'[。\n]', intro_text) if part.strip() and not promotional.search(part)]
    intro = '。'.join(intro_sentences)[:1800]
    if intro:
        intro += '。'
    # Profile introductions are retained as attributed source text, never rewritten into verified rankings.
    summary_text = main_business or '该公司的主营业务描述尚未补齐。'
    timeline = []
    founded, listed = valid_date(old_company.get('setup_date')), valid_date(legacy.get('list_date'))
    for date, title, text in ((founded, '当前主体注册', '公司资料记载的当前法律主体注册日期。'),
                              (listed, 'A股上市', '股票基础资料记载的上市日期。')):
        if date and date <= as_of:
            timeline.append({'date': date, 'title': title, 'text': text, 'kind': 'fact', 'sourceIds': ['legacy-profile'], 'status': 'available'})
    business_model = [{'title': '主营业务（公司资料）', 'text': main_business, 'kind': 'company_statement',
                       'sourceIds': ['current-profile' if evidence.get('mainBusiness') else 'legacy-profile'], 'status': 'available'}] if main_business else []
    dossier = {
        'schemaVersion': 1, 'code': code, 'name': evidence.get('name') or legacy.get('name') or code, 'industry': industry,
        'companyType': comp_type, 'asOf': as_of, 'profileAsOf': profile_as_of, 'updatedAt': as_of,
        'summary': {'text': summary_text, 'products': products, 'customers': '', 'revenue': '',
                    'sourceIds': ['current-profile' if evidence.get('mainBusiness') else 'legacy-profile'] if main_business else []},
        'profile': {'founded': founded, 'listed': listed, 'website': old_company.get('website') or None,
                    'intro': intro, 'mainBusiness': main_business, 'businessScope': business_scope},
        'timeline': timeline, 'businessModel': business_model, 'competitive': [], 'risks': [],
        'finance': finance, 'segments': segments, 'sources': [],
        'coverage': {
            'profile': {'status': 'available' if main_business else 'missing', 'note': '主营资料按其查询日期标注；旧简介和注册资料未记录原采集日。简介中的自述排位未经独立核实。'},
            'financialHistory': {'status': 'available' if finance['annual'] or finance['quarterly'] else 'missing', 'note': f'已有{len(finance["annual"])}个年度、{len(finance["quarterly"])}个含可用指标的单季记录；有记录不代表所有期间或字段齐备，缺失保留为空。' if raw else '尚无可追溯历史合并报表。'},
            'latestFinancial': {'status': 'available' if finance['latest'] else 'missing', 'note': '现有来源内、截至档案日期已披露的最新一期；原快照筛选截止日为' + str(financial_as_of) + '。'},
            'balanceSheet': {'status': 'review' if raw.get('balancesheet') and not any(p['totalAssets'] is not None for p in finance['annual']) else 'available' if any(p['totalAssets'] is not None for p in finance['annual']) else 'missing', 'note': '原源缺报表类型的资产负债值未并入已验证序列。'},
            'segments': {'status': 'review' if segments else 'missing', 'note': '分部披露日待核；重叠、父子层级、不同币种均不混算。'},
            'research': {'status': 'missing', 'note': '尚未逐项核验公司成长史、客户结构和竞争地位。'},
        },
    }
    if narrative:
        if valid_date(narrative.get('reviewedAsOf')) and narrative['reviewedAsOf'] > as_of:
            narrative = None
        else:
            for source in narrative.get('sources', []):
                if source['id'] in sources:
                    raise ValueError('Narrative source id collision: ' + source['id'])
                sources[source['id']] = source
            for field in ('timeline', 'businessModel', 'competitive', 'risks'):
                additions = narrative.get(field, [])
                if field == 'timeline':
                    additions = [event for event in additions if not valid_date(event.get('date')) or event['date'] <= as_of]
                    dossier[field] = sorted(dossier[field] + additions, key=lambda event: event.get('date', ''))
                elif additions:
                    dossier[field] = additions
            if narrative.get('summary'):
                if not isinstance(narrative['summary'], dict):
                    raise ValueError('Narrative summary must follow CompanyDossier.summary contract: ' + code)
                dossier['summary'] = dict(dossier['summary'], **narrative['summary'])
            dossier['coverage']['research'] = {'status': 'partial', 'note': '已有首版经营解读；来源与公司自述分别标注，不代表已逐页核读全部原始披露。整理日期：' + str(narrative.get('reviewedAsOf') or '未记录')}
            reviewed = valid_date(narrative.get('reviewedAsOf'))
            latest_ann = (finance.get('latest') or {}).get('annDate')
            stale = bool(reviewed and latest_ann and latest_ann > reviewed)
            for section in ('businessModel', 'competitive', 'risks'):
                if dossier[section]:
                    dossier['coverage'][section] = {'status': 'review' if stale else 'available',
                        'note': ('已有更新披露（' + latest_ann + '），原解释保留，待复核。') if stale else '正文核阅日期：' + str(reviewed or '未记录')}
            if stale:
                dossier['coverage']['research'] = {'status': 'review', 'note': '新披露晚于正文核阅日期；解释待复核，原有历史与来源保留。'}
    if finance['profitReconciliation']:
        pending_count = sum(item['status'] == 'review' for item in finance['profitReconciliation'])
        dossier['coverage']['profitReconciliation'] = {'status': 'review' if pending_count else 'available',
            'note': f'{len(finance["profitReconciliation"])}个报告期有利润归属核对记录，其中{pending_count}期待复核。原值保留，相关单季利润同步标记。'}
    dossier['sources'] = sorted(sources.values(), key=lambda source: source['id'])
    validate_dossier(dossier)
    return dossier, financial_issues, bool(narrative)


def validate_dossier(dossier):
    source_ids = {source['id'] for source in dossier['sources']}
    if len(source_ids) != len(dossier['sources']):
        raise ValueError('Duplicate source ids: ' + dossier['code'])
    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == 'sourceIds' and any(identifier not in source_ids for identifier in child):
                    raise ValueError('Unresolved source id: ' + dossier['code'])
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError('Non-finite numeric value')
    walk(dossier)
    for p in dossier['finance']['annual'] + dossier['finance']['quarterly'] + ([dossier['finance']['latest']] if dossier['finance']['latest'] else []):
        if p['period'] > dossier['asOf'] or p['annDate'] and p['annDate'] > dossier['asOf']:
            raise ValueError('Future report: ' + dossier['code'])
        if p.get('reportType') != '1':
            raise ValueError('Nonconsolidated financial point')
    for source in dossier['sources']:
        if source.get('publishedAt') and valid_date(source['publishedAt']) and source['publishedAt'] > dossier['asOf']:
            # A current profile source can be newer than a historical fiscal cutoff;
            # financial/narrative claims cannot cite future publications.
            if source['id'] in ({x for item in dossier['timeline'] + dossier['businessModel'] + dossier['competitive'] + dossier['risks'] for x in item['sourceIds']} | set(dossier['summary']['sourceIds'])):
                raise ValueError('Claim cites future source: ' + source['id'])
