"""Offline projection tests using actual checker, review, builder and page contracts."""
import sys
sys.dont_write_bytecode = True
import copy
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

import project_content as projection
import test_approval_chain as fixtures

chain = projection.chain
CODE = fixtures.CODE


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ChainTests("test_full_chain_is_read_only_and_never_deploy_ready")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        (self.root / "publication").mkdir()
        self.bundle = self.root / self.fixture.bundle_path
        self.reader = json.loads((self.bundle / "reader.json").read_text(encoding="utf-8"))
        self.evidence = json.loads((self.bundle / "evidence.json").read_text(encoding="utf-8"))
        self.sources = json.loads((self.bundle / "sources.json").read_text(encoding="utf-8"))
        self.round = 0

    def reseal(self):
        self.round += 1
        for name, value in [("reader.json", self.reader), ("evidence.json", self.evidence), ("sources.json", self.sources)]:
            self.fixture.put(self.bundle / name, value)
        self.fixture.put(self.bundle / "manifest.json", {"schemaVersion": 1, "jobId": chain.checker.JOB_ID, "code": CODE,
            "files": [{"path": p.relative_to(self.bundle).as_posix(), "sha256": chain.sha(p.read_bytes())}
                      for p in sorted(self.bundle.rglob("*")) if p.is_file() and p.name not in {"manifest.json", "ready.json"}]})
        manifest = chain.sha((self.bundle / "manifest.json").read_bytes())
        self.fixture.edit(self.fixture.bundle_path + "/ready.json", lambda row: row.update(manifestSha256=manifest))
        self.fixture.edit(self.fixture.review_path, lambda row: row.update(manifestSha256=manifest,
            reviewedClaimIds=[c["id"].strip() for c in self.evidence["claims"]]))
        built = chain.builder.build_candidate(self.root, self.fixture.bundle_path, self.fixture.review_path, "projection-fixture-" + str(self.round))
        self.assertEqual(built["status"], "local_candidate_built", built)
        self.fixture.edit(self.fixture.page_path, lambda row: row.update(manifestSha256=manifest,
            candidatePath=built["candidatePath"], htmlSha256=built["htmlSha256"], reviewedAt=datetime.now(timezone.utc).isoformat()))

    def run_projection(self):
        return projection.project_company(self.root, CODE)

    def assert_rejected(self, result, code=None):
        self.assertEqual(result["status"], "rejected", result)
        self.assertEqual(result["outputs"], [])
        self.assertTrue(result["noDeploy"])
        self.assertFalse(result["readyForPublication"])
        if code:
            self.assertEqual(result["errors"][0]["code"], code, result)

    def load_output(self, result):
        self.assertIn(result["status"], {"local_content_projected", "existing_projection_verified"}, result)
        directory = self.root / result["outputs"][0]["path"]
        return directory, json.loads((directory / "content.json").read_text(encoding="utf-8")), json.loads((directory / "mapping.json").read_text(encoding="utf-8"))

    def test_actual_contract_preserves_all_seven_texts_digits_and_citations(self):
        self.reader["answers"][0]["text"] = "TEST FIXTURE 收入 123.40；不是 1234。\n逐字保留 <script>never execute</script>。"
        self.reader["answers"] = list(reversed(self.reader["answers"]))
        self.evidence["claims"][0]["claimType"] = "calculation"
        self.evidence["claims"][0]["limitations"] = ["TEST FIXTURE 仅合并口径", "不外推 2027"]
        self.evidence["claims"][0]["citations"][0]["pdfPage"] = 12
        self.reseal()
        before = {p.relative_to(self.root).as_posix(): (chain.sha(p.read_bytes()), p.stat().st_mtime_ns)
                  for p in self.root.rglob("*") if p.is_file()}
        result = self.run_projection()
        directory, content, mapping = self.load_output(result)
        self.assertEqual(content["schema"], "atlas-company-seven-questions")
        self.assertEqual(content["answers"], list(reversed(self.reader["answers"])))
        self.assertEqual(content["claims"], self.evidence["claims"])
        self.assertNotIn("noDeploy", content)
        self.assertNotIn("jobId", content)
        self.assertEqual(mapping["output"]["sha256"], chain.sha((directory / "content.json").read_bytes()))
        self.assertEqual({p.name for p in directory.iterdir()}, {"content.json", "mapping.json"})
        for path, signature in before.items():
            p = self.root / path
            self.assertEqual(signature, (chain.sha(p.read_bytes()), p.stat().st_mtime_ns))

    def test_omits_audio_unused_claims_sources_and_local_archive_fields(self):
        original = self.bundle / "sources/original.pdf"
        original.parent.mkdir()
        original.write_bytes(b"TEST FIXTURE ONLY, not a real PDF")
        self.sources["sources"][0].update(localPath="sources/original.pdf", sha256=chain.sha(original.read_bytes()))
        self.sources["sources"].append({**self.sources["sources"][0], "id": "unused_source", "title": "C:/PRIVATE/not_public"})
        self.evidence["claims"].append({**copy.deepcopy(self.evidence["claims"][0]), "id": "unused_claim", "claim": "C:/PRIVATE/not_public"})
        self.reader["audioScript"] = "C:/PRIVATE/never_publish_audio"
        self.reseal()
        _, content, mapping = self.load_output(self.run_projection())
        self.assertEqual(len(content["claims"]), 7)
        self.assertEqual(len(content["sources"]), 1)
        public = json.dumps(content)
        for forbidden in ("localPath", "sha256", "readLocations", "audioScript", "unused_claim", "unused_source", "PRIVATE", "reviewedAt", "manifest"):
            self.assertNotIn(forbidden, public)
        self.assertIn(self.fixture.bundle_path + "/sources/original.pdf", mapping["acceptedInputHashes"])

    def test_repeat_is_identical_and_read_only_even_if_global_queue_revision_changes(self):
        first = self.run_projection()
        directory, _, _ = self.load_output(first)
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir()}
        self.fixture.state["revision"] += 1
        self.fixture.save_state()
        second = self.run_projection()
        self.assertEqual(second["status"], "existing_projection_verified", second)
        self.assertEqual(first["outputs"], second["outputs"])
        self.assertNotEqual(first["approvalBindingId"], second["approvalBindingId"])
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir()})

    def test_changed_output_and_extra_file_refused_without_overwrite(self):
        directory, _, _ = self.load_output(self.run_projection())
        file = directory / "content.json"
        original = file.read_bytes()
        file.write_bytes(b"changed")
        self.assert_rejected(self.run_projection(), "output_conflict")
        self.assertEqual(file.read_bytes(), b"changed")
        file.write_bytes(original)
        (directory / "unexpected.txt").write_bytes(b"TEST FIXTURE")
        self.assert_rejected(self.run_projection(), "output_conflict")

    def test_partial_directory_is_not_silently_repaired(self):
        manifest = chain.sha((self.bundle / "manifest.json").read_bytes())
        directory = self.root / "publication/projections" / CODE / manifest
        directory.mkdir(parents=True)
        (directory / "content.json").write_bytes(b"partial")
        self.assert_rejected(self.run_projection(), "output_conflict")
        self.assertFalse((directory / "mapping.json").exists())

    def test_current_revocation_does_not_reuse_previously_valid_output(self):
        directory, _, _ = self.load_output(self.run_projection())
        before = {p.name: p.read_bytes() for p in directory.iterdir()}
        value = json.loads((self.root / self.fixture.review_path).read_text(encoding="utf-8"))
        value.update(contentDecision="needs_revision", reviewedAt=self.fixture.now.isoformat())
        self.fixture.put(self.root / "reviews/revoked.json", value)
        self.assert_rejected(self.run_projection(), "approval_chain_rejected")
        self.assertEqual(before, {p.name: p.read_bytes() for p in directory.iterdir()})

    def test_higher_unsealed_version_blocks_projection(self):
        (self.root / "inbox" / CODE / "v002").mkdir()
        self.assert_rejected(self.run_projection(), "approval_chain_rejected")
        self.assertFalse((self.root / "publication/projections").exists())

    def test_wrong_company_missing_claim_and_missing_source_are_rejected(self):
        original = projection.project_values
        for field in ("code", "claim", "source"):
            def corrupt(documents, selected, field=field):
                if field == "code": documents["reader.json"]["code"] = fixtures.OTHER
                elif field == "claim": documents["reader.json"]["answers"][0]["claimIds"] = ["absent"]
                else: documents["sources.json"]["sources"] = []
                return original(documents, selected)
            with self.subTest(field=field), patch.object(projection, "project_values", side_effect=corrupt):
                self.assert_rejected(self.run_projection())
        self.assertFalse((self.root / "publication/projections").exists())

    def test_transform_losing_text_digit_claim_or_mapping_is_rejected(self):
        original = projection.project_values
        for kind in ("digit", "question", "claim", "citation", "limitation", "mapping", "extra"):
            def corrupt(documents, selected, kind=kind):
                public, mappings = original(documents, selected)
                if kind == "digit": public["answers"][0]["text"] += " 999"
                elif kind == "question": public["answers"].pop()
                elif kind == "claim": public["claims"].pop()
                elif kind == "citation": public["claims"][0]["citations"][0]["excerpt"] = "Changed excerpt"
                elif kind == "limitation": del public["claims"][0]["limitations"]
                elif kind == "mapping": mappings.pop()
                else: public["internal"] = "review data"
                return public, mappings
            with self.subTest(kind=kind), patch.object(projection, "project_values", side_effect=corrupt):
                self.assert_rejected(self.run_projection())
        self.assertFalse((self.root / "publication/projections").exists())

    def test_public_text_local_path_rejected_not_silently_sanitized(self):
        for value in ("C:\\Users\\private\\secret.pdf", "file:///C:/secret", "\\\\host\\share\\file", "/home/private/file", "reviews/000977.SZ/review.json", "../private/file"):
            with self.subTest(value=value):
                original = self.reader["answers"][0]["text"]
                self.reader["answers"][0]["text"] = "TEST FIXTURE " + value
                self.reseal()
                self.assert_rejected(self.run_projection(), "private_path")
                self.reader["answers"][0]["text"] = original
        self.assertFalse((self.root / "publication/projections").exists())

    def test_public_source_requires_https(self):
        original = projection.project_values
        def corrupt(documents, selected):
            documents["sources.json"]["sources"][0]["url"] = "http://example.org/fixture"
            return original(documents, selected)
        with patch.object(projection, "project_values", side_effect=corrupt):
            self.assert_rejected(self.run_projection())

    def test_legitimate_publication_and_sources_url_paths_pass_real_chain(self):
        original = self.bundle / "sources/report-2025.pdf"
        original.parent.mkdir()
        original.write_bytes(b"TEST FIXTURE ONLY, not a real PDF")
        self.sources["sources"][0].update(localPath="sources/report-2025.pdf", sha256=chain.sha(original.read_bytes()))
        self.sources["sources"][0]["url"] = "https://example.org/publication/sources/report-2025.pdf"
        self.reseal()
        _, public, _ = self.load_output(self.run_projection())
        self.assertEqual(public["sources"][0]["url"], self.sources["sources"][0]["url"])

    def test_url_rule_still_rejects_credentials_and_embedded_machine_paths(self):
        for url in ("https://name:secret@example.org/publication/report.pdf",
                    "https://example.org/report?local=C%3A%5CUsers%5Cprivate%5Csource.pdf",
                    "https://example.org/report?local=%2Fhome%2Fprivate%2Fsource.pdf"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                projection.safe_public({"sources": [{"url": url}]}, set())

    def test_mutated_working_document_cannot_redefine_original_text(self):
        original = projection.project_values
        def corrupt(documents, selected):
            documents["reader.json"]["answers"][0]["text"] = "TEST FIXTURE altered 999"
            return original(documents, selected)
        with patch.object(projection, "project_values", side_effect=corrupt):
            self.assert_rejected(self.run_projection(), "content_changed")

    def test_actual_payload_drift_after_chain_cannot_enter_output(self):
        original = projection.accepted
        calls = 0
        def changed(root, code):
            nonlocal calls
            result = original(root, code)
            calls += 1
            if calls == 1:
                (self.bundle / "reader.json").write_bytes(b"Changed payload after approval check")
            return result
        with patch.object(projection, "accepted", side_effect=changed):
            self.assert_rejected(self.run_projection(), "input_drift")
        self.assertFalse((self.root / "publication/projections").exists())

    def test_concurrent_queue_drift_refuses_without_rewriting_state(self):
        original = projection.project_values
        def change_queue(documents, selected):
            self.fixture.state["revision"] += 1
            self.fixture.save_state()
            return original(documents, selected)
        with patch.object(projection, "project_values", side_effect=change_queue):
            self.assert_rejected(self.run_projection(), "input_drift")
        self.assertEqual(json.loads((self.root / "queue-state.json").read_text())["revision"], 2)
        self.assertFalse((self.root / "publication/projections").exists())

    def test_interrupted_write_retains_unaccepted_directory_and_no_success_marker(self):
        original = projection.write_new
        def interrupt(path, raw):
            if path.name == "mapping.json":
                raise OSError("TEST FIXTURE simulated write interruption")
            original(path, raw)
        with patch.object(projection, "write_new", side_effect=interrupt):
            result = self.run_projection()
        self.assert_rejected(result)
        directory = self.root / result["retainedUnacceptedDirectory"]
        self.assertTrue((directory / "content.json").exists())
        self.assertFalse((directory / "mapping.json").exists())
        saved = (directory / "content.json").read_bytes()
        recovered = self.run_projection()
        self.assertEqual(recovered["status"], "local_content_projected", recovered)
        self.assertFalse(recovered["reusedAttempt"])
        self.assertNotEqual(directory, self.root / recovered["outputs"][0]["path"])
        self.assertEqual((directory / "content.json").read_bytes(), saved)
        self.assertFalse((directory / "mapping.json").exists())

    def test_hardlinked_output_is_rejected(self):
        directory, _, _ = self.load_output(self.run_projection())
        os.link(directory / "content.json", self.root / "linked-copy.json")
        self.assert_rejected(self.run_projection(), "unsafe_filesystem")

    def test_output_directory_symlink_is_rejected_when_supported(self):
        outside = self.root / "unrelated"
        outside.mkdir()
        try:
            os.symlink(outside, self.root / "publication/projections", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("This Windows account cannot create a real directory symlink")
        self.assert_rejected(self.run_projection(), "unsafe_filesystem")
        self.assertEqual(list(outside.iterdir()), [])

    def test_cli_only_company_and_truthful_stdout(self):
        stream = io.StringIO()
        with patch.object(projection, "ROOT", self.root), redirect_stdout(stream):
            exit_code = projection.main(["--company", CODE])
        result = json.loads(stream.getvalue())
        self.assertEqual(exit_code, 0, result)
        self.assertTrue(result["requires_renderer_adapter"])
        self.assertFalse(result["readyForPublication"])
        with patch.object(projection, "ROOT", self.root), redirect_stdout(io.StringIO()):
            self.assertEqual(projection.main(["--company", "../../unsafe"]), 1)


if __name__ == "__main__":
    unittest.main()
