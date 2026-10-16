#!/usr/bin/env python3
"""Project a currently approved company into a new offline content format. Never deploy."""
from __future__ import annotations

import argparse
import copy
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import unquote

sys.dont_write_bytecode = True
import approval_chain as chain
import projection_storage as storage

ROOT = Path(__file__).absolute().parent.parent
SCHEMA = "atlas-company-seven-questions"
OVERVIEW_SCHEMA = "atlas-company-overview"
SOURCE_FIELDS = ("id", "title", "publisher", "publishedAt", "reportPeriod", "url")
CLAIM_FIELDS = ("id", "questionId", "claim", "claimType", "sourceIds", "citations", "limitations")
PAYLOADS = ("reader.json", "evidence.json", "sources.json")
QUESTIONS = tuple(f"Q{i}" for i in range(1, 8))
FLAGS = {"localOnly": True, "noDeploy": True, "readyForPublication": False,
         "requires_renderer_adapter": True, "validatedRecordBindingsOnly": True}
LOCAL_PATH = re.compile(
    r"(?i)(?:(?<![a-z0-9])[a-z]:[\\/]|file\s*:|\\\\|(?:^|[\s\"'（(])//[^/\s]+/|"
    r"/(?:users|home|tmp|var|mnt|private|appdata|documents\s+and\s+settings)/|"
    r"(?:~|\.\.?)[\\/]|(?:\.codex-output|inbox|reviews|candidate|publication|sources)[\\/])"
)
ABSOLUTE_LOCAL_PATH = re.compile(
    r"(?i)(?:(?<![a-z0-9])[a-z]:[\\/]|file\s*:|\\\\|"
    r"/(?:users|home|tmp|var|mnt|private|appdata|documents\s+and\s+settings)/|~[\\/])"
)


class ProjectionError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def need(ok, code, message):
    if not ok:
        raise ProjectionError(code, message)


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def pointer_part(value):
    return str(value).replace("~", "~0").replace("/", "~1")


def leaves(value, pointer=""):
    if isinstance(value, dict) and value:
        for key in sorted(value):
            yield from leaves(value[key], pointer + "/" + pointer_part(key))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from leaves(item, pointer + "/" + str(index))
    else:
        yield pointer, value


def at(value, pointer):
    for part in pointer.split("/")[1:]:
        part = part.replace("~1", "/").replace("~0", "~")
        value = value[int(part)] if isinstance(value, list) else value[part]
    return value


def safe_public(value, forbidden_paths):
    for pointer, item in leaves(value):
        if not isinstance(item, str):
            continue
        # Public websites legitimately use /publication/ and /sources/. Only this
        # explicit HTTPS metadata field gets URL rules; prose keeps the local-path
        # checks. Decode URL escapes before rejecting embedded machine paths.
        is_source_url = re.fullmatch(r"/sources/\d+/url", pointer) is not None
        if is_source_url:
            chain.checker.source_url(item, pointer)
        inspected = unquote(item) if is_source_url else item
        normalized = inspected.replace("\\", "/").casefold()
        pattern = ABSOLUTE_LOCAL_PATH if is_source_url else LOCAL_PATH
        # A public URL may legitimately have the same relative path as a local
        # archive. Only absolute machine roots remain forbidden in that URL.
        sensitive = {p for p in forbidden_paths if re.match(r"(?i)^(?:[a-z]:/|/)", p)} if is_source_url else forbidden_paths
        need(not pattern.search(inspected) and not any(p in normalized for p in sensitive),
             "private_path", "Public field contains a local/internal path: " + pointer)


def keyed(rows, key, label):
    result = {}
    need(isinstance(rows, list), "projection_schema", label + " must be an array")
    for index, row in enumerate(rows):
        need(isinstance(row, dict) and isinstance(row.get(key), str) and row[key].strip(),
             "projection_schema", label + " requires nonempty identifiers")
        identity = row[key].strip()
        need(identity not in result, "duplicate_id", label + " contains duplicate identifiers")
        result[identity] = (index, row)
    return result


