"""Offline release fault tests; all test artifacts remain in diagnostics/release."""
import copy
import os
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import unittest
from unittest.mock import patch

import release_bundle
import release_common as common
import release_remote as remote

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent / "diagnostics/release" / ("selftest-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
ROOT.mkdir(parents=True)
BASE = ROOT / "base"
BASE.mkdir()
(BASE / "assets").mkdir()
(BASE / "index.html").write_text('<script type="module" src="/assets/main.js"></script><link href="/assets/style.css" rel="stylesheet">', encoding="utf-8")
(BASE / "assets/main.js").write_text('import "./chunk.js";', encoding="utf-8")
(BASE / "assets/chunk.js").write_text('console.log("ready");', encoding="utf-8")
(BASE / "assets/style.css").write_text("body{color:black}", encoding="utf-8")
source = Path(os.environ.get("ATLAS_PUBLIC_ROOT", str(APP / "public"))) / "data/companies"
index = common.load_json(source / "index.json")
entries = index["companies"][:2]
digest = hashlib.sha256()
docs = {}
for entry in entries:
    data = (source / "snapshots" / index["snapshotId"] / (entry["code"] + ".json")).read_bytes()
    digest.update(entry["code"].encode("ascii"))
    digest.update(data)
    docs[entry["code"]] = data
index["snapshotId"] = index["asOf"] + "-" + digest.hexdigest()[:16]
index["companies"] = entries
index["coverage"] = {"total": 2, "basic": 2, "deep": sum(entry["depth"] == "deep" for entry in entries),
                       "financialHistory": sum(entry["hasHistory"] for entry in entries),
                       "missingProfiles": sum(not json.loads(data)["profile"]["mainBusiness"] for data in docs.values())}
snapshot = BASE / "data/companies/snapshots" / index["snapshotId"]
snapshot.mkdir(parents=True)
for code, data in docs.items():
    (snapshot / (code + ".json")).write_bytes(data)
(BASE / "data/companies/index.json").write_bytes(common.json_bytes(index))


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.root = ROOT / hashlib.sha256(self._testMethodName.encode()).hexdigest()[:6]
        self.site = self.root / "dist"
        shutil.copytree(BASE, self.site)

    def test_valid_all_companies_and_asset_graph(self):
        summary, files = common.validate_site(self.site, 2)
        self.assertEqual(summary["companyCount"], 2)
        self.assertIn("assets/chunk.js", summary["assetReferences"])

    def test_brand_and_market_dependencies_are_complete(self):
        brand = self.site / 'images/brand/noise-lab-logo-night.png'
        brand.parent.mkdir(parents=True)
        brand.write_bytes(b'public-image-fixture')
        script = self.site / 'assets/chunk.js'
        script.write_text('const logo="/images/brand/noise-lab-logo-night.png"; fetch("/data/market/latest.json");')
        with self.assertRaisesRegex(ValueError, 'Missing asset'):
            common.validate_site(self.site, 2)
        market = self.site / 'data/market/latest.json'
        market.parent.mkdir(parents=True)
        payload = {'schemaVersion':1,'tradeDate':'2026-09-24','coverage':{'listed':2,'valued':1,'missing':1},
                   'stocks':{'000001.SZ':{'mv':123},'000002.SZ':{'mv':None}},'source':{'field':'total_mv','unit':'亿元'}}
        market.write_bytes(common.json_bytes(payload))
        summary, _ = common.validate_site(self.site, 2)
        self.assertIn('data/market/latest.json', summary['assetReferences'])
        self.assertIn('images/brand/noise-lab-logo-night.png', summary['assetReferences'])
        payload['coverage']['valued'] = 2
        market.write_bytes(common.json_bytes(payload))
        with self.assertRaisesRegex(ValueError, 'Market coverage'):
            common.validate_site(self.site, 2)

    def test_new_public_paths_do_not_allow_private_files(self):
        for path in ('images/brand/private.json', 'data/market/state.json', 'fonts/private.md', 'diagnostics/report.json', 'audio/private.json', 'audio/companies/601138/receipt.json', 'images/company/private.png'):
            self.assertFalse(common.allowed_path(path,index['snapshotId']), path)
        self.assertTrue(common.allowed_path('fonts/noise-atlas-display-LICENSE.txt',index['snapshotId']))

    def test_company_narration_dependency_is_required(self):
        script = self.site / 'assets/chunk.js'
        script.write_text('const narration="/audio/companies/601138/overview-2025.mp3?v=verified";')
        with self.assertRaisesRegex(ValueError, 'Missing asset'):
            common.validate_site(self.site, 2)
        audio = self.site / 'audio/companies/601138/overview-2025.mp3'
        audio.parent.mkdir(parents=True)
        audio.write_bytes(b'public-audio-fixture')
        summary, _ = common.validate_site(self.site, 2)
        self.assertIn('audio/companies/601138/overview-2025.mp3', summary['assetReferences'])

    def test_independent_count_prevents_silent_drop(self):
        with self.assertRaisesRegex(ValueError, "Expected 3"):
            common.validate_site(self.site, 3)

    def test_missing_company_rejected(self):
        (self.site / "data/companies/snapshots" / index["snapshotId"] / (entries[0]["code"] + ".json")).unlink()
        with self.assertRaisesRegex(ValueError, "every indexed company"):
            common.validate_site(self.site, 2)

    def test_schema_damage_rejected(self):
        path = self.site / "data/companies/snapshots" / index["snapshotId"] / (entries[0]["code"] + ".json")
        doc = common.load_json(path)
        del doc["finance"]
        path.write_bytes(common.json_bytes(doc))
        with self.assertRaisesRegex(ValueError, "finance"):
            common.validate_site(self.site, 2)

    def test_unknown_source_reference_rejected(self):
        path = self.site / "data/companies/snapshots" / index["snapshotId"] / (entries[0]["code"] + ".json")
        doc = common.load_json(path)
        doc["summary"]["sourceIds"] = ["does-not-exist"]
        path.write_bytes(common.json_bytes(doc))
        with self.assertRaisesRegex(ValueError, "unresolved source"):
            common.validate_site(self.site, 2)

    def test_content_mutation_rejected(self):
        path = self.site / "data/companies/snapshots" / index["snapshotId"] / (entries[0]["code"] + ".json")
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "Snapshot content hash"):
            common.validate_site(self.site, 2)

    def test_missing_asset_rejected(self):
        (self.site / "assets/chunk.js").unlink()
        with self.assertRaisesRegex(ValueError, "Missing asset"):
            common.validate_site(self.site, 2)

    def test_secret_or_source_file_rejected(self):
        (self.site / ".env").write_text("placeholder")
        with self.assertRaisesRegex(ValueError, "Unexpected/nonpublic"):
            common.validate_site(self.site, 2)

    def test_historical_snapshot_excluded_and_archive_verifies(self):
        old = self.site / "data/companies/snapshots/20200101-0000000000000000"
        old.mkdir()
        (old / "000001.SZ.json").write_text("{}")
        report = release_bundle.build(self.site, self.root / "output", 2)
        self.assertEqual(report["excludedHistoricalFiles"], 1)
        destination = self.root / "extracted"
        # Capacity has dedicated fault tests; this test isolates archive extraction
        # and remains runnable on Windows without pretending to test statvfs.
        with patch.object(remote, "fsync_dir"), patch.object(remote, "check_capacity", return_value={"status": "mocked_for_archive_test"}):
            remote.safe_extract(Path(report["archive"]), destination, report["releaseId"])
        manifest = common.verify_release(destination)
        self.assertEqual(manifest["validation"]["companyCount"], 2)

    def test_archive_traversal_rejected_before_writing(self):
        path = self.root / "malicious.tar.gz"
        with tarfile.open(path, "w:gz") as tar:
            item = tarfile.TarInfo("../outside.txt")
            item.size = 1
            tar.addfile(item, io.BytesIO(b"x"))
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            remote.safe_extract(path, self.root / "extracted", "ignored")
        self.assertFalse((self.root / "extracted").exists())

    def test_archive_symlink_rejected(self):
        path = self.root / "symlink.tar.gz"
        with tarfile.open(path, "w:gz") as tar:
            item = tarfile.TarInfo("site/assets/evil")
            item.type = tarfile.SYMTYPE
            item.linkname = "/etc/passwd"
            tar.addfile(item)
        with self.assertRaisesRegex(ValueError, "regular files only"):
            remote.safe_extract(path, self.root / "extracted", "ignored")

    def test_immutable_collision_rejected(self):
        target = self.root / "target.js"
        target.write_text("different")
        with self.assertRaisesRegex(ValueError, "collision"):
            remote.hardlink(self.site / "assets/chunk.js", target)

    def test_duplicate_and_nonfinite_json_rejected(self):
        path = self.root / "invalid.json"
        path.write_text('{"a":1,"a":2}')
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            common.load_json(path)
        path.write_text('{"a":NaN}')
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            common.load_json(path)

    def test_cross_platform_order_and_legacy_manifest_compatibility(self):
        (self.site / "assets/App-Z.js").write_text('console.log("uppercase");', encoding="utf-8")
        (self.site / "assets/CompanyLibrary-Z.js").write_text('console.log("mixed case");', encoding="utf-8")
        report = release_bundle.build(self.site, self.root / "output", 2)
        release = self.root / "output" / report["releaseId"]
        path = release / "release-manifest.json"
        manifest = common.load_json(path)
        names = [row["path"] for row in manifest["files"]]
        self.assertEqual(names, sorted(names))
        self.assertNotEqual(names, sorted(names, key=str.casefold))
        # Simulate an existing manifest emitted in WindowsPath ordering; its
        # original checksums file must still match its own original sequence.
        manifest["files"].sort(key=lambda row: row["path"].casefold())
        path.write_bytes(common.json_bytes(manifest))
        sums = "".join(row["sha256"] + "  site/" + row["path"] + "\n" for row in manifest["files"])
        (release / "SHA256SUMS").write_text(sums, encoding="utf-8", newline="\n")
        common.verify_release(release)
        manifest["files"][0]["bytes"] += 1
        path.write_bytes(common.json_bytes(manifest))
        with self.assertRaisesRegex(ValueError, "content differs"):
            common.verify_release(release)

    def test_manifest_duplicate_path_and_extra_fields_rejected(self):
        item = {"path": "assets/app.js", "bytes": 1, "sha256": "a" * 64}
        with self.assertRaisesRegex(ValueError, "Duplicate manifest"):
            common.canonical_files([item, dict(item)])
        with self.assertRaisesRegex(ValueError, "Invalid manifest file fields"):
            common.canonical_files([{**item, "unexpected": True}])


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReleaseTests))
    (ROOT / "result.json").write_bytes(common.json_bytes({"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "passed": result.wasSuccessful(), "linuxAtomicSwitchExecuted": False, "networkUsed": False}))
    print("Test artifacts:", str(ROOT))
    raise SystemExit(0 if result.wasSuccessful() else 1)
