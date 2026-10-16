"""Real contracts on temporary synthetic packages; never review actual company facts."""
import sys
sys.dont_write_bytecode = True
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import approval_chain as chain

HERE = Path(__file__).absolute().parent
CODE = "000977.SZ"
OTHER = "600588.SH"


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".approval-chain-test-", dir=HERE)
        self.root = Path(self.temporary.name)
        self.now = datetime.now(timezone.utc)
        self.addCleanup(self.cleanup)
        trust = patch.object(chain.checker, "TRUSTED_ROOT", self.root)
        trust.start(); self.addCleanup(trust.stop)
        original = chain.checker.check_bundle
        fast = patch.object(chain.checker, "check_bundle", side_effect=lambda p: original(p, 0))
        fast.start(); self.addCleanup(fast.stop)
        self.put(self.root / "company-universe.json", {
            "schemaVersion": 1, "jobId": chain.checker.JOB_ID,
            "sourceIndex": str(self.root / "synthetic-index.json"), "sourceSha256": "f" * 64,
            "sourceAsOf": "2026-10-02", "generatedAt": self.now.isoformat(), "cutoff": "2026-10-02",
            "companies": [{"code": c, "name": "TEST FIXTURE " + c} for c in [CODE, OTHER]]})
        self.state = {"schemaVersion": 1, "jobId": chain.checker.JOB_ID, "revision": 1,
                      "phase": "pilot", "lease": None, "blocked": {}, "observations": {}}
        self.save_state()
        self.bundle_path, self.review_path, self.candidate_path, self.page_path = self.make_chain(CODE)

    def cleanup(self):
        self.assertEqual(self.root.resolve().parent, HERE.resolve())
        self.assertTrue(self.root.name.startswith(".approval-chain-test-"))
        self.temporary.cleanup()

    def put(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(chain.builder.json_bytes(value))

    def edit(self, relative, change):
        path = self.root / relative
        value = json.loads(path.read_text(encoding="utf-8"))
        change(value)
        self.put(path, value)

    def save_state(self):
        self.put(self.root / "queue-state.json", self.state)

    def make_chain(self, code, version="v001"):
        bundle_path = f"inbox/{code}/{version}"
        bundle = self.root / bundle_path
        reader = {"schemaVersion": 1, "code": code, "name": "TEST FIXTURE " + code,
                  "asOf": "2026-10-02", "tagline": "TEST FIXTURE ONLY", "introduction": "Synthetic content, not a company fact.",
                  "answers": [{"questionId": f"Q{i}", "text": "Synthetic answer only.", "claimIds": [f"c{i}"]} for i in range(1, 8)]}
        evidence = {"schemaVersion": 1, "companyCode": code, "cutoff": "2026-10-02",
                    "claims": [{"id": f"c{i}", "questionId": f"Q{i}", "claim": "TEST FIXTURE claim.",
                                "claimType": "interpretation", "sourceIds": ["s1"], "limitations": "Synthetic only.",
                                "citations": [{"sourceId": "s1", "section": "TEST FIXTURE", "excerpt": "Synthetic excerpt."}]} for i in range(1, 8)]}
        sources = {"schemaVersion": 1, "sources": [{"id": "s1", "title": "TEST FIXTURE", "publisher": "SYNTHETIC",
                    "publishedAt": "2026-01-01", "reportPeriod": "2025-12-31", "url": "https://example.org/fixture", "readLocations": ["TEST FIXTURE"]}]}
        for name, value in [("reader.json", reader), ("evidence.json", evidence), ("sources.json", sources)]:
            self.put(bundle / name, value)
        (bundle / "读者稿.md").write_text("TEST FIXTURE ONLY.\nSynthetic answer only.\n", encoding="utf-8")
        self.put(bundle / "manifest.json", {"schemaVersion": 1, "jobId": chain.checker.JOB_ID, "code": code,
                 "files": [{"path": p.name, "sha256": chain.sha(p.read_bytes())} for p in sorted(bundle.iterdir())]})
        manifest_hash = chain.sha((bundle / "manifest.json").read_bytes())
        self.put(bundle / "ready.json", {"schemaVersion": 1, "jobId": chain.checker.JOB_ID, "code": code,
                 "manifestSha256": manifest_hash, "completedAt": (self.now - timedelta(minutes=2)).isoformat()})
        review_path = f"reviews/{code}/{version}/review.json"
        review = {"schemaVersion": 1, "jobId": chain.checker.JOB_ID, "code": code,
                  "bundlePath": bundle_path, "manifestSha256": manifest_hash, "contentDecision": "approved",
                  "reviewer": "TEST FIXTURE ONLY", "reviewedAt": (self.now - timedelta(minutes=1)).isoformat(),
                  "reviewedClaimIds": [f"c{i}" for i in range(1, 8)], "scope": "Synthetic test; never approve facts."}
        self.put(self.root / review_path, review)
        result = chain.builder.build_candidate(self.root, bundle_path, review_path, "fixture-" + version)
        self.assertEqual(result["status"], "local_candidate_built", result)
        page_path = f"reviews/{code}/{version}/page-review.json"
        self.put(self.root / page_path, {"schemaVersion": 1, "jobId": chain.checker.JOB_ID, "code": code,
                 "manifestSha256": manifest_hash, "candidatePath": result["candidatePath"], "htmlSha256": result["htmlSha256"],
                 "pageDecision": "passed", "reviewer": "TEST FIXTURE PAGE REVIEWER", "reviewedAt": datetime.now(timezone.utc).isoformat()})
        return bundle_path, review_path, result["candidatePath"], page_path

    def check(self, codes=None):
        return chain.check_selection(self.root, [CODE] if codes is None else codes)

    def refused(self, expected=None, codes=None):
        result = self.check(codes)
        self.assertEqual(result["status"], "rejected", result)
        self.assertEqual(result["acceptedInputs"], [])
        self.assertNotIn("bindingId", result)
        self.assertFalse(result["readyForPublication"])
        self.assertTrue(result["noDeploy"])
        if expected:
            self.assertEqual(result["errors"][0]["code"], expected, result)
        return result

    def test_full_chain_is_read_only_and_never_deploy_ready(self):
        snapshot = lambda: {p.relative_to(self.root).as_posix(): (chain.sha(p.read_bytes()), p.stat().st_mtime_ns) for p in self.root.rglob("*") if p.is_file()}
        before = snapshot()
        result = self.check()
        self.assertEqual(result["status"], "verified_for_conversion_inputs", result)
        self.assertFalse(result["readyForPublication"])
        self.assertTrue(result["noDeploy"])
        self.assertEqual(len(result["acceptedInputs"]), 1)
        item = result["acceptedInputs"][0]
        self.assertEqual(item["bundlePath"], self.bundle_path)
        self.assertIn(self.bundle_path + "/reader.json", item["inputHashes"])
        self.assertEqual(result["bindingId"], self.check()["bindingId"])
        self.assertEqual(before, snapshot())

    @unittest.skipUnless(os.name == "nt", "Windows directory size observation")
    def test_windows_review_directory_size_only_change_does_not_block_chain(self):
        scratch = self.root / "reviews" / "_scratch"
        scratch.mkdir()
        original_stat, original_entries = Path.lstat, Path.iterdir
        after_listing = False
        # Freeze unrelated observed attributes: fresh Windows directories can
        # independently change 0x10000000 after listing. This fixture varies
        # size only; production still rejects all other identity drift.
        scratch_info = original_stat(scratch)
        def observed_stat(path, *args, **kwargs):
            info = original_stat(path, *args, **kwargs)
            if path != scratch:
                return info
            values = {name: getattr(scratch_info, name) for name in dir(scratch_info) if name.startswith("st_")}
            return SimpleNamespace(**{**values, "st_size": 0 if after_listing else 4096})
        def entries(path):
            nonlocal after_listing
            rows = list(original_entries(path))
            if path == scratch:
                after_listing = True
            return iter(rows)
        with patch.object(Path, "lstat", observed_stat), patch.object(Path, "iterdir", entries):
            result = self.check()
        self.assertEqual(result["status"], "verified_for_conversion_inputs", result)
        self.assertEqual(len(result["acceptedInputs"]), 1)

    def test_directory_discovery_time_change_still_rejected(self):
        original_stat, original_entries = Path.lstat, Path.iterdir
        target = self.root / "reviews"
        after_listing = False
        def observed_stat(path, *args, **kwargs):
            info = original_stat(path, *args, **kwargs)
            if path != target or not after_listing:
                return info
            values = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
            return SimpleNamespace(**{**values, "st_mtime_ns": info.st_mtime_ns + 1})
        def entries(path):
            nonlocal after_listing
            rows = list(original_entries(path))
            if path == target:
                after_listing = True
            return iter(rows)
        with patch.object(Path, "lstat", observed_stat), patch.object(Path, "iterdir", entries):
            self.refused("input_drift")

    def test_actual_new_review_between_controls_is_not_hidden(self):
        original = chain.control_snapshot
        calls = 0
        def add_review(root, codes):
            nonlocal calls
            result = original(root, codes)
            calls += 1
            if calls == 1:
                value = json.loads((self.root / self.review_path).read_text(encoding="utf-8"))
                value.update(contentDecision="needs_revision", reviewedAt=self.now.isoformat())
                self.put(self.root / "reviews" / "new-revocation.json", value)
            return result
        with patch.object(chain, "control_snapshot", side_effect=add_review):
            result = self.refused()
        self.assertIn(result["errors"][0]["code"], {"review_not_approved", "input_drift"})

    def test_missing_or_failed_page_review_blocks(self):
        path = self.root / self.page_path
        raw = path.read_bytes(); path.unlink()
        self.refused("candidate_chain_rejected")
        path.write_bytes(raw)
        self.edit(self.page_path, lambda v: v.update(pageDecision="failed"))
        self.refused("candidate_chain_rejected")

    def test_page_cross_company_bundle_hash_and_traversal_bindings(self):
        path = self.root / self.page_path; raw = path.read_bytes()
        for change in [{"code": OTHER}, {"manifestSha256": "0" * 64}, {"htmlSha256": "0" * 64},
                       {"candidatePath": "../outside"}, {"candidatePath": "candidate/600588.SH/fixture-v001"}]:
            with self.subTest(change=change):
                path.write_bytes(raw)
                self.edit(self.page_path, lambda v: v.update(change))
                self.refused("candidate_chain_rejected")

    def test_current_revision_review_blocks_previous_approval(self):
        value = json.loads((self.root / self.review_path).read_text(encoding="utf-8"))
        value.update(contentDecision="needs_revision", reviewedAt=self.now.isoformat())
        self.put(self.root / "reviews/revocation.json", value)
        self.refused("review_not_approved")

    def test_partial_declared_claim_coverage_cannot_approve_full_reader(self):
        self.edit(self.review_path, lambda v: v.update(reviewedClaimIds=["c1"]))
        result = self.refused()
        # The builder's source gate can reject this approval before the
        # publication layer's defensive coverage check is reached.
        self.assertIn(result["errors"][0]["code"], {"review_missing", "review_coverage"})

    def test_equal_timestamp_negative_review_wins(self):
        value = json.loads((self.root / self.review_path).read_text(encoding="utf-8"))
        value["contentDecision"] = "insufficient_evidence"
        self.put(self.root / "reviews/revocation.json", value)
        self.refused("review_not_approved")

    def test_review_removed_malformed_or_drifted_is_not_adopted(self):
        path = self.root / self.review_path; raw = path.read_bytes()
        path.unlink(); self.refused("review_missing")
        path.write_bytes(b"{"); self.refused("review_missing")
        path.write_bytes(raw)
        self.edit(self.review_path, lambda v: v.update(scope="Changed approval bytes"))
        self.refused("candidate_chain_rejected")

    def test_remembered_later_review_removal_cannot_revive_old_approval(self):
        self.state["observations"][CODE] = {"version": "v001", "reviewPath": "reviews/deleted-revocation.json"}
        self.save_state()
        self.refused()

    def test_cross_company_or_cross_package_review_cannot_approve(self):
        path = self.root / self.review_path; raw = path.read_bytes()
        for change in [{"code": OTHER}, {"bundlePath": f"inbox/{CODE}/v002"}, {"manifestSha256": "0" * 64}]:
            with self.subTest(change=change):
                path.write_bytes(raw)
                self.edit(self.review_path, lambda v: v.update(change))
                self.refused("review_missing")

    def test_newer_unfinished_version_blocks_old_approved(self):
        (self.root / "inbox" / CODE / "v002").mkdir()
        self.refused("latest_not_ready")

    def test_newer_ready_version_replaces_old_chain(self):
        newer = self.make_chain(CODE, "v002")
        (self.root / newer[1]).unlink()
        self.refused("review_missing")

    def test_numeric_latest_and_duplicate_numeric_alias(self):
        (self.root / "inbox" / CODE / "v1000").mkdir()
        (self.root / "inbox" / CODE / "v999").mkdir()
        self.refused("latest_not_ready")
        (self.root / "inbox" / CODE / "v0001").mkdir()
        self.refused("ambiguous_version")

    def test_remembered_newer_version_prevents_resurrection(self):
        self.state["observations"][CODE] = {"version": "v002", "status": "in_progress"}
        self.save_state()
        self.refused("version_regression")

    def test_cached_complete_does_not_grant_approval(self):
        self.state["observations"][CODE] = {"version": "v001", "status": "complete"}
        self.save_state()
        (self.root / self.page_path).unlink()
        self.refused("candidate_chain_rejected")

    def test_html_and_payload_tampering_are_refused(self):
        path = self.root / self.candidate_path / "index.html"; raw = path.read_bytes()
        path.write_bytes(b"Changed HTML")
        self.refused("candidate_chain_rejected")
        path.write_bytes(raw)
        (self.root / self.bundle_path / "reader.json").write_bytes(b"Changed payload")
        self.refused("mechanical_rejected")

    def test_adoption_immutable_anchor_is_enforced(self):
        path = self.root / self.candidate_path / "adoption.json"
        self.state["observations"][CODE] = {"version": "v001", "immutableCandidates": {self.candidate_path: chain.sha(path.read_bytes())}}
        self.save_state()
        self.assertEqual(self.check()["status"], "verified_for_conversion_inputs")
        self.edit(self.candidate_path + "/adoption.json", lambda v: v["limitations"].append("Changed receipt"))
        self.refused("candidate_chain_rejected")

    def test_adoption_cannot_reference_outside_or_another_company(self):
        path = self.root / self.candidate_path / "adoption.json"; raw = path.read_bytes()
        for change in [{"reviewPath": "../review.json"}, {"bundlePath": "../outside"}, {"code": OTHER}, {"output": {"path": "../index.html", "sha256": "0" * 64}}]:
            with self.subTest(change=change):
                path.write_bytes(raw)
                self.edit(self.candidate_path + "/adoption.json", lambda v: v.update(change))
                self.refused("candidate_chain_rejected")

    def test_unadopted_candidate_files_cannot_be_carried_forward(self):
        (self.root / self.candidate_path / "ui.js").write_bytes(b"UNAPPROVED UI")
        self.refused("candidate_extra_files")

    def test_unknown_company_bad_selection_and_config_fail_closed(self):
        for codes in [[], [CODE, CODE], ["../outside"], ["999999.SH"]]:
            with self.subTest(codes=codes): self.refused(codes=codes)
        (self.root / "company-universe.json").write_bytes(b"{")
        self.refused()

    def test_batch_is_all_or_nothing(self):
        other = self.make_chain(OTHER)
        self.assertEqual(len(self.check([CODE, OTHER])["acceptedInputs"]), 2)
        (self.root / other[3]).unlink()
        self.refused(codes=[CODE, OTHER])

    def test_no_filesystem_links_for_approval_records(self):
        path = self.root / self.review_path
        other = self.root / "same-review.json"
        try:
            os.link(path, other)
        except OSError:
            self.skipTest("Host does not permit a real hardlink fixture")
        self.refused("unsafe_filesystem")

    def test_real_symlink_package_directory_is_refused(self):
        target = self.root / "synthetic-outside"; target.mkdir()
        link = self.root / "inbox" / CODE / "v002"
        try:
            os.symlink(target, link, target_is_directory=True)
        except OSError:
            self.skipTest("Host does not permit a real symlink fixture")
        self.addCleanup(link.unlink)
        self.refused("unsafe_path")

    def test_new_version_appearing_during_check_is_refused(self):
        original = chain.control_snapshot
        calls = 0
        def changing(*args):
            nonlocal calls
            result = original(*args); calls += 1
            if calls == 1: (self.root / "inbox" / CODE / "v002").mkdir()
            return result
        with patch.object(chain, "control_snapshot", side_effect=changing):
            self.refused("input_drift")

    def test_html_drift_during_final_control_scan_is_refused(self):
        original = chain.control_snapshot
        calls = 0
        def changing(*args):
            nonlocal calls
            result = original(*args); calls += 1
            if calls == 3: (self.root / self.candidate_path / "index.html").write_bytes(b"late change")
            return result
        with patch.object(chain, "control_snapshot", side_effect=changing):
            self.refused("input_drift")

    def test_main_stdout_and_exit_codes_only(self):
        with patch.object(chain, "ROOT", self.root):
            capture = io.StringIO()
            with redirect_stdout(capture): status = chain.main(["--company", CODE])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(capture.getvalue())["status"], "verified_for_conversion_inputs")
            (self.root / self.page_path).unlink()
            with redirect_stdout(io.StringIO()): self.assertEqual(chain.main(["--company", CODE]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