def project_values(documents, selected):
    """Whitelist projection. Text and ID bytes inside parsed strings are not rewritten."""
    reader, evidence, sources = (documents[name] for name in PAYLOADS)
    need(reader["code"] == evidence["companyCode"] == selected["code"]
         and reader["name"] == selected["name"], "company_identity", "Selected company and payload identity differ")
    answers = keyed(reader["answers"], "questionId", "answers")
    claims = keyed(evidence["claims"], "id", "claims")
    source_map = keyed(sources["sources"], "id", "sources")
    is_overview = chain.checker.content_tier(reader) == 'L'
    questions = ('Q1', 'Q2') if is_overview else QUESTIONS
    need(set(answers) == set(questions), 'questions', 'Exact tier question set must be retained')
    output = {'schema': OVERVIEW_SCHEMA if is_overview else SCHEMA, 'schemaVersion': 1}
    mappings = []

    def copy_field(target, source_file, source_pointer, container, key):
        value = copy.deepcopy(at(documents[source_file], source_pointer))
        container[key] = value
        for suffix, leaf in leaves(value):
            mappings.append({"sourceFile": source_file, "sourcePointer": source_pointer + suffix,
                             "sourceSha256": selected["verifiedPayloadHashes"][source_file],
                             "targetPointer": target + suffix, "valueSha256": chain.sha(chain.canonical(leaf))})

    for field in ("code", "name", "asOf", "tagline", "introduction"):
        copy_field("/" + field, "reader.json", "/" + field, output, field)
    if is_overview:
        copy_field('/contentTier', 'reader.json', '/contentTier', output, 'contentTier')
        copy_field('/businessModel', 'reader.json', '/businessModel', output, 'businessModel')
    output['answers'] = []
    used_claims = chain.checker.reader_claim_ids(reader) if is_overview else set()
    need(used_claims <= claims.keys(), 'missing_claim', 'A diagram or answer refers to an absent claim')
    for question in questions:
        index, answer = answers[question]
        row = {}
        target_index = len(output["answers"])
        for field in ("questionId", "text", "claimIds"):
            copy_field(f"/answers/{target_index}/{field}", "reader.json", f"/answers/{index}/{field}", row, field)
        for raw_id in answer["claimIds"]:
            cid = raw_id.strip()
            need(cid in claims, "missing_claim", "An answer refers to an absent claim")
            need(claims[cid][1]["questionId"] == question, "question_claim_mismatch", "Answer and claim questions differ")
            used_claims.add(cid)
        output["answers"].append(row)

    output["claims"] = []
    used_sources = set()
    for cid, (index, claim) in claims.items():
        if cid not in used_claims:
            continue
        need(claim["claimType"] in chain.checker.CLAIM_TYPES, "claim_type", "Unknown claim type")
        refs = {sid.strip() for sid in claim["sourceIds"]}
        cited = {citation["sourceId"].strip() for citation in claim["citations"]}
        need(refs and refs == cited and refs <= source_map.keys(), "missing_source", "Claim sources and citations must resolve exactly")
        row = {}
        target_index = len(output["claims"])
        for field in CLAIM_FIELDS:
            if field in claim:
                copy_field(f"/claims/{target_index}/{field}", "evidence.json", f"/claims/{index}/{field}", row, field)
        output["claims"].append(row)
        used_sources |= refs

    output["sources"] = []
    for sid, (index, source) in source_map.items():
        if sid not in used_sources:
            continue
        chain.checker.source_url(source["url"], "source.url")
        row = {}
        target_index = len(output["sources"])
        for field in SOURCE_FIELDS:
            copy_field(f"/sources/{target_index}/{field}", "sources.json", f"/sources/{index}/{field}", row, field)
        output["sources"].append(row)
    return output, sorted(mappings, key=lambda row: row["targetPointer"])


