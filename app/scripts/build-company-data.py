#!/usr/bin/env python3
"""Build immutable company dossiers from read-only local sources; no API credentials needed."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

from company_data import build_dossier, valid_date, validate_dossier

APP = Path(__file__).resolve().parents[1]


def load(path, default=None):
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(str(path))
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError) as exc:
        raise ValueError(f'Invalid JSON source: {path} ({type(exc).__name__}: {exc})') from None


def optional_source(path, warnings, dataset):
    try:
        result = load(path, {})
        if not isinstance(result, dict):
            raise ValueError('Expected JSON object: ' + str(path))
        return result
    except ValueError as exc:
        warnings.append({'dataset': dataset, 'path': str(path), 'status': 'unavailable', 'reason': str(exc)})
        return {}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_bytes(data)
    temp.replace(path)


def find_knowledge_root():
    candidates = ([Path(os.environ['ATLAS_KNOWLEDGE_ROOT'])] if os.environ.get('ATLAS_KNOWLEDGE_ROOT') else []) + [APP.parent / '20_资料与证据' / '基础资料' / 'A股知识库网站']
    return next((candidate for candidate in candidates if (candidate / 'site/data/stocks').is_dir()), None)


def is_a_share(code):
    return bool(re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', code)) and not code.startswith(('900', '200'))


def reject_source_snapshot_overwrite(output):
    """The legacy builder cannot replace an adopted original-source snapshot."""
    index = load(output / 'index.json', {})
    if index.get('sourceRelease') or '-sources-' in str(index.get('snapshotId') or ''):
        raise ValueError('Original-source company snapshot is protected: legacy builder '
                         'must use an isolated --output-dir; no public pointer was changed')


def build(args):
    knowledge_root = Path(args.knowledge_root).resolve() if args.knowledge_root else find_knowledge_root()
    if not knowledge_root:
        raise ValueError('Pass --knowledge-root pointing to the read-only A-share knowledge source')
    output = Path(args.output_dir).resolve() if args.output_dir else APP / 'public/data/companies'
    reject_source_snapshot_overwrite(output)
    if output == knowledge_root or knowledge_root in output.parents:
        raise ValueError('Output must not modify the original knowledge source')
    evidence = load(Path(args.evidence_file))
    if evidence.get('schemaVersion') != 2 or evidence.get('status') not in ('complete', 'partial_optional'):
        raise ValueError('Current evidence dataset is not validated')
    overlay_root = Path(args.overlay_root).resolve() if args.overlay_root else APP.parent / 'diagnostics/company-updates/overlay'
    overlay_ref = Path(os.path.relpath(overlay_root, APP.parent)).as_posix()
    overlay_status = load(overlay_root / 'status.json', {})
    overlay_as_of = valid_date(overlay_status.get('asOf'))
    overlay_stocks = load(overlay_root / 'stocks.json', [])
    overlay_companies = load(overlay_root / 'companies.json', {})
    if (overlay_stocks or overlay_companies) and not overlay_as_of:
        raise ValueError('Overlay has no valid status.asOf')
    current = {code: dict(item) for code, item in evidence['stocks'].items() if item.get('listStatus') == 'L' and is_a_share(code)}
    if overlay_stocks:
        current = {}
        for item in overlay_stocks:
            code = item.get('ts_code', '')
            if item.get('list_status') != 'L' or not is_a_share(code):
                continue
            stock = dict(evidence['stocks'].get(code, {}))
            stock.update({'code': code, 'name': item.get('name') or code, 'industry': item.get('industry'),
                          'listStatus': 'L', 'listDate': item.get('list_date'), 'industryAsOf': overlay_as_of})
            current[code] = stock
    for code, item in current.items():
        profile = overlay_companies.get(code)
        if profile:
            item.update({'mainBusiness': profile.get('main_business'), 'businessScope': profile.get('business_scope'), 'profileAsOf': overlay_as_of})
    if not current:
        raise ValueError('No current listed stock universe')
    narrative_path = APP / 'content/company-narratives.json'
    narratives = load(narrative_path, {'schemaVersion': 1, 'companies': {}})
    if narratives.get('schemaVersion') != 1:
        raise ValueError('Unsupported narrative schema')
    narratives = narratives['companies']
    finance_reviews = load(APP / 'content/company-finance-reviews.json', {}).get('companies', {})
    old_files = {path.stem: path for path in (knowledge_root / 'site/data/stocks').glob('*.json')}
    missing_base = sorted(set(current) - set(old_files))
    old_only = sorted(set(old_files) - set(current))
    docs, entries, issues = {}, [], Counter()
    source_warnings = []
    coverage = {'total': len(current), 'basic': 0, 'financialHistory': 0, 'deep': 0, 'missingProfiles': 0}
    layer_counts = {'currentEvidence': sum(code in evidence['stocks'] for code in current), 'legacyBaseMatched': 0, 'rawFinancialFiles': 0,
                    'latestFinancial': 0, 'segments': 0, 'reviewedNarratives': 0, 'profileIntroductions': 0}
    layer_counts.update({'overlayListedUniverse': len(overlay_stocks), 'overlayProfilesMatched': 0, 'overlayFinancialFiles': 0})
    for index, code in enumerate(sorted(current)):
        warning_start = len(source_warnings)
        legacy = optional_source(old_files[code], source_warnings, 'legacyBase') if code in old_files else {}
        if legacy:
            if legacy.get('code') != code:
                raise ValueError('Legacy profile code mismatch: ' + code)
            layer_counts['legacyBaseMatched'] += 1
        if current[code].get('listDate'):
            legacy = dict(legacy, list_date=current[code]['listDate'])
        profile = overlay_companies.get(code)
        if profile:
            layer_counts['overlayProfilesMatched'] += 1
            old_company = dict(legacy.get('company') or {})
            for src, dest in (('introduction', 'intro'), ('setup_date', 'setup_date'), ('website', 'website'),
                              ('main_business', 'business'), ('business_scope', 'scope')):
                if profile.get(src) is not None:
                    old_company[dest] = profile[src]
            legacy = dict(legacy, company=old_company)
        raw_path = knowledge_root / 'data/value/raw' / (code + '.json')
        raw = optional_source(raw_path, source_warnings, 'rawFinancial')
        if raw:
            if raw.get('ts_code') != code:
                raise ValueError('Raw financial code mismatch: ' + code)
            layer_counts['rawFinancialFiles'] += 1
        raw = {dataset: [dict(row, _sourceRef=f'data/value/raw/{code}.json', _priority=0) for row in rows]
               for dataset, rows in raw.items() if isinstance(rows, list)}
        overlay_financial_path = overlay_root / 'financial' / (code + '.json')
        new_financial = load(overlay_financial_path, {})
        if new_financial:
            if not overlay_as_of:
                raise ValueError('Financial overlay has no valid status.asOf')
            if new_financial.get('ts_code', code) != code:
                raise ValueError('Overlay financial code mismatch: ' + code)
            layer_counts['overlayFinancialFiles'] += 1
            for dataset in ('income', 'cashflow', 'balancesheet', 'mainbz'):
                raw.setdefault(dataset, []).extend(dict(row, _sourceRef=f'{overlay_ref}/financial/{code}.json', _priority=2)
                                                  for row in new_financial.get(dataset, []))
        try:
            dossier, company_issues, deep = build_dossier(code, current[code], legacy, raw, args.as_of,
                                                         evidence.get('financialAsOf') or evidence['tradeDate'], narratives.get(code), finance_reviews.get(code))
        except ValueError as exc:
            raise ValueError(f'{code}: {exc}') from None
        if profile:
            for source in dossier['sources']:
                if source['id'] == 'current-profile':
                    source['localRef'] = f'{overlay_ref}/companies.json'
                    source['asOf'] = overlay_as_of
                    source['title'] = 'Tushare 公司资料更新快照（公司自述）'
            for event in dossier['timeline']:
                if event['title'] == '当前主体注册' and profile.get('setup_date'):
                    event['sourceIds'] = ['current-profile']
        if current[code].get('listDate'):
            dossier['sources'].append({'id': 'current-listing', 'title': 'Tushare 股票基础资料更新快照',
                'asOf': overlay_as_of, 'localRef': f'{overlay_ref}/stocks.json', 'sourceType': 'provider'})
            for event in dossier['timeline']:
                if event['title'] == 'A股上市':
                    event['sourceIds'] = ['current-listing']
        if code not in old_files:
            dossier['sources'] = [source for source in dossier['sources'] if source['id'] != 'legacy-profile']
        for source in dossier['sources']:
            reference = source.get('localRef') or ''
            if reference.startswith('src/'):
                source['localRef'] = 'app/' + reference
                root_label = 'project-root'
            elif reference.startswith(overlay_ref + '/'):
                root_label = 'project-root'
            else:
                root_label = 'knowledge-root'
            source['document'] = f'[来源根: {root_label}] ' + str(source.get('document') or '')
        if len(source_warnings) > warning_start:
            dossier['coverage']['sourceIntegrity'] = {'status': 'review',
                'note': '可选旧来源缺损，已跳过且未修改原文件；本档案仅使用其余可读来源。' +
                        '；'.join(item['dataset'] + ': ' + Path(item['path']).name for item in source_warnings[warning_start:])}
        validate_dossier(dossier)
        for dataset, counts in company_issues.items():
            if isinstance(counts, dict):
                for key, value in counts.items():
                    issues[f'{dataset}.{key}'] += value
            else:
                issues[dataset] += counts
        history = bool(dossier['finance']['annual'] or dossier['finance']['quarterly'])
        coverage['basic'] += 1
        coverage['financialHistory'] += int(history)
        coverage['deep'] += int(deep)
        coverage['missingProfiles'] += int(not dossier['profile']['mainBusiness'])
        layer_counts['latestFinancial'] += int(dossier['finance']['latest'] is not None)
        layer_counts['segments'] += int(bool(dossier['segments']))
        layer_counts['reviewedNarratives'] += int(deep)
        layer_counts['profileIntroductions'] += int(bool(dossier['profile']['intro']))
        docs[code] = encode(dossier)
        entries.append({'code': code, 'name': dossier['name'], 'industry': dossier['industry'],
                        'summary': dossier['summary']['text'][:220], 'hasHistory': history,
                        'depth': 'deep' if deep else 'basic', 'updatedAt': dossier['updatedAt']})
        if (index + 1) % 800 == 0:
            print(f'Validated dossiers: {index + 1}/{len(current)}', flush=True)
    digest = hashlib.sha256()
    for code, content in sorted(docs.items()):
        digest.update(code.encode('ascii'))
        digest.update(content)
    snapshot_id = args.as_of + '-' + digest.hexdigest()[:16]
    snapshot = output / 'snapshots' / snapshot_id
    reject_source_snapshot_overwrite(output)
    # Do not expose the new snapshot through index.json until every file has been verified.
    for code, content in docs.items():
        target = snapshot / (code + '.json')
        if target.exists():
            if target.read_bytes() != content:
                raise ValueError('Immutable snapshot collision: ' + code)
        else:
            atomic(target, content)
    generated = datetime.now(timezone.utc).isoformat()
    index_data = {'schemaVersion': 1, 'generatedAt': generated, 'asOf': args.as_of,
                  'snapshotId': snapshot_id, 'coverage': coverage, 'companies': entries}
    # Read-back verifies the exact immutable files that the index will reference.
    for code, content in docs.items():
        if (snapshot / (code + '.json')).read_bytes() != content:
            raise ValueError('Snapshot read-back failed: ' + code)
    reject_source_snapshot_overwrite(output)
    atomic(output / 'index.json', encode(index_data))
    report = {'status': 'pass', 'generatedAt': generated, 'asOf': args.as_of, 'snapshotId': snapshot_id,
              'coverage': coverage, 'sourceLayers': layer_counts, 'missingLegacyBase': missing_base,
              'legacyNotCurrentlyListed': old_only, 'financialExclusions': dict(issues),
              'sourceWarnings': source_warnings,
              'sourceRoot': str(knowledge_root), 'outputRoot': str(output),
              'dossierBytes': sum(len(value) for value in docs.values()),
              'sourcePolicy': 'Original knowledge source read-only; no old auto-evaluations or valuations copied; monetary history recalculated from dated raw consolidated report rows.'}
    report_path = Path(getattr(args, 'report_file', None) or APP.parent / 'diagnostics/company-data-report.json')
    atomic(report_path, encode(report))
    print(json.dumps({key: report[key] for key in ('status', 'snapshotId', 'coverage', 'sourceLayers', 'dossierBytes')}, ensure_ascii=True), flush=True)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--knowledge-root')
    parser.add_argument('--as-of', default=datetime.now().strftime('%Y%m%d'))
    parser.add_argument('--output-dir')
    parser.add_argument('--report-file', help='Private quality report path; use with isolated candidate builds')
    parser.add_argument('--evidence-file', default=str(APP / 'src/lib/evidence-data.json'))
    parser.add_argument('--overlay-root', help='Read-only stock/company/financial increment directory')
    args = parser.parse_args()
    if not valid_date(args.as_of):
        parser.error('--as-of must be YYYYMMDD')
    try:
        build(args)
    except Exception as exc:
        print(json.dumps({'status': 'failed', 'error': type(exc).__name__, 'message': str(exc),
                          'indexPolicy': 'No index switch before all dossiers pass validation'}, ensure_ascii=True), file=sys.stderr)
        sys.exit(1)
