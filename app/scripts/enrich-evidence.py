#!/usr/bin/env python3
"""Build complete THS concept/industry memberships and business-scale evidence.

Uses only TUSHARE_TOKEN from the environment and the official HTTPS endpoint.
python scripts/enrich-evidence.py --trade-date 20260918 --financial-period 20260630
All network responses are cached by fetch date. --offline rebuilds from that cache.
Core input failures abort before replacing evidence-data.json; optional financial
or company-profile permission gaps are explicitly reported, never fabricated.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import threading
import time
from urllib import request

ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTICS = ROOT.parent / 'diagnostics'
AUDIT_RAW = DIAGNOSTICS / 'tushare-audit-raw'
API = 'https://api.tushare.pro'
CATALOG_FIELDS = 'ts_code,name,count,exchange,type'
INDUSTRY_LEVELS = {'881': 'industry', '884': 'subindustry'}
CLASSIFICATION_SOURCE = '同花顺 · Tushare Pro ths_index/ths_member'
DOCS = {
    'stock_basic': 'https://tushare.pro/document/2?doc_id=25',
    'stock_company': 'https://tushare.pro/document/2?doc_id=112',
    'income_vip': 'https://tushare.pro/document/2?doc_id=33',
    'ths_member': 'https://tushare.pro/document/2?doc_id=261',
    'ths_index': 'https://tushare.pro/document/2?doc_id=259',
    'ths_daily': 'https://tushare.pro/document/2?doc_id=260',
    'daily': 'https://tushare.pro/document/2?doc_id=27',
    'daily_basic': 'https://tushare.pro/document/2?doc_id=32',
}


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def number(value, divisor=1):
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value) / divisor
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


class APIError(RuntimeError):
    pass


class Client:
    def __init__(self, as_of, offline=False):
        self.token = os.environ.get('TUSHARE_TOKEN', '')
        self.as_of = as_of
        self.cache = DIAGNOSTICS / ('evidence-raw-' + as_of)
        self.offline = offline
        self.lock = threading.Lock()
        self.last = 0
        self.calls = []

    def call(self, api, params, fields, label, required=True, audit_file=None):
        cache_file = self.cache / (label + '.json')
        if cache_file.exists():
            cached = json.loads(cache_file.read_text(encoding='utf-8'))
            if cached.get('api') != api or cached.get('params') != params or cached.get('fields') != fields:
                raise APIError('Cache query mismatch: ' + label)
            if cached.get('status') == 'success':
                if required and not cached['rows']:
                    raise APIError('Required cached response is empty: ' + label)
                self.calls.append({'api': api, 'label': label, 'cached': True, 'rows': len(cached['rows'])})
                return cached['rows']
        if audit_file and audit_file.exists():
            audited = json.loads(audit_file.read_text(encoding='utf-8'))
            timestamp = audited.get('fetchedAt') or audited.get('checked_at') or audited.get('started') or ''
            query_matches = (audited.get('api', api) == api and audited.get('params', params) == params
                             and audited.get('fields', fields) == fields)
            if query_matches and timestamp[:10].replace('-', '') == self.as_of and audited.get('code', 0) == 0 and audited.get('rows'):
                cached = {'api': api, 'params': params, 'fields': fields, 'status': 'success',
                          'fetchedAt': timestamp, 'rows': audited['rows'], 'reusedAuditFile': str(audit_file.relative_to(DIAGNOSTICS))}
                write_json(cache_file, cached)
                self.calls.append({'api': api, 'label': label, 'audited': True, 'rows': len(cached['rows'])})
                return cached['rows']
        if self.offline:
            raise APIError('Offline cache missing: ' + label)
        if self.as_of != datetime.now().strftime('%Y%m%d'):
            raise APIError('Live fetch cannot be labelled as a different membership date: ' + label)
        if not self.token:
            raise APIError('TUSHARE_TOKEN environment variable is required')
        payload = json.dumps({'api_name': api, 'token': self.token, 'params': params, 'fields': fields}).encode('utf-8')
        for attempt in range(4):
            # All worker starts share one gate: at most 143 requests/minute.
            with self.lock:
                delay = max(0, 0.43 - (time.monotonic() - self.last))
                if delay:
                    time.sleep(delay)
                self.last = time.monotonic()
            try:
                req = request.Request(API, data=payload, headers={'Content-Type': 'application/json'})
                with request.urlopen(req, timeout=45) as response:
                    result = json.loads(response.read().decode('utf-8'))
            except Exception as exc:
                if attempt == 3:
                    raise APIError(f'{api}: transport failure ({type(exc).__name__})') from None
                time.sleep(2 ** attempt)
                continue
            if result.get('code') != 0:
                message = str(result.get('msg') or '').replace(self.token, '[redacted]')
                if any(x in message.lower() for x in ['每分钟', '频繁', '最多访问', 'limit']) and attempt < 3:
                    time.sleep(10 + attempt * 10)
                    continue
                failure = {'api': api, 'params': params, 'fetchedAt': now(), 'status': 'failed',
                           'code': result.get('code'), 'message': message}
                write_json(self.cache / (label + '.failure.json'), failure)
                raise APIError(f'{api}: code {result.get("code")}; {message}')
            data = result.get('data') or {}
            keys, items = data.get('fields'), data.get('items')
            if not isinstance(keys, list) or not isinstance(items, list):
                raise APIError('Malformed response: ' + api)
            rows = [dict(zip(keys, row)) for row in items]
            if required and not rows:
                raise APIError('Required response is empty: ' + label)
            write_json(cache_file, {'api': api, 'params': params, 'fields': fields,
                                   'fetchedAt': now(), 'status': 'success', 'rows': rows})
            self.calls.append({'api': api, 'label': label, 'cached': False, 'rows': len(rows)})
            return rows
        raise APIError('Retries exhausted: ' + api)


def fetch_members(client, board):
    code = board['ts_code']
    rows = client.call('ths_member', {'ts_code': code}, 'ts_code,con_code,con_name,is_new,in_date,out_date',
                       'ths_member-' + code, required=bool(number(board.get('count'))),
                       audit_file=AUDIT_RAW / ('ths_member-' + code + '.json'))
    if len(rows) >= 5000:
        raise APIError('Potential truncated membership: ' + code)
    if any(r.get('ts_code') not in (None, code) for r in rows):
        raise APIError('Membership board mismatch: ' + code)
    current = {r['con_code']: r for r in rows if r.get('con_code') and r.get('is_new') != 'N'}
    if not current and number(board.get('count')):
        raise APIError('No current members: ' + code)
    return code, current


def select_catalog(catalog, kind):
    """Retain all concepts; explicitly scope industries to the native index series.

    The API exposes N/I, not parent links or a standardized numbered hierarchy.
    881/884 identify the displayed industry/subindustry series only. Never infer
    a parent from shared stocks, and never mix the 700-series into that taxonomy.
    """
    if not catalog or len(catalog) >= 5000:
        raise APIError('Empty or potentially truncated catalog: ' + kind)
    if any(not r.get('ts_code') or not r.get('name') or r.get('type') != kind
           or r.get('exchange') != 'A' for r in catalog):
        raise APIError('Unexpected classification catalog row: ' + kind)
    if len({r['ts_code'] for r in catalog}) != len(catalog):
        raise APIError('Duplicate classification codes: ' + kind)
    selected, excluded = [], []
    for row in sorted(catalog, key=lambda r: r['ts_code']):
        if kind == 'N':
            selected.append({**row, 'level': 'concept'})
        elif row['ts_code'][:3] in INDUSTRY_LEVELS:
            selected.append({**row, 'level': INDUSTRY_LEVELS[row['ts_code'][:3]]})
        else:
            excluded.append({'code': row['ts_code'], 'name': row['name'],
                             'reason': 'Outside the native 881/884 industry series; not merged into a claimed taxonomy.'})
    if kind == 'N' and len({r['name'] for r in selected}) != len(selected):
        raise APIError('Duplicate concept names; schema requires unique name keys')
    return selected, {'source': CLASSIFICATION_SOURCE, 'api': 'ths_index',
                      'query': {'exchange': 'A', 'type': kind}, 'sourceCount': len(catalog),
                      'includedCount': len(selected), 'excludedCount': len(excluded),
                      'sourcePrefixes': dict(sorted(Counter(r['ts_code'][:3] for r in catalog).items())),
                      'includedPrefixes': dict(sorted(Counter(r['ts_code'][:3] for r in selected).items())),
                      'excluded': excluded, 'minimumMemberCount': None,
                      'excludedNameFragments': [], 'hierarchyVerified': False}


def classification_row(board, members, stocks, board_quotes, as_of):
    code = board['ts_code']
    codes = sorted(members[code])
    quoted = [stocks[c] for c in codes if stocks[c]['amount'] is not None]
    weighted = [s for s in quoted if s['pct'] is not None and s['amount'] > 0]
    mv_rows = [stocks[c] for c in codes if stocks[c]['mv'] is not None]
    denominator = sum(s['amount'] for s in weighted)
    return {
        'code': code, 'name': board['name'], 'level': board['level'], 'members': codes,
        'pct': number(board_quotes.get(code, {}).get('pct_change')),
        'weightedPct': sum(s['amount'] * s['pct'] for s in weighted) / denominator if denominator else None,
        'amount': sum(s['amount'] for s in quoted) if quoted else None,
        'mv': sum(s['mv'] for s in mv_rows) if mv_rows else None,
        'count': len(codes), 'quotedCount': len(quoted), 'mvCount': len(mv_rows), 'catalogCount': board.get('count'),
        'source': CLASSIFICATION_SOURCE, 'membershipAsOf': as_of,
        'membershipStatus': 'available' if codes else 'empty_source',
        'provenance': {'catalogApi': 'ths_index', 'membershipApi': 'ths_member', 'catalogType': board['type'],
                       'catalogCode': code, 'exchange': board['exchange'], 'hierarchyVerified': False,
                       'levelBasis': 'source concept type N' if board['type'] == 'N' else 'native index code series ' + code[:3],
                       'sourceUrl': DOCS['ths_index'], 'membershipUrl': DOCS['ths_member']},
    }


def validate_classifications(evidence):
    """Fail before committing a snapshot if a membership is dropped or one-sided."""
    stocks, boards, industries = evidence['stocks'], evidence['boards'], evidence['industries']
    expected_concepts, expected_industries = defaultdict(set), defaultdict(set)
    for name, board in boards.items():
        if name != board['name'] or board['count'] != len(set(board['members'])):
            raise APIError('Invalid concept membership: ' + name)
        for code in board['members']:
            if code not in stocks:
                raise APIError('Member stock missing: ' + code)
            expected_concepts[code].add(name)
    for index, board in industries.items():
        if index != board['code'] or board['level'] != INDUSTRY_LEVELS.get(index[:3]):
            raise APIError('Invalid industry code or level: ' + index)
        if board['count'] != len(set(board['members'])):
            raise APIError('Duplicate industry members: ' + index)
        for code in board['members']:
            if code not in stocks:
                raise APIError('Member stock missing: ' + code)
            expected_industries[code].add(index)
    for code, stock in stocks.items():
        if set(stock['concepts']) != expected_concepts[code]:
            raise APIError('Concept reverse membership mismatch: ' + code)
        refs = stock['thsIndustries']
        if len(refs) != len({r['code'] for r in refs}) or {r['code'] for r in refs} != expected_industries[code]:
            raise APIError('Industry reverse membership mismatch: ' + code)
        if any(r['name'] != industries[r['code']]['name'] or r['level'] != industries[r['code']]['level'] for r in refs):
            raise APIError('Industry reverse label mismatch: ' + code)
    coverage = evidence['catalogCoverage']
    for kind, count in (('concepts', len(boards)), ('industries', len(industries))):
        row = coverage[kind]
        if row['includedCount'] != count or row['includedCount'] + row['excludedCount'] != row['sourceCount']:
            raise APIError('Catalog source count mismatch: ' + kind)
    if coverage['concepts']['excludedCount']:
        raise APIError('Concept catalog cannot silently exclude entries')


def fetch_financials(client, period, cutoff, warnings):
    fields = 'ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,revenue,total_revenue,n_income_attr_p,update_flag'
    rows, offset, fingerprints = [], 0, set()
    try:
        while True:
            params = {'period': period, 'report_type': '1', 'limit': 3000, 'offset': offset}
            page = client.call('income_vip', params, fields, f'income_vip-{period}-{offset}', required=False)
            signature = hashlib.sha256(json.dumps(page, sort_keys=True).encode()).hexdigest()
            if page and signature in fingerprints:
                raise APIError('income_vip pagination repeated a page')
            fingerprints.add(signature)
            rows.extend(page)
            print(f'Financial rows: {len(rows)}', flush=True)
            if len(page) < 3000:
                break
            offset += len(page)
    except APIError as exc:
        warnings.append({'dataset': 'income_vip', 'status': 'unavailable', 'reason': str(exc),
                         'fallback': 'No cross-sectional substitute accepted; financial fields remain null.'})
        return {}, {'status': 'unavailable', 'reason': str(exc), 'period': period, 'asOf': cutoff}
    eligible, excluded = defaultdict(list), defaultdict(int)
    for row in rows:
        dates = [str(row[x]) for x in ('ann_date', 'f_ann_date') if row.get(x)]
        published = max(dates) if dates else ''
        if str(row.get('end_date')) != period or str(row.get('report_type')) not in ('1', '1.0'):
            excluded['wrongPeriodOrReportType'] += 1
        elif not re.fullmatch(r'\d{8}', published) or published > cutoff:
            excluded['missingOrFutureAnnouncement'] += 1
        elif row.get('ts_code'):
            row['_published'] = published
            eligible[row['ts_code']].append(row)
    selected = {}
    for code, options in eligible.items():
        # Latest announcement wins; API update flag resolves same-date corrected copies.
        options.sort(key=lambda r: (r['_published'], str(r.get('update_flag') or ''), json.dumps(r, sort_keys=True)))
        selected[code] = options[-1]
    return selected, {'status': 'available' if selected else 'empty', 'period': period, 'asOf': cutoff,
                      'rawRows': len(rows), 'uniqueReports': len(selected),
                      'duplicateRowsRemoved': sum(len(v) - 1 for v in eligible.values()), 'excluded': dict(excluded)}


def build(args):
    client = Client(args.membership_as_of, args.offline)
    warnings = []
    daily = client.call('daily', {'trade_date': args.trade_date}, 'ts_code,trade_date,close,pct_chg,amount',
                        'daily-' + args.trade_date, audit_file=AUDIT_RAW / ('daily-' + args.trade_date + '.json'))
    daily_basic = client.call('daily_basic', {'trade_date': args.trade_date}, 'ts_code,trade_date,total_mv,turnover_rate',
                              'daily_basic-' + args.trade_date, audit_file=AUDIT_RAW / ('daily_basic-' + args.trade_date + '.json'))
    ths_daily = client.call('ths_daily', {'trade_date': args.trade_date}, 'ts_code,trade_date,pct_change,total_mv',
                            'ths_daily-' + args.trade_date, audit_file=AUDIT_RAW / ('ths_daily-' + args.trade_date + '.json'))
    for dataset in (daily, daily_basic, ths_daily):
        if any(r.get('trade_date') != args.trade_date for r in dataset):
            raise APIError('Mixed quote dates')
    audit = DIAGNOSTICS / ('classification-audit-' + args.membership_as_of)
    catalog = client.call('ths_index', {'exchange': 'A', 'type': 'N'}, CATALOG_FIELDS,
                          'ths_index-catalog-N', audit_file=audit / 'catalog-N.json')
    industry_catalog = client.call('ths_index', {'exchange': 'A', 'type': 'I'}, CATALOG_FIELDS,
                                   'ths_index-catalog-I', audit_file=audit / 'catalog-I.json')
    boards, concept_coverage = select_catalog(catalog, 'N')
    industry_boards, industry_coverage = select_catalog(industry_catalog, 'I')
    classifications = boards + industry_boards
    print(f'All concepts: {len(boards)}; industries/subindustries: {len(industry_boards)}; quote date: {args.trade_date}', flush=True)
    members = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch_members, client, b) for b in classifications]
        for future in as_completed(futures):
            code, rows = future.result()
            members[code] = rows
            if len(members) % 25 == 0 or len(members) == len(classifications):
                print(f'Complete memberships: {len(members)}/{len(classifications)}', flush=True)
    basic_rows = []
    for exchange in ('SSE', 'SZSE', 'BSE'):
        rows = client.call('stock_basic', {'exchange': exchange, 'list_status': 'L'},
                           'ts_code,name,industry,market,exchange,list_status,list_date', 'stock_basic-' + exchange)
        if len(rows) >= 6000:
            raise APIError('Potential stock_basic truncation: ' + exchange)
        basic_rows.extend(rows)
    basic = {r['ts_code']: r for r in basic_rows}
    listing_rows, listing_status = dict(basic), {'L': {'status': 'available', 'rows': len(basic)}}
    for status in ('D', 'P'):
        try:
            rows = client.call('stock_basic', {'list_status': status},
                               'ts_code,name,industry,market,exchange,list_status,list_date',
                               'stock_basic-status-' + status, required=False)
            if len(rows) >= 6000 or any(r.get('list_status') != status for r in rows):
                raise APIError('Invalid stock_basic listing-status response: ' + status)
            # Supplement status evidence only; never expand the visible universe
            # with every historical security or replace current listed records.
            for row in rows:
                listing_rows.setdefault(row['ts_code'], row)
            listing_status[status] = {'status': 'available', 'rows': len(rows)}
        except APIError as exc:
            listing_status[status] = {'status': 'unavailable', 'reason': str(exc)}
            warnings.append({'dataset': 'stock_basic', 'listStatus': status, 'status': 'unavailable', 'reason': str(exc)})
    companies, company_status = {}, {}
    for exchange in ('SSE', 'SZSE', 'BSE'):
        try:
            rows = client.call('stock_company', {'exchange': exchange},
                               'ts_code,com_name,exchange,main_business,business_scope,introduction', 'stock_company-' + exchange)
            if len(rows) >= 4500:
                raise APIError('Potential stock_company truncation: ' + exchange)
            companies.update({r['ts_code']: r for r in rows})
            company_status[exchange] = {'status': 'available', 'rows': len(rows)}
        except APIError as exc:
            company_status[exchange] = {'status': 'unavailable', 'reason': str(exc)}
            warnings.append({'dataset': 'stock_company', 'exchange': exchange, 'status': 'unavailable', 'reason': str(exc)})
    financials, financial_status = fetch_financials(client, args.financial_period, args.trade_date, warnings)
    quotes = {r['ts_code']: r for r in daily}
    metrics = {r['ts_code']: r for r in daily_basic}
    board_quotes = {r['ts_code']: r for r in ths_daily}
    all_members = {c: r for group in members.values() for c, r in group.items()}
    concepts = defaultdict(list)
    for board in boards:
        for code in members[board['ts_code']]:
            concepts[code].append(board['name'])
    ths_industries = defaultdict(list)
    for board in industry_boards:
        for code in members[board['ts_code']]:
            ths_industries[code].append({'code': board['ts_code'], 'name': board['name'], 'level': board['level']})
    stocks = {}
    for code in sorted(set(all_members) | set(basic) | set(quotes)):
        base, q, m, company, fin = basic.get(code, {}), quotes.get(code, {}), metrics.get(code, {}), companies.get(code, {}), financials.get(code, {})
        revenue_field = 'total_revenue' if number(fin.get('total_revenue')) is not None else 'revenue'
        revenue = number(fin.get(revenue_field), 1e8)
        stock_name = base.get('name') or all_members.get(code, {}).get('con_name') or code
        stocks[code] = {
            'code': code, 'name': stock_name, 'pct': number(q.get('pct_chg')), 'amount': number(q.get('amount'), 1e5),
            'mv': number(m.get('total_mv'), 1e4), 'turnover': number(m.get('turnover_rate')), 'industry': base.get('industry') or None,
            'concepts': sorted(concepts[code]), 'thsIndustries': sorted(ths_industries[code], key=lambda r: r['code']),
            'thsIndustryAsOf': args.membership_as_of, 'return5': None, 'amount5': None, 'limitStreak': None,
            'revenue': revenue, 'profit': number(fin.get('n_income_attr_p'), 1e8),
            'reportPeriod': fin.get('end_date') or None, 'reportAnnDate': fin.get('_published') or None,
            'revenueField': revenue_field if revenue is not None else None, 'revenueRank': None, 'industryPeerCount': 0,
            'mainBusiness': company.get('main_business') or None, 'businessScope': company.get('business_scope') or None,
            'industryPositionVerified': False, 'mainBusinessConceptMatchVerified': False,
            'isST': 'ST' in stock_name.upper(), 'listStatus': listing_rows.get(code, {}).get('list_status') or None,
            'listingStatusAsOf': args.membership_as_of,
            'listingStatusSource': 'Tushare Pro stock_basic list_status=L/D/P',
            'listingStatusNote': None if code in listing_rows else 'No matching stock_basic L/D/P status; source membership retained, current listing unconfirmed.',
            'isFinancial': str(fin.get('comp_type')) in ('2', '3', '4', '7') or base.get('industry') in ('银行', '证券', '保险', '多元金融'),
            'profileAsOf': args.membership_as_of, 'industryAsOf': args.membership_as_of,
        }
    peers = defaultdict(list)
    for stock in stocks.values():
        if stock['industry'] and stock['revenue'] is not None and stock['revenue'] > 0 and stock['listStatus'] == 'L':
            peers[stock['industry']].append(stock)
    for industry, group in peers.items():
        group.sort(key=lambda s: (-s['revenue'], s['code']))
        previous_revenue, rank = None, 0
        for index, stock in enumerate(group):
            if stock['revenue'] != previous_revenue:
                rank = index + 1
            previous_revenue = stock['revenue']
            stock['revenueRank'] = rank
        for stock in stocks.values():
            if stock['industry'] == industry:
                stock['industryPeerCount'] = len(group)
    board_data, industry_data, catalog_mismatches = {}, {}, []
    for board in classifications:
        code = board['ts_code']
        codes = sorted(members[code])
        target = board_data if board['type'] == 'N' else industry_data
        key = board['name'] if board['type'] == 'N' else code
        target[key] = classification_row(board, members, stocks, board_quotes, args.membership_as_of)
        if len(codes) != board.get('count'):
            catalog_mismatches.append({'code': code, 'name': board['name'], 'catalogCount': board.get('count'), 'memberCount': len(codes)})
    for coverage, kind in ((concept_coverage, 'N'), (industry_coverage, 'I')):
        selected_codes = {b['ts_code'] for b in classifications if b['type'] == kind}
        coverage['catalogCountDifferences'] = [r for r in catalog_mismatches if r['code'] in selected_codes]
        coverage['membershipAsOf'] = args.membership_as_of
    evidence = {
        'schemaVersion': 2, 'status': 'partial_optional' if warnings else 'complete',
        'tradeDate': args.trade_date, 'membershipAsOf': args.membership_as_of,
        'financialPeriod': args.financial_period, 'financialAsOf': args.trade_date, 'generatedAt': now(),
        'boards': board_data, 'industries': industry_data, 'stocks': stocks,
        'industrySource': CLASSIFICATION_SOURCE, 'industryMembershipAsOf': args.membership_as_of,
        'catalogCoverage': {'concepts': concept_coverage, 'industries': industry_coverage},
        'source': {'provider': 'Tushare Pro', 'endpoint': API, 'docs': DOCS, 'cacheDirectory': client.cache.name},
        'coverage': {'boardCount': len(board_data), 'industryCount': len(industry_data),
                     'industryLevelCount': sum(b['level'] == 'industry' for b in industry_boards),
                     'subindustryLevelCount': sum(b['level'] == 'subindustry' for b in industry_boards),
                     'stockCount': len(stocks), 'membershipCount': sum(len(members[b['ts_code']]) for b in boards),
                     'industryMembershipCount': sum(len(members[b['ts_code']]) for b in industry_boards),
                     'quotedStocks': len(quotes), 'listedStocks': len(basic), 'companyProfiles': len(companies),
                     'delistedMemberStocks': sum(s['listStatus'] == 'D' for s in stocks.values()),
                     'suspendedMemberStocks': sum(s['listStatus'] == 'P' for s in stocks.values()),
                     'unconfirmedListingStocks': sum(s['listStatus'] is None for s in stocks.values()),
                     'stocksWithRevenue': sum(s['revenue'] is not None for s in stocks.values()),
                     'stocksWithMainBusiness': sum(s['mainBusiness'] is not None for s in stocks.values())},
        'financialStatus': financial_status, 'companyStatus': company_status, 'listingStatus': listing_status, 'warnings': warnings,
        'method': {
            'membership': 'All A-market ths_index type=N catalog entries, without prefix, member-count, or name exclusions. All returned current members are retained, including stocks without quotes. Current membership, not a historical reconstruction.',
            'excludedNameFragments': [],
            'industryMembership': 'A-market ths_index type=I native 881 industry and 884 subindustry series, with all returned current ths_member constituents. Other type=I series remain explicitly excluded. Levels are independent source-code series, not a reconstructed numbered industry tree; no authoritative parent links are available from these endpoints.',
            'industryLevelLabels': {'industry': '同花顺行业（881 系列）', 'subindustry': '同花顺细分行业（884 系列）'},
            'industryParentLinks': {'status': 'unavailable', 'inferredFromOverlap': False},
            'legacyStockIndustry': 'stocks.industry and revenueRank retain stock_basic.industry as a separate legacy comparison basis; they are not the THS classification displayed in thsIndustries.',
            'listingStatus': 'stock_basic L/D/P lists are checked separately. Source members are retained regardless of current listing status; null means unconfirmed, not currently listed. D/P lookups supplement status only and do not expand the stock universe.',
            'candidateLabel': '经营规模候选', 'candidateOrder': 'Full concept members with positive same-period company-wide revenue and known industry; revenue descending, stock code ascending; maximum five. Default excludes financial company types 2/3/4/7 and industries 银行/证券/保险/多元金融; explicit industry filter allows comparisons within that industry. Negative profits and ST names are retained.',
            'revenue': 'total_revenue (营业总收入) when present, otherwise revenue (营业收入); CNY yuan / 100000000. Company-wide cumulative consolidated half-year data, not revenue attributable to the selected concept.',
            'reportSelection': 'income_vip report_type=1; matching period; max(ann_date,f_ann_date) <= quote date; latest announcement then update_flag; stable serialization tie-break.',
            'industryRank': 'Competition rank by positive same-period revenue within stock_basic industry, among currently listed stocks with available valid reports. Ties share rank; missing reports excluded. Not a market-share or industry-position ranking.',
            'industryComparison': 'Different industries are not comparable for industry leadership. Revenue is a scale observation only; industry position and concept-to-main-business fit remain unverified.',
            'stockEdges': 'Undirected union of each visible stock choosing its top two neighbors by shared concept count (minimum three), ties by code. Jaccard percentage = intersection / union * 100. Concept scope is the complete type=N catalog, not the drill subset.',
            'boardPct': 'pct is official THS index daily pct_change; weightedPct is current-member amount-weighted daily pct_chg. They are distinct measures.',
            'units': {'amount': '亿元 (daily amount 千元 / 100000)', 'mv': '亿元 (daily_basic total_mv 万元 / 10000)', 'revenue': '亿元', 'profit': '亿元', 'pct': '%', 'turnover': '%'},
            'unfetchedFields': ['return5', 'amount5', 'limitStreak'],
            'unfetchedReason': 'This release prioritizes company business evidence; five-session and limit-up rankings were not requested for production.',
            'profileLimitation': 'Company profiles, industry classification and concept membership are the latest fetch snapshot. Announcement cutoff controls report selection but is not an immutable historical database guarantee.',
        },
    }
    assert len(members) == len(classifications)
    validate_classifications(evidence)
    assert all(s['reportAnnDate'] is None or s['reportAnnDate'] <= args.trade_date for s in stocks.values())
    assert all(not s['industryPositionVerified'] for s in stocks.values())
    serialized = json.dumps(evidence, ensure_ascii=False, allow_nan=False)
    if client.token and client.token in serialized:
        raise APIError('Credential detected in output; refusing write')
    output = ROOT / 'src' / 'lib' / 'evidence-data.json'
    write_json(output, evidence)
    report = {'status': evidence['status'], 'generatedAt': evidence['generatedAt'], 'tradeDate': args.trade_date,
              'membershipAsOf': args.membership_as_of, 'coverage': evidence['coverage'],
              'catalogCoverage': evidence['catalogCoverage'],
              'financialStatus': financial_status, 'companyStatus': company_status, 'listingStatus': listing_status, 'warnings': warnings,
              'catalogCountDifferences': catalog_mismatches, 'calls': sorted(client.calls, key=lambda x: x['label']),
              'outputBytes': output.stat().st_size, 'outputSha256': hashlib.sha256(output.read_bytes()).hexdigest()}
    write_json(DIAGNOSTICS / 'evidence-build-report.json', report)
    print(json.dumps({'status': evidence['status'], 'coverage': evidence['coverage'], 'financialStatus': financial_status,
                      'outputBytes': report['outputBytes']}, ensure_ascii=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trade-date', help='Defaults to the tradeDate in the current evidence snapshot (legacy stardata.js fallback)')
    parser.add_argument('--membership-as-of', default=datetime.now().strftime('%Y%m%d'))
    parser.add_argument('--financial-period', '--period', dest='financial_period', help='Defaults to the latest report period after its regular disclosure deadline')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    if not args.trade_date:
        current = ROOT / 'src' / 'lib' / 'evidence-data.json'
        if current.exists():
            args.trade_date = json.loads(current.read_text(encoding='utf-8')).get('tradeDate')
        if not args.trade_date:
            snapshot_header = (ROOT / 'src' / 'lib' / 'stardata.js').read_text(encoding='utf-8')[:4096]
            match = re.search(r'"tradeDate"\s*:\s*"(\d{8})"', snapshot_header)
            if not match:
                parser.error('Current evidence/stardata has no tradeDate; pass --trade-date explicitly')
            args.trade_date = match.group(1)
    if not args.financial_period:
        year, month_day = int(args.trade_date[:4]), args.trade_date[4:]
        if month_day >= '1031':
            args.financial_period = f'{year}0930'
        elif month_day >= '0831':
            args.financial_period = f'{year}0630'
        elif month_day >= '0430':
            args.financial_period = f'{year}0331'
        else:
            args.financial_period = f'{year - 1}0930'
    for value in (args.trade_date, args.membership_as_of, args.financial_period):
        datetime.strptime(value, '%Y%m%d')
    try:
        build(args)
    except Exception as exc:
        failure = {'status': 'failed', 'failedAt': now(), 'type': type(exc).__name__, 'reason': str(exc),
                   'tradeDate': args.trade_date, 'membershipAsOf': args.membership_as_of,
                   'outputReplaced': False}
        token = os.environ.get('TUSHARE_TOKEN')
        if token:
            failure['reason'] = failure['reason'].replace(token, '[redacted]')
        write_json(DIAGNOSTICS / 'evidence-build-failure.json', failure)
        print(json.dumps(failure, ensure_ascii=True), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
