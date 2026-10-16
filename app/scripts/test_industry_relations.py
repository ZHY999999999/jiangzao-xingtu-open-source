"""Tests for official SW parent joins, member lineage and safe refresh failure."""
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

SPEC = importlib.util.spec_from_file_location('industry_relations', Path(__file__).with_name('build-industry-relations.py'))
DATA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DATA)

CATALOG = [
    {'index_code': '801770.SI', 'industry_name': '通信', 'level': 'L1', 'industry_code': '730000', 'parent_code': '0', 'src': 'SW2021', 'is_pub': '1'},
    {'index_code': '801102.SI', 'industry_name': '通信设备', 'level': 'L2', 'industry_code': '730200', 'parent_code': '730000', 'src': 'SW2021', 'is_pub': '1'},
    {'index_code': '851024.SI', 'industry_name': '通信网络设备及器件', 'level': 'L3', 'industry_code': '730204', 'parent_code': '730200', 'src': 'SW2021', 'is_pub': '1'},
    {'index_code': '851025.SI', 'industry_name': 'Empty leaf', 'level': 'L3', 'industry_code': '730205', 'parent_code': '730200', 'src': 'SW2021', 'is_pub': '0'},
]
MEMBER = {'l1_code': '801770.SI', 'l1_name': '通信', 'l2_code': '801102.SI', 'l2_name': '通信设备',
          'l3_code': '851024.SI', 'l3_name': '通信网络设备及器件', 'ts_code': '300308.SZ', 'name': '中际旭创', 'is_new': 'Y'}
EVIDENCE = {'stocks': {'300308.SZ': {'name': '中际旭创', 'listStatus': 'L'},
                       '999999.SZ': {'name': 'Uncovered stock', 'listStatus': 'L'}},
            'industries': {'881129.TI': {'code': '881129.TI', 'name': '通信设备', 'members': ['300308.SZ']}}}


