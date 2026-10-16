"""Release identity failure cases; isolated fixtures never modify the live app."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from release_common import validate_site_version, require_version_progress

APP = Path(__file__).resolve().parents[1]
VERSION = {"version": "1.0.0", "date": "2026-09-27", "revision": "0123456789ab",
           "changes": ["版本入口"], "history": [{"version": "1.0.0", "date": "2026-09-27", "changes": ["版本入口"]}]}


class WebsiteVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "index.html").write_text('<meta name="application-version" content="1.0.0+0123456789ab">', encoding="utf-8")
        self.write_version(VERSION)

    def write_version(self, value):
        (self.root / "version.json").write_text(json.dumps(value), encoding="utf-8")

    def test_valid_metadata(self):
        self.assertEqual(validate_site_version(self.root)["version"], "1.0.0")

    def test_html_fallback_is_not_version_json(self):
        (self.root / "version.json").write_text('<html>SPA fallback</html>')
        with self.assertRaises(ValueError):
            validate_site_version(self.root)

    def test_mixed_html_and_json_rejected(self):
        changed = copy.deepcopy(VERSION)
        changed["revision"] = "aaaaaaaaaaaa"
        self.write_version(changed)
        with self.assertRaisesRegex(ValueError, "disagree"):
            validate_site_version(self.root)

    def test_missing_metadata_fails_but_legacy_verifies(self):
        (self.root / "version.json").unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            validate_site_version(self.root)
        (self.root / "index.html").write_text('<html>legacy</html>')
        self.assertIsNone(validate_site_version(self.root))

    def test_data_only_allowed_but_same_version_changed_code_rejected(self):
        require_version_progress(VERSION, VERSION)
        require_version_progress(None, VERSION)
        with self.assertRaisesRegex(ValueError, "version bump"):
            require_version_progress(VERSION, {**VERSION, "revision": "bbbbbbbbbbbb"})
        require_version_progress(VERSION, {**VERSION, "version": "1.0.1", "revision": "bbbbbbbbbbbb"})

    def test_downgrade_and_unversioned_candidate_rejected(self):
        with self.assertRaisesRegex(ValueError, "decrease"):
            require_version_progress(VERSION, {**VERSION, "version": "0.9.0"})
        with self.assertRaisesRegex(ValueError, "require version.json"):
            require_version_progress(VERSION, None)

    def test_history_must_match_current(self):
        changed = copy.deepcopy(VERSION)
        changed["history"][0]["changes"] = ["other"]
        self.write_version(changed)
        with self.assertRaisesRegex(ValueError, "history mismatch"):
            validate_site_version(self.root)

    def test_bump_preserves_history_and_syncs_package_files(self):
        (self.root / 'scripts').mkdir()
        shutil.copyfile(APP / 'scripts/bump-site-version.mjs', self.root / 'scripts/bump-site-version.mjs')
        fixtures = {
            'package.json': {'name': 'isolated-version-test', 'version': '1.0.0'},
            'package-lock.json': {'version': '1.0.0', 'packages': {'': {'version': '1.0.0'}}},
            'release-history.json': copy.deepcopy(VERSION['history']),
        }
        for file, data in fixtures.items():
            (self.root / file).write_text(json.dumps(data), encoding='utf-8')
        for kind, expected in [('patch', '1.0.1'), ('minor', '1.1.0'), ('major', '2.0.0')]:
            result = subprocess.run([shutil.which('node') or 'node', str(self.root / 'scripts/bump-site-version.mjs'), kind, '验证说明'], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            history = json.loads((self.root / 'release-history.json').read_text('utf-8'))
            package = json.loads((self.root / 'package.json').read_text('utf-8'))
            lock = json.loads((self.root / 'package-lock.json').read_text('utf-8'))
            self.assertEqual([history[0]['version'], package['version'], lock['version'], lock['packages']['']['version']], [expected] * 4)
        self.assertEqual([row['version'] for row in history], ['2.0.0', '1.1.0', '1.0.1', '1.0.0'])


if __name__ == '__main__':
    unittest.main()
