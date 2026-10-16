#!/usr/bin/env python3
"""Refresh the local market-cap snapshot from the latest completed trading day.

python scripts/update-market-snapshot.py --publish
Without --publish, validate and keep the candidate only in private diagnostics.
TUSHARE_TOKEN is read by the existing HTTPS client; it is never written to disk.
No source-vault files, quotes in evidence-data.json, or deployed sites are changed.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT.parent / 'diagnostics' / 'market-updates'
PUBLIC = ROOT / 'public' / 'data' / 'market'
CN = timezone(timedelta(hours=8))
MIN_STOCKS = 4000
MIN_COVERAGE = .98
MAX_CANDIDATE_DAYS = 5
PAGE_SIZE = 3000
MAX_PAGES = 12
EXCHANGES = {'SSE': 'SH', 'SZSE': 'SZ', 'BSE': 'BJ'}
CODE = re.compile(r'\d{6}\.(SH|SZ|BJ)')
DOCS = {
    'daily_basic': 'https://tushare.pro/document/2?doc_id=32',
    'daily': 'https://tushare.pro/document/2?doc_id=27',
    'stock_basic': 'https://tushare.pro/document/2?doc_id=25',
    'trade_cal': 'https://tushare.pro/document/2?doc_id=26',
}


def read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def fingerprint(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def write(path, value):
    """A failed write never leaves a partially written public JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(encoded(value))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def client(run):
    spec = importlib.util.spec_from_file_location('market_evidence_client', ROOT / 'scripts' / 'enrich-evidence.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The shared client's date identifies when a response was fetched, not its trade date.
    instance = module.Client(datetime.now().strftime('%Y%m%d'))
    instance.cache = run / 'api-cache'
    return instance


def pages(api, name, params, fields):
    """Bound pagination and reject servers that ignore limit/offset or repeat rows."""
    output, seen_pages = [], set()
    for page in range(MAX_PAGES):
        query = dict(params, limit=PAGE_SIZE, offset=page * PAGE_SIZE)
        rows = api.call(name, query, fields, name + '-' + fingerprint(query)[:20], required=False)
        if not isinstance(rows, list) or len(rows) > PAGE_SIZE:
            raise ValueError('Unexpected page size: ' + name)
        digest = fingerprint(rows)
        if rows and digest in seen_pages:
            raise ValueError('Pagination repeated a page: ' + name)
        seen_pages.add(digest)
        output.extend(rows)
        if len(rows) < PAGE_SIZE:
            return output
    raise ValueError('Pagination exceeded safe bound: ' + name)


def eligible_dates(calendar, moment, start):
    """Use the actual exchange calendar; avoid today's still-publishing EOD feed."""
    today = moment.strftime('%Y%m%d')
    expected = {(start + timedelta(days=i)).strftime('%Y%m%d')
                for i in range((moment.date() - start.date()).days + 1)}
    dates = {}
    for row in calendar:
        day = row.get('cal_date')
        if row.get('exchange') != 'SSE' or day not in expected or day in dates or str(row.get('is_open')) not in ('0', '1'):
            raise ValueError('Invalid, duplicate, or mismatched trading-calendar row')
        dates[day] = str(row['is_open']) == '1'
    if set(dates) != expected:
        raise ValueError('Trading calendar is incomplete')
    # Official daily_basic publication window is 15:00-17:00 China time.
    allow_today = (moment.hour, moment.minute) >= (17, 10)
    eligible = sorted((day for day, opened in dates.items() if opened and (day < today or allow_today)), reverse=True)
    if not eligible:
        raise ValueError('No completed trading day found in calendar')
    return eligible[:MAX_CANDIDATE_DAYS]


def valid_code(code):
    return isinstance(code, str) and CODE.fullmatch(code) is not None


def is_a_share(code):
    return not code.startswith(('200', '900'))


def universe(api):
    result = {}
    for exchange, suffix in EXCHANGES.items():
        rows = pages(api, 'stock_basic', {'exchange': exchange, 'list_status': 'L'},
                     'ts_code,list_status,list_date,exchange')
        for row in rows:
            code, listed = row.get('ts_code'), str(row.get('list_date') or '')
            if not valid_code(code) or not code.endswith('.' + suffix) or row.get('exchange') != exchange or row.get('list_status') != 'L':
                raise ValueError('Invalid listed-universe identity: ' + exchange)
            if not re.fullmatch(r'\d{8}', listed):
                raise ValueError('Missing listing date: ' + code)
            datetime.strptime(listed, '%Y%m%d')
            if not is_a_share(code):
                continue
            if code in result:
                raise ValueError('Duplicate listed stock: ' + code)
            result[code] = listed
        if not any(code.endswith('.' + suffix) for code in result):
            raise ValueError('Empty listed universe for exchange: ' + exchange)
    if len(result) < MIN_STOCKS:
        raise ValueError('Listed A-share universe below coverage floor')
    return result


def dated_rows(rows, trade_date, name):
    result = {}
    for row in rows:
        code = row.get('ts_code')
        if not valid_code(code) or row.get('trade_date') != trade_date:
            raise ValueError('Invalid stock or mismatched trade date: ' + name)
        if code in result:
            raise ValueError('Duplicate stock in ' + name + ': ' + code)
        result[code] = row
    return {code: row for code, row in result.items() if is_a_share(code)}


def positive_mv(value):
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError('Boolean market-cap value')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError('Malformed market-cap value') from None
    if not math.isfinite(number) or number <= 0:
        raise ValueError('Non-positive or non-finite market-cap value')
    return number / 10000  # Tushare total_mv: 万元 -> 亿元.


def build_snapshot(listed, basic_rows, quote_rows, trade_date, moment, previous=None, skipped=None):
    listed = {code: day for code, day in listed.items() if day <= trade_date}
    if len(listed) < MIN_STOCKS:
        raise ValueError('Trading-day listed universe below coverage floor')
    basic = dated_rows(basic_rows, trade_date, 'daily_basic')
    quotes = dated_rows(quote_rows, trade_date, 'daily')
    if not basic or not quotes:
        raise ValueError('Required market response is empty')
    # A traded stock without its same-date basic row is a partial feed, not a suspension.
    missing_traded = (set(quotes) & set(listed)) - set(basic)
    if missing_traded:
        raise ValueError('daily_basic omitted traded stocks: ' + str(len(missing_traded)))
    stocks = {code: {'mv': positive_mv(basic.get(code, {}).get('total_mv'))} for code in sorted(listed)}
    by_exchange = {}
    for suffix in EXCHANGES.values():
        expected = {code for code in listed if code.endswith('.' + suffix)}
        valued = {code for code in expected if stocks[code]['mv'] is not None}
        quoted = expected & set(quotes)
        if not expected or len(valued) / len(expected) < MIN_COVERAGE or len(quoted) / len(expected) < MIN_COVERAGE:
            raise ValueError('Market feed below per-exchange completeness floor: ' + suffix)
        previous_codes = {code for code in (previous or {}).get('stocks', {}) if code.endswith('.' + suffix)}
        if previous_codes and len(previous_codes - expected) > max(1, int(len(previous_codes) * .005)):
            raise ValueError('Unexpected listed-universe removal: ' + suffix)
        by_exchange[suffix] = {'listed': len(expected), 'valued': len(valued), 'missing': len(expected - valued), 'quoted': len(quoted)}
    valued_count = sum(row['mv'] is not None for row in stocks.values())
    iso_date = datetime.strptime(trade_date, '%Y%m%d').date().isoformat()
    snapshot = {
        'schemaVersion': 1, 'tradeDate': iso_date, 'asOf': moment.isoformat(),
        'snapshotId': trade_date + '-' + fingerprint([iso_date, stocks])[:16],
        'stocks': stocks,
        'coverage': {'listed': len(stocks), 'valued': valued_count, 'missing': len(stocks) - valued_count},
        'source': {'provider': 'Tushare Pro', 'api': 'daily_basic', 'field': 'total_mv',
                   'sourceUnit': '万元', 'unit': '亿元', 'divisor': 10000, 'url': DOCS['daily_basic'],
                   'universeApi': 'stock_basic', 'calendarApi': 'trade_cal', 'crossCheckApi': 'daily',
                   'calendarExchange': 'SSE', 'market': 'Listed A shares (SH/SZ/BJ)',
                   'completionCutoff': '17:10 Asia/Shanghai', 'missingPolicy': 'null; no prior-day carry forward'},
        'validation': {'byExchange': by_exchange, 'minimumCoverage': MIN_COVERAGE,
                       'basicRows': len(basic), 'quoteRows': len(quotes),
                       'unlistedBasicCodes': sorted(set(basic) - set(listed)),
                       'unavailableTradeDates': skipped or []},
    }
    if previous and iso_date < previous['tradeDate']:
        raise ValueError('Candidate would move the market snapshot backwards')
    return snapshot


def acquire(api, moment, previous):
    start = (moment - timedelta(days=45)).replace(hour=0, minute=0, second=0, microsecond=0)
    calendar = pages(api, 'trade_cal', {'exchange': 'SSE', 'start_date': start.strftime('%Y%m%d'),
                                      'end_date': moment.strftime('%Y%m%d')}, 'exchange,cal_date,is_open')
    candidates = eligible_dates(calendar, moment, start)
    listed = universe(api)
    skipped = []
    for day in candidates:
        basic = pages(api, 'daily_basic', {'trade_date': day}, 'ts_code,trade_date,total_mv')
        quotes = pages(api, 'daily', {'trade_date': day}, 'ts_code,trade_date')
        # Only an entirely absent feed allows an older date. Invalid/partial data fails closed.
        if not basic or not quotes:
            skipped.append(datetime.strptime(day, '%Y%m%d').date().isoformat())
            continue
        return build_snapshot(listed, basic, quotes, day, moment, previous, skipped)
    raise ValueError('No available complete market feed in the last five completed trading days')


def publish(snapshot, destination, state_root):
    latest = destination / 'latest.json'
    previous = read(latest)
    if previous and snapshot['tradeDate'] < previous['tradeDate']:
        raise ValueError('Refusing to publish an older trade date')
    if previous and previous.get('snapshotId') == snapshot['snapshotId']:
        return False
    if latest.exists():
        # Backup is complete before the atomic replacement. Immutable diagnostics retain all versions.
        backup = state_root / 'backups' / (hashlib.sha256(latest.read_bytes()).hexdigest() + '.json')
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(latest, backup)
        if backup.read_bytes() != latest.read_bytes():
            raise ValueError('Last-good snapshot backup failed verification')
    write(latest, snapshot)
    return True


def run_update(publish_output=False, api=None, moment=None, state_root=None, destination=None):
    state_root, destination = state_root or STATE, destination or PUBLIC
    moment = (moment or datetime.now(CN)).astimezone(CN)
    state = read(state_root / 'state.json', {})
    run = state_root / 'runs' / moment.strftime('%Y%m%d-%H%M%S%f')
    run.mkdir(parents=True, exist_ok=False)
    before = (destination / 'latest.json').read_bytes() if (destination / 'latest.json').exists() else None
    try:
        previous = read(destination / 'latest.json')
        snapshot = acquire(api or client(run), moment, previous)
        write(run / 'candidate.json', snapshot)
        changed = publish(snapshot, destination, state_root) if publish_output else False
        report = {'status': ('updated' if changed else 'unchanged') if publish_output else 'validated_not_published',
                  'checkedAt': moment.isoformat(), 'tradeDate': snapshot['tradeDate'], 'snapshotId': snapshot['snapshotId'],
                  'coverage': snapshot['coverage'], 'candidate': str(run / 'candidate.json'),
                  'unavailableTradeDates': snapshot['validation']['unavailableTradeDates']}
        state.update({'lastCheckAt': moment.isoformat(), 'consecutiveFailures': 0})
        if publish_output:
            state.update({'lastSuccessAt': moment.isoformat(), 'lastSuccessTradeDate': snapshot['tradeDate'],
                          'activeSnapshot': snapshot['snapshotId']})
    except Exception as exc:
        message = str(exc)
        token = os.environ.get('TUSHARE_TOKEN')
        if token:
            message = message.replace(token, '[redacted]')
        after = (destination / 'latest.json').read_bytes() if (destination / 'latest.json').exists() else None
        state.update({'lastFailureAt': moment.isoformat(), 'consecutiveFailures': state.get('consecutiveFailures', 0) + 1})
        report = {'status': 'failed', 'checkedAt': moment.isoformat(), 'reason': message,
                  'previousSnapshotPreserved': before == after, 'consecutiveFailures': state['consecutiveFailures']}
    write(run / 'result.json', report)
    write(state_root / 'last-check.json', report)
    write(state_root / 'state.json', state)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish', action='store_true', help='Atomically update local public/data/market/latest.json; no deployment')
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    lock = STATE / 'update.lock'
    if lock.exists() and time.time() - lock.stat().st_mtime > 6 * 3600:
        lock.unlink()
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        print(json.dumps({'status': 'unchanged', 'reason': 'another market refresh is running'}))
        return 0
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(str(os.getpid()))
        report = run_update(args.publish)
        print(json.dumps(report, ensure_ascii=True))
        return 1 if report['status'] == 'failed' else 0
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    sys.exit(main())