class IndustryRelationTests(unittest.TestCase):
    def result(self, catalog=None, rows=None, evidence=None):
        return DATA.build(deepcopy(catalog or CATALOG), deepcopy(rows if rows is not None else [MEMBER]),
                          deepcopy(evidence or EVIDENCE), '2026-09-22', 'test-cache')

    def test_official_parent_codes_join_to_index_codes(self):
        result = self.result()
        boards = {b['code']: b for b in result['boards']}
        self.assertEqual(len(boards), 4)
        self.assertEqual(len(result['relations']), 3)
        self.assertIsNone(boards['801770.SI']['parentCode'])
        self.assertEqual(boards['801102.SI']['parentCode'], '801770.SI')
        self.assertEqual(boards['801102.SI']['parentIndustryCode'], '730000')
        self.assertEqual(boards['851024.SI']['parentCode'], '801102.SI')
        self.assertEqual(boards['801770.SI']['members'], ['300308.SZ'])
        self.assertEqual(boards['851025.SI']['membershipStatus'], 'empty_source')
        self.assertTrue(all(r['verificationStatus'] == 'verified' and r['sourceRefs'] for r in result['relations']))

    def test_matching_ths_names_do_not_create_cross_system_links(self):
        result = self.result()
        self.assertNotIn('881129.TI', {b['code'] for b in result['boards']})
        self.assertTrue(all(r[x]['system'] == 'sw2021' for r in result['relations'] for x in ('from', 'to')))

    def test_unknown_members_and_listing_gaps_are_explicit(self):
        new = {**MEMBER, 'ts_code': '111111.SZ', 'name': 'New source member'}
        original = deepcopy(EVIDENCE)
        result = DATA.build(CATALOG, [MEMBER, new], EVIDENCE, '2026-09-22', 'test-cache')
        self.assertEqual(EVIDENCE, original)
        self.assertEqual(result['stockNames']['111111.SZ'], 'New source member')
        self.assertEqual(result['coverage']['membersMissingFromEvidence'], ['111111.SZ'])
        self.assertEqual(result['coverage']['unresolved'][0]['code'], '999999.SZ')

    def test_invalid_parent_and_member_lineage_fail(self):
        bad_catalog = deepcopy(CATALOG)
        bad_catalog[2]['parent_code'] = '730000'
        with self.assertRaises(DATA.SHARED.APIError):
            self.result(catalog=bad_catalog)
        with self.assertRaises(DATA.SHARED.APIError):
            self.result(rows=[{**MEMBER, 'l2_code': '801770.SI'}])
        with self.assertRaises(DATA.SHARED.APIError):
            self.result(rows=[{**MEMBER, 'l1_code': 'UNKNOWN.SI'}])

    def test_unknown_source_leaf_keeps_verified_ancestors_without_aliasing(self):
        result = self.result(rows=[{**MEMBER, 'l3_code': 'UNKNOWN.SI'}])
        boards = {b['code']: b for b in result['boards']}
        self.assertEqual(boards['801102.SI']['members'], ['300308.SZ'])
        self.assertEqual(boards['851024.SI']['members'], [])
        self.assertNotIn('UNKNOWN.SI', boards)
        self.assertEqual(result['coverage']['membershipPathGaps'][0]['sourceIndexCode'], 'UNKNOWN.SI')
        self.assertEqual(result['status'], 'complete_with_source_gaps')
        self.assertIn('UNKNOWN.SI', boards['851024.SI']['membershipWarning'])
        self.assertEqual(boards['851024.SI']['membershipWarningDetails']['catalogCode'], '851024.SI')
        self.assertFalse(boards['851024.SI']['membershipWarningDetails']['inferredAlias'])

    def test_listing_status_uses_exact_codes_not_retirement_names(self):
        rows = [MEMBER, {**MEMBER, 'ts_code': '111111.SZ', 'name': 'Unknown(退市)'},
                {**MEMBER, 'ts_code': '222222.SZ', 'name': 'Delisted without suffix'},
                {**MEMBER, 'ts_code': '333333.SZ', 'name': 'Suspended'}]
        listings = {'300308.SZ': {'list_status': 'L'}, '222222.SZ': {'list_status': 'D'},
                    '333333.SZ': {'list_status': 'P'}}
        result = DATA.build(CATALOG, rows, EVIDENCE, '2026-09-22', 'test-cache', listings)
        self.assertEqual(result['coverage']['stockStatusCounts'], {'L': 1, 'D': 1, 'P': 1, 'null': 1})
        self.assertIsNone(result['stockStatuses']['111111.SZ']['listStatus'])
        self.assertEqual(result['stockStatuses']['222222.SZ']['listStatus'], 'D')
        self.assertEqual(set(result['stockStatuses']), set(result['stockNames']))

    def test_offline_listing_requires_successful_same_date_complete_caches(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            requests = [('stock_basic-' + ex, {'exchange': ex, 'list_status': 'L'},
                         [{'ts_code': ex, 'list_status': 'L'}]) for ex in ('SSE', 'SZSE', 'BSE')]
            requests += [('stock_basic-status-D', {'list_status': 'D'}, [{'ts_code': 'retired', 'list_status': 'D'}]),
                         ('stock_basic-status-P', {'list_status': 'P'}, [])]
            for label, params, rows in requests:
                (cache / (label + '.json')).write_text(json.dumps({'api': 'stock_basic', 'params': params,
                    'status': 'success', 'fetchedAt': '2026-09-22T03:55:07+00:00', 'rows': rows}), encoding='utf-8')
            listings, sources = DATA.load_cached_listing(cache, '2026-09-22')
            self.assertEqual(listings['retired']['list_status'], 'D')
            self.assertEqual(len(sources), 5)
            with self.assertRaises(DATA.SHARED.APIError):
                DATA.load_cached_listing(cache, '2026-09-21')
            (cache / 'stock_basic-status-P.json').unlink()
            with self.assertRaises(DATA.SHARED.APIError):
                DATA.load_cached_listing(cache, '2026-09-22')

    def test_duplicate_and_noncurrent_rows_do_not_inflate_members(self):
        result = self.result(rows=[MEMBER, MEMBER, {**MEMBER, 'ts_code': '222222.SZ', 'is_new': 'N'}])
        self.assertEqual(result['coverage']['duplicateMemberRows'], 1)
        self.assertEqual(result['coverage']['stockCount'], 1)
        self.assertEqual(len(result['coverage']['excludedMemberships']), 1)

    def test_capped_sector_response_is_refetched_by_official_children(self):
        class Client:
            def __init__(self): self.params = []
            def call(self, api, params, fields, label, **kwargs):
                self.params.append(params)
                return [MEMBER] * 2000 if 'l1_code' in params else [MEMBER]
        client = Client()
        rows = DATA.collect_sector(client, CATALOG[0], CATALOG)
        self.assertEqual(len(rows), 1)
        self.assertEqual(client.params[-1], {'l2_code': '801102.SI', 'is_new': 'Y'})

    def test_failed_collection_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'src/lib/industry-relations.json'
            output.parent.mkdir(parents=True)
            before = json.dumps(self.result(), ensure_ascii=False).encode('utf-8')
            output.write_bytes(before)
            (output.parent / 'evidence-data.json').write_text(json.dumps(EVIDENCE), encoding='utf-8')
            class Client:
                def __init__(self, *args): self.token = ''
                def call(self, api, *args, **kwargs):
                    if api == 'index_classify': return deepcopy(CATALOG)
                    raise DATA.SHARED.APIError('Simulated member collection failure')
            with patch.object(DATA, 'ROOT', root), patch.object(DATA.SHARED, 'Client', Client), \
                    patch.object(DATA, 'load_cached_listing', return_value=({}, [])), redirect_stdout(io.StringIO()):
                with self.assertRaises(DATA.SHARED.APIError):
                    DATA.run(SimpleNamespace(as_of='2026-09-22', offline=True))
            self.assertEqual(output.read_bytes(), before)

    def test_missing_listing_cache_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / 'src/lib/industry-relations.json'
            output.parent.mkdir(parents=True)
            before = json.dumps(self.result(), ensure_ascii=False).encode('utf-8')
            output.write_bytes(before)
            with patch.object(DATA, 'ROOT', root), redirect_stdout(io.StringIO()):
                with self.assertRaises(DATA.SHARED.APIError):
                    DATA.run(SimpleNamespace(as_of='2026-09-22', offline=True))
            self.assertEqual(output.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
