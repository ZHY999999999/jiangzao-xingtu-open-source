#!/usr/bin/env python3
"""Check disclosures, validate a complete candidate snapshot, then atomically publish.

The original knowledge vault and handwritten notes are read-only. Credentials only
come from TUSHARE_TOKEN. A failed run never advances the public index or success date.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT.parent / 'diagnostics' / 'company-updates'
PUBLIC = ROOT / 'public' / 'data' / 'companies'
CN = timezone(timedelta(hours=8))
FIELDS = {
    'income': 'ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,update_flag,revenue,total_revenue,n_income_attr_p,n_income,minority_gain,oper_cost,sell_exp,admin_exp,rd_exp,fin_exp',
    'balancesheet': 'ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,update_flag,total_assets,total_liab,total_hldr_eqy_exc_min_int,money_cap,accounts_receiv,inventories,goodwill,contract_liab',
    'cashflow': 'ts_code,ann_date,f_ann_date,end_date,report_type,comp_type,update_flag,n_cashflow_act,n_cashflow_inv_act,n_cash_flows_fnc_act,c_pay_acq_const_fiolta',
}

def read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':')), encoding='utf-8')
    temporary.replace(path)

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()

def client(as_of, run):
    spec = importlib.util.spec_from_file_location('evidence_fetch', ROOT / 'scripts' / 'enrich-evidence.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    instance = module.Client(as_of)
    instance.cache = run / 'api-cache'
    return instance

def pages(api, name, params, fields, page_size=3000):
    offset, seen = 0, set()
    while True:
        query = dict(params, limit=page_size, offset=offset)
        rows = api.call(name, query, fields, name + '-' + fingerprint(query)[:16], required=False)
        digest = fingerprint(rows)
        if rows and digest in seen:
            raise ValueError('Pagination repeated a page: ' + name)
        seen.add(digest)
        yield from rows
        if len(rows) < page_size:
            return
        offset += len(rows)

def validate_universe(stocks, previous):
    codes = [row.get('ts_code') or row.get('code') for row in stocks]
    if len(codes) < 4000 or len(set(codes)) != len(codes) or any(not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',str(code)) for code in codes):
        raise ValueError('Listed A-share catalogue failed coverage/uniqueness validation')
    old_codes = {row.get('ts_code') or row.get('code') for row in previous}
    for exchange in ('SH','SZ','BJ'):
        current = {code for code in codes if code.endswith('.' + exchange)}
        baseline = {code for code in old_codes if code and code.endswith('.' + exchange)}
        if not current:
            raise ValueError('Empty listed universe for exchange: ' + exchange)
        if baseline and len(baseline - current) > max(1, int(len(baseline) * .005)):
            raise ValueError('Unexpected listed-universe removals for ' + exchange + '; manual delisting reconciliation required')

def acquire(as_of, since, run, previous, deep_check=False):
    api = client(as_of, run)
    overlay = run / 'overlay'
    if previous and Path(previous).is_dir():
        # Copies are private working input; source vault files are never rewritten.
        shutil.copytree(previous, overlay)
    overlay.mkdir(parents=True, exist_ok=True)
    stocks, profiles = [], {}
    for exchange in ('SSE', 'SZSE', 'BSE'):
        rows = list(pages(api, 'stock_basic', {'exchange': exchange, 'list_status':'L'}, 'ts_code,name,symbol,industry,market,exchange,list_status,list_date'))
        if not rows:
            raise ValueError('Empty listed universe for exchange: ' + exchange)
        stocks.extend(r for r in rows if not r['ts_code'].startswith(('200','900')))
        rows = list(pages(api, 'stock_company', {'exchange':exchange}, 'ts_code,com_name,exchange,setup_date,main_business,business_scope,introduction,website'))
        profiles.update({r['ts_code']:r for r in rows})
    old_stocks = read(overlay / 'stocks.json', [])
    if not old_stocks:
        old_stocks = read(PUBLIC / 'index.json', {}).get('companies', [])
    validate_universe(stocks, old_stocks)
    stocks.sort(key=lambda row: row['ts_code'])
    write(overlay / 'stocks.json', stocks)
    write(overlay / 'companies.json', profiles)
    changed_financial = set()
    for table, fields in FIELDS.items():
        rows = list(pages(api, table + '_vip', {'start_date': since, 'end_date':as_of, 'report_type':'1'}, fields))
        if deep_check:
            for period in review_periods(as_of):
                rows.extend(pages(api, table + '_vip', {'period':period,'report_type':'1'}, fields))
        grouped = defaultdict(list)
        for row in rows:
            if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',str(row.get('ts_code',''))):
                raise ValueError('Invalid financial stock identifier')
            ann = str(row.get('ann_date') or '')
            if not ann or ann > as_of or (not deep_check and ann < since) or str(row.get('report_type')) != '1':
                raise ValueError('Disclosure range or consolidated type mismatch: ' + table)
            grouped[row['ts_code']].append(row)
        for code, additions in grouped.items():
            path = overlay / 'financial' / (code + '.json')
            raw = read(path, {'ts_code':code})
            combined = merge_disclosures(raw.get(table, []), additions)
            if fingerprint(combined) != fingerprint(raw.get(table, [])):
                changed_financial.add(code)
            raw[table] = combined
            write(path, raw)
    segment_periods = []
    if deep_check:
        periods = review_periods(as_of)
        segment_periods = sorted([p for p in periods if p.endswith(('1231','0630'))], reverse=True)[:2]
        for period in segment_periods:
            segment_rows = list(pages(api,'fina_mainbz_vip',{'period':period},'ts_code,end_date,bz_item,bz_sales,bz_profit,bz_cost,curr_type,bz_code,update_flag',page_size=100))
            grouped = defaultdict(list)
            for row in segment_rows:
                if row.get('end_date') != period: raise ValueError('Business segment period mismatch')
                if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',str(row.get('ts_code',''))): raise ValueError('Invalid business-segment stock identifier')
                grouped[row['ts_code']].append(row)
            for code, rows in grouped.items():
                path = overlay / 'financial' / (code + '.json')
                raw = read(path, {'ts_code':code})
                raw['mainbz'] = merge_segments(raw.get('mainbz', []), rows)
                write(path,raw)
    digest = hashlib.sha256()
    for path in sorted(overlay.rglob('*.json')):
        if path.name == 'status.json': continue
        digest.update(path.relative_to(overlay).as_posix().encode())
        digest.update(fingerprint(read(path)).encode())
    write(overlay / 'status.json', {'asOf':as_of,'checkedAt':datetime.now(CN).isoformat(),'announcementWindow':{'from':since,'to':as_of},'financialChangedCodes':sorted(changed_financial),'dataFingerprint':digest.hexdigest(),'periodRecheck':review_periods(as_of) if deep_check else [],'segmentPeriods':segment_periods,'limits':'Daily disclosure-window checks; weekly recheck of five annual and eight quarterly periods plus two segment periods. Older unchanged-announcement revisions require a targeted historical refresh.'})
    return overlay

def review_periods(as_of):
    year = int(as_of[:4])
    quarters = sorted([f'{y}{end}' for y in range(year-3,year+1) for end in ('0331','0630','0930','1231') if f'{y}{end}' <= as_of],reverse=True)[:8]
    annual = [f'{y}1231' for y in range(year-5,year) if f'{y}1231' <= as_of]
    return sorted(set(quarters + annual))

def merge_disclosures(previous, incoming):
    """A fresh pull replaces the same published revision; older run files remain immutable."""
    def key(row):
        return tuple(str(row.get(field) or '') for field in ('ts_code','end_date','report_type','ann_date','f_ann_date'))
    new_groups = defaultdict(list)
    for row in incoming: new_groups[key(row)].append(row)
    selected = {}
    for identity, versions in new_groups.items():
        updated = [row for row in versions if str(row.get('update_flag')) in ('1','1.0')]
        versions = updated or versions
        unique = {fingerprint(row): row for row in versions}
        if len(unique) != 1:
            raise ValueError('Fresh disclosure has unresolved same-date versions: ' + '|'.join(identity))
        selected[identity] = next(iter(unique.values()))
    result = [row for row in previous if key(row) not in selected]
    result.extend(selected.values())
    return sorted(result, key=lambda row: (key(row),fingerprint(row)))

def merge_segments(previous, incoming):
    """Refresh returned dimensions only; a VIP pull must not erase custom dimensions."""
    def group(row): return tuple(str(row.get(k) or '') for k in ('end_date', 'bz_code', 'curr_type'))
    replaced = {group(row) for row in incoming}
    return sorted([row for row in previous if group(row) not in replaced] + incoming, key=fingerprint)


def input_fingerprint(overlay, knowledge):
    status = read(overlay / 'status.json', {})
    data_hash = status.get('dataFingerprint')
    if not data_hash:
        # Imported immutable overlays need not have the updater's private metadata.
        digest = hashlib.sha256()
        for path in sorted(overlay.rglob('*.json')):
            if path.name == 'status.json': continue
            digest.update(path.relative_to(overlay).as_posix().encode())
            digest.update(fingerprint(read(path)).encode())
        data_hash = digest.hexdigest()
    original_files = []
    for folder in ('site/data/stocks','data/value/raw'):
        for path in sorted((knowledge / folder).glob('*.json')):
            stat = path.stat()
            original_files.append((path.relative_to(knowledge).as_posix(),stat.st_size,stat.st_mtime_ns))
    build_inputs = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
                    ('src/lib/evidence-data.json','scripts/company_data.py','scripts/build-company-data.py','scripts/check-company-updates.py')}
    return fingerprint([data_hash,original_files,read(ROOT / 'content/company-narratives.json',{}),
                        read(ROOT / 'content/company-finance-reviews.json',{}),build_inputs])

def validate_snapshot(folder):
    index = read(folder / 'index.json')
    if not index or index.get('schemaVersion') != 1:
        raise ValueError('Candidate company index missing or incompatible')
    codes = [c['code'] for c in index['companies']]
    if len(codes) < 4000 or len(codes) != len(set(codes)) or len(codes) != index['coverage']['total']:
        raise ValueError('Candidate coverage invalid')
    token = os.environ.get('TUSHARE_TOKEN', '')
    for code in codes:
        path = folder / 'snapshots' / index['snapshotId'] / (code + '.json')
        content = path.read_text(encoding='utf-8')
        if token and token in content:
            raise ValueError('Credential found in candidate output')
        company = json.loads(content)
        if company['code'] != code:
            raise ValueError('Company identity mismatch')
        sources = {s['id'] for s in company['sources']}
        for source in company['sources']:
            if '[来源根: project-root]' in source.get('document','') and source.get('localRef'):
                reference = (ROOT.parent / source['localRef']).resolve()
                if ROOT.parent.resolve() not in reference.parents or not reference.is_file():
                    raise ValueError('Missing or out-of-project update source: ' + code)
        for claim in company['timeline'] + company['businessModel'] + company['competitive'] + company['risks']:
            if not set(claim['sourceIds']).issubset(sources):
                raise ValueError('Unresolved evidence reference: ' + code)
    return index

def stage_snapshot(candidate, destination):
    index = validate_snapshot(candidate)
    previous = read(destination / 'index.json')
    source = candidate / 'snapshots' / index['snapshotId']
    target = destination / 'snapshots' / index['snapshotId']
    if target.exists():
        for path in source.iterdir():
            if not (target / path.name).exists() or path.read_bytes() != (target / path.name).read_bytes():
                raise ValueError('Immutable snapshot collision')
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
    return previous, index

def source_snapshot_is_protected(index):
    return bool(index and (index.get('sourceRelease') or
                           '-sources-' in str(index.get('snapshotId') or '')))


def publication_destinations():
    destinations = [PUBLIC]
    if (ROOT / 'dist' / 'index.html').exists():
        destinations.append(ROOT / 'dist' / 'data' / 'companies')
    return destinations


def reject_legacy_publication(destinations, candidate_index=None):
    # A candidate must carry an explicit source release, not only a source-like name.
    if candidate_index and candidate_index.get('sourceRelease'):
        return
    for destination in destinations:
        if source_snapshot_is_protected(read(destination / 'index.json', {})):
            raise ValueError('Original-source company snapshot is protected: legacy '
                             'company publication is disabled; existing snapshot and '
                             'success watermark must be retained')


def publish_all(candidate, destinations, commit_state=None):
    candidate_index = read(candidate / 'index.json', {})
    reject_legacy_publication(destinations, candidate_index)
    # Stage and verify every target before any public pointer moves.
    staged = [(destination, *stage_snapshot(candidate, destination)) for destination in destinations]
    reject_legacy_publication(destinations, candidate_index)
    switched = []
    try:
        for destination, previous, index in staged:
            reject_legacy_publication([destination], index)
            write(destination / 'index.json', index)
            switched.append((destination, previous))
        if commit_state:
            commit_state(staged[0][2])
    except Exception:
        rollback_errors = []
        for destination, previous in reversed(switched):
            try:
                if previous is None:
                    (destination / 'index.json').unlink(missing_ok=True)
                else:
                    write(destination / 'index.json', previous)
            except Exception:
                rollback_errors.append(str(destination))
        if rollback_errors:
            raise RuntimeError('Index rollback failed: ' + ', '.join(rollback_errors)) from None
        raise
    return staged[0][1], staged[0][2]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--knowledge-root', type=Path, default=Path(os.environ.get('ATLAS_KNOWLEDGE_ROOT', str(ROOT.parent / '20_资料与证据' / '基础资料' / 'A股知识库网站'))))
    parser.add_argument('--as-of', default=datetime.now(CN).strftime('%Y%m%d'))
    parser.add_argument('--overlay-root', type=Path, help='Use an already fetched overlay without network calls')
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--deep-check', action='store_true', help='Recheck recent periods and business segments; also automatic on Sundays')
    args = parser.parse_args()
    if args.publish:
        # Deliberately outside the run/failure ledger: blocked publication is not a
        # successful refresh and must not perform collection or advance watermarks.
        reject_legacy_publication(publication_destinations())
    day = datetime.strptime(args.as_of, '%Y%m%d').replace(tzinfo=CN)
    state = read(STATE / 'state.json', {})
    if not args.force and not args.overlay_root and state.get('lastSuccessDate') == args.as_of:
        print(json.dumps({'status':'unchanged','reason':'already checked today'})); return
    run = STATE / 'runs' / (args.as_of + '-' + datetime.now(CN).strftime('%H%M%S%f'))
    run.mkdir(parents=True, exist_ok=True)
    last_success = state.get('lastSuccessDate')
    since = (datetime.strptime(last_success,'%Y%m%d').replace(tzinfo=CN) - timedelta(days=7) if last_success else day - timedelta(days=45)).strftime('%Y%m%d')
    published = False
    try:
        overlay = args.overlay_root or acquire(args.as_of, since, run, state.get('activeOverlay'), args.deep_check or day.weekday() == 6)
        input_hash = input_fingerprint(overlay, args.knowledge_root)
        if args.publish and input_hash and input_hash == state.get('inputFingerprint'):
            state.update({'lastSuccessDate':args.as_of,'checkedAt':datetime.now(CN).isoformat(),'activeOverlay':str(overlay.resolve()),'consecutiveFailures':0})
            write(STATE / 'state.json',state)
            report = {'status':'unchanged','asOf':args.as_of,'reason':'No source data or curated text changed','snapshotId':state.get('activeSnapshot')}
            write(run / 'result.json',report);write(STATE / 'last-check.json',report)
            print(json.dumps(report));return
        candidate = run / 'candidate'
        command = [sys.executable, str(ROOT / 'scripts' / 'build-company-data.py'), '--knowledge-root',str(args.knowledge_root), '--as-of', args.as_of, '--overlay-root',str(overlay), '--output-dir',str(candidate), '--report-file',str(run / 'company-data-report.json')]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
        (run / 'build.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        if result.returncode:
            raise ValueError('Company candidate build failed; see private build.log')
        candidate_index = validate_snapshot(candidate)
        previous = read(PUBLIC / 'index.json', {})
        changed = previous.get('snapshotId') != candidate_index['snapshotId']
        if args.publish:
            destinations = publication_destinations()
            def commit_state(index):
                next_state = dict(state, lastSuccessDate=args.as_of, checkedAt=datetime.now(CN).isoformat(),
                                  activeOverlay=str(overlay.resolve()), activeSnapshot=index['snapshotId'],
                                  consecutiveFailures=0, inputFingerprint=input_hash)
                write(STATE / 'state.json', next_state)
                state.update(next_state)
            previous, index = publish_all(candidate, destinations, commit_state)
            published = True
            old_codes = {x['code'] for x in (previous or {}).get('companies',[])}
            report = {'status':'updated' if changed else 'unchanged','asOf':args.as_of,'snapshotId':index['snapshotId'],'previousSnapshot':(previous or {}).get('snapshotId'),'coverage':index['coverage'],'newCompanies':sorted({c['code'] for c in index['companies']} - old_codes),'disclosureWindow':{'from':since,'to':args.as_of}}
        else:
            report = {'status':'validated_not_published','asOf':args.as_of,'candidate':str(candidate),'coverage':candidate_index['coverage']}
        write(run / 'result.json',report); write(STATE / 'last-check.json',report)
        print(json.dumps(report,ensure_ascii=True))
    except Exception as exc:
        message = str(exc)
        token = os.environ.get('TUSHARE_TOKEN')
        if token: message = message.replace(token,'[redacted]')
        state['consecutiveFailures'] = state.get('consecutiveFailures',0) + 1
        state['lastFailureAt'] = datetime.now(CN).isoformat()
        write(STATE / 'state.json',state)
        report = {'status':'failed','reason':message,'previousSnapshotPreserved':not published and not message.startswith('Index rollback failed:'),'consecutiveFailures':state['consecutiveFailures']}
        write(run / 'result.json',report);write(STATE / 'last-check.json',report)
        print(json.dumps(report,ensure_ascii=True));sys.exit(1)

if __name__ == '__main__':
    STATE.mkdir(parents=True, exist_ok=True)
    lock = STATE / 'update.lock'
    if lock.exists() and time.time() - lock.stat().st_mtime > 4 * 3600:
        lock.unlink()
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print(json.dumps({'status':'unchanged','reason':'another check is running'}))
        sys.exit(0)
    try:
        with os.fdopen(descriptor, 'w') as stream: stream.write(str(os.getpid()))
        main()
    finally:
        lock.unlink(missing_ok=True)
