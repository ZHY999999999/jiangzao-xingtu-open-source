#!/usr/bin/env python3
"""Read-only offline bindings for current reviewed local candidates. Never deploys."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

# Imports must not create __pycache__, even when invoked without python -B.
sys.dont_write_bytecode = True
HERE = Path(__file__).absolute().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import package_check as checker
import build_candidate as builder
import queue_controller as queue
import preflight as guard

LIMITATIONS = [
    "Validates recorded approval bindings, not reviewer identity, independence, facts, rights or actual browser inspection.",
    "Only the highest existing numeric vNNN package in each requested tier is eligible; unfinished or unclassifiable newer versions block fallback.",
    "No website field conversion, fixed application baseline, exclusive publisher, release or production readback is connected.",
    "The supplied company selection is not a release authorization or an arbitrary file allowlist.",
    "Read-only point-in-time evidence, not a filesystem sandbox or a durable lock; revalidate immediately before later use.",
    "A record removed before observation without retained queue evidence cannot be reconstructed or authenticated by hashes.",
]


class ChainError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def need(ok, code, message):
    if not ok:
        raise ChainError(code, message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()


def read_file(path):
    raw, _ = guard.read_regular(path)
    return raw


def directory_entries(path):
    """Strict directory discovery: never follow a dangling link or hide unknown types."""
    guard.guarded_path(path)
    need(stat.S_ISDIR(path.lstat().st_mode), "unsafe_path", "Expected a real directory")
    before = guard.identity(path.lstat())
    entries = sorted(path.iterdir(), key=lambda p: p.name)
    guard.validate_names([p.name for p in entries])
    for item in entries:
        info = item.lstat()
        need(not guard.is_link(info), "unsafe_path", "Linked directory entries are forbidden")
        need(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), "unsafe_path", "Special filesystem entry is forbidden")
    need(guard.identity(path.lstat()) == before, "input_drift", "Directory changed during discovery")
    return entries


def versions_for(root, code, content_tier=None):
    rows = directory_entries(root / "inbox" / code)
    need(bool(rows), "no_package", code + ": no package directory")
    versions, numbers = [], set()
    for path in rows:
        match = queue.VERSION.fullmatch(path.name)
        need(match is not None and stat.S_ISDIR(path.lstat().st_mode), "package_layout", code + ": expected only vNNN package directories")
        number = int(match[1])
        need(number not in numbers, "ambiguous_version", code + ": numeric package versions must be unique")
        numbers.add(number)
        versions.append((number, path.name))
    selected = []
    for _, name in sorted(versions):
        marker = root / 'inbox' / code / name / 'reader.json'
        try:
            reader = checker.parse_json(read_file(marker), 'reader.json tier marker')
            need(isinstance(reader, dict), 'package_layout', 'Tier marker must be an object')
            tier = checker.content_tier(reader)
            need(reader.get('code') == code, 'package_layout', 'Tier marker company differs')
        except (ValueError, OSError, KeyError, TypeError):
            # An unclassifiable newer package may belong to either tier. Never
            # use this uncertainty to resurrect an older approval.
            selected.append(name)
            continue
        if tier == content_tier:
            selected.append(name)
    need(bool(selected), 'no_package', code + ': no package for selected content tier')
    return selected


def review_inventory(root):
    """All reviews/ JSON can contain a newer revocation; no caller-selected review."""
    pending, files, hashes = [root / "reviews"], [], {}
    while pending:
        for path in directory_entries(pending.pop()):
            if path.is_dir():
                pending.append(path)
            elif path.suffix.lower() == ".json":
                relative = path.relative_to(root).as_posix()
                hashes[relative] = sha(read_file(path))
                if path.name != "page-review.json":
                    files.append(path)
    return sorted(files), hashes


def state_snapshot(root):
    raw = read_file(root / "queue-state.json")
    value = checker.parse_json(raw, "queue-state.json")
    need(isinstance(value, dict) and type(value.get("schemaVersion")) is int
         and value["schemaVersion"] == 1 and value.get("jobId") == checker.JOB_ID
         and isinstance(value.get("observations"), dict), "queue_state", "A valid existing queue state is required; its status alone never grants approval")
    return value, sha(raw)


def control_snapshot(root, codes, content_tier=None):
    # Never call refresh/status/run_command: those write metadata and read sourceIndex.
    companies = checker.load_companies(root)
    need(all(code in companies for code in codes), "company_not_allowed", "Selected company is absent from the trusted local universe")
    universe_path = root / "company-universe.json"
    universe_hash = sha(read_file(universe_path)) if universe_path.exists() or universe_path.is_symlink() else None
    state, state_hash = state_snapshot(root)
    reviews, review_hashes = review_inventory(root)
    versions = {code: versions_for(root, code, content_tier) for code in codes}
    # Bind all classification markers, including other-tier versions. A marker
    # changing tiers during verification must invalidate the observation.
    markers = {}
    for code in codes:
        for directory in directory_entries(root / 'inbox' / code):
            path = directory / 'reader.json'
            markers[path.relative_to(root).as_posix()] = sha(read_file(path)) if path.exists() else None
    candidate_directories = {}
    for code in codes:
        path = root / "candidate" / code
        candidate_directories[code] = [p.name for p in directory_entries(path)] if path.exists() or path.is_symlink() else []
    snapshot = {"companyUniverseSha256": universe_hash, "queueStateSha256": state_hash,
                "reviewFiles": review_hashes, "packageVersions": versions,
                "candidateDirectories": candidate_directories,
                "selectedCompanies": {c: companies[c] for c in codes}, "contentTier": content_tier, "tierMarkers": markers}
    return snapshot, state, reviews


def verify_company(root, code, controls, state, reviews):
    version = controls["packageVersions"][code][-1]
    bundle_path = f"inbox/{code}/{version}"
    bundle = root / bundle_path
    prior = state["observations"].get(code, {})
    need(isinstance(prior, dict), "queue_state", "Invalid retained company observation")
    if (prior.get('contentTier') == 'L' and controls['contentTier'] is None) or (
            prior.get('version') and prior['version'] not in controls['packageVersions'][code]
            and f"inbox/{code}/{prior['version']}/reader.json" in controls['tierMarkers']):
        # Queue may currently work on the other tier. It cannot replace this
        # tier's review, but immutable candidate anchors still apply below.
        prior = {'immutableCandidates': prior.get('immutableCandidates', {})}
    if prior.get("version") is not None:
        previous = queue.VERSION.fullmatch(prior["version"]) if isinstance(prior["version"], str) else None
        need(previous is not None and int(previous[1]) <= int(queue.VERSION.fullmatch(version)[1]),
             "version_regression", code + ": retained queue evidence knows a newer version; refusing to resurrect an older package")
    anchors = prior.get("immutableCandidates", {})
    need(isinstance(anchors, dict), "queue_state", "Invalid immutable candidate anchors")
    for path, value in anchors.items():
        parts = builder.relative(path, "candidate", 3).split("/")
        need(parts[1] == code, "queue_state", "Cross-company immutable candidate anchor")
        guard.valid_digest(value, "immutable candidate anchor")
    need((bundle / "ready.json").exists(), "latest_not_ready", code + ": latest package is unfinished; old approval is not eligible")
    receipt = builder.machine_check(bundle)
    bodies = builder.load_payload(bundle, receipt)
    review = queue.find_review(root, reviews, receipt, bundle_path, bodies)
    need(review is not None, "review_missing", code + ": no current valid bound content review")
    need(review["value"]["contentDecision"] == "approved", "review_not_approved", code + ": current review requires revision or evidence")
    reader = checker.parse_json(bodies["reader.json"], "reader.json")
    need(checker.content_tier(reader) == controls['contentTier'], 'content_tier', 'Package does not belong to the selected content tier')
    used_claims = checker.reader_claim_ids(reader)
    reviewed_claims = {cid.strip() for cid in review["value"]["reviewedClaimIds"]}
    sampled_batch = review["value"].get("reviewScope") == "sampled_batch"
    if not sampled_batch:
        need(used_claims <= reviewed_claims, "review_coverage", code + ": current approval does not declare coverage of every claim used by the selected answers and business diagram")
    else:
        need(bool(review["value"].get("contentSampled")) == bool(reviewed_claims), "review_scope", "Unsampled approval must not invent individually reviewed claims")
    if prior.get("version") == version and prior.get("reviewPath") and prior["reviewPath"] != review["path"]:
        # Saved status is not an approval, but disappearing/malformed later review
        # evidence must not cause an older valid approval to spring back to life.
        previous_path = builder.relative(prior["reviewPath"], "reviews")
        previous_raw = read_file(root / previous_path)
        previous_value = checker.parse_json(previous_raw, "previous review")
        need(isinstance(previous_value, dict) and previous_value.get("bundlePath") == bundle_path,
             "review_regression", "Retained review evidence cannot be resolved for this package")
        need(builder.timestamp(review["value"]["reviewedAt"], "current review") >=
             builder.timestamp(previous_value.get("reviewedAt"), "previous review"),
             "review_regression", "A newer retained review cannot be replaced by an older approval")
    candidate = queue.adopted_candidate(root, receipt, bundle_path, review, prior)
    need(candidate is not None, "candidate_chain_rejected", code + ": adoption, current review, HTML, immutable anchor or passed page review is missing or inconsistent")
    candidate_path = builder.relative(candidate["candidatePath"], "candidate", 3)
    need(candidate_path.split("/")[1] == code, "candidate_binding", "Candidate company differs")
    tree, _ = guard.snapshot_tree(root / candidate_path)
    need(set(tree) == {"adoption.json", "index.html"}, "candidate_extra_files", "Only the adopted HTML and receipt may be carried forward")
    need(tree["adoption.json"] == candidate["adoptionSha256"] and tree["index.html"] == candidate["htmlSha256"], "input_drift", "Candidate changed after chain validation")
    # Strict reads add hardlink rejection beyond the existing builder/queue contracts.
    inputs = {bundle_path + "/manifest.json": receipt["manifestSha256"],
              bundle_path + "/ready.json": receipt["readySha256"]}
    for name, expected in receipt["verifiedPayloadHashes"].items():
        path = bundle / name
        digest, _ = guard.read_regular(path, keep_bytes=False)
        need(digest == expected, "input_drift", "Validated payload changed during binding")
        inputs[bundle_path + "/" + name] = expected
    for name, expected in [(review["path"], review["sha256"]),
                           (candidate_path + "/adoption.json", candidate["adoptionSha256"]),
                           (candidate_path + "/index.html", candidate["htmlSha256"]),
                           (candidate["pageReviewPath"], candidate["pageReviewSha256"])]:
        guard.relative_name(name)
        need(sha(read_file(root / name)) == expected, "input_drift", "Approval-chain record changed during binding")
        inputs[name] = expected
    repair_binding = {}
    if "producer-repair.json" in receipt["verifiedPayloadHashes"]:
        repair_path = review.get("repairReviewPath")
        repair_sha = review.get("repairReviewSha256")
        need(isinstance(repair_path, str) and isinstance(repair_sha, str),
             "repair_review_missing", "Legacy repair must retain its independent semantic-difference review")
        guard.relative_name(repair_path)
        guard.valid_digest(repair_sha, "repair review")
        need(sha(read_file(root / repair_path)) == repair_sha, "input_drift", "Repair review changed during binding")
        inputs[repair_path] = repair_sha
        repair_binding = {"repairReviewPath": repair_path, "repairReviewSha256": repair_sha}
    batch_binding = {}
    if sampled_batch:
        rv = review["value"]
        need(candidate.get("pageReviewScope") == "sampled_batch" and type(candidate.get("browserObserved")) is bool, "review_scope", "Batch content needs explicit batch page scope")
        batch_binding = {"reviewScope":"sampled_batch", "contentSampled":rv["contentSampled"], "browserObserved":candidate["browserObserved"], "batchId":rv["batchId"], "batchEnvelopeSha256":rv["batchEnvelopeSha256"], "batchReviewSha256":review["sha256"], "batchPageReviewSha256":candidate["pageReviewSha256"], "actuallyReviewedClaimIds":sorted(reviewed_claims)}
        env = builder.batch_envelope(root, rv["batchEnvelopePath"], rv["batchEnvelopeSha256"])
        inputs[rv["batchEnvelopePath"]] = rv["batchEnvelopeSha256"]
        inputs[rv["authorizationPath"]] = rv["authorizationSha256"]
        for member in env["members"]:
            folder = member["bundlePath"]
            inputs[folder + "/manifest.json"] = member["manifestSha256"]
            inputs[folder + "/ready.json"] = member["readySha256"]
            manifest = checker.parse_json(read_file(root / folder / "manifest.json"), "batch manifest")
            inputs.update({folder + "/" + row["path"]:row["sha256"] for row in manifest["files"]})
        page = checker.parse_json(read_file(root / candidate["pageReviewPath"]), "batch page")
        for member in page["members"]:
            inputs[member["candidatePath"] + "/adoption.json"] = member["adoptionSha256"]
            inputs[member["candidatePath"] + "/index.html"] = member["htmlSha256"]
            inputs.update({row["path"]:row["sha256"] for row in member.get("evidence", [])})
    # The two marker paths also receive strict regular-file/hardlink checks.
    for name in (bundle_path + "/manifest.json", bundle_path + "/ready.json"):
        need(sha(read_file(root / name)) == inputs[name], "input_drift", "Package marker changed")
    return {**({"contentTier": "L"} if controls["contentTier"] == "L" else {}), "code": code, "name": controls["selectedCompanies"][code], "version": version,
            "bundlePath": bundle_path, "manifestSha256": receipt["manifestSha256"],
            "readySha256": receipt["readySha256"], "verifiedPayloadHashes": receipt["verifiedPayloadHashes"],
            "reviewPath": review["path"], "reviewSha256": review["sha256"], **repair_binding,
            **({"referencedClaimIds":sorted(used_claims)} if sampled_batch else {"declaredCoverageClaimIds":sorted(used_claims)}),
            **batch_binding,
            "contentDecision": "approved", **candidate,
            "pageDecision": "passed", "priorAdoptionAnchorChecked": candidate_path in anchors,
            "mechanicalWarnings": receipt["warnings"], "inputHashes": inputs}


def tool_hashes():
    modules = [Path(__file__).absolute(), Path(guard.__file__).absolute(),
               Path(checker.__file__).absolute(), Path(builder.__file__).absolute(), Path(queue.__file__).absolute()]
    return {p.name: sha(read_file(p)) for p in modules}


def merged_hashes(*maps):
    result = {}
    for values in maps:
        for name, digest in values.items():
            guard.relative_name(name)
            guard.valid_digest(digest, "observed input")
            need(name not in result or result[name] == digest, "input_drift", "Conflicting observations of one input")
            result[name] = digest
    return dict(sorted(result.items()))


def readback_inputs(root, hashes):
    """Actual bytes once per unique file; never mtime or a cached current decision."""
    for name, expected in hashes.items():
        actual, _ = guard.read_regular(root / name, keep_bytes=False)
        need(actual == expected, "input_drift", "Bound input changed at complete readback: " + name)


def directory_shapes(root, hashes):
    """Complete bound bundle/candidate membership, including empty directories.

    File bytes remain in the deduplicated hash readback. This separate metadata
    observation detects previously unknown members and rejects linked/special
    shapes; it does not treat timestamps as proof of current content.
    """
    prefixes = sorted({"/".join(name.split("/")[:3]) for name in hashes
                       if name.split("/")[0] in {"inbox", "candidate"} and len(name.split("/")) >= 4})
    result = {}
    for prefix in prefixes:
        base = root / prefix
        pending = [base]
        shape = {".": "directory"}
        while pending:
            folder = pending.pop()
            for path in directory_entries(folder):
                info = path.lstat()
                name = path.relative_to(base).as_posix()
                guard.relative_name(name)
                need(not guard.is_link(info), "unsafe_path", "A bound tree contains a link/reparse point")
                if stat.S_ISDIR(info.st_mode):
                    shape[name] = "directory"
                    pending.append(path)
                else:
                    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                         "unsafe_path", "A bound tree contains a hardlinked or special file")
                    shape[name] = "file"
        result[prefix] = dict(sorted(shape.items()))
    return result


def readback_observation(root, before):
    """Bind the full directory inventory on both sides of actual byte reads."""
    expected = before["observedDirectoryShapes"]
    need(directory_shapes(root, before["observedInputHashes"]) == expected,
         "input_drift", "Bound directory membership or entry type changed")
    readback_inputs(root, before["observedInputHashes"])
    need(directory_shapes(root, before["observedInputHashes"]) == expected,
         "input_drift", "Bound directory membership changed during byte readback")


def validation_pass(root, codes, controls, state, reviews, shared):
    if not shared:
        return [verify_company(root, c, controls, state, reviews) for c in codes], {}, {}
    with builder.validation_observation(root) as observation:
        selected = [verify_company(root, c, controls, state, reviews) for c in codes]
    return selected, dict(observation.hashes), dict(observation.counts)


def checkpoint_selection(root, before, codes, content_tier=None):
    """Use only after check_selection in this operation; not an approval entrypoint.

    Re-observes all control records and every frozen input byte. No semantic cache
    is alive here, and none survives into a later invocation of check_selection.
    """
    need(before.get("status") == "verified_for_conversion_inputs" and "observedInputHashes" in before,
         "observation_missing", "A completed shared observation is required")
    codes = sorted(codes)
    need([item["code"] for item in before["acceptedInputs"]] == codes,
         "company_selection", "Checkpoint selection differs")
    binding_keys = ("acceptedInputs", "controlSnapshotSha256", "companyUniverseSha256", "queueStateSha256", "toolHashes", "observedInputHashes", "observedDirectoryShapes")
    need(sha(canonical({k:before[k] for k in binding_keys})) == before["bindingId"], "input_drift", "In-memory binding was changed")
    controls, _, _ = control_snapshot(root, codes, content_tier)
    need(sha(canonical(controls)) == before["controlSnapshotSha256"] and tool_hashes() == before["toolHashes"],
         "input_drift", "Current control records or tools changed")
    readback_observation(root, before)
    after, _, _ = control_snapshot(root, codes, content_tier)
    need(after == controls and tool_hashes() == before["toolHashes"], "input_drift", "Control records changed during complete byte readback")
    need(directory_shapes(root, before["observedInputHashes"]) == before["observedDirectoryShapes"],
         "input_drift", "Bound directory membership changed during final control observation")


def check_selection(root, codes, content_tier=None, *, shared_observation=False):
    """Testable core. CLI always uses the script's fixed parent root."""
    result = {"schemaVersion": 1, "jobId": checker.JOB_ID, "status": "rejected",
              "localOnly": True, "readyForPublication": False, "noDeploy": True,
              "validatedRecordBindingsOnly": True, "acceptedInputs": [], "errors": [],
              "limitations": LIMITATIONS.copy()}
    try:
        need(content_tier in (None, 'L'), 'content_tier', 'Unknown requested content tier')
        root = Path(os.path.abspath(root))
        guard.guarded_path(root)
        need(root == Path(os.path.abspath(checker.TRUSTED_ROOT)), "trusted_root", "Checker trust root and selected task root must be the same")
        need(isinstance(codes, list) and bool(codes) and all(isinstance(c, str) and queue.CODE.fullmatch(c) for c in codes), "company_selection", "Select one or more full company codes")
        need(len(codes) == len(set(codes)), "company_selection", "Duplicate company selection")
        codes = sorted(codes)
        observe = lambda: control_snapshot(root, codes, content_tier) if content_tier else control_snapshot(root, codes)
        tools_before = tool_hashes()
        first_controls, state, reviews = observe()
        first, first_reads, first_counts = validation_pass(root, codes, first_controls, state, reviews, shared_observation)
        first_shapes = directory_shapes(root, merged_hashes(first_reads, *(item["inputHashes"] for item in first))) if shared_observation else {}
        second_controls, second_state, second_reviews = observe()
        need(first_controls == second_controls, "input_drift", "Package discovery, review records, queue evidence or trusted universe changed")
        second, second_reads, second_counts = validation_pass(root, codes, second_controls, second_state, second_reviews, shared_observation)
        second_shapes = directory_shapes(root, merged_hashes(second_reads, *(item["inputHashes"] for item in second))) if shared_observation else {}
        need(first_reads == second_reads, "input_drift", "Complete observed read sets changed between independent passes")
        need(first_shapes == second_shapes, "input_drift", "Complete bound directory shapes changed between independent passes")
        need(first == second, "input_drift", "A complete approval chain changed between independent passes")
        final_controls, _, _ = observe()
        need(final_controls == first_controls and tools_before == tool_hashes(), "input_drift", "Control records or validation tools changed before completion")
        # Union once, including dependencies read only by the shared validators.
        observed_hashes = merged_hashes(second_reads, *(item["inputHashes"] for item in second))
        if shared_observation:
            readback_observation(root, {"observedInputHashes": observed_hashes, "observedDirectoryShapes": second_shapes})
        else:
            readback_inputs(root, observed_hashes)
        final_again, _, _ = observe()
        need(final_again == first_controls, "input_drift", "New package or review appeared during final readback")
        if shared_observation:
            need(directory_shapes(root, observed_hashes) == second_shapes, "input_drift", "Bound directory changed during final control observation")
        binding = {"acceptedInputs": second, "controlSnapshotSha256": sha(canonical(first_controls)),
                   "companyUniverseSha256": first_controls["companyUniverseSha256"],
                   "queueStateSha256": first_controls["queueStateSha256"], "toolHashes": tools_before}
        if shared_observation:
            binding["observedInputHashes"] = observed_hashes
            binding["observedDirectoryShapes"] = second_shapes
            result["observationCounts"] = {"firstPass":first_counts, "secondPass":second_counts,
                                            "uniqueInputFiles":len(observed_hashes)}
        result.update(status="verified_for_conversion_inputs", checkedAt=datetime.now(timezone.utc).isoformat(),
                      bindingId=sha(canonical(binding)), **binding)
    except (ChainError, guard.Refused, checker.PackageError, builder.BuildError, queue.QueueError, OSError, TypeError, KeyError, ValueError) as error:
        result["errors"].append({"code": getattr(error, "code", "invalid_or_unreadable_chain"),
                                 "message": str(error) if isinstance(error, ValueError) else "Chain input could not be read safely"})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", action="append", required=True, help="Full company code; repeat to require a complete batch")
    parser.add_argument('--content-tier', choices=['L'], default=None)
    args = parser.parse_args(argv)
    result = check_selection(ROOT, args.company, args.content_tier)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["status"] == "verified_for_conversion_inputs" else 1


if __name__ == "__main__":
    raise SystemExit(main())
