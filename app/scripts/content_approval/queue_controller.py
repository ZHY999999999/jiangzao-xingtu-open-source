#!/usr/bin/env python3
"""Local, leased production queue. Website catalogue != current listing verification.

Only writes company-universe.json, queue-state.json and a short-held lock here.
Never writes production packages, approvals, candidates, source project or network.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid

sys.dont_write_bytecode = True
import package_check as checker
import build_candidate as builder

ROOT = Path(__file__).absolute().parent
CODE = re.compile(r"[0-9]{6}\.(SH|SZ|BJ)\Z")
VERSION = re.compile(r"v([0-9]{3,})\Z")
PAGE_FIELDS = {"schemaVersion", "jobId", "code", "manifestSha256", "candidatePath", "htmlSha256", "pageDecision", "reviewer", "reviewedAt"}
L_REPRESENTATIVES = ["000333.SZ", "600588.SH", "600036.SH"]
REPAIR_PURPOSE = "legacy_reader_voice_repair"
REPAIR_PAYLOAD = "producer-repair.json"
BATCH_PURPOSE = "l_industry_batch"
BATCH_AUTHORIZATION = "reviews/runs/l1-20261004/batch-authorization.json"


class QueueError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise QueueError(message)


def utcnow():
    return datetime.now(timezone.utc)


def iso(value):
    return value.astimezone(timezone.utc).isoformat()


def parse_time(value):
    require(isinstance(value, str), "Expected ISO time")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise QueueError("Expected ISO time") from None
    require(result.tzinfo is not None and result.utcoffset() is not None, "Time requires timezone")
    return result.astimezone(timezone.utc)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    return checker.parse_json(builder.read_regular(path), path.name)


def atomic_json(path, value):
    checker.directory_guard(path.parent)
    if path.exists():
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and not checker.is_reparse(info), "Unsafe output path")
    elif path.is_symlink():
        raise QueueError("Unsafe dangling output link")
    temp = path.parent / ("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(builder.json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()  # Only this call's exact temporary metadata file.


@contextmanager
def short_lock(root, timeout=5):
    checker.directory_guard(root)
    path = root / ".queue-controller.lock"
    if path.exists() or path.is_symlink():
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and not checker.is_reparse(info), "Unsafe queue lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0), 0o600)
    stream = os.fdopen(fd, "r+b")
    locked = False
    try:
        if os.fstat(stream.fileno()).st_size == 0:
            stream.write(b"0")
            stream.flush()
        until = time.monotonic() + timeout
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError:
                if time.monotonic() >= until:
                    raise QueueError("Queue lock is busy") from None
                time.sleep(0.05)
        yield
    finally:
        if locked:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def config(root):
    value = read_json(root / "queue-config.json")
    require(isinstance(value, dict), "Invalid queue config")
    require(value.get("jobId") == checker.JOB_ID, "Wrong queue jobId")
    require(value.get("cutoff") == "2026-10-02", "Wrong queue cutoff")
    source = Path(value.get("sourceIndex", ""))
    require(source.is_absolute(), "sourceIndex must be an absolute read-only path")
    pilots = value.get("pilotCodes")
    require(isinstance(pilots, list) and len(pilots) == 5 and len(set(pilots)) == 5 and all(isinstance(c, str) and CODE.fullmatch(c) for c in pilots), "Expected five distinct pilot codes")
    require(CODE.fullmatch(value.get("benchmarkCode", "")) is not None and value["benchmarkCode"] not in pilots, "Invalid benchmark code")
    require(type(value.get("autoExpandAfterPilot")) is bool, "autoExpandAfterPilot must be boolean")
    require(value.get("leaseMinutes", 90) == 90, "This queue uses a renewable 90-minute lease")
    require(value.get("targetContentTier") in (None, "L"), "Unsupported target content tier")
    if value.get("targetContentTier") == "L":
        builder.relative(value.get("scopePath"), "migrations")
        require(isinstance(value.get("scopeSha256"), str) and checker.SHA256.fullmatch(value["scopeSha256"]), "Frozen L scope requires a SHA256 binding")
    return value


def refresh_universe(root, cfg, now):
    source_path = root / cfg["scopePath"] if cfg.get("targetContentTier") == "L" else Path(cfg["sourceIndex"])
    raw = builder.read_regular(source_path)
    if cfg.get("targetContentTier") == "L":
        require(sha(raw) == cfg["scopeSha256"], "Frozen L scope bytes changed")
    source = checker.parse_json(raw, "sourceIndex")
    require(isinstance(source.get("companies"), list) and source["companies"], "Empty website company catalogue")
    by_code = {}
    for row in source["companies"]:
        require(isinstance(row, dict), "Invalid company entry")
        code, name = row.get("code"), row.get("name")
        require(isinstance(code, str) and CODE.fullmatch(code) is not None, "Invalid complete company code")
        require(isinstance(name, str) and name == name.strip() and bool(name), "Empty or ambiguous company name")
        require(code not in by_code or by_code[code] == name, "Conflicting names for one company code")
        by_code[code] = name
    require(set(cfg["pilotCodes"]) <= by_code.keys(), "A pilot code is absent from the website catalogue")
    value = source.get("asOf")
    require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{8}", value), "Invalid website catalogue date")
    source_date = date.fromisoformat(value if "-" in value else f"{value[:4]}-{value[4:6]}-{value[6:]}")
    require(source_date <= now.astimezone(timezone(timedelta(hours=8))).date(), "Website catalogue date is in the future")
    result = {"schemaVersion": 1, "jobId": cfg["jobId"], "sourceIndex": cfg["sourceIndex"],
              "sourceSha256": sha(raw), "sourceAsOf": source["asOf"], "generatedAt": iso(now), "cutoff": cfg["cutoff"],
              "companies": [{"code": code, "name": by_code[code]} for code in sorted(by_code)]}
    path = root / "company-universe.json"
    if path.exists():
        existing = read_json(path)
        # Preserve the trusted configuration bytes while the source is unchanged.
        # Concurrent package checking binds this entire file, including generatedAt.
        require(isinstance(existing, dict), "Invalid existing company universe")
        parse_time(existing.get("generatedAt"))
        if {k: v for k, v in existing.items() if k != "generatedAt"} == {k: v for k, v in result.items() if k != "generatedAt"}:
            return existing
    atomic_json(path, result)
    return result


def read_state(root, cfg):
    path = root / "queue-state.json"
    if not path.exists():
        return {"schemaVersion": 1, "jobId": cfg["jobId"], "revision": 0, "phase": "pilot", "lease": None, "blocked": {}, "observations": {}}
    state = read_json(path)
    require(state.get("schemaVersion") == 1 and state.get("jobId") == cfg["jobId"], "Invalid queue state identity")
    require(type(state.get("revision")) is int and isinstance(state.get("blocked"), dict) and isinstance(state.get("observations"), dict), "Invalid queue state shape")
    require(isinstance(state.get("repairReceipts", {}), dict), "Invalid repair receipts")
    require(isinstance(state.get("batchReceipts", {}), dict), "Invalid batch receipts")
    if state.get("lease"):
        lease = state["lease"]
        if is_batch_lease(lease):
            validate_batch_lease(lease, cfg)
        else:
            require(CODE.fullmatch(lease.get("code", "")) is not None and VERSION.fullmatch(lease.get("version", "")) is not None, "Invalid saved lease")
        parse_time(lease["expiresAt"])
        uuid.UUID(lease["runId"])
    return state


def save_state(root, state, now):
    state["updatedAt"] = iso(now)
    state["revision"] += 1
    atomic_json(root / "queue-state.json", state)


def start_tier(root, tier, clock=utcnow):
    """Explicit, immutable migration; never turns legacy approval into L approval."""
    require(tier == "L", "Only L can be explicitly started")
    root = Path(os.path.abspath(root))
    with short_lock(root):
        now = clock()
        cfg = config(root)
        state = read_state(root, cfg)
        require(active_lease(state, now) is None, "Cannot change tier while a production lease is active")
        if cfg.get("targetContentTier") == "L":
            refresh_universe(root, cfg, now)
            return {"status": "already_started", "contentTier": "L", "scopePath": cfg["scopePath"], "scopeSha256": cfg["scopeSha256"], "migrationPath": cfg["migrationPath"]}
        original_config = builder.read_regular(root / "queue-config.json")
        original_state = builder.read_regular(root / "queue-state.json") if (root / "queue-state.json").exists() else builder.json_bytes(state)
        original_index = builder.read_regular(Path(cfg["sourceIndex"]))
        # Validate the same frozen bytes before installing a new scope.
        source = checker.parse_json(original_index, "sourceIndex")
        require(isinstance(source, dict) and isinstance(source.get("companies"), list) and bool(source["companies"]), "Invalid L source catalogue")
        by_code = {}
        for row in source["companies"]:
            require(isinstance(row, dict) and isinstance(row.get("code"), str) and CODE.fullmatch(row["code"]) and isinstance(row.get("name"), str) and row["name"].strip() == row["name"] and bool(row["name"]), "Invalid L source company")
            require(row["code"] not in by_code or by_code[row["code"]] == row["name"], "Conflicting company names")
            by_code[row["code"]] = row["name"]
        require(set(cfg["pilotCodes"]) <= by_code.keys(), "Pilot company missing from L scope")
        catalogue_date = source.get("asOf", "")
        require(isinstance(catalogue_date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}|\d{8}", catalogue_date), "Invalid L catalogue date")
        parsed_date = date.fromisoformat(catalogue_date if "-" in catalogue_date else f"{catalogue_date[:4]}-{catalogue_date[4:6]}-{catalogue_date[6:]}")
        require(parsed_date <= now.astimezone(timezone(timedelta(hours=8))).date(), "L catalogue date is in the future")
        migrations = root / "migrations"
        builder.ensure_directory(migrations)
        folder = migrations / ("L-" + now.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
        folder.mkdir(exist_ok=False)
        frozen = {"source-index.json": original_index, "queue-state-before.json": original_state, "queue-config-before.json": original_config}
        for name, raw in frozen.items():
            builder.write_new(folder / name, raw)
        migration_path = folder.relative_to(root).as_posix()
        receipt = {"schemaVersion": 1, "jobId": checker.JOB_ID, "contentTier": "L", "startedAt": iso(now), "sourceIndex": cfg["sourceIndex"], "sourceSha256": sha(original_index), "companyCount": len(by_code), "benchmarkCode": cfg["benchmarkCode"], "files": {name: sha(raw) for name, raw in frozen.items()}, "legacyCompletionGrantsL": False}
        builder.write_new(folder / "migration.json", builder.json_bytes(receipt))
        cfg.update(targetContentTier="L", scopePath=migration_path + "/source-index.json", scopeSha256=sha(original_index), migrationPath=migration_path)
        atomic_json(root / "queue-config.json", cfg)
        state.update(activeTier="L", phase="L", lease=None, blocked={}, migrationPath=migration_path)
        save_state(root, state, now)
        refresh_universe(root, cfg, now)
        return {"status": "tier_started", "contentTier": "L", "companyCount": len(by_code), "scopePath": cfg["scopePath"], "scopeSha256": cfg["scopeSha256"], "migrationPath": migration_path}


def safe_children(folder):
    if not folder.exists():
        return []
    checker.directory_guard(folder)
    result = []
    for path in folder.iterdir():
        info = path.lstat()
        require(not checker.is_reparse(info), "Linked queue input refused")
        if stat.S_ISDIR(info.st_mode):
            result.append(path)
    return result


def review_files(root):
    start = root / "reviews"
    if not start.exists():
        return []
    checker.directory_guard(start)
    files = []
    for folder, dirs, names in os.walk(start, followlinks=False):
        for name in dirs:
            checker.directory_guard(Path(folder) / name)
        for name in names:
            if name.endswith(".json") and name != "page-review.json":
                files.append(Path(folder) / name)
    return files


def is_repair_lease(lease):
    return bool(lease and lease.get("purpose") == REPAIR_PURPOSE)


def validate_repair_lease(lease, cfg):
    require(is_repair_lease(lease) and lease.get("queueTier") == cfg.get("targetContentTier") == "L" and lease.get("contentTier") is None, "Invalid legacy repair lease scope")
    require(lease.get("code") != cfg["benchmarkCode"], "Benchmark is read-only")
    checker.text(lease.get("producerId"), "lease.producerId")
    require(str(uuid.UUID(lease["repairId"])) == lease["repairId"], "Invalid repair id")
    require(str(uuid.UUID(lease["leaseId"])) == lease["leaseId"], "Invalid repair lease id")
    require(builder.relative(lease["baseBundlePath"], "inbox", 3).split("/")[1] == lease["code"], "Repair base company mismatch")
    require(isinstance(lease.get("baseManifestSha256"), str) and checker.SHA256.fullmatch(lease["baseManifestSha256"]), "Invalid repair base hash")


def repair_version_inventory(root, code, exclude_path=None):
    result = {}
    for path in safe_children(root / "inbox" / code):
        if not VERSION.fullmatch(path.name) or path.relative_to(root).as_posix() == exclude_path:
            continue
        reader_path = path / "reader.json"
        result[path.name] = sha(builder.read_regular(reader_path)) if reader_path.exists() else None
    return result


def repair_base_binding(root, cfg, code, base_path, base_hash, prior, exclude_path=None, failed_paths=()):
    """Bind the latest legacy base to actual package/review/page bytes."""
    require(cfg.get("targetContentTier") == "L", "Legacy repair is an explicit exception inside the frozen L queue")
    require(code != cfg["benchmarkCode"], "Benchmark is read-only")
    scope_raw = builder.read_regular(root / cfg["scopePath"])
    require(sha(scope_raw) == cfg["scopeSha256"], "Frozen scope changed")
    scope = checker.parse_json(scope_raw, "L scope")
    require(code in {r["code"] for r in scope["companies"]}, "Repair company is outside the frozen scope")
    base_path = builder.relative(base_path, "inbox", 3)
    parts = base_path.split("/")
    require(parts[1] == code and VERSION.fullmatch(parts[2]), "Invalid legacy repair base path")
    require(isinstance(base_hash, str) and checker.SHA256.fullmatch(base_hash), "Invalid base manifest hash")
    inventory = repair_version_inventory(root, code, exclude_path)
    versions = sorted((p for p in safe_children(root / "inbox" / code) if VERSION.fullmatch(p.name)), key=lambda p: int(VERSION.fullmatch(p.name)[1]))
    legacy = []
    for path in versions:
        if path.relative_to(root).as_posix() == exclude_path:
            continue
        try:
            value = read_json(path / "reader.json")
            require(isinstance(value, dict), "Invalid version reader")
            if checker.content_tier(value) is None:
                if path.relative_to(root).as_posix() not in failed_paths:
                    legacy.append(path)
        except (OSError, ValueError, TypeError, KeyError):
            if path.relative_to(root).as_posix() in failed_paths:
                continue  # Caller binds this exact failed attempt's full tree.
            require(int(VERSION.fullmatch(path.name)[1]) < int(VERSION.fullmatch(parts[2])[1]), "A newer package has an unknown tier; repair cannot bypass it")
    require(legacy and legacy[-1].relative_to(root).as_posix() == base_path, "Repair base must be the latest legacy version; no fallback across a newer repair")
    receipt = checker.check_bundle(root / base_path)
    require(receipt.get("mechanicalPassed") is True and not receipt.get("errors") and receipt.get("contentTier") is None and receipt.get("manifestSha256") == base_hash, "Legacy repair base package failed identity/hash/mechanical checks")
    bodies = builder.load_payload(root / base_path, receipt)
    review = find_review(root, review_files(root), receipt, base_path, bodies)
    require(review and review["value"]["contentDecision"] == "approved", "Legacy repair base lacks a current independent approved review")
    candidate = adopted_candidate(root, receipt, base_path, review, prior)
    require(candidate is not None, "Legacy repair base lacks a valid candidate and actual page acceptance")
    final = checker.check_bundle(root / base_path)
    builder.same_receipt(receipt, final)
    require(final.get("mechanicalPassed") is True and find_review(root, review_files(root), final, base_path, bodies) == review and adopted_candidate(root, final, base_path, review, prior) == candidate, "Legacy repair base changed during verification")
    require(repair_version_inventory(root, code, exclude_path) == inventory, "Company version inventory changed while verifying legacy repair base")
    return {"bundlePath": base_path, "manifestSha256": base_hash, "readySha256": receipt["readySha256"], "reviewPath": review["path"], "reviewSha256": review["sha256"], "versionInventory": inventory, **candidate}


def next_reserved_version(root, code, state):
    values = [int(VERSION.fullmatch(p.name)[1]) for p in safe_children(root / "inbox" / code) if VERSION.fullmatch(p.name)]
    records = list(state.get("repairReceipts", {}).values()) + ([state["lease"]] if state.get("lease") else [])
    records += [member for batch in state.get("batchReceipts", {}).values() for member in batch.get("members", [])]
    values += [int(VERSION.fullmatch(row["version"])[1]) for row in records if row.get("code") == code and VERSION.fullmatch(row.get("version", ""))]
    return f"v{max(values, default=0) + 1:03d}"


def repair_payload(root, receipt, bundle_path):
    expected = receipt.get("verifiedPayloadHashes", {}).get(REPAIR_PAYLOAD)
    require(expected is not None and receipt.get("contentTier") is None, "Repair metadata is required only on an unmarked legacy seven-question package")
    raw = builder.read_regular(root / bundle_path / REPAIR_PAYLOAD)
    require(sha(raw) == expected, "Repair metadata differs from its verified manifest hash")
    value = checker.parse_json(raw, REPAIR_PAYLOAD)
    checker.shape(value, {"schemaVersion", "jobId", "code", "producer", "repair"}, set(), REPAIR_PAYLOAD)
    require(value["jobId"] == checker.JOB_ID and value["code"] == receipt["code"], "Repair metadata identity mismatch")
    checker.shape(value["producer"], {"id", "runId"}, set(), "repair.producer")
    checker.text(value["producer"]["id"], "repair.producer.id")
    require(str(uuid.UUID(value["producer"]["runId"])) == value["producer"]["runId"], "Repair producer run requires a canonical UUID")
    row = value["repair"]
    checker.shape(row, {"purpose", "repairId", "leaseId", "baseBundlePath", "baseManifestSha256", "reason"}, {"retryOf", "failedBundlePath", "failedPackageSha256"}, "repair")
    require(row["purpose"] == REPAIR_PURPOSE, "Unknown repair purpose")
    for key in ("repairId", "leaseId"):
        require(str(uuid.UUID(row[key])) == row[key], "Repair identifiers require canonical UUIDs")
    checker.text(row["reason"], "repair.reason")
    require(builder.relative(row["baseBundlePath"], "inbox", 3).split("/")[1] == receipt["code"], "Repair base belongs to another company")
    require(isinstance(row["baseManifestSha256"], str) and checker.SHA256.fullmatch(row["baseManifestSha256"]), "Invalid repair base hash")
    if "retryOf" in row:
        require({"failedBundlePath", "failedPackageSha256"} <= row.keys(), "Retry metadata must bind its failed package")
        require(str(uuid.UUID(row["retryOf"])) == row["retryOf"], "Invalid retry predecessor id")
        require(builder.relative(row["failedBundlePath"], "inbox", 3).split("/")[1] == receipt["code"], "Retry predecessor company mismatch")
        require(isinstance(row["failedPackageSha256"], str) and checker.SHA256.fullmatch(row["failedPackageSha256"]), "Invalid failed package snapshot hash")
    else:
        require("failedBundlePath" not in row and "failedPackageSha256" not in row, "Failed package fields require retryOf")
    return value, expected


def repair_metadata_fields(lease):
    keys = ("purpose", "repairId", "leaseId", "baseBundlePath", "baseManifestSha256", "reason")
    if lease.get("retryOf"):
        keys += ("retryOf", "failedBundlePath", "failedPackageSha256")
    return {key: lease[key] for key in keys}


def failed_repair_binding(root, record, now):
    """A retry needs a real failed immutable attempt, never a pending review."""
    path = root / builder.relative(record["bundlePath"], "inbox", 3)
    require(path.exists(), "Retry predecessor has no package to preserve; resume its existing request instead")
    first = checker.collect(path)
    hashes, _ = checker.read_tree(path, first)
    require(checker.collect(path) == first, "Failed repair changed during snapshot")
    binding = {"repairId": record["repairId"], "bundlePath": record["bundlePath"], "packageSha256": sha(builder.json_bytes(hashes))}
    receipt = checker.check_bundle(path)
    if "ready.json" in hashes and receipt.get("mechanicalPassed") is not True:
        binding.update(failureKind="mechanical", errors=receipt.get("errors", []))
    elif receipt.get("mechanicalPassed") is True:
        bodies = builder.load_payload(path, receipt)
        review = find_review(root, review_files(root), receipt, record["bundlePath"], bodies)
        if review and review["value"]["contentDecision"] in {"needs_revision", "insufficient_evidence"}:
            binding.update(failureKind="independent_review", manifestSha256=receipt["manifestSha256"], reviewPath=review["path"], reviewSha256=review["sha256"], decision=review["value"]["contentDecision"])
        else:
            require(not review or review["value"]["contentDecision"] != "approved", "Approved repair must be used as the next base, not bypassed as a failed attempt")
            require(record.get("status") == "blocked" and bool(record.get("blockReason")) and parse_time(record["retryAfter"]) <= now, "Mechanically valid repair awaits review/approval; it cannot be skipped")
            binding.update(failureKind="explicit_block", blockReason=record["blockReason"], retryAfter=record["retryAfter"])
    else:
        require(record.get("status") == "blocked" and bool(record.get("blockReason")) and parse_time(record["retryAfter"]) <= now, "Unsealed repair requires an explicit matured block before a new immutable attempt")
        binding.update(failureKind="explicit_block", blockReason=record["blockReason"], retryAfter=record["retryAfter"])
    final = checker.collect(path); final_hashes, _ = checker.read_tree(path, final)
    require(first == final and hashes == final_hashes, "Failed repair changed while verifying retry grounds")
    return binding


def verify_failure_chain(root, state, chain, now):
    require(isinstance(chain, list), "Invalid repair failure chain")
    seen = set()
    for expected in chain:
        require(isinstance(expected, dict) and expected.get("repairId") not in seen, "Duplicate/invalid repair failure chain")
        seen.add(expected["repairId"])
        saved = state.get("repairReceipts", {}).get(expected["repairId"])
        require(saved is not None and failed_repair_binding(root, saved, now) == expected, "A retry predecessor or its failure evidence changed")
    return [row["bundlePath"] for row in chain]


def validate_repair_sidecar(root, review_path, review_raw, review, receipt, bundle_path):
    payload, payload_hash = repair_payload(root, receipt, bundle_path)
    state = read_state(root, config(root))
    row = payload["repair"]
    submitted = state.get("repairReceipts", {}).get(row["repairId"], {})
    require(submitted.get("status") == "submitted" and submitted.get("manifestSha256") == receipt["manifestSha256"] and submitted.get("readySha256") == receipt["readySha256"] and submitted.get("payloadSha256") == payload_hash and submitted.get("bundlePath") == bundle_path and submitted.get("leaseId") == row["leaseId"] and submitted.get("runId") == payload["producer"]["runId"] and submitted.get("producerId") == payload["producer"]["id"] and submitted.get("baseBundlePath") == row["baseBundlePath"] and submitted.get("baseManifestSha256") == row["baseManifestSha256"], "Repair approval requires an actual matching controller submission receipt")
    verify_failure_chain(root, state, submitted.get("failureChain", []), utcnow())
    path = review_path.parent / "repair-review.json"
    raw = builder.read_regular(path)
    value = checker.parse_json(raw, "repair-review")
    fields = {"schemaVersion", "jobId", "code", "bundlePath", "manifestSha256", "baseBundlePath", "baseManifestSha256", "producer", "leaseId", "repairId", "reviewSha256", "reviewer", "reviewedAt", "checks", "semanticDiff"}
    checker.shape(value, fields, set(), "repair-review")
    require(value["jobId"] == checker.JOB_ID and value["code"] == receipt["code"] and value["bundlePath"] == bundle_path and value["manifestSha256"] == receipt["manifestSha256"] and value["baseBundlePath"] == row["baseBundlePath"] and value["baseManifestSha256"] == row["baseManifestSha256"] and value["producer"] == payload["producer"] and value["leaseId"] == row["leaseId"] and value["repairId"] == row["repairId"] and value["reviewSha256"] == sha(review_raw), "Repair sidecar binding mismatch")
    reviewer = checker.text(value["reviewer"], "repair-review.reviewer")
    require(reviewer == checker.text(review["reviewer"], "review.reviewer") and reviewer.casefold() != payload["producer"]["id"].strip().casefold(), "Repair requires the same independent reviewer; self-review is forbidden")
    require(builder.timestamp(value["reviewedAt"], "repair-review.reviewedAt") >= builder.timestamp(review["reviewedAt"], "review.reviewedAt"), "Repair sidecar predates its bound review")
    checker.shape(value["checks"], builder.L_CHECKS, set(), "repair-review.checks")
    for key, check in value["checks"].items():
        checker.shape(check, {"decision", "reason"}, set(), "repair-review.checks." + key)
        require(check["decision"] == "passed", "All three reader checks must pass for repair approval")
        checker.text(check["reason"], "repair-review.checks.reason")
    diff = value["semanticDiff"]
    checker.shape(diff, {"decision", "reason", "changedPaths", "factsUnchanged", "sourceReuse", "audioDisposition"}, set(), "repair-review.semanticDiff")
    require(diff["decision"] == "passed" and diff["factsUnchanged"] is True, "Legacy viewpoint repair cannot introduce unreviewed factual changes")
    for key in ("reason", "sourceReuse", "audioDisposition"):
        checker.text(diff[key], "repair-review.semanticDiff." + key)
    for changed in checker.string_list(diff["changedPaths"], "repair-review.semanticDiff.changedPaths", nonempty=True):
        checker.safe_relative(changed, "repair-review.semanticDiff.changedPaths")
        require(changed in receipt["verifiedPayloadHashes"], "Repair changed path is absent from the submitted payload")
    require(builder.read_regular(path) == raw, "Repair sidecar changed during read")
    return {"repairReviewPath": path.relative_to(root).as_posix(), "repairReviewSha256": sha(raw), "repairId": row["repairId"]}


def reserved_repair_bundle(root, bundle_path):
    path = root / "queue-state.json"
    if not path.exists():
        return False
    state = read_json(path)
    return any(row.get("bundlePath") == bundle_path for row in state.get("repairReceipts", {}).values())


def repair_legacy(root, run_id, code, base_path, base_hash, reason, producer_id, repair_id=None, clock=utcnow, retry_of=None):
    require(isinstance(run_id, str), "--run-id UUID is required")
    run_id = str(uuid.UUID(run_id))
    require(isinstance(code, str) and CODE.fullmatch(code), "--code requires a complete company code")
    producer_id = checker.text(producer_id, "producer-id")
    reason = checker.text(reason, "reason")
    base_path = builder.relative(base_path, "inbox", 3)
    require(isinstance(base_hash, str) and checker.SHA256.fullmatch(base_hash), "--base-manifest requires lowercase SHA256")
    retry_of = str(uuid.UUID(retry_of)) if retry_of else None
    repair_id = str(uuid.UUID(repair_id)) if repair_id else str(uuid.uuid5(uuid.UUID(run_id), code + "|" + base_path + "|" + base_hash + ("|retry:" + retry_of if retry_of else "")))
    for _ in range(4):
        with short_lock(root):
            cfg = config(root); state = read_state(root, cfg); revision = state["revision"]; now = clock()
            require(cfg.get("targetContentTier") == "L", "Legacy repair requires the active frozen L queue")
            saved = state.get("repairReceipts", {}).get(repair_id)
            if saved:
                require(saved.get("runId") == run_id and saved.get("code") == code and saved.get("baseBundlePath") == base_path and saved.get("baseManifestSha256") == base_hash and saved.get("producerId") == producer_id and saved.get("reason") == reason, "Repair id belongs to another run or request; it cannot be reused")
                require(saved.get("retryOf") == retry_of, "Repair id belongs to another retry lineage")
                require(saved.get("status") != "blocked" or parse_time(saved["retryAfter"]) <= now, "Repair is blocked until its recorded retry time")
            lease = active_lease(state, now)
            if not (saved and saved.get("status") == "submitted"):
                require(not lease or (is_repair_lease(lease) and lease.get("repairId") == repair_id and lease.get("runId") == run_id), "Another unexpired lease is active; finish it before requesting legacy repair")
            exclude = saved.get("bundlePath") if saved else None
            prior = state["observations"].get(code, {})
            predecessor = state.get("repairReceipts", {}).get(retry_of) if retry_of else None
            if retry_of:
                require(predecessor and predecessor.get("code") == code and predecessor.get("baseBundlePath") == base_path and predecessor.get("baseManifestSha256") == base_hash and retry_of != repair_id, "Retry must belong to the same original approved base and company")
        failure_chain = list((saved or predecessor or {}).get("failureChain", []))
        if retry_of and not saved:
            failure_chain.append(failed_repair_binding(root, predecessor, now))
        failed_paths = [] if saved and saved.get("status") == "submitted" else verify_failure_chain(root, state, failure_chain, now)
        binding = None if saved and saved.get("status") == "submitted" else repair_base_binding(root, cfg, code, base_path, base_hash, prior, exclude, failed_paths)
        submitted_receipt = None
        if saved and saved.get("status") == "submitted":
            submitted_receipt = checker.check_bundle(root / saved["bundlePath"])
            require(submitted_receipt.get("mechanicalPassed") is True and submitted_receipt.get("manifestSha256") == saved.get("manifestSha256") and submitted_receipt.get("readySha256") == saved.get("readySha256"), "Previously submitted repair package drifted")
            repair_payload(root, submitted_receipt, saved["bundlePath"])
        with short_lock(root):
            current = read_state(root, cfg)
            if current["revision"] != revision or config(root) != cfg:
                continue
            state = current; now = clock()
            if submitted_receipt:
                return {"status": "already_submitted", "purpose": REPAIR_PURPOSE, "repairId": repair_id, "code": code, "version": saved["version"], "bundlePath": saved["bundlePath"], "manifestSha256": saved["manifestSha256"], "queueTier": "L", "contentApproved": False}
            live = active_lease(state, now)
            require(not live or (is_repair_lease(live) and live.get("repairId") == repair_id and live.get("runId") == run_id), "Lease changed while verifying repair base")
            require(repair_version_inventory(root, code, exclude) == binding["versionInventory"], "Company versions changed before repair lease acquisition")
            receipts = state.setdefault("repairReceipts", {})
            if saved:
                lease = {key: saved[key] for key in ("runId", "leaseId", "code", "version", "contentTier", "queueTier", "purpose", "repairId", "producerId", "baseBundlePath", "baseManifestSha256", "reason")}
                if retry_of:
                    lease.update({key: saved[key] for key in ("retryOf", "failedBundlePath", "failedPackageSha256")})
                require(binding == saved.get("baseBinding"), "Repair base approval changed since assignment")
            else:
                old = state.get("lease")
                if is_repair_lease(old) and old["repairId"] in receipts:
                    receipts[old["repairId"]].update(status="expired", expiredAt=iso(now))
                lease = {"runId": run_id, "leaseId": str(uuid.uuid4()), "code": code, "version": next_reserved_version(root, code, state), "contentTier": None, "queueTier": "L", "purpose": REPAIR_PURPOSE, "repairId": repair_id, "producerId": producer_id, "baseBundlePath": base_path, "baseManifestSha256": base_hash, "reason": reason}
                if retry_of:
                    lease.update(retryOf=retry_of, failedBundlePath=predecessor["bundlePath"], failedPackageSha256=failure_chain[-1]["packageSha256"])
            lease["expiresAt"] = iso(now + timedelta(minutes=90))
            validate_repair_lease(lease, cfg)
            state["lease"] = lease
            bundle_path = f"inbox/{code}/{lease['version']}"
            receipts[repair_id] = {**(saved or {}), **lease, "status": "assigned", "bundlePath": bundle_path, "assignedAt": (saved or {}).get("assignedAt", iso(now)), "baseBinding": binding, "failureChain": failure_chain}
            save_state(root, state, now)
            payload = {"schemaVersion": 1, "jobId": checker.JOB_ID, "code": code, "producer": {"id": producer_id, "runId": run_id}, "repair": repair_metadata_fields(lease)}
            return {"status": "assigned", "resumed": saved is not None, "purpose": REPAIR_PURPOSE, "queueTier": "L", "payloadTier": "legacy", "repairId": repair_id, "code": code, "version": lease["version"], "bundlePath": bundle_path, "lease": lease, "requiredPayloadFile": REPAIR_PAYLOAD, "requiredPayload": payload, "contentApproved": False}
    return {"status": "busy", "reason": "queue_changed_during_repair_verification"}


def _parsed_reviews(files):
    for path in files:
        try:
            raw = builder.read_regular(path)
            value = checker.parse_json(raw, "review")
            if isinstance(value, dict):
                yield path, raw, value
        except (OSError, ValueError, TypeError, KeyError):
            continue  # Preserve the existing malformed/unreadable record policy.


def _review_records(root, files, bundle_path):
    observation = builder.current_observation(root)
    if observation is None:
        yield from _parsed_reviews(files)
        return
    # This is a retrieval index, never an approval. Every indexed byte is bound
    # by read_regular; callers still read back all inputs and directory shapes.
    # A different inventory gets a different index; the second pass starts empty.
    indexes = getattr(observation, "_queue_review_indexes", None)
    if indexes is None:
        indexes = observation._queue_review_indexes = {}
    key = tuple(files)
    if key not in indexes:
        index = {}
        for path, raw, value in _parsed_reviews(key):
            if value.get("kind") == "l_batch_review":
                rows = value.get("members")
                bundles = {row.get("bundlePath") for row in rows
                           if isinstance(row, dict) and isinstance(row.get("bundlePath"), str)} if isinstance(rows, list) else set()
            else:
                name = value.get("bundlePath")
                bundles = {name} if isinstance(name, str) else set()
            for name in bundles:
                index.setdefault(name, []).append((path, raw, value))
        indexes[key] = index
    # Validators and callers may mutate dicts: never expose the cached values.
    for path, raw, value in indexes[key].get(bundle_path, ()):
        yield path, raw, copy.deepcopy(value)


def find_review(root, files, receipt, bundle_path, bodies):
    matches = []
    for path, raw, value in _review_records(root, files, bundle_path):
        try:
            if value.get("kind") == "l_batch_review":
                # A member index can only rule out an unrelated batch. It never
                # grants approval: every potentially matching record below must
                # still pass the complete envelope/member/decision validator.
                rows = value.get("members")
                if not isinstance(rows, list) or not any(isinstance(row, dict) and row.get("bundlePath") == bundle_path for row in rows):
                    continue
                value = builder.validate_batch_review(root, value, receipt, bundle_path, bodies)
                at = builder.timestamp(value["reviewedAt"], "reviewedAt")
                matches.append((at, value["contentDecision"] != "approved", path.as_posix(), raw, value, {}))
                continue
            if value.get("bundlePath") != bundle_path:
                continue
            repair_anchor = {}
            if value.get("contentDecision") == "approved":
                builder.validate_review(raw, receipt, bundle_path, bodies, root)
                try:
                    if REPAIR_PAYLOAD in receipt.get("verifiedPayloadHashes", {}):
                        repair_anchor = validate_repair_sidecar(root, path, raw, value, receipt, bundle_path)
                    else:
                        require(not reserved_repair_bundle(root, bundle_path), "A reserved repair cannot omit its protected producer metadata")
                except (OSError, ValueError, TypeError, KeyError):
                    # A later, otherwise valid review with a broken/missing
                    # repair gate must not silently fall back to an older pass.
                    repair_anchor = {"repairInvalid": True}
            elif value.get("contentDecision") in {"needs_revision", "insufficient_evidence"}:
                checker.shape(value, builder.REVIEW_FIELDS, builder.REVIEW_OPTIONAL, "review")
                require(value["jobId"] == checker.JOB_ID and value["code"] == receipt["code"] and value["manifestSha256"] == receipt["manifestSha256"], "Review binding mismatch")
                checker.text(value["reviewer"], "reviewer")
                checker.text(value["scope"], "scope")
                claimed = set(checker.string_list(value["reviewedClaimIds"], "reviewedClaimIds", nonempty=True))
                known = {c["id"].strip() for c in checker.parse_json(bodies["evidence.json"], "evidence")["claims"]}
                require(claimed <= known, "Unknown reviewed claim")
                builder.validate_l_review_fields(value, checker.parse_json(bodies["reader.json"], "reader"), checker.parse_json(bodies["ready.json"], "ready"), False)
            else:
                continue
            at = builder.timestamp(value["reviewedAt"], "reviewedAt")
            ready = checker.parse_json(bodies["ready.json"], "ready")
            require(at >= parse_time(ready["completedAt"]), "Review predates package")
            matches.append((at, value["contentDecision"] != "approved", path.as_posix(), raw, value, repair_anchor))
        except (OSError, ValueError, TypeError, KeyError):
            continue  # Unrelated/malformed/stale JSON never approves or rejects a package.
    if not matches:
        return None
    _, _, selected, raw, value, repair_anchor = max(matches, key=lambda row: row[:3])
    if repair_anchor.get("repairInvalid"):
        return None
    return {"path": Path(selected).relative_to(root).as_posix(), "sha256": sha(raw), "value": value, **repair_anchor}


def batch_page_acceptance(root, receipt, review, candidate_path, adoption, html_hash):
    observation = builder.current_observation(root)
    key = (review["path"], review["sha256"], adoption["rendererSha256"])
    if observation is None:
        records = _batch_page_records(root, review, adoption["rendererSha256"])
    else:
        if key not in observation.pages:
            observation.counts["pageScans"] += 1
            observation.pages[key] = _batch_page_records(root, review, adoption["rendererSha256"])
        records = observation.pages[key]
    matches = []
    for at, failed, path, raw, value in records:
        selected = next((row for row in value["members"] if row["code"] == receipt["code"]), None)
        if selected is not None and selected["candidatePath"] == candidate_path and selected["htmlSha256"] == html_hash:
            matches.append((at, failed, path, raw, value, selected))
    if not matches:
        return None
    _, _, path, raw, value, selected = max(matches, key=lambda r:r[:3])
    if value["pageDecision"] != "passed":
        return None
    return {"pageReviewPath":Path(path).relative_to(root).as_posix(), "pageReviewSha256":sha(raw), "pageReviewScope":"sampled_batch", "browserObserved":selected["browserObserved"], "batchPageReviewSha256":sha(raw)}


def _batch_page_records(root, review, renderer_sha256):
    member_review = review["value"]
    require(member_review["contentDecision"] == "approved", "Excluded or rejected content cannot receive page acceptance")
    env = builder.batch_envelope(root, member_review["batchEnvelopePath"], member_review["batchEnvelopeSha256"])
    excluded = set(member_review.get("excludedCodes", []))
    matches = []
    folder = root / "reviews/batches" / env["batchId"]
    checker.directory_guard(folder)
    for path in sorted(folder.iterdir()):
        if path.suffix != ".json":
            continue
        try:
            raw = builder.read_regular(path); value = checker.parse_json(raw, "batch page review")
            if not isinstance(value, dict) or value.get("kind") != "l_batch_page_review":
                continue
            checker.shape(value, {"schemaVersion", "kind", "jobId", "contentTier", "reviewScope", "batchId", "batchEnvelopePath", "batchEnvelopeSha256", "batchReviewPath", "batchReviewSha256", "rendererSha256", "pageDecision", "reviewer", "reviewedAt", "scope", "sampling", "members"}, {"browserOperator"}, "batch page review")
            require(value["jobId"] == checker.JOB_ID and value["contentTier"] == "L" and value["reviewScope"] == "sampled_batch", "Invalid batch page scope")
            require(value["batchId"] == env["batchId"] and value["batchEnvelopePath"] == member_review["batchEnvelopePath"] and value["batchEnvelopeSha256"] == member_review["batchEnvelopeSha256"], "Batch page envelope mismatch")
            require(value["batchReviewPath"] == review["path"] and value["batchReviewSha256"] == review["sha256"], "Batch page review approval drift")
            require(value["rendererSha256"] == renderer_sha256 and value["pageDecision"] in {"passed", "needs_revision"}, "Invalid batch page decision/renderer")
            require(checker.text(value["reviewer"], "batch page reviewer").casefold() != env["producer"]["id"].casefold(), "Batch author cannot be its own independent page reviewer")
            checker.text(value["scope"], "batch page scope")
            checker.shape(value["sampling"], {"method", "reason", "riskCodes"}, set(), "page sampling")
            checker.text(value["sampling"]["method"], "page sample method"); checker.text(value["sampling"]["reason"], "page sample reason")
            risk = set(checker.string_list(value["sampling"]["riskCodes"], "page risk codes"))
            expected = {r["code"]:r for r in env["members"] if r["code"] not in excluded}
            require(isinstance(value["members"], list) and len(value["members"]) == len(expected), "Page record must identify exactly the eligible sampled/unsampled members")
            sampled = set(); seen = set()
            at = builder.timestamp(value["reviewedAt"], "batch page reviewedAt")
            for row in value["members"]:
                checker.shape(row, {"code", "bundlePath", "manifestSha256", "candidatePath", "htmlSha256", "adoptionSha256", "browserObserved"}, {"browserChecks", "evidence"}, "batch page member")
                code = row["code"]
                require(code in expected and code not in seen and all(row[k] == expected[code][k] for k in ("bundlePath", "manifestSha256")), "Batch page member mismatch")
                seen.add(code)
                name = builder.relative(row["candidatePath"], "candidate", 3)
                require(name.split('/')[1] == code and type(row["browserObserved"]) is bool, "Invalid batch candidate/scope")
                member_adoption_raw = builder.read_regular(root / name / "adoption.json")
                member_adoption = checker.parse_json(member_adoption_raw, "member adoption")
                require(sha(member_adoption_raw) == row["adoptionSha256"] and sha(builder.read_regular(root / name / "index.html")) == row["htmlSha256"], "Batch candidate bytes drifted")
                require(member_adoption["bundlePath"] == row["bundlePath"] and member_adoption["manifestSha256"] == row["manifestSha256"] and member_adoption["reviewPath"] == review["path"] and member_adoption["reviewSha256"] == review["sha256"], "Batch adoption identity/approval mismatch")
                require(member_adoption.get("contentTier") == "L" and member_adoption["rendererSha256"] == value["rendererSha256"] == member_adoption["toolHashes"]["build_candidate.py"], "Batch mixed renderers")
                require(at >= parse_time(member_adoption["builtAt"]), "Batch page review predates a member build")
                if row["browserObserved"]:
                    sampled.add(code)
                    checker.shape(row.get("browserChecks"), {"desktop", "narrow", "evidenceExpanded"}, set(), "sample browser checks")
                    require(all(type(v) is bool for v in row["browserChecks"].values()), "Browser flags must be boolean")
                    require(value["pageDecision"] != "passed" or all(row["browserChecks"].values()), "Passed sample lacks actual desktop/narrow/expanded checks")
                    require(isinstance(row.get("evidence"), list) and bool(row["evidence"]), "Observed sample requires saved browser evidence")
                    for item in row["evidence"]:
                        checker.shape(item, {"path", "sha256"}, set(), "browser evidence")
                        evidence_path = builder.relative(item["path"], "reviews")
                        require(sha(builder.read_regular(root / evidence_path)) == item["sha256"], "Browser evidence drift")
                else:
                    require("browserChecks" not in row and "evidence" not in row, "Unobserved member cannot claim individual browser evidence/checks")
            require(sampled and risk <= sampled, "Missing page sample/risk member")
            require(builder.read_regular(path) == raw, "Batch page record changed during validation")
            matches.append((at, value["pageDecision"] != "passed", path.as_posix(), raw, value))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return matches


def adopted_candidate(root, receipt, bundle_path, review, prior):
    for folder in sorted(safe_children(root / "candidate" / receipt["code"]), key=lambda p: p.name, reverse=True):
        try:
            raw = builder.read_regular(folder / "adoption.json")
            adoption = checker.parse_json(raw, "adoption")
            candidate_path = folder.relative_to(root).as_posix()
            require(adoption.get("schemaVersion") == 1 and adoption.get("jobId") == checker.JOB_ID and adoption.get("code") == receipt["code"], "Adoption identity mismatch")
            require(adoption.get("status") == "local_candidate_built" and adoption.get("candidate_only") is True and adoption.get("no_deploy") is True, "Invalid adoption status")
            require(adoption.get("bundlePath") == bundle_path and adoption.get("manifestSha256") == receipt["manifestSha256"] and adoption.get("readySha256") == receipt["readySha256"] and adoption.get("verifiedPayloadHashes") == receipt["verifiedPayloadHashes"], "Adoption package hashes drifted")
            require(adoption.get("reviewPath") == review["path"] and adoption.get("reviewSha256") == review["sha256"] and adoption.get("review") == review["value"], "Adoption review drifted")
            output = adoption.get("output", {})
            require(output.get("path") == "index.html", "Invalid HTML path")
            html_hash = sha(builder.read_regular(folder / "index.html"))
            require(output.get("sha256") == html_hash, "Candidate HTML drifted")
            remembered = prior.get("immutableCandidates", {}).get(candidate_path)
            if remembered:
                require(remembered == sha(raw), "Previously adopted immutable record changed")
            if review["value"].get("reviewScope") == "sampled_batch":
                page_binding = batch_page_acceptance(root, receipt, review, candidate_path, adoption, html_hash)
                require(page_binding is not None, "Batch page acceptance missing or rejected")
                require(builder.read_regular(folder / "adoption.json") == raw and sha(builder.read_regular(root / review["path"])) == review["sha256"], "Batch adoption/review changed")
                return {"candidatePath":candidate_path, "adoptionSha256":sha(raw), "htmlSha256":html_hash, **page_binding}
            page_path = root / "reviews" / receipt["code"] / receipt["version"] / "page-review.json"
            page_raw = builder.read_regular(page_path)
            page = checker.parse_json(page_raw, "page-review")
            is_l = receipt.get("contentTier") == "L"
            checker.shape(page, PAGE_FIELDS | ({"contentTier", "rendererSha256", "browserChecks"} if is_l else set()), set(), "page-review")
            require(type(page["schemaVersion"]) is int and page["schemaVersion"] == 1, "Invalid page-review schema")
            require(page["jobId"] == checker.JOB_ID and page["code"] == receipt["code"] and page["manifestSha256"] == receipt["manifestSha256"] and page["candidatePath"] == candidate_path and page["htmlSha256"] == html_hash and page["pageDecision"] == "passed", "Page review binding mismatch")
            checker.text(page["reviewer"], "page-review.reviewer")
            if is_l:
                require(adoption.get("contentTier") == page["contentTier"] == "L", "L adoption/page tier mismatch")
                require(adoption.get("rendererSha256") == page["rendererSha256"] == adoption.get("toolHashes", {}).get("build_candidate.py"), "Renderer hash binding mismatch")
                require(isinstance(page["rendererSha256"], str) and checker.SHA256.fullmatch(page["rendererSha256"]), "Invalid renderer SHA256")
                checker.shape(page["browserChecks"], {"desktop", "narrow", "evidenceExpanded"}, set(), "page-review.browserChecks")
                require(all(value is True for value in page["browserChecks"].values()), "L requires actual desktop, narrow and expanded-evidence browser checks")
            require(builder.timestamp(page["reviewedAt"], "page-review.reviewedAt") >= parse_time(adoption["builtAt"]), "Page review predates build")
            require(builder.read_regular(folder / "adoption.json") == raw and builder.read_regular(page_path) == page_raw, "Candidate receipt changed during scan")
            require(sha(builder.read_regular(root / review["path"])) == review["sha256"], "Review changed during candidate check")
            if review.get("repairReviewPath"):
                require(sha(builder.read_regular(root / review["repairReviewPath"])) == review["repairReviewSha256"], "Repair review sidecar changed during candidate check")
            require(sha(builder.read_regular(folder / "index.html")) == html_hash, "HTML changed during candidate check")
            return {"candidatePath": candidate_path, "adoptionSha256": sha(raw), "htmlSha256": html_hash,
                    "pageReviewPath": page_path.relative_to(root).as_posix(), "pageReviewSha256": sha(page_raw)}
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return None


def _inspection_inventory(root):
    """Current control bytes plus complete package/review/candidate membership.

    Metadata is only an invalidation inventory, never evidence of file contents.
    The shared pass's complete actual read set is separately hashed again.
    """
    shapes, controls = {}, {}
    for base in (root / "inbox", root / "candidate", root / "reviews"):
        if not os.path.lexists(base):
            shapes[base.name] = None
            continue
        pending = [base]
        while pending:
            folder = pending.pop()
            checker.directory_guard(folder)
            shapes[folder.relative_to(root).as_posix()] = "directory"
            for path in sorted(folder.iterdir()):
                info = path.lstat()
                require(not checker.is_reparse(info), "Linked inspection input refused")
                name = path.relative_to(root).as_posix()
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                else:
                    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "Unsafe inspection member")
                    shapes[name] = "file"
                    if (base.name == "reviews" and path.suffix.lower() == ".json") or (base.name == "inbox" and path.name == "reader.json"):
                        controls[name] = sha(builder.read_regular(path))
    for name in ("queue-config.json", "queue-state.json", "company-universe.json", "pilot.json"):
        path = root / name
        controls[name] = sha(builder.read_regular(path)) if os.path.lexists(path) else None
    tools = {str(Path(module).absolute()): sha(builder.read_regular(Path(module)))
             for module in (__file__, checker.__file__, builder.__file__)}
    return {"shapes": shapes, "controls": controls, "tools": tools}


def _inspection_readback(root, hashes):
    for name, expected in hashes.items():
        require(sha(builder.read_regular(root / name)) == expected, "Inspection input changed during readback: " + name)


def inspect_packages(root, companies, prior=None, target_tier=None):
    """Two fresh shared passes; no memo or approved status survives this call."""
    root = Path(root)
    before = _inspection_inventory(root)
    passes = []
    for _ in range(2):
        with builder.validation_observation(root) as observation:
            facts = _inspect_packages_pass(root, companies, prior, target_tier)
        hashes = dict(observation.hashes)
        require(_inspection_inventory(root) == before, "Inspection controls or directory membership changed")
        _inspection_readback(root, hashes)
        require(_inspection_inventory(root) == before, "Inspection changed during complete readback")
        passes.append((facts, hashes))
    require(passes[0] == passes[1], "Independent package inspection passes differ")
    return passes[1][0]


def _inspect_packages_pass(root, companies, prior=None, target_tier=None):
    """Rehash actual ready packages; imported metadata never grants completion."""
    prior = prior or {}
    if target_tier is None and (root / "queue-config.json").exists():
        target_tier = config(root).get("targetContentTier")
    files = review_files(root)
    facts = {}
    for company in safe_children(root / "inbox"):
        code = company.name
        if code not in companies:
            continue
        try:
            versions = [p for p in safe_children(company) if VERSION.fullmatch(p.name)]
            if not versions:
                continue
            versions.sort(key=lambda p: (int(VERSION.fullmatch(p.name)[1]), p.name))
            overall_latest = versions[-1]
            next_version = f"v{int(VERSION.fullmatch(overall_latest.name)[1]) + 1:03d}"
            if target_tier == "L":
                matching = []
                for version in versions:
                    try:
                        reader = read_json(version / "reader.json")
                        require(isinstance(reader, dict), "Untrustworthy package reader")
                        tier = checker.content_tier(reader)
                        if tier == "L":
                            matching.append(version)
                    except (OSError, ValueError, TypeError, KeyError):
                        # Never silently fall back across an unknown newest
                        # version. A current owner can still resume its lease.
                        if version == overall_latest:
                            raise QueueError("Latest package content tier cannot be trusted") from None
                if not matching:
                    facts[code] = {"status": "pending", "contentTier": "L", "nextVersion": next_version, "legacyBundlePath": overall_latest.relative_to(root).as_posix(), "immutableCandidates": dict(prior.get(code, {}).get("immutableCandidates", {}))}
                    continue
                versions = matching
            latest = versions[-1]
            bundle_path = latest.relative_to(root).as_posix()
            anchors = dict(prior.get(code, {}).get("immutableCandidates", {}))
            fact = {"status": "in_progress", "version": latest.name, "nextVersion": latest.name, "bundlePath": bundle_path, "immutableCandidates": anchors}
            if target_tier == "L":
                fact["contentTier"] = "L"
            if not (latest / "ready.json").exists():
                facts[code] = fact
                continue
            receipt = checker.check_bundle(latest)
            fact.update(nextVersion=next_version, manifestSha256=receipt.get("manifestSha256"))
            if receipt.get("mechanicalPassed") is not True or receipt.get("status") != "awaiting_semantic_review" or receipt.get("errors"):
                fact.update(status="invalid_package", reason="Sealed package failed mechanical checks", errors=receipt.get("errors", []))
                facts[code] = fact
                continue
            bodies = builder.load_payload(latest, receipt)
            if target_tier == "L":
                require(receipt.get("contentTier") == "L", "Selected package is not L")
            if receipt.get("contentTier") == "L":
                fact["contentTier"] = "L"
            review = find_review(root, files, receipt, bundle_path, bodies)
            if not review:
                fact.update(status="awaiting_review")
            elif review["value"]["contentDecision"] != "approved":
                fact.update(status="needs_revision", reviewPath=review["path"], reviewSha256=review["sha256"], reason=review["value"]["contentDecision"])
            else:
                fact.update(status="awaiting_candidate", reviewPath=review["path"], reviewSha256=review["sha256"])
                if review["value"].get("reviewScope") == "sampled_batch":
                    fact.update(reviewScope="sampled_batch", contentSampled=review["value"]["contentSampled"], batchId=review["value"]["batchId"])
                candidate = adopted_candidate(root, receipt, bundle_path, review, prior.get(code, {}))
                if candidate:
                    final = checker.check_bundle(latest)
                    builder.same_receipt(receipt, final)
                    require(final.get("mechanicalPassed") is True, "Package drifted at completion check")
                    # Package checking may take time. Revocations, a new review or
                    # HTML edits during it must invalidate this same observation.
                    final_review = find_review(root, review_files(root), final, bundle_path, bodies)
                    require(final_review == review, "Review changed during final package check")
                    require(adopted_candidate(root, final, bundle_path, review, prior.get(code, {})) == candidate, "Candidate changed during final package check")
                    anchors[candidate["candidatePath"]] = candidate["adoptionSha256"]
                    fact.update(status="complete", **candidate)
            facts[code] = fact
        except (OSError, ValueError, TypeError, KeyError) as error:
            facts[code] = {"status": "blocked_input", "reason": type(error).__name__ + ": input cannot be trusted", "immutableCandidates": dict(prior.get(code, {}).get("immutableCandidates", {}))}
    return facts


def active_lease(state, now):
    lease = state.get("lease")
    return lease if lease and parse_time(lease["expiresAt"]) > now else None


def eligible(cfg, companies, facts, blocked, now):
    pilots_done = all(facts.get(code, {}).get("status") == "complete" for code in cfg["pilotCodes"])
    is_l = cfg.get("targetContentTier") == "L"
    continuous = is_l or (pilots_done and cfg["autoExpandAfterPilot"])
    pool = ([c for c in L_REPRESENTATIVES if c in companies] + sorted(set(companies) - set(L_REPRESENTATIVES))) if is_l else sorted(companies) if continuous else cfg["pilotCodes"]
    choices, counts = [], {}
    for order, code in enumerate(pool):
        if code == cfg["benchmarkCode"]:
            counts["benchmark_exempt"] = counts.get("benchmark_exempt", 0) + 1
            continue
        fact = facts.get(code, {"status": "pending", "nextVersion": "v001"})
        status = fact["status"]
        if is_l and status == "complete" and fact.get("contentTier") != "L":
            status = "pending"
        block = blocked.get(code)
        if status != "complete" and block and parse_time(block["retryAfter"]) > now:
            status = "blocked"
        counts[status] = counts.get(status, 0) + 1
        if status in {"needs_revision", "invalid_package", "in_progress", "pending"}:
            priority = 0 if status in {"needs_revision", "invalid_package"} else 1 if status == "in_progress" else 2
            choices.append((priority, order, code, fact.get("nextVersion", "v001"), status))
    choices.sort()
    return ("L" if is_l else "continuous" if continuous else "pilot"), choices, counts


def universe_summary(cfg, companies, facts, blocked, phase, now):
    counts, actionable, backlog, held = {}, [], 0, 0
    for code in sorted(companies):
        fact = facts.get(code, {"status": "pending"})
        status = fact["status"]
        if cfg.get("targetContentTier") == "L" and status == "complete" and fact.get("contentTier") != "L":
            status = "pending"
        if code == cfg["benchmarkCode"]:
            status = "benchmark_exempt"
        elif status != "complete" and code in blocked and parse_time(blocked[code]["retryAfter"]) > now:
            status = "blocked"
        counts[status] = counts.get(status, 0) + 1
        if status not in {"complete", "benchmark_exempt"}:
            backlog += 1
            held += int(phase == "pilot" and code not in cfg["pilotCodes"])
        if status not in {"complete", "benchmark_exempt", "pending"}:
            # Compact actionable receipts, not all company/package facts.
            item = {"code": code, "name": companies[code], "status": status}
            for key in ("version", "nextVersion", "bundlePath", "reviewPath", "reason"):
                if key in fact:
                    item[key] = fact[key]
            if status == "blocked":
                item.update(reason=blocked[code]["reason"], retryAfter=blocked[code]["retryAfter"])
            actionable.append(item)
    return {"universeCounts": counts, "backlogCount": backlog, "heldByPilotCount": held,
            "actionable": actionable[:50], "actionableTotal": len(actionable),
            "actionableTruncated": len(actionable) > 50, "fullFactsPath": "queue-state.json"}


def run_command(root, command, run_id=None, reason=None, retry_after=None, inspector=inspect_packages, bundle_checker=None, clock=utcnow, tier=None, code=None, base_bundle=None, base_manifest=None, producer_id=None, repair_id=None, retry_of=None, batch_id=None, size=20, industry=None, reuse_pending_codes=None, member_codes=None):
    root = Path(os.path.abspath(root))
    if command == "start-tier":
        return start_tier(root, tier, clock)
    if command == "repair-legacy":
        return repair_legacy(root, run_id, code, base_bundle, base_manifest, reason, producer_id, repair_id, clock, retry_of)
    cfg = config(root)
    if command in {"next-batch", "done-batch", "block-batch"} or (command == "renew" and is_batch_lease(read_state(root, cfg).get("lease"))):
        return run_batch_command(root, command, run_id, batch_id, size, industry, producer_id, reason, retry_after, inspector, clock, reuse_pending_codes, member_codes)
    if command in {"done", "block"}:
        require(not is_batch_lease(read_state(root, cfg).get("lease")), "Use done-batch/block-batch for a batch lease")
    if command in {"next", "done", "block", "renew"}:
        require(isinstance(run_id, str), "--run-id UUID is required")
        run_id = str(uuid.UUID(run_id))
    # File hashing happens outside the mutex. Revisions reject stale scans.
    for _ in range(4):
        now = clock()
        with short_lock(root):
            cfg = config(root)
            universe = refresh_universe(root, cfg, now)
            state = read_state(root, cfg)
            revision = state["revision"]
            if command == "refresh":
                return {"status": "refreshed", "sourceSha256": universe["sourceSha256"], "sourceAsOf": universe["sourceAsOf"], "companyCount": len(universe["companies"])}
        companies = {r["code"]: r["name"] for r in universe["companies"]}
        facts = inspector(root, companies, state["observations"])
        done_receipt = None
        done_repair = None
        if command == "done" and state.get("lease") and state["lease"]["runId"] == run_id:
            lease = state["lease"]
            done_receipt = (bundle_checker or checker.check_bundle)(root / "inbox" / lease["code"] / lease["version"])
            if is_repair_lease(lease):
                validate_repair_lease(lease, cfg)
                require(done_receipt.get("mechanicalPassed") is True and not done_receipt.get("errors") and done_receipt.get("contentTier") is None, "Repair done requires a valid legacy seven-question package")
                bundle_path = f"inbox/{lease['code']}/{lease['version']}"
                payload, payload_hash = repair_payload(root, done_receipt, bundle_path)
                require(payload["producer"] == {"id": lease["producerId"], "runId": lease["runId"]} and payload["repair"] == repair_metadata_fields(lease), "Repair payload does not belong to the current producing lease")
                saved = state.get("repairReceipts", {}).get(lease["repairId"], {})
                require(saved.get("leaseId") == lease["leaseId"] and saved.get("runId") == run_id and saved.get("status") == "assigned", "Missing assigned repair receipt")
                failed_paths = verify_failure_chain(root, state, saved.get("failureChain", []), clock())
                base_binding = repair_base_binding(root, cfg, lease["code"], lease["baseBundlePath"], lease["baseManifestSha256"], state["observations"].get(lease["code"], {}), bundle_path, failed_paths)
                require(base_binding == saved.get("baseBinding"), "Repair base changed since the lease was granted")
                final_repair = checker.check_bundle(root / bundle_path)
                builder.same_receipt(done_receipt, final_repair)
                require(final_repair.get("mechanicalPassed") is True, "Repair package changed during submission")
                done_repair = {"manifestSha256": done_receipt["manifestSha256"], "readySha256": done_receipt["readySha256"], "payloadSha256": payload_hash}
        with short_lock(root):
            current = read_state(root, cfg)
            if current["revision"] != revision or config(root) != cfg:
                continue
            now = clock()
            state = current
            lease = active_lease(state, now)
            if lease:
                if is_repair_lease(lease):
                    validate_repair_lease(lease, cfg)
                else:
                    require(lease.get("contentTier") == cfg.get("targetContentTier"), "Active lease belongs to another content tier")
            if not lease:
                expired = state.get("lease")
                if is_batch_lease(expired):
                    state["batchReceipts"][expired["batchId"]].update(status="expired", expiredAt=iso(now))
                if is_repair_lease(expired) and expired["repairId"] in state.get("repairReceipts", {}):
                    state["repairReceipts"][expired["repairId"]].update(status="expired", expiredAt=iso(now))
                state["lease"] = None
            # A reserved repair version remains unavailable even when its writer
            # has not created a directory, or its lease has since expired.
            for company_code, fact in facts.items():
                if (fact.get("status") != "in_progress" and any(row.get("code") == company_code for row in state.get("repairReceipts", {}).values())) or any(any(m["code"] == company_code for m in row.get("members", [])) for row in state.get("batchReceipts", {}).values()):
                    reserved = next_reserved_version(root, company_code, state)
                    if VERSION.fullmatch(fact.get("nextVersion", "v001")) and int(VERSION.fullmatch(reserved)[1]) > int(VERSION.fullmatch(fact.get("nextVersion", "v001"))[1]):
                        fact["nextVersion"] = reserved
            phase, choices, counts = eligible(cfg, companies, facts, state["blocked"], now)
            state.update(phase=phase, sourceSha256=universe["sourceSha256"], sourceAsOf=universe["sourceAsOf"], observations=facts)
            result = {"jobId": cfg["jobId"], "phase": phase, "companyCount": len(companies), "counts": counts, "sourceSha256": universe["sourceSha256"], "websiteCatalogueAsOf": universe["sourceAsOf"]}
            if state.get("repairReceipts"):
                result["repairCounts"] = {status: sum(row.get("status") == status for row in state["repairReceipts"].values()) for status in ("assigned", "submitted", "blocked", "expired")}
            if cfg.get("targetContentTier") == "L":
                result.update(contentTier="L", scopePath=cfg["scopePath"], scopeSha256=cfg["scopeSha256"], legacyObservationSnapshotPath=cfg["migrationPath"] + "/queue-state-before.json")
                try:
                    live_hash = sha(builder.read_regular(Path(cfg["sourceIndex"])))
                    result.update(liveCatalogueSha256=live_hash, catalogueChangedSinceScope=live_hash != cfg["scopeSha256"])
                except (OSError, ValueError):
                    result.update(liveCatalogueStatus="unreadable; frozen scope remains authoritative")
            if command == "status":
                result.update(universe_summary(cfg, companies, facts, state["blocked"], phase, now))
                result.update(status="status", lease=lease, nextEligible=choices[0][2] if choices else None,
                              executableScopeCount=len(companies) - int(cfg["benchmarkCode"] in companies) if phase in {"continuous", "L"} else len(cfg["pilotCodes"]))
            elif command == "next":
                if is_batch_lease(lease):
                    result.update(status="busy", lease=lease, reason="batch_writer_lease_active")
                elif lease and lease["runId"] != run_id:
                    result.update(status="busy", lease=lease)
                elif lease:
                    lease["expiresAt"] = iso(now + timedelta(minutes=90))
                    result.update(status="assigned", resumed=True, code=lease["code"], name=companies.get(lease["code"]), version=lease["version"], bundlePath=f"inbox/{lease['code']}/{lease['version']}", lease=lease)
                    if is_repair_lease(lease):
                        state["repairReceipts"][lease["repairId"]]["expiresAt"] = lease["expiresAt"]
                        result.update(purpose=REPAIR_PURPOSE, queueTier="L", payloadTier="legacy", repairId=lease["repairId"])
                elif choices:
                    _, _, code, version, previous = choices[0]
                    lease = {"runId": run_id, "leaseId": str(uuid.uuid4()), "code": code, "version": version, "expiresAt": iso(now + timedelta(minutes=90))}
                    if cfg.get("targetContentTier") == "L":
                        lease["contentTier"] = "L"
                    state["lease"] = lease
                    state["blocked"].pop(code, None)
                    result.update(status="assigned", resumed=previous == "in_progress", code=code, name=companies[code], version=version, bundlePath=f"inbox/{code}/{version}", previousStatus=previous, lease=lease)
                else:
                    drained = all(k in {"complete", "benchmark_exempt"} for k in counts)
                    result.update(status="done" if drained else "waiting", reason="backlog_drained" if drained else "awaiting_review_candidate_or_retry", keepScheduleActive=True)
            else:
                require(lease is not None and lease["runId"] == run_id, "No unexpired lease owned by this run")
                if command == "renew":
                    lease["expiresAt"] = iso(now + timedelta(minutes=90))
                    if is_repair_lease(lease):
                        state["repairReceipts"][lease["repairId"]]["expiresAt"] = lease["expiresAt"]
                    result.update(status="renewed", lease=lease)
                elif command == "block":
                    require(isinstance(reason, str) and bool(reason.strip()), "--reason is required")
                    due = parse_time(retry_after)
                    require(due > now, "retry-after must be in the future")
                    if is_repair_lease(lease):
                        state["repairReceipts"][lease["repairId"]].update(status="blocked", blockReason=reason.strip(), retryAfter=iso(due), recordedAt=iso(now))
                    else:
                        state["blocked"][lease["code"]] = {"version": lease["version"], "reason": reason.strip(), "retryAfter": iso(due), "recordedAt": iso(now)}
                    state["lease"] = None
                    result.update(status="blocked", code=lease["code"], retryAfter=iso(due))
                elif command == "done":
                    require(done_receipt and done_receipt.get("mechanicalPassed") is True and done_receipt.get("status") == "awaiting_semantic_review" and not done_receipt.get("errors") and done_receipt.get("code") == lease["code"] and done_receipt.get("version") == lease["version"], "done refused: leased package is not a stable mechanically valid ready bundle")
                    if lease.get("contentTier") == "L":
                        require(done_receipt.get("contentTier") == "L" and done_receipt.get("producer", {}).get("runId") == run_id, "done refused: L package tier/producer run does not match the lease")
                        require(REPAIR_PAYLOAD not in done_receipt.get("verifiedPayloadHashes", {}), "L submission cannot masquerade as a legacy repair")
                    if is_repair_lease(lease):
                        require(done_repair is not None, "Missing verified repair submission")
                        state["repairReceipts"][lease["repairId"]].update(status="submitted", submittedAt=iso(now), **done_repair)
                    state["lease"] = None
                    if not is_repair_lease(lease):
                        state["blocked"].pop(lease["code"], None)
                    result.update(status="submitted", code=lease["code"], version=lease["version"], manifestSha256=done_receipt["manifestSha256"], contentApproved=False)
                    if is_repair_lease(lease):
                        result.update(purpose=REPAIR_PURPOSE, repairId=lease["repairId"], queueTier="L", payloadTier="legacy")
                else:
                    raise QueueError("Unknown command")
            save_state(root, state, now)
            return result
    return {"status": "busy", "reason": "queue_changed_during_scan"}


def is_batch_lease(lease):
    return bool(lease and lease.get("purpose") == BATCH_PURPOSE)


def validate_batch_lease(lease, cfg):
    require(is_batch_lease(lease) and lease.get("contentTier") == cfg.get("targetContentTier") == "L", "Invalid batch lease tier")
    for key in ("batchId", "leaseId", "runId"):
        require(str(uuid.UUID(lease[key])) == lease[key], "Invalid batch lease UUID")
    checker.text(lease["producerId"], "batch producer"); checker.text(lease["industry"], "batch industry")
    require(lease["scopeSha256"] == cfg["scopeSha256"], "Batch lease scope mismatch")
    members = lease.get("members")
    require(isinstance(members, list) and 1 <= len(members) <= 50, "Invalid batch member count")
    require(len({r["code"] for r in members}) == len(members), "Duplicate batch member")
    for row in members:
        checker.shape(row, {"code", "version"}, set(), "batch reservation")
        require(CODE.fullmatch(row["code"]) and VERSION.fullmatch(row["version"]) and row["code"] != cfg["benchmarkCode"], "Invalid or exempt batch member")
    parse_time(lease["assignedAt"]); parse_time(lease["expiresAt"])


def run_batch_command(root, command, run_id, batch_id=None, size=20, industry=None, producer_id=None,
                      reason=None, retry_after=None, inspector=inspect_packages, clock=utcnow, reuse_pending_codes=None, member_codes=None):
    """One writer and one existing queue. Review/page acceptance remains separate."""
    require(isinstance(run_id, str) and str(uuid.UUID(run_id)) == run_id, "Canonical --run-id required")
    if batch_id is not None:
        require(str(uuid.UUID(batch_id)) == batch_id, "Canonical --batch-id required")
    member_codes = member_codes or []
    require(isinstance(member_codes, list) and len(set(member_codes)) == len(member_codes) and all(CODE.fullmatch(c) for c in member_codes), "Invalid explicit member list")
    require(not member_codes or industry is None, "Use either explicit --member-code or --industry")
    require(len(member_codes) <= size, "Explicit member list exceeds requested batch size")
    reuse_pending_codes = reuse_pending_codes or []
    require(not member_codes or set(reuse_pending_codes) <= set(member_codes), "Reused pending drafts must belong to the explicit member list")
    require(isinstance(reuse_pending_codes, list) and len(set(reuse_pending_codes)) == len(reuse_pending_codes) and all(CODE.fullmatch(c) for c in reuse_pending_codes), "Invalid explicit pending-draft selection")
    require(len(reuse_pending_codes) <= size, "Too many explicitly reused drafts for this batch")
    require(type(size) is int and 20 <= size <= 50, "Batch requested size must be 20..50; a final industry remainder may be smaller")
    for _ in range(4):
        now = clock()
        with short_lock(root):
            cfg = config(root); state = read_state(root, cfg)
            require(cfg.get("targetContentTier") == "L", "Batch production is L-only")
            lease = active_lease(state, now)
            if lease and (not is_batch_lease(lease) or lease["runId"] != run_id):
                return {"status":"busy", "lease":lease}
            records = state.get("batchReceipts", {})
            saved = records.get(batch_id) if batch_id else None
            if saved:
                require(saved["runId"] == run_id, "Batch id belongs to another run, including after expiry")
                if saved["status"] == "submitted":
                    builder.batch_envelope(root, saved["envelopePath"], saved["envelopeSha256"])
                    return {"status":"already_submitted", "batchId":batch_id, "envelopePath":saved["envelopePath"], "envelopeSha256":saved["envelopeSha256"], "contentApproved":False}
            if lease:
                validate_batch_lease(lease, cfg)
                require(batch_id is None or batch_id == lease["batchId"], "Different batch already owns this run's lease")
                if command in {"next-batch", "renew"}:
                    require(not member_codes or set(member_codes) == {r["code"] for r in lease["members"]}, "Cannot change a resumed batch member list")
                    require(industry is None or industry == lease["industry"], "Cannot change a resumed batch's industry")
                    require(producer_id is None or producer_id == lease["producerId"], "Cannot change a resumed batch producer")
                    lease["expiresAt"] = iso(now + timedelta(minutes=90))
                    state["batchReceipts"][lease["batchId"]]["expiresAt"] = lease["expiresAt"]
                    save_state(root, state, now)
                    return {"status":"assigned" if command == "next-batch" else "renewed", "resumed":True, "batchId":lease["batchId"], "lease":lease, "members":lease["members"]}
                if command == "block-batch":
                    checker.text(reason, "batch block reason"); due = parse_time(retry_after)
                    require(due > now, "retry-after must be future")
                    for member in lease["members"]:
                        state["blocked"][member["code"]] = {"version":member["version"], "reason":reason, "retryAfter":iso(due), "recordedAt":iso(now)}
                    state["batchReceipts"][lease["batchId"]].update(status="blocked", reason=reason, retryAfter=iso(due))
                    state["lease"] = None; save_state(root, state, now)
                    return {"status":"blocked", "batchId":lease["batchId"], "contentApproved":False}
            else:
                require(command == "next-batch", "No unexpired batch lease owned by this run")
                require(saved is None, "Expired/blocked batch ids cannot be reassigned; start a new batch/version")
            revision = state["revision"]
            universe = refresh_universe(root, cfg, now)
        # Costly hashes/scans are outside the mutex; the revision is checked below.
        companies = {r["code"]:r["name"] for r in universe["companies"]}
        if command == "next-batch":
            checker.text(producer_id, "--producer-id")
            facts = inspector(root, companies, state["observations"])
            _, choices, _ = eligible(cfg, companies, facts, state["blocked"], now)
            scope = read_json(root / cfg["scopePath"])
            by_industry = {r["code"]:r.get("industry") for r in scope["companies"]}
            draft_inputs = []
            for reused_code in reuse_pending_codes:
                fact = facts.get(reused_code, {})
                require(reused_code != cfg["benchmarkCode"] and fact.get("contentTier") == "L" and fact.get("status") == "awaiting_review", "Only an explicitly selected mechanically valid awaiting-review L draft may be reused")
                require(reused_code not in state["blocked"] or parse_time(state["blocked"][reused_code]["retryAfter"]) <= now, "Explicit reuse cannot bypass an active block")
                prior_path = builder.relative(fact["bundlePath"], "inbox", 3)
                prior_receipt = builder.machine_check(root / prior_path)
                require(prior_receipt.get("contentTier") == "L" and prior_receipt["code"] == reused_code and prior_receipt["manifestSha256"] == fact["manifestSha256"], "Pending draft identity drift")
                draft_inputs.append({"code":reused_code, "bundlePath":prior_path, "manifestSha256":prior_receipt["manifestSha256"], "readySha256":prior_receipt["readySha256"]})
                choices.insert(0, (-1, 0, reused_code, fact["nextVersion"], "awaiting_review"))
            if member_codes:
                require(set(member_codes) <= {r[2] for r in choices}, "Explicit member is ineligible, already complete, blocked, exempt or awaiting unselected review")
                chosen = [r for r in choices if r[2] in set(member_codes)]
                industry_values = {checker.text(by_industry.get(r[2]), "frozen member industry") for r in chosen}
                industry = next(iter(industry_values)) if len(industry_values) == 1 else "mixed_existing_evidence"
            else:
                if industry is None and choices:
                    industry = by_industry.get(choices[0][2])
                if not choices:
                    return {"status":"waiting", "reason":"no_eligible_L_members"}
                checker.text(industry, "frozen industry")
                require(all(by_industry.get(c) == industry for c in reuse_pending_codes), "Explicit reused drafts must belong to the selected industry")
                chosen = [r for r in choices if by_industry.get(r[2]) == industry][:size]
                if not chosen:
                    return {"status":"waiting", "reason":"no_eligible_members_in_industry", "industry":industry}
            auth_raw = builder.read_regular(root / BATCH_AUTHORIZATION)
            auth = checker.parse_json(auth_raw, "batch authorization")
            require(auth.get("authority") == "direct_user_message_in_current_thread" and bool(auth.get("supersedesExecutionRequirements")), "Explicit batch authorization missing")
        else:
            require(command == "done-batch", "Unknown batch operation")
            receipts = []
            for member in lease["members"]:
                path = f'inbox/{member["code"]}/{member["version"]}'
                receipt = builder.machine_check(root / path)
                require(receipt.get("contentTier") == "L" and receipt.get("producer") == {"id":lease["producerId"], "runId":run_id}, "Batch member producer/run mismatch")
                require(receipt["code"] == member["code"] and receipt["version"] == member["version"], "Batch member identity mismatch")
                ready = read_json(root / path / "ready.json")
                require(parse_time(ready["completedAt"]) >= parse_time(lease["assignedAt"]), "Cannot enroll an old package retroactively")
                receipts.append({**member, "bundlePath":path, "manifestSha256":receipt["manifestSha256"], "readySha256":receipt["readySha256"]})
        with short_lock(root):
            current = read_state(root, cfg)
            if current["revision"] != revision or config(root) != cfg:
                continue
            state = current; now = clock(); active = active_lease(state, now)
            if command == "next-batch":
                require(active is None, "Writer lease appeared during batch selection")
                expired = state.get("lease")
                if is_batch_lease(expired):
                    state["batchReceipts"][expired["batchId"]].update(status="expired", expiredAt=iso(now))
                if is_repair_lease(expired):
                    state["repairReceipts"][expired["repairId"]].update(status="expired", expiredAt=iso(now))
                batch_id = batch_id or str(uuid.uuid4())
                require(batch_id not in state.get("batchReceipts", {}), "Never reuse a batch id")
                members = [{"code":r[2], "version":next_reserved_version(root, r[2], state)} for r in chosen]
                lease = {"purpose":BATCH_PURPOSE, "contentTier":"L", "batchId":batch_id, "leaseId":str(uuid.uuid4()), "runId":run_id, "producerId":producer_id, "industry":industry, "scopeSha256":cfg["scopeSha256"], "authorizationPath":BATCH_AUTHORIZATION, "authorizationSha256":sha(auth_raw), "assignedAt":iso(now), "expiresAt":iso(now + timedelta(minutes=90)), "members":members, "draftInputs":draft_inputs, "memberIndustries":{m["code"]:by_industry[m["code"]] for m in members}}
                validate_batch_lease(lease, cfg)
                require(builder.read_regular(root / BATCH_AUTHORIZATION) == auth_raw, "Batch authorization changed during assignment")
                state["lease"] = lease
                state.setdefault("batchReceipts", {})[batch_id] = {**lease, "status":"assigned"}
                state.update(observations=facts, phase="L")
                save_state(root, state, now)
                return {"status":"assigned", "resumed":False, "batchId":batch_id, "lease":lease, "members":members, "contentApproved":False}
            require(active is not None and active == lease and active["runId"] == run_id, "Batch lease expired or changed during checks")
            for row in receipts:
                require(sha(builder.read_regular(root / row["bundlePath"] / "manifest.json")) == row["manifestSha256"] and sha(builder.read_regular(root / row["bundlePath"] / "ready.json")) == row["readySha256"], "Member changed before batch submission")
            envelope_path = "reviews/batches/" + lease["batchId"] + "/batch.json"
            dest = root / envelope_path
            submitted_at = read_json(dest)["submittedAt"] if dest.exists() else iso(now)
            envelope = {"schemaVersion":1, "kind":"l_batch_envelope", "jobId":checker.JOB_ID, "contentTier":"L", "batchId":lease["batchId"], "leaseId":lease["leaseId"], "producer":{"id":lease["producerId"], "runId":run_id}, "industry":lease["industry"], "scopeSha256":lease["scopeSha256"], "authorizationPath":lease["authorizationPath"], "authorizationSha256":lease["authorizationSha256"], "assignedAt":lease["assignedAt"], "submittedAt":submitted_at, "members":receipts, "draftInputs":lease.get("draftInputs", []), "memberIndustries":lease["memberIndustries"]}
            raw = builder.json_bytes(envelope)
            if dest.exists():
                require(builder.read_regular(dest) == raw, "Do not overwrite an existing batch envelope")
            else:
                for folder in (root / "reviews", root / "reviews/batches", dest.parent):
                    builder.ensure_directory(folder)
                builder.write_new(dest, raw)
            state["batchReceipts"][lease["batchId"]].update(status="submitted", submittedAt=submitted_at, envelopePath=envelope_path, envelopeSha256=sha(raw))
            state["lease"] = None
            for row in receipts:
                state["blocked"].pop(row["code"], None)
            save_state(root, state, now)
            return {"status":"submitted", "batchId":lease["batchId"], "envelopePath":envelope_path, "envelopeSha256":sha(raw), "memberCount":len(receipts), "contentApproved":False}
    return {"status":"busy", "reason":"queue_changed_during_batch_scan"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["refresh", "status", "next", "done", "block", "renew", "start-tier", "repair-legacy", "next-batch", "done-batch", "block-batch"])
    parser.add_argument("--tier", choices=["L"])
    parser.add_argument("--run-id")
    parser.add_argument("--reason")
    parser.add_argument("--retry-after")
    parser.add_argument("--code")
    parser.add_argument("--base-bundle")
    parser.add_argument("--base-manifest")
    parser.add_argument("--producer-id")
    parser.add_argument("--repair-id")
    parser.add_argument("--batch-id")
    parser.add_argument("--size", type=int, default=20)
    parser.add_argument("--industry")
    parser.add_argument("--reuse-pending-code", action="append", default=[])
    parser.add_argument("--member-code", action="append", default=[])
    parser.add_argument("--retry-of", help="Prior failed repair UUID; allocates a new immutable attempt")
    args = parser.parse_args()
    try:
        result = run_command(ROOT, args.command, args.run_id, args.reason, args.retry_after, tier=args.tier, code=args.code, base_bundle=args.base_bundle, base_manifest=args.base_manifest, producer_id=args.producer_id, repair_id=args.repair_id, retry_of=args.retry_of, batch_id=args.batch_id, size=args.size, industry=args.industry, reuse_pending_codes=args.reuse_pending_code, member_codes=args.member_code)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"status": "error", "error": str(error)}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
