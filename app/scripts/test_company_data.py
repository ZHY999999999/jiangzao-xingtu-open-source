import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from company_data import (INCOME_FIELDS, build_dossier, build_finance, build_segments,
                          select_reports, validate_dossier)


def income(period, ann, total, profit=10, **extra):
    return {'end_date': period, 'ann_date': ann, 'report_type': '1', 'total_revenue': total,
            'n_income_attr_p': profit, **extra}


class FinancialSemantics(unittest.TestCase):
    def finance(self, rows, **raw):
        return build_finance({'income': rows, **raw}, {}, '20260921', {}, 'raw.json')[0]

    def test_cutoff_whole_latest_consolidated_version(self):
        rows = [income('20260630', '20260801', 200, rd_exp=20),
                income('20260630', '20260820', 220),
                income('20260630', '20261001', 500),
                income('20260630', '20260822', 30, report_type='6')]
        selected, issues = select_reports(rows, '20260921', INCOME_FIELDS)
        self.assertEqual(selected['20260630']['total_revenue'], 220)
        self.assertNotIn('rd_exp', selected['20260630'])
        self.assertEqual(issues['futureAnnouncement'], 1)
        self.assertEqual(issues['unverifiedOrNonconsolidatedReport'], 1)

    def test_real_actual_announcement_controls_cutoff(self):
        selected, _ = select_reports([income('20260630', '20260801', 200, f_ann_date='20261001')], '20260921', INCOME_FIELDS)
        self.assertEqual(selected, {})

    def test_ambiguous_same_date_corrections_not_guessed(self):
        rows = [income('20260630', '20260801', 200), income('20260630', '20260801', 201)]
        selected, issues = select_reports(rows, '20260921', INCOME_FIELDS)
        self.assertEqual(selected, {})
        self.assertEqual(issues['ambiguousSameDateRevisions'], 1)
        rows[1]['update_flag'] = '1'
        selected, _ = select_reports(rows, '20260921', INCOME_FIELDS)
        self.assertEqual(selected['20260630']['total_revenue'], 201)

    def test_no_announcement_and_parent_report_excluded(self):
        rows = [income('20260630', None, 200), income('20260630', '20260801', 300, report_type='6')]
        selected, issues = select_reports(rows, '20260921', INCOME_FIELDS)
        self.assertFalse(selected)
        self.assertEqual(issues['missingAnnouncementDate'], 1)

    def test_half_year_and_annual_not_queried_as_single_quarter(self):
        f = self.finance([income('20250331', '20250420', 100, 8), income('20250630', '20250820', 180, -2),
                          income('20250930', '20251020', 300, 20), income('20251231', '20260320', 430, 30)])
        self.assertEqual([p['revenue'] for p in f['annual']], [430])
        self.assertEqual([p['revenue'] for p in f['quarterly']], [100, 80, 120, 130])
        self.assertEqual(f['quarterly'][1]['netProfit'], -10)
        self.assertEqual(f['latest']['revenue'], 430)

    def test_no_cross_year_or_missing_quarter_subtraction(self):
        f = self.finance([income('20251231', '20260320', 430), income('20260630', '20260820', 180)])
        self.assertEqual(f['quarterly'], [])
        self.assertEqual(f['latest']['revenue'], 180)

    def test_correction_vintages_not_mixed(self):
        f = self.finance([income('20260331', '20260420', 100), income('20260331', '20260901', 105),
                          income('20260630', '20260820', 180)])
        self.assertEqual([p['revenue'] for p in f['quarterly']], [105])
        self.assertTrue(any('更正版本' in note for note in f['notes']))

    def test_synchronized_restatements_allow_difference(self):
        f = self.finance([income('20260331', '20260420', 100), income('20260331', '20260901', 105),
                          income('20260630', '20260820', 180), income('20260630', '20260901', 190)])
        self.assertEqual([p['revenue'] for p in f['quarterly']], [105, 85])

    def test_revenue_field_switch_suppresses_revenue_difference(self):
        f = self.finance([income('20260331', '20260420', None, revenue=100), income('20260630', '20260820', 200)])
        self.assertIsNone(f['quarterly'][1]['revenue'])

    def test_missing_stays_none_negative_and_zero_remain(self):
        f = self.finance([income('20260331', '20260420', 0, -10)])
        p = f['latest']
        self.assertEqual(p['revenue'], 0)
        self.assertEqual(p['netProfit'], -10)
        self.assertIsNone(p['rdExpense'])

    def test_balance_requires_consolidation_and_is_never_differenced(self):
        raw = [{'end_date': '20251231', 'ann_date': '20260320', 'total_assets': 200}]
        f = self.finance([income('20251231', '20260320', 100)], balancesheet=raw)
        self.assertIsNone(f['annual'][0]['totalAssets'])
        raw[0]['report_type'] = '1'
        f = self.finance([income('20251231', '20260320', 100)], balancesheet=raw)
        self.assertEqual(f['annual'][0]['totalAssets'], 200)

    def test_current_finance_does_not_create_fake_history(self):
        e = {'reportPeriod': '20260630', 'reportAnnDate': '20260820', 'revenue': 2, 'revenueField': 'total_revenue', 'profit': -.1}
        f, _, _ = build_finance({}, e, '20260921', {}, 'none.json')
        self.assertEqual(f['latest']['revenue'], 200000000)
        self.assertEqual(f['quarterly'], [])
        self.assertEqual(f['annual'], [])

    def test_fresh_overlay_correction_beats_fixed_old_evidence(self):
        raw = {'income': [income('20260630', '20260820', 110, _priority=2, update_flag='1')]}
        evidence = {'reportPeriod': '20260630', 'reportAnnDate': '20260820', 'revenue': 100 / 1e8,
                    'revenueField': 'total_revenue', 'profit': 10 / 1e8}
        f, _, _ = build_finance(raw, evidence, '20260921', {}, 'raw.json')
        self.assertEqual(f['latest']['revenue'], 110)

    def test_two_conflicting_updated_rows_block_candidate(self):
        raw = {'income': [income('20260630', '20260820', 110, _priority=2, update_flag='1'),
                          income('20260630', '20260820', 120, _priority=2, update_flag='1')]}
        with self.assertRaisesRegex(ValueError, 'refusing candidate'):
            build_finance(raw, {}, '20260921', {}, 'raw.json')

    def test_profit_review_follows_both_quarter_dependencies_without_changing_values(self):
        f = self.finance([income('20260331', '20260420', 100, 10, n_income=15, minority_gain=5),
                          income('20260630', '20260820', 200, 20, n_income=40, minority_gain=5),
                          income('20260930', '20261020', 300, 30, n_income=35, minority_gain=5)])
        self.assertEqual(f['quarterly'][1]['netProfit'], 10)
        self.assertEqual(f['quarterly'][1]['profitReviewPeriods'], ['20260630'])
        self.assertEqual(f['latest']['profitReviewPeriods'], ['20260630'])
        self.assertEqual(f['quarterly'][0]['profitReviewPeriods'], [])
        raw = {'income': [income('20250630', '20250820', 200, 20, n_income=40, minority_gain=5),
                          income('20250930', '20251020', 300, 30, n_income=35, minority_gain=5)]}
        f = self.finance(raw['income'])
        self.assertEqual(f['quarterly'][0]['period'], '20250930')
        self.assertEqual(f['quarterly'][0]['profitReviewPeriods'], ['20250630'])
        self.assertEqual(f['quarterly'][0]['netProfit'], 10)

    def test_review_is_bound_to_verified_values_and_missing_minority_not_zero(self):
        raw = {'income': [income('20251231', '20260320', 100, 20, n_income=40, minority_gain=5)]}
        review = {'20251231': {'totalNetProfit': 40, 'parentNetProfit': 20, 'minorityProfit': 5,
                              'status': 'available', 'note': 'Other equity holders verified',
                              'source': {'id': 'filing', 'title': 'Original report'}}}
        f = build_finance(raw, {}, '20260921', {}, 'raw.json', review)[0]
        self.assertEqual(f['annual'][0]['profitReviewPeriods'], [])
        self.assertEqual(f['profitReconciliation'][0]['status'], 'available')
        raw['income'][0]['n_income'] = 45
        f = build_finance(raw, {}, '20260921', {}, 'raw.json', review)[0]
        self.assertEqual(f['annual'][0]['profitReviewPeriods'], ['20251231'])
        del raw['income'][0]['minority_gain']
        self.assertEqual(self.finance(raw['income'])['profitReconciliation'], [])

    def test_one_yuan_difference_not_silently_assumed_rounding(self):
        f = self.finance([income('20250630', '20250820', 100, 20, n_income=26, minority_gain=5)])
        self.assertEqual(f['profitReconciliation'][0]['residual'], 1)
        self.assertEqual(f['latest']['profitReviewPeriods'], ['20250630'])


