"""Regression tests for complete THS catalogs and atomic classification refreshes."""
from contextlib import redirect_stdout
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('enrich_evidence', Path(__file__).with_name('enrich-evidence.py'))
DATA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DATA)


def catalog_row(code, name, kind='N', count=1):
    return {'ts_code': code, 'name': name, 'type': kind, 'exchange': 'A', 'count': count}


CONCEPTS = [catalog_row('886033.TI', '共封装光学(CPO)', count=2),
            catalog_row('885792.TI', '赛马概念'),
            catalog_row('887001.TI', 'Future prefix'),
            catalog_row('883001.TI', 'Source concept'),
            catalog_row('885338.TI', '融资融券')]
INDUSTRIES = [catalog_row('881001.TI', 'Industry', 'I', 2),
              catalog_row('884001.TI', 'Subindustry', 'I'),
              catalog_row('700001.TI', 'Separate index series', 'I')]


class FakeClient:
    fail_member = None

    def __init__(self, as_of, offline=False):
        self.as_of, self.token, self.calls = as_of, '', []
        self.cache = DATA.DIAGNOSTICS / ('test-cache-' + as_of)

    def call(self, api, params, fields, label, required=True, audit_file=None):
        if api == 'ths_index':
            return deepcopy(CONCEPTS if params['type'] == 'N' else INDUSTRIES)
        if api == 'ths_member':
            if params['ts_code'] == self.fail_member:
                raise DATA.APIError('Simulated collection failure')
            codes = ['000001.SZ', '999999.SZ'] if params['ts_code'] in ('886033.TI', '881001.TI') else ['000001.SZ']
            return [{'ts_code': params['ts_code'], 'con_code': c, 'con_name': 'Source member ' + c,
                     'is_new': 'Y'} for c in codes]
        if api == 'daily':
            return [{'ts_code': '000001.SZ', 'trade_date': '20260918', 'amount': 100000, 'pct_chg': 2}]
        if api == 'daily_basic':
            return [{'ts_code': '000001.SZ', 'trade_date': '20260918', 'total_mv': 30000, 'turnover_rate': 3}]
        if api == 'ths_daily':
            return [{'ts_code': '886033.TI', 'trade_date': '20260918', 'pct_change': 1.5}]
        if api == 'stock_basic':
            if params.get('list_status') in ('D', 'P'):
                return []
            return [{'ts_code': '000001.SZ', 'name': 'Known stock', 'industry': 'Legacy industry', 'list_status': 'L'}]
        if api == 'stock_company':
            return [{'ts_code': '000001.SZ', 'main_business': 'Disclosed business', 'business_scope': 'Disclosed scope'}]
        if api == 'income_vip':
            return [{'ts_code': '000001.SZ', 'ann_date': '20260830', 'f_ann_date': '20260830',
                     'end_date': '20260630', 'report_type': '1', 'total_revenue': 200000000,
                     'n_income_attr_p': 10000000, 'comp_type': '1', 'update_flag': '1'}]
        raise AssertionError(api)


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / 'src/lib/evidence-data.json'
        self.args = SimpleNamespace(trade_date='20260918', membership_as_of='20260922',
                                    financial_period='20260630', offline=True)

    def build(self, client=FakeClient):
        with patch.object(DATA, 'ROOT', self.root), patch.object(DATA, 'DIAGNOSTICS', self.root / 'diagnostics'), \
                patch.object(DATA, 'Client', client), redirect_stdout(io.StringIO()):
            DATA.build(self.args)
        return json.loads(self.output.read_text(encoding='utf-8'))

    def test_no_concept_prefix_size_or_name_filter(self):
        selected, coverage = DATA.select_catalog(CONCEPTS, 'N')
        self.assertEqual(len(CONCEPTS), len(selected))
        self.assertEqual(coverage['sourceCount'], coverage['includedCount'])
        self.assertEqual(coverage['excluded'], [])
        self.assertIn('887001.TI', {b['ts_code'] for b in selected})
        self.assertIn('885792.TI', {b['ts_code'] for b in selected})
        self.assertIn('885338.TI', {b['ts_code'] for b in selected})

    def test_industry_levels_and_exclusions_are_explicit(self):
        selected, coverage = DATA.select_catalog(INDUSTRIES, 'I')
        self.assertEqual([b['level'] for b in selected], ['industry', 'subindustry'])
        self.assertEqual(coverage['sourceCount'], 3)
        self.assertEqual(coverage['includedCount'], 2)
        self.assertEqual(coverage['excludedCount'], 1)
        self.assertEqual(coverage['excluded'][0]['code'], '700001.TI')
        self.assertFalse(coverage['hierarchyVerified'])

    def test_build_preserves_unknown_member_and_reverse_memberships(self):
        evidence = self.build()
        self.assertEqual(evidence['schemaVersion'], 2)
        self.assertEqual(evidence['boards']['共封装光学(CPO)']['code'], '886033.TI')
        unknown = evidence['stocks']['999999.SZ']
        for field in ('pct', 'amount', 'mv', 'revenue', 'profit', 'industry', 'listStatus'):
            self.assertIsNone(unknown[field], field)
        self.assertEqual(unknown['concepts'], ['共封装光学(CPO)'])
        self.assertEqual(unknown['thsIndustries'], [{'code': '881001.TI', 'name': 'Industry', 'level': 'industry'}])
        self.assertEqual(evidence['stocks']['000001.SZ']['industry'], 'Legacy industry')
        self.assertNotIn('Industry', evidence['stocks']['000001.SZ']['concepts'])
        self.assertEqual(evidence['financialAsOf'], '20260918')
        self.assertEqual(evidence['membershipAsOf'], '20260922')
        DATA.validate_classifications(evidence)

    def test_validation_rejects_one_sided_or_missing_members(self):
        evidence = self.build()
        evidence['stocks']['999999.SZ']['thsIndustries'] = []
        with self.assertRaisesRegex(DATA.APIError, 'reverse membership'):
            DATA.validate_classifications(evidence)
        evidence = self.build()
        del evidence['stocks']['999999.SZ']
        with self.assertRaisesRegex(DATA.APIError, 'stock missing'):
            DATA.validate_classifications(evidence)

    def test_failed_collection_preserves_existing_snapshot(self):
        self.build()
        before = self.output.read_bytes()
        class FailedClient(FakeClient):
            fail_member = '884001.TI'
        with self.assertRaisesRegex(DATA.APIError, 'Simulated collection failure'):
            self.build(FailedClient)
        self.assertEqual(self.output.read_bytes(), before)

    def test_delisted_source_member_is_retained_with_explicit_status(self):
        class DelistedClient(FakeClient):
            def call(self, api, params, fields, label, **kwargs):
                if api == 'stock_basic' and params.get('list_status') == 'D':
                    return [{'ts_code': '999999.SZ', 'name': 'Historical source member', 'list_status': 'D'},
                            {'ts_code': '888888.SZ', 'name': 'Unrelated delisted stock', 'list_status': 'D'}]
                return super().call(api, params, fields, label, **kwargs)
        evidence = self.build(DelistedClient)
        self.assertEqual(evidence['stocks']['999999.SZ']['listStatus'], 'D')
        self.assertIn('999999.SZ', evidence['boards']['共封装光学(CPO)']['members'])
        self.assertNotIn('888888.SZ', evidence['stocks'])
        self.assertEqual(evidence['coverage']['delistedMemberStocks'], 1)

    def test_empty_source_list_is_kept_and_unknown_metrics_stay_null(self):
        row = catalog_row('884253.TI', 'Empty source industry', 'I', None)
        row['level'] = 'subindustry'
        result = DATA.classification_row(row, {row['ts_code']: {}}, {}, {}, '20260922')
        self.assertEqual(result['members'], [])
        self.assertEqual(result['membershipStatus'], 'empty_source')
        self.assertIsNone(result['amount'])
        self.assertIsNone(result['mv'])
        self.assertIsNone(result['pct'])
        self.assertIsNone(result['weightedPct'])

    def test_catalog_integrity_and_accounting_are_validated(self):
        for bad in ([], CONCEPTS + [CONCEPTS[0]], [catalog_row('881001.TI', 'Wrong type', 'I')]):
            with self.assertRaises(DATA.APIError):
                DATA.select_catalog(bad, 'N')
        evidence = self.build()
        evidence['catalogCoverage']['concepts']['sourceCount'] += 1
        with self.assertRaisesRegex(DATA.APIError, 'source count mismatch'):
            DATA.validate_classifications(evidence)


if __name__ == '__main__':
    unittest.main()