def verify_projection(output, mappings, documents, selected, root):
    """Independent preservation assertions: no changed numbers, omitted text or hidden fields."""
    reader, evidence, sources = (documents[name] for name in PAYLOADS)
    is_overview = chain.checker.content_tier(reader) == 'L'
    expected_fields = {'schema', 'schemaVersion', 'code', 'name', 'asOf', 'tagline', 'introduction', 'answers', 'claims', 'sources'}
    if is_overview:
        expected_fields |= {'contentTier', 'businessModel'}
    need(set(output) == expected_fields
         and output['schema'] == (OVERVIEW_SCHEMA if is_overview else SCHEMA) and type(output['schemaVersion']) is int and output['schemaVersion'] == 1,
         "projection_schema", "Only the new explicit public schema is allowed")
    for field in ("code", "name", "asOf", "tagline", "introduction"):
        need(output[field] == reader[field], "content_changed", "Reader field was changed: " + field)
    if is_overview:
        need(output['contentTier'] == 'L' and output['businessModel'] == reader['businessModel'],
             'content_changed', 'Business model text and references must be preserved')
    expected_answers = sorted(reader["answers"], key=lambda row: row["questionId"])
    need(output["answers"] == expected_answers and len(output["answers"]) == (2 if is_overview else 7),
         "content_changed", "Selected tier answer texts, references and ordering must be preserved")
    used = chain.checker.reader_claim_ids(reader)
    expected_claims = [{k: c[k] for k in CLAIM_FIELDS if k in c} for c in evidence["claims"] if c["id"].strip() in used]
    need(output["claims"] == expected_claims, "content_changed", "A cited claim, type, citation or limitation was changed or lost")
    refs = {sid.strip() for c in expected_claims for sid in c["sourceIds"]}
    expected_sources = [{k: s[k] for k in SOURCE_FIELDS} for s in sources["sources"] if s["id"].strip() in refs]
    need(output["sources"] == expected_sources, "content_changed", "Public source metadata was changed or lost")
    expected_pointers = {p for p, _ in leaves(output) if p not in {"/schema", "/schemaVersion"}}
    need(len(mappings) == len(expected_pointers) and {m["targetPointer"] for m in mappings} == expected_pointers,
         "mapping_coverage", "Every copied public value needs one exact source mapping")
    for mapping in mappings:
        name = mapping["sourceFile"]
        need(name in PAYLOADS and mapping["sourceSha256"] == selected["verifiedPayloadHashes"][name], "mapping_binding", "Mapping source hash differs")
        source_value = at(documents[name], mapping["sourcePointer"])
        target_value = at(output, mapping["targetPointer"])
        need(source_value == target_value and mapping["valueSha256"] == chain.sha(chain.canonical(target_value)),
             "content_changed", "Mapped public value differs from its original JSON value")
    forbidden = {str(Path(root).absolute()).replace("\\", "/").casefold(), selected["bundlePath"].casefold()}
    forbidden |= {s["localPath"].replace("\\", "/").casefold() for s in sources["sources"] if s.get("localPath")}
    safe_public(output, forbidden)


def accepted(root, code, content_tier=None):
    result = chain.check_selection(root, [code], content_tier) if content_tier else chain.check_selection(root, [code])
    need(result.get("status") == "verified_for_conversion_inputs" and len(result.get("acceptedInputs", [])) == 1,
         "approval_chain_rejected", "Current approval chain rejected: " + ",".join(e["code"] for e in result.get("errors", [])))
    selected = result["acceptedInputs"][0]
    need(selected["code"] == code and selected["contentDecision"] == "approved" and selected["pageDecision"] == "passed",
         "approval_binding", "Selected company must have current content and page approval")
    if selected.get("reviewScope") == "sampled_batch":
        need(all(k in selected for k in ("contentSampled", "browserObserved", "batchId", "batchEnvelopeSha256", "batchReviewSha256", "batchPageReviewSha256", "actuallyReviewedClaimIds")), "review_scope", "Batch release eligibility lost its actual review scope")
        need(selected["contentSampled"] or selected["actuallyReviewedClaimIds"] == [], "review_scope", "Unsampled company cannot claim individual review")
    # approved/passed express eligibility under the selected individual or batch policy.
    return result, selected