class SegmentSemantics(unittest.TestCase):
    def row(self, name, sales, **extra):
        return {'end_date': '20260630', 'bz_code': 'P', 'bz_item': name, 'bz_sales': sales, 'curr_type': 'CNY', **extra}

    def group(self, rows):
        return build_segments(rows, '20260921', {'20260630': {'total_revenue': 100}})

    def test_parent_child_not_double_counted(self):
        groups = self.group([self.row('产品', 100), self.row('产品:A', 60), self.row('产品:B', 40)])
        self.assertTrue(all(item['share'] is None for item in groups[0]['items']))

    def test_same_value_aliases_not_independent_parts(self):
        groups = self.group([self.row('其他系列酒', 20), self.row('其他酒系列', 20), self.row('茅台酒', 60)])
        self.assertTrue(all(item['share'] is None for item in groups[0]['items']))

    def test_dimensions_and_currencies_never_mix(self):
        groups = self.group([self.row('A', 60), self.row('B', 40), self.row('海外', 60, bz_code='D'), self.row('USD A', 50, curr_type='USD')])
        self.assertEqual(len(groups), 3)
        usd = next(group for group in groups if group['currency'] == 'USD')
        self.assertIsNone(usd['items'][0]['share'])
        product = next(group for group in groups if group['dimension'] == '产品' and group['currency'] == 'CNY')
        self.assertEqual(sum(item['share'] for item in product['items']), 100)

    def test_exact_duplicate_removed_new_snapshot_not_added_to_old(self):
        rows = [self.row('A', 40, _priority=0), self.row('B', 60, _priority=0),
                self.row('A', 100, _priority=2), self.row('A', 100, _priority=2)]
        groups = self.group(rows)
        self.assertEqual(len(groups[0]['items']), 1)
        self.assertEqual(groups[0]['items'][0]['revenue'], 100)

    def test_unchanged_rows_survive_new_group_snapshot(self):
        groups = self.group([self.row('A', 40, _priority=0), self.row('B', 60, _priority=0),
                             self.row('A', 40, _priority=2), self.row('B', 50, _priority=2)])
        self.assertEqual({row['name']: row['revenue'] for row in groups[0]['items']}, {'A': 40, 'B': 50})


