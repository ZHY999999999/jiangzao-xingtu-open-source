"""Collect the complete SW2021 hierarchy with official parent and member codes.

python scripts/build-industry-relations.py --as-of 2026-09-22
Use --offline to rebuild from the dated cache. The previous snapshot is kept if
a required collection or validation fails. THS catalogs are never remapped into
SW: matching names, F10 text and member overlap do not establish taxonomy identity.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('enrich_evidence', Path(__file__).with_name('enrich-evidence.py'))
SHARED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SHARED)
LEVELS = {'L1': 'sector', 'L2': 'industry', 'L3': 'subindustry'}
CATALOG_FIELDS = 'index_code,industry_name,level,industry_code,is_pub,parent_code,src'
MEMBER_FIELDS = 'l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,ts_code,name,in_date,out_date,is_new'
CLASSIFY_DOC = 'https://tushare.pro/document/2?doc_id=181'
MEMBER_DOC = 'https://tushare.pro/document/2?doc_id=335'
LISTING_DOC = 'https://tushare.pro/document/2?doc_id=25'
SOURCE = '申万2021 · Tushare Pro index_classify/index_member_all'


def load_cached_listing(cache, as_of):
    """Require complete, same-date L/D/P evidence; never infer status from names."""
    requests = [('stock_basic-' + exchange, {'exchange': exchange, 'list_status': 'L'})
                for exchange in ('SSE', 'SZSE', 'BSE')]
    requests += [('stock_basic-status-' + status, {'list_status': status}) for status in ('D', 'P')]
    by_code, sources = {}, []
    for label, params in requests:
        path = cache / (label + '.json')
        if not path.exists():
            raise SHARED.APIError('Required listing cache missing: ' + label)
        cached = json.loads(path.read_text(encoding='utf-8'))
        if (cached.get('api') != 'stock_basic' or cached.get('params') != params
                or cached.get('status') != 'success'
                or (cached.get('fetchedAt') or '')[:10].replace('-', '') != as_of.replace('-', '')):
            raise SHARED.APIError('Invalid or stale listing cache: ' + label)
        rows = cached.get('rows')
        if not isinstance(rows, list) or len(rows) >= 6000 or (params['list_status'] == 'L' and not rows):
            raise SHARED.APIError('Empty, malformed or potentially truncated listing cache: ' + label)
        for row in rows:
            code = row.get('ts_code')
            if not code or row.get('list_status') != params['list_status']:
                raise SHARED.APIError('Unexpected listing status row: ' + label)
            if code in by_code and by_code[code]['list_status'] != row['list_status']:
                raise SHARED.APIError('Conflicting listing statuses: ' + code)
            by_code[code] = {**row, 'cacheFile': path.name, 'fetchedAt': cached['fetchedAt']}
        sources.append({'cacheFile': path.name, 'params': params, 'fetchedAt': cached['fetchedAt'], 'rowCount': len(rows)})
    return by_code, sources


def validate_catalog(rows):
    if not rows or len(rows) >= 5000:
        raise SHARED.APIError('Empty or potentially truncated SW catalog')
    by_industry, by_index = {}, {}
    for row in rows:
        if row.get('src') != 'SW2021' or row.get('level') not in LEVELS or not row.get('industry_name'):
            raise SHARED.APIError('Unexpected SW classification row')
        if row.get('index_code') in by_index or row.get('industry_code') in by_industry:
            raise SHARED.APIError('Duplicate SW classification code')
        if not row.get('index_code') or not row.get('industry_code'):
            raise SHARED.APIError('Missing SW classification code')
        by_industry[row['industry_code']], by_index[row['index_code']] = row, row
    for row in rows:
        if row['level'] == 'L1':
            if str(row.get('parent_code')) != '0':
                raise SHARED.APIError('SW root has a parent')
            continue
        parent = by_industry.get(row.get('parent_code'))
        expected = 'L1' if row['level'] == 'L2' else 'L2'
        if not parent or parent['level'] != expected:
            raise SHARED.APIError('Missing or invalid official SW parent: ' + row['index_code'])
    return by_industry, by_index


def fetch_group(client, row, required=True):
    field = {'L1': 'l1_code', 'L2': 'l2_code', 'L3': 'l3_code'}[row['level']]
    code = row['index_code']
    rows = client.call('index_member_all', {field: code, 'is_new': 'Y'}, MEMBER_FIELDS,
                       'index_member_all-' + code + '-Y', required=required)
    if any(r.get(field) != code for r in rows):
        raise SHARED.APIError('SW membership group mismatch: ' + code)
    return rows


def collect_sector(client, sector, catalog):
    rows = fetch_group(client, sector)
    if len(rows) < 2000:
        return rows
    # The endpoint has a documented 2,000-row response ceiling. Subdivide by the
    # authoritative child codes rather than assuming undocumented pagination.
    children = [r for r in catalog if r['parent_code'] == sector['industry_code']]
    if not children:
        raise SHARED.APIError('Truncated SW sector without catalog children')
    full = []
    for child in children:
        child_rows = fetch_group(client, child, required=False)
        if len(child_rows) >= 2000:
            leaves = [r for r in catalog if r['parent_code'] == child['industry_code']]
            if not leaves:
                raise SHARED.APIError('Truncated SW industry without catalog children')
            child_rows = []
            for leaf in leaves:
                page = fetch_group(client, leaf, required=False)
                if len(page) >= 2000:
                    raise SHARED.APIError('Potential truncated SW leaf: ' + leaf['index_code'])
                child_rows.extend(page)
        full.extend(child_rows)
    return full


def build(catalog, member_rows, evidence, as_of, cache_name, listing_rows=None, listing_sources=None):
    by_industry, by_index = validate_catalog(catalog)
    members, stock_names, paths = defaultdict(set), {}, defaultdict(set)
    excluded, duplicates, name_mismatches, path_gaps, seen = [], 0, [], [], set()
    for row in member_rows:
        if row.get('is_new') != 'Y':
            excluded.append({'code': row.get('ts_code'), 'reason': 'source_not_current', 'is_new': row.get('is_new')})
            continue
        stock = row.get('ts_code')
        indexes = [row.get('l1_code'), row.get('l2_code'), row.get('l3_code')]
        if not stock or indexes[0] not in by_index:
            raise SHARED.APIError('Unknown SW member path: ' + str(stock))
        valid_indexes = []
        for level, index in enumerate(indexes, 1):
            if index not in by_index:
                path_gaps.append({'code': stock, 'name': row.get('name') or stock,
                                  'reason': 'membership_index_missing_from_catalog', 'sourceLevel': 'L' + str(level),
                                  'sourceIndexCode': index, 'sourceIndustryName': row.get('l' + str(level) + '_name'),
                                  'preservedAncestorCodes': list(valid_indexes), 'sourcePath': indexes})
                break
            current = by_index[index]
            if current['level'] != 'L' + str(level):
                raise SHARED.APIError('SW member level mismatch: ' + stock)
            if level > 1 and current['parent_code'] != by_index[indexes[level - 2]]['industry_code']:
                raise SHARED.APIError('SW member path contradicts official parent: ' + stock)
            if row.get('l' + str(level) + '_name') != current['industry_name']:
                name_mismatches.append({'stockCode': stock, 'indexCode': index,
                                        'catalogName': current['industry_name'], 'memberName': row.get('l' + str(level) + '_name')})
            valid_indexes.append(index)
        signature = (stock, *indexes)
        if signature in seen:
            duplicates += 1
        seen.add(signature)
        paths[stock].add(tuple(valid_indexes))
        stock_names[stock] = row.get('name') or stock
        for index in valid_indexes:
            members[index].add(stock)
    boards, relations = [], []
    for row in sorted(catalog, key=lambda r: r['industry_code']):
        code = row['index_code']
        parent = by_industry.get(row['parent_code'])
        stock_codes = sorted(members[code])
        source_ref = {'url': CLASSIFY_DOC, 'title': 'Tushare Pro 申万行业分类（SW2021）',
                      'locator': 'index_classify src=SW2021; index_code=' + code,
                      'excerpt': f"index_code={code}; industry_code={row['industry_code']}; industry_name={row['industry_name']}; level={row['level']}; parent_code={row['parent_code']}; src=SW2021"}
        boards.append({'code': code, 'name': row['industry_name'], 'level': LEVELS[row['level']],
                       'system': 'sw2021', 'industryCode': row['industry_code'], 'sourceLevel': row['level'],
                       'parentCode': parent['index_code'] if parent else None, 'parentIndustryCode': row['parent_code'],
                       'members': stock_codes, 'count': len(stock_codes), 'source': SOURCE,
                       'membershipAsOf': as_of.replace('-', ''), 'classificationAsOf': as_of,
                       'membershipStatus': 'available' if stock_codes else 'empty_source',
                       'isPublishedIndex': str(row.get('is_pub')) == '1', 'sourceRefs': [source_ref,
                        {'url': MEMBER_DOC, 'title': 'Tushare Pro 申万行业成分（分级）',
                         'locator': 'index_member_all is_new=Y', 'excerpt': 'Current memberships collected by all official L1 index codes; every L1/L2/L3 path validated against index_classify parent_code.'}]})
        # A same-name conflicting source record is a warning, never a code alias.
        # Match its already-verified parent only to locate the affected catalog UI.
        conflicts = [gap for gap in path_gaps
                     if gap['sourceLevel'] == row['level'] and gap['sourceIndustryName'] == row['industry_name']
                     and parent and gap['preservedAncestorCodes'][-1:] == [parent['index_code']]]
        if conflicts:
            conflict_codes = sorted({str(gap['sourceIndexCode']) for gap in conflicts})
            boards[-1]['membershipWarning'] = (f"分类目录代码为 {code}；成员接口的同名记录使用未收录代码 "
                + '、'.join(conflict_codes) + f"（{len(conflicts)} 条）。代码冲突尚未解决，未将这些成员映射到本板块；"
                + f"当前已验证成员 {len(stock_codes)} 只。")
            boards[-1]['membershipWarningDetails'] = {'reason': 'unresolved_source_code_conflict',
                'catalogCode': code, 'conflictingSourceCodes': conflict_codes, 'affectedRows': len(conflicts),
                'inferredAlias': False, 'sourceRefs': [source_ref, {'url': MEMBER_DOC,
                'title': 'Tushare Pro 申万行业成分代码冲突', 'locator': 'index_member_all is_new=Y',
                'excerpt': 'unresolved source codes=' + ','.join(conflict_codes) + '; no members aliased by name'}]}
        if parent:
            relations.append({'id': 'class:sw2021:' + parent['index_code'] + '>' + code, 'type': 'classification',
                              'from': {'system': 'sw2021', 'kind': LEVELS[parent['level']], 'code': parent['index_code']},
                              'to': {'system': 'sw2021', 'kind': LEVELS[row['level']], 'code': code},
                              'statement': f"{row['industry_name']}属于{parent['industry_name']}，依据申万2021官方分类父级代码。",
                              'asOf': as_of, 'verificationStatus': 'verified', 'sourceRefs': [source_ref]})
    stocks = evidence.get('stocks', {})
    listed = {code for code, stock in stocks.items() if stock.get('listStatus') == 'L'}
    covered = set(stock_names)
    listing_rows = listing_rows or {}
    stock_statuses = {}
    for code in sorted(covered):
        listing = listing_rows.get(code, {})
        stock_statuses[code] = {'listStatus': listing.get('list_status'),
            'listingStatusAsOf': as_of.replace('-', ''),
            'listingStatusSource': 'Tushare Pro stock_basic list_status=L/D/P',
            'listingStatusNote': None if listing else 'No exact code match in the dated stock_basic L/D/P caches; listing status unconfirmed.',
            'sourceRefs': [{'url': LISTING_DOC, 'title': 'Tushare Pro 股票列表',
                            'locator': 'stock_basic ts_code=' + code,
                            'excerpt': 'Exact code match: list_status=' + str(listing.get('list_status'))
                                if listing else 'No exact code match in the complete dated L/D/P responses.'}],
            'cacheFile': listing.get('cacheFile'), 'fetchedAt': listing.get('fetchedAt')}
    status_counts = {status: sum(s['listStatus'] == status for s in stock_statuses.values()) for status in ('L', 'D', 'P')}
    status_counts['null'] = sum(s['listStatus'] is None for s in stock_statuses.values())
    missing_listed = sorted(listed - covered)
    unresolved = [{'code': c, 'name': stocks[c]['name'], 'reason': 'not_returned_by_current_SW_membership_source'} for c in missing_listed]
    unresolved.extend(sorted(path_gaps, key=lambda r: (r['code'], r['sourceLevel'])))
    result = {'schemaVersion': 1, 'system': 'sw2021', 'asOf': as_of, 'generatedAt': SHARED.now(),
              'status': 'complete_with_source_gaps' if unresolved else 'complete',
              'boards': boards, 'relations': relations, 'stockNames': dict(sorted(stock_names.items())),
              'stockStatuses': stock_statuses,
              'source': {'provider': 'Tushare Pro', 'endpoint': SHARED.API, 'catalogApi': 'index_classify',
                         'catalogQuery': {'src': 'SW2021'}, 'membershipApi': 'index_member_all',
                         'membershipQuery': {'is_new': 'Y', 'partition': 'all L1 index codes'},
                         'catalogFields': CATALOG_FIELDS, 'membershipFields': MEMBER_FIELDS,
                         'cacheDirectory': cache_name, 'docs': [CLASSIFY_DOC, MEMBER_DOC, LISTING_DOC],
                         'listingApi': 'stock_basic', 'listingAsOf': as_of,
                         'listingCacheDirectory': 'evidence-raw-' + as_of.replace('-', ''),
                         'listingCacheSources': listing_sources or []},
              'coverage': {'classificationCount': len(boards), 'levelCounts': dict(Counter(b['level'] for b in boards)),
                           'relationCount': len(relations), 'stockCount': len(covered),
                           'rawMemberRows': len(member_rows), 'duplicateMemberRows': duplicates,
                           'boardMembershipCount': sum(len(b['members']) for b in boards),
                           'emptyBoards': [{'code': b['code'], 'name': b['name'], 'level': b['level']} for b in boards if not b['members']],
                           'sourceNameMismatches': name_mismatches, 'excludedMemberships': excluded,
                           'membershipPathGaps': sorted(path_gaps, key=lambda r: (r['code'], r['sourceLevel'])),
                           'multipleCurrentPaths': [{'code': c, 'paths': [list(p) for p in sorted(ps)]} for c, ps in sorted(paths.items()) if len(ps) > 1],
                           'existingEvidenceStockCount': len(stocks), 'membersMissingFromEvidence': sorted(covered - set(stocks)),
                           'stockStatusCounts': status_counts,
                           'unconfirmedListingStocks': sorted(c for c, s in stock_statuses.items() if s['listStatus'] is None),
                           'currentlyListedEvidenceStocks': len(listed), 'coveredCurrentlyListedStocks': len(listed & covered),
                           'uncoveredListedStockCount': len(missing_listed), 'unresolvedCount': len(unresolved),
                           'unresolved': unresolved,
                           'taxonomyBoundary': 'SW2021 parent links use official industry_code/parent_code only. THS 881/884 records are a separate catalog and receive no inferred links.',
                           'membershipLimitation': 'is_new=Y describes latest source classification membership, not the currently listed stock universe. Listing status is checked by exact code against dated stock_basic L/D/P responses; unmatched codes remain null and names never determine status.',
                           'upstreamDownstream': 'Classification links only; supplier, customer and industry-chain relationships are not inferred.'}}
    validate_result(result)
    return result


def validate_result(result):
    by_code = {b['code']: b for b in result['boards']}
    if len(by_code) != len(result['boards']):
        raise SHARED.APIError('Duplicate output board code')
    relation_ids = set()
    for relation in result['relations']:
        if relation['id'] in relation_ids or relation['type'] != 'classification':
            raise SHARED.APIError('Duplicate or unexpected relation')
        relation_ids.add(relation['id'])
        parent, child = by_code[relation['from']['code']], by_code[relation['to']['code']]
        if child['parentCode'] != parent['code'] or not set(child['members']).issubset(parent['members']):
            raise SHARED.APIError('Invalid hierarchy or incomplete ancestor members')
        if not relation['sourceRefs'] or any(r['system'] != 'sw2021' for r in (relation['from'], relation['to'])):
            raise SHARED.APIError('Missing source or mixed taxonomy relationship')
    if len(result['relations']) != sum(b['parentCode'] is not None for b in result['boards']):
        raise SHARED.APIError('Incomplete hierarchy edges')
    if any(c not in result['stockNames'] for b in result['boards'] for c in b['members']):
        raise SHARED.APIError('Unnamed source member')
    if set(result['stockStatuses']) != set(result['stockNames']):
        raise SHARED.APIError('Incomplete member listing-status coverage')
    if any(s['listStatus'] not in ('L', 'D', 'P', None) for s in result['stockStatuses'].values()):
        raise SHARED.APIError('Unexpected member listing status')


def run(args):
    as_of = args.as_of.replace('-', '')
    listing_rows, listing_sources = load_cached_listing(ROOT.parent / 'diagnostics' / ('evidence-raw-' + as_of), args.as_of)
    client = SHARED.Client(as_of, args.offline)
    client.cache = ROOT.parent / 'diagnostics' / ('industry-relations-raw-' + as_of)
    catalog = client.call('index_classify', {'src': 'SW2021'}, CATALOG_FIELDS, 'index_classify-SW2021')
    validate_catalog(catalog)
    sectors = [r for r in catalog if r['level'] == 'L1']
    member_rows = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(collect_sector, client, r, catalog): r for r in sectors}
        for done, future in enumerate(as_completed(futures), 1):
            member_rows.extend(future.result())
            print(f'SW sector memberships: {done}/{len(sectors)}', flush=True)
    evidence = json.loads((ROOT / 'src/lib/evidence-data.json').read_text(encoding='utf-8'))
    result = build(catalog, member_rows, evidence, args.as_of, client.cache.name, listing_rows, listing_sources)
    serialized = json.dumps(result, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    if client.token and client.token in serialized:
        raise SHARED.APIError('Credential found; refusing output')
    output = ROOT / 'src/lib/industry-relations.json'
    SHARED.write_json(output, result)
    print(json.dumps({'status': result['status'], 'classificationCount': len(result['boards']), 'relationCount': len(result['relations']),
                      'stockCount': result['coverage']['stockCount'], 'levelCounts': result['coverage']['levelCounts'],
                      'unresolvedCount': result['coverage']['unresolvedCount'],
                      'stockStatusCounts': result['coverage']['stockStatusCounts'],
                      'outputSha256': hashlib.sha256(output.read_bytes()).hexdigest()}, ensure_ascii=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--as-of', default=date.today().isoformat())
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    datetime.strptime(args.as_of, '%Y-%m-%d')
    try:
        run(args)
    except Exception as exc:
        token = SHARED.os.environ.get('TUSHARE_TOKEN') or ''
        reason = str(exc).replace(token, '[redacted]') if token else str(exc)
        print(json.dumps({'status': 'failed', 'type': type(exc).__name__, 'reason': reason,
                          'outputReplaced': False}, ensure_ascii=True), file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
