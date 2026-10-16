"""Failure and revision regression tests. No network or original data writes."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('company_updates', Path(__file__).with_name('check-company-updates.py'))
updates = importlib.util.module_from_spec(spec)
spec.loader.exec_module(updates)


def row(value, **extra):
    return dict(ts_code='600519.SH', end_date='20260630', ann_date='20260801',
                report_type='1', update_flag='1', revenue=value, **extra)


class UpdateSafety(unittest.TestCase):
    def test_returned_segment_dimension_replaces_whole_group_only(self):
        def segment(dimension, name, value, period='20260630'):
            return dict(end_date=period, bz_code=dimension, bz_item=name, bz_sales=value, curr_type='CNY')
        old = [segment('P', 'Old', 40), segment('P', 'Kept', 60), segment('D', 'Local', 100),
               segment('455006000', 'Direct', 50), segment('P', 'Prior year', 100, '20251231')]
        new = [segment('P', 'New', 100)]
        result = updates.merge_segments(old, new)
        self.assertEqual(len(result), 4)
        self.assertIn(new[0], result)
        self.assertTrue(all(item in result for item in old[2:]))
        self.assertEqual(updates.merge_segments(old, []), sorted(old, key=updates.fingerprint))

    def test_failed_state_commit_restores_every_index(self):
        with tempfile.TemporaryDirectory() as directory:
            destinations = [Path(directory) / 'public', Path(directory) / 'dist']
            old = {'snapshotId': 'old'}
            candidate = {'snapshotId': 'candidate'}
            for target in destinations:
                updates.write(target / 'index.json', old)
            def fail_state(index):
                self.assertEqual(index, candidate)
                raise OSError('state commit failed')
            with patch.object(updates, 'stage_snapshot', return_value=(old, candidate)):
                with self.assertRaisesRegex(OSError, 'state commit'):
                    updates.publish_all(Path(directory), destinations, fail_state)
            for target in destinations:
                self.assertEqual(updates.read(target / 'index.json'), old)

    def test_import_without_private_hash_still_detects_data_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            overlay, knowledge = root / 'overlay', root / 'kb'
            updates.write(overlay / 'status.json', {'asOf': '20260925'})
            updates.write(overlay / 'financial/000001.SZ.json', {'income': [row(100)]})
            before = updates.input_fingerprint(overlay, knowledge)
            updates.write(overlay / 'financial/000001.SZ.json', {'income': [row(101)]})
            self.assertNotEqual(before, updates.input_fingerprint(overlay, knowledge))

    def test_public_index_baseline_protects_first_update(self):
        baseline = [{'code': f'{n:06d}.SH'} for n in range(2500)] + [{'code':f'{n:06d}.SZ'} for n in range(2500)] + [{'code':f'{n:06d}.BJ'} for n in range(500)]
        truncated = [{'ts_code':r['code']} for r in baseline if not (r['code'].endswith('.SH') and int(r['code'][:6]) < 800)]
        self.assertGreater(len(truncated), 4000)
        with self.assertRaisesRegex(ValueError, 'removals'):
            updates.validate_universe(truncated, baseline)
        updates.validate_universe([{'ts_code':r['code']} for r in baseline], baseline)

    def test_same_revision_fresh_response_replaces_entire_row(self):
        result = updates.merge_disclosures([row(100, rd_exp=12)], [row(110)])
        self.assertEqual(result, [row(110)])
        self.assertNotIn('rd_exp', result[0])

    def test_conflicting_fresh_revisions_block_update(self):
        with self.assertRaisesRegex(ValueError, 'unresolved'):
            updates.merge_disclosures([], [row(100), row(110)])

    def test_identical_api_rechecks_do_not_duplicate(self):
        self.assertEqual(updates.merge_disclosures([row(100)], [row(110), row(110)]), [row(110)])

    def test_review_periods_cross_year_and_exclude_incomplete_period(self):
        periods = updates.review_periods('20260921')
        self.assertIn('20251231', periods)
        self.assertIn('20211231', periods)
        self.assertIn('20260630', periods)
        self.assertNotIn('20260930', periods)
        self.assertEqual(len(periods), len(set(periods)))

    def test_repeated_pagination_is_rejected(self):
        class RepeatingAPI:
            def call(self, *args, **kwargs): return [row(100)]
        with self.assertRaisesRegex(ValueError, 'repeated'):
            list(updates.pages(RepeatingAPI(), 'income_vip', {}, 'revenue', page_size=1))

    def test_second_pointer_failure_restores_first(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / 'public', Path(directory) / 'dist'
            old_a, old_b, candidate = {'snapshotId':'a'}, {'snapshotId':'b'}, {'snapshotId':'new'}
            updates.write(a / 'index.json', old_a)
            updates.write(b / 'index.json', old_b)
            real_write = updates.write
            def failing_write(path, value):
                if path == b / 'index.json' and value == candidate:
                    raise OSError('Injected second-destination failure')
                real_write(path, value)
            with patch.object(updates, 'stage_snapshot', side_effect=[(old_a,candidate),(old_b,candidate)]), patch.object(updates, 'write', side_effect=failing_write):
                with self.assertRaisesRegex(OSError, 'Injected'):
                    updates.publish_all(Path(directory), [a,b])
            self.assertEqual(updates.read(a / 'index.json'), old_a)
            self.assertEqual(updates.read(b / 'index.json'), old_b)

    def test_all_staging_completes_before_pointer_changes(self):
        with patch.object(updates, 'stage_snapshot', side_effect=[({},{}), ValueError('Invalid second target')]), patch.object(updates, 'write') as writer:
            with self.assertRaises(ValueError):
                updates.publish_all(Path('candidate'), [Path('public'),Path('dist')])
            writer.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
