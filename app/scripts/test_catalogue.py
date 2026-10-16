"""Synthetic full approval chain tests; no real company approvals or output."""
import sys
sys.dont_write_bytecode = True
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import verify_catalogue as gate
import test_project_content as fixtures


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        # Short dedicated evidence root keeps native Windows fixtures below MAX_PATH.
        workspace = Path(__file__).absolute().parents[2] / "ce"
        workspace.mkdir(exist_ok=True)
        location = patch.object(fixtures.fixtures, "HERE", workspace)
        location.start(); self.addCleanup(location.stop)
        self.f = fixtures.ProjectionTests("test_cli_only_company_and_truthful_stdout")
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.root = self.f.root
        self.app = self.root / "app"; self.app.mkdir()
        self.baseline = self.root / "old"; self.baseline.mkdir()
        for folder in ("src", "scripts", "public", "content/company-editorial", "content/company-seven-questions"):
            (self.app / folder).mkdir(parents=True, exist_ok=True)
        for name in gate.ROOT_FILES:
            (self.app / name).write_text("{}", encoding="utf-8")
        self.index = {"schemaVersion": 1, "snapshotId": "test-fixed-snapshot", "asOf": "20261002",
            "coverage": {"total": 8, "financialHistory": 4}, "companies": []}
        codes = [fixtures.CODE, "601138.SH", "000001.SZ", "000333.SZ", "600036.SH", "600519.SH", "601318.SH", "688981.SH"]
        for i, code in enumerate(codes):
            self.index["companies"].append({"code": code, "name": "TEST FIXTURE " + code, "depth": "basic" if i in (1, 2) else "deep"})
        self.put(self.app / "public/data/companies/index.json", self.index)
        self.selection = {"schemaVersion": 1, "indexSha256": gate.chain.sha((self.app / "public/data/companies/index.json").read_bytes()), "legacy": [], "sevenQuestions": []}
        for code in codes[1:3]:
            item = {"code": code, "name": "TEST FIXTURE " + code, "tagline": "Synthetic only", "createdAt": "2026-10-02", "reportBasis": "Synthetic",
                    "products": [], "customers": [], "process": [], "costs": [], "sources": [], "financeNotes": [], "evidenceGaps": [], "revenueMix": {}}
            name = "content/company-editorial/" + code + ".json"
            self.put(self.app / name, item); self.put(self.baseline / name, item)
            self.selection["legacy"].append({"code": code, "sha256": gate.chain.sha((self.app / name).read_bytes())})
        self.project()

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gate.chain.builder.json_bytes(value))

    def project(self):
        result = self.f.run_projection()
        self.assertIn(result["status"], ["local_content_projected", "existing_projection_verified"], result)
        self.projection = self.root / result["outputs"][0]["path"]
        self.content = self.app / "content/company-seven-questions" / (fixtures.CODE + ".json")
        raw = (self.projection / "content.json").read_bytes(); self.content.write_bytes(raw)
        self.selection["sevenQuestions"] = [{"code": fixtures.CODE, "sha256": gate.chain.sha(raw)}]
        self.seal_selection()

    def seal_selection(self):
        self.put(self.app / "content-selection.json", self.selection)

    def run_gate(self):
        # Settle first enumeration of freshly created synthetic Windows dirs.
        # The real gate still compares every identity attribute and byte.
        for directory in [self.root, *self.root.rglob('*')]:
            if directory.is_dir(): list(directory.iterdir())
        return gate.verify(self.root, self.app, self.baseline)

    def test_shared_public_is_fully_hashed_without_local_copy(self):
        import shutil
        shared = self.root / "external-public"
        shutil.copytree(self.app / "public", shared)
        (shared / "sentinel.txt").write_text("frozen", encoding="utf-8")
        result = gate.verify(self.root, self.app, self.baseline, shared)
        self.assertEqual(result["applicationInputs"]["public/sentinel.txt"], gate.chain.sha(b"frozen"))
        self.assertEqual(result["catalogue"]["index"]["sha256"], self.selection["indexSha256"])

    def test_shared_public_byte_drift_is_rejected(self):
        import shutil
        shared = self.root / "external-public"
        shutil.copytree(self.app / "public", shared)
        (shared / "sentinel.txt").write_text("frozen", encoding="utf-8")
        # Settle first enumeration attributes of the newly copied Windows fixture.
        for directory in [self.root, *self.root.rglob("*")]:
            if directory.is_dir(): list(directory.iterdir())
        actual = gate.chain.checkpoint_selection
        def drift(root, before, codes, content_tier=None):
            (shared / "sentinel.txt").write_text("changed", encoding="utf-8")
            return actual(root, before, codes, content_tier)
        with patch.object(gate.chain, "checkpoint_selection", side_effect=drift):
            with self.assertRaisesRegex(ValueError, "Application inputs changed"):
                gate.verify(self.root, self.app, self.baseline, shared)

    def test_three_contents_not_eight_deep_union(self):
        result = self.run_gate(); catalogue = result["catalogue"]
        self.assertEqual(catalogue["counts"], {"readable": 3, "legacy": 2, "reviewedSeven": 1})
        deep = {r["code"] for r in self.index["companies"] if r["depth"] == "deep"}
        self.assertEqual(len(deep | {r["code"] for r in catalogue["entries"]}), 8)
        self.assertEqual([r["status"] for r in catalogue["entries"]].count("release-reviewed-seven"), 1)
        for forbidden in ("reviewer", "reviewPath", "bundlePath", "queueState", "manifestSha256", "localPath", str(self.root)):
            self.assertNotIn(forbidden, json.dumps(catalogue))

    def test_between_runs_unrelated_queue_change_preserves_public_directory(self):
        first = self.run_gate(); self.f.fixture.state["revision"] += 1; self.f.fixture.save_state()
        second = self.run_gate()
        self.assertEqual(first["catalogue"], second["catalogue"])
        self.assertNotEqual(first["approvalBindingId"], second["approvalBindingId"])

    def test_legacy_creation_date_is_not_cutoff_and_seven_gaps_are_not_zero(self):
        path = "content/company-editorial/601138.SH.json"
        old = json.loads((self.app / path).read_bytes())
        old.update(createdAt="2026-10-02", reportBasis="资料截止 2026-10-01")
        self.put(self.app / path, old); self.put(self.baseline / path, old)
        self.selection["legacy"][0]["sha256"] = gate.chain.sha((self.app / path).read_bytes()); self.seal_selection()
        entries = {row["code"]: row for row in self.run_gate()["catalogue"]["entries"]}
        self.assertEqual(entries["601138.SH"]["createdAt"], "2026-10-02")
        self.assertEqual(entries["601138.SH"]["reportBasis"], "资料截止 2026-10-01")
        self.assertNotIn("asOf", entries["601138.SH"])
        self.assertEqual(entries[fixtures.CODE]["asOf"], "2026-10-02")
        self.assertNotIn("createdAt", entries[fixtures.CODE])
        self.assertNotIn("gaps", entries[fixtures.CODE])

    def test_unselected_approved_company_is_not_public(self):
        self.f.fixture.make_chain(fixtures.fixtures.OTHER)
        self.assertEqual(self.run_gate()["catalogue"]["counts"]["readable"], 3)

    def test_current_review_revocation_refuses_old_receipt(self):
        self.run_gate()
        self.f.fixture.edit(self.f.fixture.review_path, lambda row: row.update(contentDecision="needs_revision"))
        with self.assertRaisesRegex(ValueError, "Current approval rejected"):
            self.run_gate()

    def test_missing_page_review_refused(self):
        (self.root / self.f.fixture.page_path).unlink()
        with self.assertRaisesRegex(ValueError, "Current approval rejected"):
            self.run_gate()

    def test_valid_schema_tampering_not_approved(self):
        value = json.loads(self.content.read_bytes()); value["tagline"] += " changed"
        self.put(self.content, value)
        self.selection["sevenQuestions"][0]["sha256"] = gate.chain.sha(self.content.read_bytes()); self.seal_selection()
        with self.assertRaisesRegex(ValueError, "currently approved text"):
            self.run_gate()

    def test_missing_selected_file_does_not_shrink_directory(self):
        self.content.unlink()
        with self.assertRaisesRegex(ValueError, "missing or changed|Nested empty directories"):
            self.run_gate()

    def test_projection_mapping_not_self_approval(self):
        path = self.projection / "mapping.json"; row = json.loads(path.read_bytes()); row["acceptedInputHashes"] = {}
        self.put(path, row)
        with self.assertRaisesRegex(ValueError, "mapping does not bind"):
            self.run_gate()

    def test_selection_cannot_declare_approval(self):
        self.selection["approved"] = True; self.seal_selection()
        with self.assertRaisesRegex(ValueError, "cannot declare approval"):
            self.run_gate()

    def test_dual_format_and_extra_module_refused(self):
        target = self.app / "content/company-editorial" / self.content.name
        target.write_bytes(self.content.read_bytes())
        with self.assertRaisesRegex(ValueError, "Actual module set"):
            self.run_gate()
        self.selection["legacy"].append(dict(self.selection["sevenQuestions"][0])); self.seal_selection()
        with self.assertRaisesRegex(ValueError, "Duplicate or mixed"):
            self.run_gate()

    def test_wrong_index_identity_and_duplicate_refused(self):
        self.index["companies"][0]["name"] = "Wrong company"
        self.put(self.app / "public/data/companies/index.json", self.index)
        self.selection["indexSha256"] = gate.chain.sha((self.app / "public/data/companies/index.json").read_bytes()); self.seal_selection()
        with self.assertRaisesRegex(ValueError, "identity differs"):
            self.run_gate()
        self.index["companies"].append(self.index["companies"][0]); self.put(self.app / "public/data/companies/index.json", self.index)
        self.selection["indexSha256"] = gate.chain.sha((self.app / "public/data/companies/index.json").read_bytes()); self.seal_selection()
        with self.assertRaisesRegex(ValueError, "duplicate company"):
            self.run_gate()

    def test_financial_history_count_requires_bounded_integer(self):
        def use(value):
            self.index["coverage"]["financialHistory"] = value
            path = self.app / "public/data/companies/index.json"
            self.put(path, self.index)
            self.selection["indexSha256"] = gate.chain.sha(path.read_bytes())
            self.seal_selection()
        for value in (-1, True, False, 1.5, 9):
            with self.subTest(rejected=value):
                use(value)
                with self.assertRaisesRegex(ValueError, "Invalid financial-history coverage count"):
                    self.run_gate()
        for value in (0, 8):
            with self.subTest(accepted=value):
                use(value)
                self.assertEqual(self.run_gate()["catalogue"]["coverage"]["financialHistory"], value)

    def test_legacy_cannot_change_under_old_label(self):
        path = self.app / "content/company-editorial/601138.SH.json"
        value = json.loads(path.read_bytes()); value["tagline"] += " changed"; self.put(path, value)
        self.selection["legacy"][0]["sha256"] = gate.chain.sha(path.read_bytes()); self.seal_selection()
        with self.assertRaisesRegex(ValueError, "frozen baseline"):
            self.run_gate()

    def test_input_and_approval_drift_in_same_assembly_rejected(self):
        actual = gate.chain.checkpoint_selection
        def drift(root, before, codes, content_tier=None):
            self.f.fixture.state["revision"] += 1; self.f.fixture.save_state()
            return actual(root, before, codes, content_tier)
        with patch.object(gate.chain, "checkpoint_selection", side_effect=drift):
            with self.assertRaisesRegex(ValueError, "Current control records"):
                self.run_gate()
        actual_inputs = gate.app_inputs; count = 0
        def changed(app):
            nonlocal count
            count += 1
            if count == 2:
                (app / "src/mid-run.ts").write_text("changed", encoding="utf-8")
            return actual_inputs(app)
        with patch.object(gate, "app_inputs", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "Application inputs changed"):
                self.run_gate()

    def test_new_approved_payload_changes_catalogue_identity(self):
        first = self.run_gate()["catalogue"]
        self.f.reader["tagline"] += " New approved synthetic input"; self.f.reseal(); self.project()
        second = self.run_gate()["catalogue"]
        self.assertNotEqual(first["catalogueSha256"], second["catalogueSha256"])

    def save_snapshot(self):
        snapshot = gate.public_snapshot(self.run_gate(), self.selection)
        self.put(self.app / 'content-approval-snapshot.json', snapshot)
        return snapshot

    def test_public_snapshot_has_no_current_approval_or_private_paths(self):
        snapshot = self.save_snapshot()
        result = gate.verify_snapshot(self.app, self.app / 'public')
        self.assertEqual(result['approvalMode'], 'public-snapshot')
        self.assertIsNone(result['approvalBindingId'])
        self.assertEqual(result['adoptions'], [])
        self.assertFalse(result['readyForPublication'])
        for private in ('bundlePath','inputHashes','reviewPath','pageReviewPath',str(self.root)):
            self.assertNotIn(private, json.dumps(snapshot))

    def test_snapshot_edited_content_rejected(self):
        self.save_snapshot()
        self.content.write_bytes(self.content.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'bytes or file set'):
            gate.verify_snapshot(self.app, self.app / 'public')

    def test_snapshot_changed_selection_rejected(self):
        self.save_snapshot()
        self.selection['sevenQuestions'] = []
        self.seal_selection()
        with self.assertRaisesRegex(ValueError, 'selection changed'):
            gate.verify_snapshot(self.app, self.app / 'public')

    def test_snapshot_extra_content_rejected(self):
        self.save_snapshot()
        self.put(self.app / 'content/company-seven-questions/999999.SZ.json', {})
        with self.assertRaisesRegex(ValueError, 'bytes or file set'):
            gate.verify_snapshot(self.app, self.app / 'public')

    def test_snapshot_mode_cannot_write_new_approval(self):
        import os
        self.save_snapshot()
        with patch.dict(os.environ, {'ATLAS_APPROVAL_MODE':'snapshot'}), patch.object(sys, 'argv', ['verify_catalogue.py','--write-public-snapshot']):
            self.assertEqual(gate.main(), 1)


class PythonCacheTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.temporary = tempfile.TemporaryDirectory(prefix='atlas-bytecode-')
        self.addCleanup(self.temporary.cleanup)
        self.app = Path(self.temporary.name)
        for name in gate.ROOT_FILES:
            (self.app / name).write_text('{}', encoding='utf-8')
        for folder in ('src', 'content', 'scripts', 'public'):
            (self.app / folder).mkdir()
        for directory in [self.app, *self.app.iterdir()]:
            if directory.is_dir(): list(directory.iterdir())

    def test_actual_import_cache_is_rejected(self):
        import os, subprocess
        module = self.app / 'scripts/cache_probe.py'
        module.write_text('VALUE = 37\n', encoding='utf-8')
        env = {k:v for k,v in os.environ.items() if k not in ('PYTHONDONTWRITEBYTECODE', 'PYTHONPYCACHEPREFIX')}
        result = subprocess.run([sys.executable, '-c', 'import cache_probe; assert cache_probe.VALUE == 37'],
                                cwd=module.parent, env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertTrue(list(module.parent.glob('__pycache__/*.pyc')), 'A real import must create the regression input')
        list((module.parent / '__pycache__').iterdir())
        with self.assertRaisesRegex(ValueError, 'Generated Python cache'):
            gate.app_inputs(self.app)

    def test_bytecode_and_cache_spellings_rejected_in_all_source_trees(self):
        for folder in ('src', 'content', 'scripts'):
            for name in ('direct.pyc', 'direct.PYC', 'direct.pyo', '__PYCACHE__/probe.bin'):
                with self.subTest(folder=folder, name=name):
                    path = self.app / folder / name
                    path.parent.mkdir(exist_ok=True)
                    path.write_bytes(b'generated-cache-fixture')
                    list(path.parent.iterdir())
                    with self.assertRaisesRegex(ValueError, 'Generated Python cache'):
                        gate.app_inputs(self.app)
                    path.unlink()
                    if path.parent.name == '__PYCACHE__': path.parent.rmdir()

    def test_normal_python_source_remains_bound(self):
        before = gate.app_inputs(self.app)
        source = self.app / 'scripts/normal.py'
        source.write_bytes(b'VALUE = 1\n')
        added = gate.app_inputs(self.app)
        self.assertNotEqual(before, added)
        self.assertEqual(added['scripts/normal.py'], gate.chain.sha(source.read_bytes()))
        source.write_bytes(b'VALUE = 2\n')
        changed = gate.app_inputs(self.app)
        self.assertNotEqual(added['scripts/normal.py'], changed['scripts/normal.py'])
        self.assertEqual(set(added), set(changed))

    def test_update_gate_disables_own_and_child_bytecode(self):
        import os, subprocess
        module = self.app / 'cache_child_probe.py'
        module.write_text('VALUE = 37\n', encoding='utf-8')
        # run_path executes the actual gate bootstrap without importing it into
        # the real source tree or running its command-line main function.
        script = Path(__file__).with_name('update_gate.py')
        code = ('import os, runpy, subprocess, sys; '
                'runpy.run_path(sys.argv[1], run_name="cache_policy_probe"); '
                'assert sys.dont_write_bytecode; '
                'assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"; '
                'subprocess.run([sys.executable,"-c","import cache_child_probe; assert cache_child_probe.VALUE == 37"], check=True)')
        env = {k:v for k,v in os.environ.items() if k not in ('PYTHONDONTWRITEBYTECODE', 'PYTHONPYCACHEPREFIX')}
        result = subprocess.run([sys.executable, '-c', code, str(script)], cwd=self.app, env=env, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertFalse(list(self.app.rglob('*.pyc')))
        self.assertFalse(list(self.app.rglob('__pycache__')))


if __name__ == "__main__":
    unittest.main()
