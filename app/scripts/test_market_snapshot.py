"""Market snapshots must never silently replace complete data with partial/stale data."""
from copy import deepcopy
from datetime import datetime, timedelta
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('market_snapshot', Path(__file__).with_name('update-market-snapshot.py'))
MARKET = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MARKET)
DAY = '20260924'
MOMENT = datetime(2026, 9, 24, 21, tzinfo=MARKET.CN)
CODES = [f'{index:06d}.{suffix}' for suffix in ('SH', 'SZ', 'BJ') for index in range(1, 51)]
LISTED = {code: '20200101' for code in CODES}
BASIC = [{'ts_code': code, 'trade_date': DAY, 'total_mv': 1250000} for code in CODES]
QUOTES = [{'ts_code': code, 'trade_date': DAY} for code in CODES]


def calendar(moment):
    start = moment - timedelta(days=45)
    return [{'exchange': 'SSE', 'cal_date': (start + timedelta(days=i)).strftime('%Y%m%d'),
             'is_open': 1 if (start + timedelta(days=i)).weekday() < 5 else 0} for i in range(46)]


class FakeAPI:
    def __init__(self, moment=MOMENT, empty_dates=(), basic=None, quotes=None):
        self.moment, self.empty_dates, self.calls = moment, empty_dates, []
        self.basic, self.quotes = deepcopy(basic if basic is not None else BASIC), deepcopy(quotes if quotes is not None else QUOTES)

    def call(self, name, params, fields, label, required=False):
        self.calls.append((name, params))
        if name == 'trade_cal':
            rows = calendar(self.moment)
        elif name == 'stock_basic':
            suffix = MARKET.EXCHANGES[params['exchange']]
            rows = [{'ts_code': code, 'list_status': 'L', 'list_date': day, 'exchange': params['exchange']}
                    for code, day in LISTED.items() if code.endswith('.' + suffix)]
        else:
            rows = self.basic if name == 'daily_basic' else self.quotes
            rows = [] if params['trade_date'] in self.empty_dates else [{**row, 'trade_date': params['trade_date']} for row in rows]
        return deepcopy(rows[params['offset']:params['offset'] + params['limit']])


class MarketSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.minimum = patch.object(MARKET, 'MIN_STOCKS', len(CODES))
        self.minimum.start()
        self.addCleanup(self.minimum.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.state, self.public = self.root / 'private', self.root / 'public'

    def build(self, basic=None, quotes=None, previous=None):
        return MARKET.build_snapshot(LISTED, BASIC if basic is None else basic,
                                     QUOTES if quotes is None else quotes, DAY, MOMENT, previous)

    def test_source_units_and_explicit_snapshot_date(self):
        result = self.build()
        self.assertEqual(result['stocks']['000001.SH']['mv'], 125)
        self.assertEqual(result['tradeDate'], '2026-09-24')
        self.assertEqual(result['coverage'], {'listed': 150, 'valued': 150, 'missing': 0})
        self.assertEqual(result['source']['divisor'], 10000)

    def test_missing_suspended_cap_is_null_not_zero_or_carried_forward(self):
        result = self.build(basic=BASIC[1:], quotes=QUOTES[1:], previous=self.build())
        self.assertIsNone(result['stocks'][CODES[0]]['mv'])
        self.assertEqual(result['coverage']['missing'], 1)

    def test_quoted_stock_without_basic_row_rejects_candidate(self):
        with self.assertRaisesRegex(ValueError, 'omitted traded'):
            self.build(basic=BASIC[1:])

    def test_null_cap_remains_missing(self):
        rows = deepcopy(BASIC)
        rows[0]['total_mv'] = None
        self.assertIsNone(self.build(basic=rows)['stocks'][CODES[0]]['mv'])

    def test_invalid_values_are_not_coerced_to_zero(self):
        for value in (0, -1, True, float('nan'), float('inf'), 'not a number'):
            rows = deepcopy(BASIC)
            rows[0]['total_mv'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.build(basic=rows)

    def test_duplicates_and_mixed_dates_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            self.build(basic=BASIC + [BASIC[0]])
        rows = deepcopy(BASIC)
        rows[0]['trade_date'] = '20260923'
        with self.assertRaisesRegex(ValueError, 'mismatched trade date'):
            self.build(basic=rows)

    def test_both_truncated_feeds_fail_coverage(self):
        with self.assertRaisesRegex(ValueError, 'completeness'):
            self.build(basic=BASIC[10:], quotes=QUOTES[10:])

    def test_before_completion_cutoff_uses_previous_open_date(self):
        morning = MOMENT.replace(hour=10)
        result = MARKET.acquire(FakeAPI(moment=morning), morning, None)
        self.assertEqual(result['tradeDate'], '2026-09-23')

    def test_nontrading_weekend_uses_exchange_calendar(self):
        saturday = MOMENT + timedelta(days=2)
        result = MARKET.acquire(FakeAPI(moment=saturday), saturday, None)
        self.assertEqual(result['tradeDate'], '2026-09-25')
        # Explicit holiday on a weekday must override the weekday heuristic.
        rows = calendar(MOMENT)
        rows[-1]['is_open'] = 0
        self.assertEqual(MARKET.eligible_dates(rows, MOMENT, MOMENT - timedelta(days=45))[0], '20260923')

    def test_missing_calendar_date_rejected(self):
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            MARKET.eligible_dates(calendar(MOMENT)[:-1], MOMENT, MOMENT - timedelta(days=45))

    def test_absent_latest_day_uses_previous_available_with_disclosure(self):
        result = MARKET.acquire(FakeAPI(empty_dates=(DAY,)), MOMENT, None)
        self.assertEqual(result['tradeDate'], '2026-09-23')
        self.assertEqual(result['validation']['unavailableTradeDates'], ['2026-09-24'])

    def test_partial_latest_day_is_not_hidden_by_older_fallback(self):
        with self.assertRaisesRegex(ValueError, 'completeness'):
            MARKET.acquire(FakeAPI(basic=BASIC[10:], quotes=QUOTES[10:]), MOMENT, None)

    def test_failure_preserves_last_good_bytes_and_success_date(self):
        prior = self.build()
        MARKET.write(self.public / 'latest.json', prior)
        MARKET.write(self.state / 'state.json', {'lastSuccessTradeDate': '2026-09-24', 'activeSnapshot': prior['snapshotId']})
        before = (self.public / 'latest.json').read_bytes()
        report = MARKET.run_update(True, FakeAPI(basic=BASIC[10:], quotes=QUOTES[10:]), MOMENT,
                                   self.state, self.public)
        self.assertEqual(report['status'], 'failed')
        self.assertTrue(report['previousSnapshotPreserved'])
        self.assertEqual((self.public / 'latest.json').read_bytes(), before)
        self.assertEqual(MARKET.read(self.state / 'state.json')['lastSuccessTradeDate'], '2026-09-24')

    def test_same_data_is_idempotent_and_updated_data_has_backup(self):
        first = self.build()
        self.assertTrue(MARKET.publish(first, self.public, self.state))
        before = (self.public / 'latest.json').read_bytes()
        same = deepcopy(first)
        same['asOf'] = '2026-09-24T22:00:00+08:00'
        self.assertFalse(MARKET.publish(same, self.public, self.state))
        self.assertEqual((self.public / 'latest.json').read_bytes(), before)
        rows = deepcopy(BASIC)
        rows[0]['total_mv'] *= 2
        self.assertTrue(MARKET.publish(self.build(basic=rows), self.public, self.state))
        backups = list((self.state / 'backups').glob('*.json'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), before)

    def test_candidate_cannot_roll_back_to_older_date(self):
        prior = self.build()
        prior['tradeDate'] = '2026-09-25'
        with self.assertRaisesRegex(ValueError, 'backwards'):
            self.build(previous=prior)

    def test_pagination_catches_repeated_or_oversized_pages(self):
        class Repeated:
            def call(self, *args, **kwargs):
                return [{'ts_code': '000001.SH'}, {'ts_code': '000002.SH'}]
        with patch.object(MARKET, 'PAGE_SIZE', 2), self.assertRaisesRegex(ValueError, 'repeated'):
            MARKET.pages(Repeated(), 'daily_basic', {}, 'ts_code')
        with patch.object(MARKET, 'PAGE_SIZE', 1), self.assertRaisesRegex(ValueError, 'page size'):
            MARKET.pages(Repeated(), 'daily_basic', {}, 'ts_code')

    def test_atomic_write_failure_preserves_existing_snapshot(self):
        MARKET.write(self.public / 'latest.json', self.build())
        before = (self.public / 'latest.json').read_bytes()
        with patch.object(Path, 'replace', side_effect=OSError('simulated disk failure')), self.assertRaises(OSError):
            MARKET.write(self.public / 'latest.json', {'broken': True})
        self.assertEqual((self.public / 'latest.json').read_bytes(), before)
        self.assertEqual(list(self.public.glob('*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