class DossierSemantics(unittest.TestCase):
    def test_financial_company_has_explicit_distinct_caveat(self):
        dossier, _, _ = build_dossier('000001.SZ', {'name': '示例银行', 'industry': '银行'}, {}, {}, '20260921', '20260918')
        self.assertEqual(dossier['companyType'], 'bank')
        self.assertTrue(any('工业企业' in note for note in dossier['finance']['notes']))

    def test_registration_is_not_brand_founding_and_promo_not_asserted(self):
        legacy = {'company': {'setup_date': '20000101', 'intro': '公司为全球领先企业。生产设备。'}, 'list_date': '20100101'}
        dossier, _, _ = build_dossier('600000.SH', {}, legacy, {}, '20260921', '20260918')
        self.assertEqual(dossier['timeline'][0]['title'], '当前主体注册')
        self.assertNotIn('全球领先', dossier['profile']['intro'])

    def test_narrative_review_changes_only_on_new_disclosure(self):
        narrative = {'reviewedAsOf': '20260801', 'summary': {'text': '有来源正文', 'sourceIds': ['n']},
                     'businessModel': [{'title': '解释', 'text': '解释', 'kind': 'interpretation', 'sourceIds': ['n']}],
                     'sources': [{'id': 'n', 'title': '文档', 'publishedAt': '20260701'}]}
        old_evidence = {'reportPeriod': '20260331', 'reportAnnDate': '20260420', 'revenue': 2, 'revenueField': 'total_revenue'}
        d, _, _ = build_dossier('600000.SH', old_evidence, {}, {}, '20260921', '20260918', narrative)
        self.assertEqual(d['coverage']['research']['status'], 'partial')
        new_evidence = dict(old_evidence, reportPeriod='20260630', reportAnnDate='20260820')
        d, _, _ = build_dossier('600000.SH', new_evidence, {}, {}, '20260921', '20260918', narrative)
        self.assertEqual(d['coverage']['businessModel']['status'], 'review')

    def test_unresolved_sources_rejected(self):
        dossier, _, _ = build_dossier('600000.SH', {}, {}, {}, '20260921', '20260918')
        dossier['summary']['sourceIds'] = ['not-real']
        with self.assertRaises(ValueError):
            validate_dossier(dossier)


class SnapshotAtomicity(unittest.TestCase):
    def test_overlay_a_share_universe_immutable_reuse_and_failed_index_switch(self):
        spec = importlib.util.spec_from_file_location('builder', Path(__file__).with_name('build-company-data.py'))
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app = root / 'app'
            app.mkdir()
            builder.APP = app
            kb, output, overlay = root / 'source', root / 'output', root / 'overlay'
            (kb / 'site/data/stocks').mkdir(parents=True)
            overlay.mkdir()
            evidence_file = app / 'evidence.json'
            evidence_file.write_text(json.dumps({'schemaVersion': 2, 'status': 'complete', 'tradeDate': '20260918', 'stocks': {}}))
            (overlay / 'stocks.json').write_text(json.dumps([{'ts_code': '600000.SH', 'name': 'A', 'list_status': 'L'}, {'ts_code': '900001.SH', 'list_status': 'L'}]))
            (overlay / 'status.json').write_text(json.dumps({'asOf': '20260921'}))
            args = SimpleNamespace(knowledge_root=str(kb), output_dir=str(output), evidence_file=str(evidence_file), overlay_root=str(overlay), as_of='20260921')
            with contextlib.redirect_stdout(io.StringIO()):
                first = builder.build(args)
                second = builder.build(args)
            self.assertEqual(first['snapshotId'], second['snapshotId'])
            self.assertEqual(first['coverage']['total'], 1)
            before = (output / 'index.json').read_bytes()
            dossier_file = output / 'snapshots' / first['snapshotId'] / '600000.SH.json'
            dossier_file.write_text('{}')
            with self.assertRaises(ValueError), contextlib.redirect_stdout(io.StringIO()):
                builder.build(args)
            self.assertEqual(before, (output / 'index.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