def read_bound(root, selected):
    relative = chain.builder.relative(selected["bundlePath"], "inbox", 3)
    need(relative.split("/")[1] == selected["code"], "company_identity", "Cross-company package path")
    bodies = {}
    for name in PAYLOADS:
        path = relative + "/" + name
        expected = selected["verifiedPayloadHashes"][name]
        need(selected["inputHashes"].get(path) == expected, "input_binding", "Payload is absent from the accepted input binding")
        raw = chain.read_file(root / path)
        need(chain.sha(raw) == expected, "input_drift", "Actual payload bytes differ from accepted SHA-256")
        bodies[name] = raw
    return bodies


def revalidate(root, code, before, selected, bodies):
    after, final_selected = accepted(root, code, selected["contentTier"]) if selected.get("contentTier") else accepted(root, code)
    need(before["bindingId"] == after["bindingId"] and selected == final_selected,
         "input_drift", "Approval records, queue evidence or selected package changed; retry later without modifying state")
    need(read_bound(root, selected) == bodies, "input_drift", "Payload bytes changed during projection")


def child_directory(parent, name):
    chain.guard.relative_name(name)
    chain.guard.guarded_path(parent)
    path = parent / name
    if not os.path.lexists(path):
        try:
            path.mkdir()
        except FileExistsError:
            pass
    chain.guard.guarded_path(path)
    need(stat.S_ISDIR(path.lstat().st_mode), "unsafe_path", "Output ancestor must be a real directory")
    return path


def write_new(path, raw):
    chain.guard.guarded_path(path.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(path, flags, 0o600), "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    need(chain.read_file(path) == raw, "output_drift", "New output failed exact byte readback")


def confirm_output(output, content_raw, mapping_raw):
    tree, _ = chain.guard.snapshot_tree(output)
    need(tree == {"content.json": chain.sha(content_raw), "mapping.json": chain.sha(mapping_raw)},
         "output_conflict", "Existing output is incomplete, changed or contains extra files; nothing is overwritten")


def projection_bytes(root, code, selected, bodies):
    documents = {name: chain.checker.parse_json(raw, name) for name, raw in bodies.items()}
    content, fields = project_values(documents, selected)
    # Reparse bound bytes for independent comparison: an accidental mutation
    # of the transform's working objects must not redefine the source truth.
    originals = {name: chain.checker.parse_json(raw, name) for name, raw in bodies.items()}
    verify_projection(content, fields, originals, selected, root)
    content_raw = encoded(content)
    mapping = {"schema": "atlas-company-content-mapping", "schemaVersion": 1, **FLAGS,
               "jobId": chain.checker.JOB_ID, "code": code, "bundlePath": selected["bundlePath"],
               "manifestSha256": selected["manifestSha256"], "readySha256": selected["readySha256"],
               "acceptedInputHashes": selected["inputHashes"],
               "output": {"path": "content.json", "schema": content["schema"], "sha256": chain.sha(content_raw)},
               "generatedConstants": {"/schema": content["schema"], "/schemaVersion": 1}, "fields": fields}
    if selected.get("reviewScope") == "sampled_batch":
        mapping["reviewScope"] = {k:selected[k] for k in ("reviewScope", "contentSampled", "browserObserved", "batchId", "batchEnvelopeSha256", "batchReviewSha256", "batchPageReviewSha256")}
    mapping_raw = encoded(mapping)
    return content, content_raw, mapping_raw


def _project_locked(root, code, result, progress, content_tier=None):
    progress["stage"] = "current_approval"
    before, selected = accepted(root, code, content_tier) if content_tier else accepted(root, code)
    bodies = read_bound(root, selected)
    content, content_raw, mapping_raw = projection_bytes(root, code, selected, bodies)
    # No checkedAt/global queue hash in immutable files: identical selected input
    # bytes produce identical projection and mapping bytes across later runs.
    revalidate(root, code, before, selected, bodies)
    manifest = chain.guard.valid_digest(selected["manifestSha256"], "manifest")
    output = root / "publication" / "projections" / code / manifest
    progress["output"] = output
    reused = os.path.lexists(output)
    reused_attempt = False
    if reused:
        progress["stage"] = "existing_output_verification"
        confirm_output(output, content_raw, mapping_raw)
    else:
        progress["stage"] = "attempt_selection"
        need(len(content_raw) + len(mapping_raw) <= storage.MAX_ATTEMPT_BYTES,
             "attempt_size_exceeded", "Projection exceeds the attempt byte budget; no content is truncated")
        expected = {"content.json": chain.sha(content_raw), "mapping.json": chain.sha(mapping_raw)}
        attempt = storage.matching_attempt(root, code, expected)
        reused_attempt = attempt is not None
        if attempt is None:
            progress["stage"] = "attempt_allocation"
            attempt = storage.allocate_attempt(root, code, len(content_raw) + len(mapping_raw))
        progress["attempt"] = attempt
        if not reused_attempt:
            progress["stage"] = "content_write"
            write_new(attempt / "content.json", content_raw)
            progress["stage"] = "post_content_approval"
            revalidate(root, code, before, selected, bodies)
            progress["stage"] = "mapping_write"
            write_new(attempt / "mapping.json", mapping_raw)
        progress["stage"] = "pre_promotion_verification"
        confirm_output(attempt, content_raw, mapping_raw)
        revalidate(root, code, before, selected, bodies)
        confirm_output(attempt, content_raw, mapping_raw)
        child_directory(child_directory(root / "publication", "projections"), code)
        progress["stage"] = "promotion"
        storage.promote_no_replace(attempt, output)
        progress["promoted"] = True
    progress["stage"] = "final_approval_and_output_verification"
    revalidate(root, code, before, selected, bodies)
    confirm_output(output, content_raw, mapping_raw)
    result.update(status="existing_projection_verified" if reused else "local_content_projected",
                  reusedAttempt=reused_attempt,
                  approvalBindingId=before["bindingId"], outputs=[{
                      "code": code, "manifestSha256": manifest, "path": output.relative_to(root).as_posix(),
                      "contentSha256": chain.sha(content_raw), "mappingSha256": chain.sha(mapping_raw),
                      "questions": len(content["answers"]), "claims": len(content["claims"]), "sources": len(content["sources"])}])

def project_company(root, code, content_tier=None):
    result = {"schemaVersion": 1, "status": "rejected", **FLAGS, "outputs": [], "errors": [],
              "limitations": ["Preserves selected text and recorded review bindings; does not establish facts, reviewer identity, rights or semantic correctness.",
                              "New offline schema only: no React adapter, application baseline, build, release or deployment.",
                              "Point-in-time cooperative locks, not a hostile-writer sandbox or permanent approval; revalidate before later use.",
                              "Windows local NTFS process-interruption recovery only; no power-loss durability promise or automatic cleanup."]}
    progress = {"stage": "company_lock"}
    try:
        root = Path(os.path.abspath(root))
        chain.guard.guarded_path(root / "publication")
        need(isinstance(code, str) and chain.queue.CODE.fullmatch(code), "company_selection", "Expected a full company code")
        with storage.lock(root, code + ".lock"):
            _project_locked(root, code, result, progress, content_tier)
    except (ValueError, OSError, TypeError, KeyError, IndexError) as error:
        # An error while leaving the lock must also retract any tentative success.
        result.update(status="busy" if getattr(error, "code", None) == "busy" else "rejected", outputs=[])
        result.pop("approvalBindingId", None)
        result.pop("reusedAttempt", None)
        result["errors"].append({"code": getattr(error, "code", "invalid_or_unreadable_input"),
                                 "message": str(error) if isinstance(error, ValueError) else "Projection input or output could not be handled safely"})
        result["failureStage"] = progress["stage"]
        if getattr(error, "details", None) is not None:
            result["errorDetails"] = error.details
        attempt, output = progress.get("attempt"), progress.get("output")
        if attempt is not None:
            result["attemptPath"] = attempt.relative_to(root).as_posix()
            retained = output if progress.get("promoted") or (not os.path.lexists(attempt) and output is not None and os.path.lexists(output)) else attempt
            result["retainedUnacceptedDirectory"] = retained.relative_to(root).as_posix()
            result["recovery"] = "Retained without cleanup. A later invocation must freshly verify the current chain and exact bytes before reuse."
        elif progress["stage"] == "existing_output_verification":
            result["recovery"] = "Existing official output is never repaired or replaced, including a legacy incomplete directory. Explicit inspection is required."
    return result


def _projection_tools():
    return {Path(p).name:chain.sha(chain.read_file(Path(p).absolute())) for p in (__file__, storage.__file__)}


def _batch_checkpoint(root, before, codes, content_tier, tools, progress, stage):
    progress["stage"] = stage
    need(_projection_tools() == tools, "input_drift", "Projection or storage code changed")
    chain.checkpoint_selection(root, before, codes, content_tier)
    need(_projection_tools() == tools, "input_drift", "Projection or storage code changed during readback")


def project_companies(root, codes, content_tier=None):
    """Project one complete selection using two fresh shared validation passes.

    Holds the same per-company cooperative locks in sorted order. Stages in
    bounded waves to respect the existing attempt store's global limit. A failed
    operation never reports partial acceptance; retained directories require a
    new full current observation before reuse. It does not deploy or approve.
    """
    result = {"schemaVersion":1, "status":"rejected", **FLAGS, "outputs":[], "errors":[],
              "limitations":["Recorded batch eligibility preserves actual sampling scope; not individual review or browser observation.",
                             "Point-in-time cooperative locking and complete byte readback, not a hostile writer sandbox or durable approval.",
                             "No cross-process atomic commit across company directories. Failure retains unaccepted outputs for fresh verified reuse."]}
    progress = {"stage":"company_locks"}; plans = []; before = None
    try:
        root = Path(os.path.abspath(root))
        chain.guard.guarded_path(root / "publication")
        need(isinstance(codes,list) and 1 <= len(codes) <= 50 and all(isinstance(c,str) and chain.queue.CODE.fullmatch(c) for c in codes) and len(set(codes)) == len(codes), "company_selection", "Select 1..50 unique full company codes")
        codes = sorted(codes)
        with ExitStack() as locks:
            for code in codes:
                locks.enter_context(storage.lock(root, code + ".lock"))
            tools = _projection_tools()
            progress["stage"] = "current_batch_approval"
            before = chain.check_selection(root, codes, content_tier, shared_observation=True)
            need(before.get("status") == "verified_for_conversion_inputs" and len(before["acceptedInputs"]) == len(codes), "approval_chain_rejected", "Current batch chain rejected: " + ",".join(e["code"] for e in before.get("errors",[])))
            for selected in before["acceptedInputs"]:
                code = selected["code"]
                need(selected["contentDecision"] == "approved" and selected["pageDecision"] == "passed", "approval_binding", "Every selected company must be eligible")
                bodies = read_bound(root, selected)
                content, content_raw, mapping_raw = projection_bytes(root, code, selected, bodies)
                need(len(content_raw) + len(mapping_raw) <= storage.MAX_ATTEMPT_BYTES, "attempt_size_exceeded", "Projection exceeds the existing attempt byte budget")
                manifest = chain.guard.valid_digest(selected["manifestSha256"], "manifest")
                output = root / "publication/projections" / code / manifest
                reused = os.path.lexists(output)
                if reused:
                    confirm_output(output, content_raw, mapping_raw)
                plans.append({"code":code, "manifest":manifest, "output":output, "reused":reused, "content":content,
                              "contentRaw":content_raw, "mappingRaw":mapping_raw, "attempt":None, "promoted":False})
            _batch_checkpoint(root,before,codes,content_tier,tools,progress,"before_batch_write")
            pending = [p for p in plans if not p["reused"]]
            # Existing global capacity is preserved (32); 50-member selection
            # uses two waves. Occupied unrelated attempts still fail closed.
            for offset in range(0,len(pending),storage.MAX_TOTAL_ATTEMPTS):
                wave = pending[offset:offset + storage.MAX_TOTAL_ATTEMPTS]
                if offset:
                    _batch_checkpoint(root,before,codes,content_tier,tools,progress,"before_next_wave_write")
                for plan in wave:
                    progress["stage"] = "batch_attempt_write"
                    expected = {"content.json":chain.sha(plan["contentRaw"]), "mapping.json":chain.sha(plan["mappingRaw"])}
                    attempt = storage.matching_attempt(root,plan["code"],expected)
                    if attempt is None:
                        attempt = storage.allocate_attempt(root,plan["code"],len(plan["contentRaw"]) + len(plan["mappingRaw"]))
                        plan["attempt"] = attempt
                        write_new(attempt/"content.json",plan["contentRaw"])
                        write_new(attempt/"mapping.json",plan["mappingRaw"])
                    plan["attempt"] = attempt
                    confirm_output(attempt,plan["contentRaw"],plan["mappingRaw"])
                _batch_checkpoint(root,before,codes,content_tier,tools,progress,"before_batch_promotion")
                for plan in wave:
                    confirm_output(plan["attempt"],plan["contentRaw"],plan["mappingRaw"])
                for plan in wave:
                    progress["stage"] = "batch_promotion"
                    child_directory(child_directory(root/"publication","projections"),plan["code"])
                    storage.promote_no_replace(plan["attempt"],plan["output"])
                    plan["promoted"] = True
            _batch_checkpoint(root,before,codes,content_tier,tools,progress,"final_batch_input_verification")
            for plan in plans:
                confirm_output(plan["output"],plan["contentRaw"],plan["mappingRaw"])
            # Output readback can be slow: close the window with one more current
            # complete input readback and control observation. Neither side of
            # this operation trusts file timestamps or a cached current verdict.
            chain.readback_observation(root,before)
            controls, _, _ = chain.control_snapshot(root,codes,content_tier)
            need(chain.sha(chain.canonical(controls)) == before["controlSnapshotSha256"] and chain.tool_hashes() == before["toolHashes"] and _projection_tools() == tools, "input_drift", "Controls or tools changed during output readback")
            need(chain.directory_shapes(root,before["observedInputHashes"]) == before["observedDirectoryShapes"], "input_drift", "Bound directory changed during final control observation")
            result.update(status="existing_batch_projections_verified" if all(p["reused"] for p in plans) else "local_batch_content_projected",
                approvalBindingId=before["bindingId"], projectionToolHashes=tools, observationCounts=before["observationCounts"],
                outputs=[{"code":p["code"], "manifestSha256":p["manifest"], "path":p["output"].relative_to(root).as_posix(),
                          "contentSha256":chain.sha(p["contentRaw"]), "mappingSha256":chain.sha(p["mappingRaw"]),
                          "questions":len(p["content"]["answers"]), "claims":len(p["content"]["claims"]), "sources":len(p["content"]["sources"])} for p in plans])
    except (ValueError,OSError,TypeError,KeyError,IndexError) as error:
        result.update(status="busy" if getattr(error,"code",None)=="busy" else "rejected",outputs=[],failureStage=progress["stage"])
        result.pop("approvalBindingId",None)
        result["errors"].append({"code":getattr(error,"code","invalid_or_unreadable_input"), "message":str(error) if isinstance(error,ValueError) else "Batch projection input/output could not be handled safely"})
        retained=[]
        for plan in plans:
            attempt=plan.get("attempt")
            if attempt is not None:
                path=plan["output"] if plan["promoted"] or (not os.path.lexists(attempt) and os.path.lexists(plan["output"])) else attempt
                retained.append(path.relative_to(root).as_posix())
        if retained:
            result["retainedUnacceptedDirectories"]=retained
            result["recovery"]="No cleanup or overwrite. Retry requires a fresh complete chain and exact byte verification."
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--company", action="append", required=True, help="Trusted full company code; repeat for one batch projection observation")
    parser.add_argument('--content-tier', choices=['L'], default=None)
    args = parser.parse_args(argv)
    result = project_company(ROOT, args.company[0], args.content_tier) if len(args.company) == 1 else project_companies(ROOT, args.company, args.content_tier)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["status"] in {"local_content_projected", "existing_projection_verified", "local_batch_content_projected", "existing_batch_projections_verified"} else 2 if result["status"] == "busy" else 1


if __name__ == "__main__":
    raise SystemExit(main())
