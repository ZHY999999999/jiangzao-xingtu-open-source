#!/usr/bin/env python3
"""Read-only pilot package checks. No ingestion, factual approval, or deployment.

Producer layout: <root>/inbox/<code>/<version>/. Write ready.json last.
Dates are YYYY-MM-DD or YYYYMMDD; reportPeriod means the period end date.
Every source localPath is an optional package-relative file listed in manifest.
The result is a point-in-time receipt: re-run after ANY edit and before promotion.
"""
from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

JOB_ID = "atlas-company-pilot-20261002"
CUTOFF = date(2026, 10, 2)
TRUSTED_ROOT = Path(__file__).absolute().parent
DEFAULT_COMPANIES = {
    "000977.SZ": "浪潮信息", "603019.SH": "中科曙光", "600588.SH": "用友网络",
    "600036.SH": "招商银行", "000333.SZ": "美的集团",
}
QUESTIONS = {f"Q{i}" for i in range(1, 8)}
CLAIM_TYPES = {"fact", "company_statement", "calculation", "interpretation"}
REQUIRED_FILES = {"reader.json", "evidence.json", "sources.json", "读者稿.md"}
MARKERS = {"manifest.json", "ready.json"}
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
COMPANY_CODE = re.compile(r"[0-9]{6}\.(?:SH|SZ|BJ)\Z")


class PackageError(ValueError):
    def __init__(self, code, path, message, status="invalid"):
        super().__init__(message)
        self.code, self.path, self.status = code, path, status


def require(condition, code, path, message):
    if not condition:
        raise PackageError(code, path, message)


def text(value, path):
    require(isinstance(value, str) and bool(value.strip()), "schema", path, "Expected a nonempty string")
    return value.strip()


def shape(value, required, optional, path):
    require(isinstance(value, dict), "schema", path, "Expected an object")
    require(required <= value.keys(), "schema", path, "Missing fields: " + ", ".join(sorted(required - value.keys())))
    require(value.keys() <= required | optional, "schema", path, "Unknown fields: " + ", ".join(sorted(value.keys() - required - optional)))
    if "schemaVersion" in required:
        require(type(value["schemaVersion"]) is int and value["schemaVersion"] == 1, "schema", path, "schemaVersion must be integer 1")


def string_list(value, path, nonempty=False):
    require(isinstance(value, list) and (bool(value) or not nonempty), "schema", path, "Expected a list" + (" with at least one item" if nonempty else ""))
    values = [text(item, path) for item in value]
    require(len(values) == len(set(values)), "duplicate_id", path, "Duplicate list identifier/location")
    return values


def parse_date(value, path):
    value = text(value, path)
    require(bool(re.fullmatch(r"(?:\d{8}|\d{4}-\d{2}-\d{2})", value)), "date", path, "Use a real YYYY-MM-DD or YYYYMMDD date")
    try:
        parsed = datetime.strptime(value, "%Y%m%d").date() if re.fullmatch(r"\d{8}", value) else date.fromisoformat(value)
    except ValueError:
        raise PackageError("date", path, "Use a real YYYY-MM-DD or YYYYMMDD date") from None
    require(parsed <= CUTOFF, "date_after_cutoff", path, "Date exceeds pilot cutoff 2026-10-02")
    return parsed


def safe_relative(value, path):
    require(isinstance(value, str) and value == value.strip(), "unsafe_path", path, "Path whitespace must not be normalized")
    value = text(value, path)
    parts = value.split("/")
    require(value == unicodedata.normalize("NFC", value) and not PurePosixPath(value).is_absolute()
            and all(p not in ("", ".", "..") for p in parts)
            and not any(ord(c) < 32 or ord(c) == 127 or c in '\\<>:"|?*' for c in value)
            and all(not p.endswith((".", " ")) and p.split(".")[0].upper() not in RESERVED for p in parts),
            "unsafe_path", path, "Use a safe package-relative POSIX path; traversal, aliases, drives and streams are forbidden")
    return value


def is_reparse(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def directory_guard(path):
    for parent in reversed((path, *path.parents)):
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and not is_reparse(info), "unsafe_path", "bundle", "Directory and ancestors must be real directories, not symbolic links/junctions")


def identity(info):
    return (info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_dev, info.st_ino)


def opened_matches_path(opened, path_identity):
    # Windows lstat can expose creation time as ctime while fstat exposes change
    # time. Keep full same-API comparisons; omit only ctime across these APIs.
    indices = (0, 1, 2, 4, 5) if os.name == "nt" else range(6)
    return all(opened[i] == path_identity[i] for i in indices)


def collect(bundle):
    directory_guard(bundle)
    result, aliases = {}, set()
    def visit(directory):
        for item in sorted(directory.iterdir()):
            name = item.relative_to(bundle).as_posix()
            safe_relative(name, name)
            key = name.casefold()
            require(key not in aliases, "unsafe_path", name, "Case-insensitive path collision")
            aliases.add(key)
            info = item.lstat()
            require(not is_reparse(info), "unsafe_path", name, "Symbolic links/junctions are forbidden")
            require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), "unsafe_path", name, "Only ordinary files/directories are allowed")
            result[name] = identity(info)
            if stat.S_ISDIR(info.st_mode):
                visit(item)
    visit(bundle)
    return result


def read_tree(bundle, snapshot):
    hashes, bodies = {}, {}
    for name, before in sorted(snapshot.items()):
        if not stat.S_ISREG(before[0]):
            continue
        directory_guard((bundle / name).parent)
        descriptor = os.open(bundle / name, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            opened = identity(os.fstat(stream.fileno()))
            if not opened_matches_path(opened, before) or identity((bundle / name).lstat()) != before:
                raise PackageError("unstable_package", name, "File changed before reading", "pending")
            capture = name in REQUIRED_FILES | MARKERS
            require(not capture or before[1] <= 16 * 1024 * 1024, "oversized_metadata", name, "Machine JSON/reader draft exceeds 16 MiB; split raw evidence into separate files")
            digest, chunks = hashlib.sha256(), []
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
                if capture:
                    chunks.append(chunk)
            if identity(os.fstat(stream.fileno())) != opened or identity((bundle / name).lstat()) != before:
                raise PackageError("unstable_package", name, "File changed during reading", "pending")
            hashes[name] = digest.hexdigest()
            if capture:
                bodies[name] = b"".join(chunks)
    return hashes, bodies


def parse_json(raw, path):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, "duplicate_json_key", path, "Duplicate JSON object key")
            result[key] = value
        return result
    def invalid(_):
        raise PackageError("invalid_json_number", path, "Non-finite JSON numbers are forbidden")
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs, parse_constant=invalid)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PackageError("invalid_json", path, "Expected complete UTF-8 JSON") from None


def _read_company_config(path):
    """One stable regular-file read; never follow a config link or sourceIndex."""
    directory_guard(path.parent)
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not is_reparse(info), "company_config_path", path.name, "Company configuration must be a real regular file, not a link/junction")
    require(info.st_size <= 16 * 1024 * 1024, "company_config_size", path.name, "Company configuration exceeds 16 MiB")
    before = identity(info)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "rb") as stream:
        opened = identity(os.fstat(stream.fileno()))
        require(opened_matches_path(opened, before), "company_config_drift", path.name, "Company configuration changed before read")
        raw = stream.read(16 * 1024 * 1024 + 1)
        require(len(raw) <= 16 * 1024 * 1024 and identity(os.fstat(stream.fileno())) == opened and identity(path.lstat()) == before, "company_config_drift", path.name, "Company configuration changed during read")
    return raw, before


def _companies_snapshot(root=None):
    """Return a fresh mapping and provenance; malformed existing config fails closed."""
    root = Path(os.path.abspath(TRUSTED_ROOT if root is None else root))
    path = root / "company-universe.json"
    try:
        directory_guard(root)
        try:
            path.lstat()
        except FileNotFoundError:
            return dict(DEFAULT_COMPANIES), {"mode": "pilot_fallback", "sha256": None, "count": len(DEFAULT_COMPANIES)}
        first, first_identity = _read_company_config(path)
        second, second_identity = _read_company_config(path)
        require(first == second and first_identity == second_identity, "company_config_drift", path.name, "Company configuration changed across stable reads; use atomic replacement")
        config = parse_json(first, path.name)
        shape(config, {"schemaVersion", "jobId", "sourceIndex", "sourceSha256", "sourceAsOf", "generatedAt", "cutoff", "companies"}, set(), path.name)
        require(config["jobId"] == JOB_ID, "company_config_job", path.name, "Company configuration belongs to another job")
        require(config["cutoff"] == CUTOFF.isoformat(), "company_config_cutoff", path.name, "Company configuration cannot extend this batch cutoff")
        source = text(config["sourceIndex"], "company-universe.sourceIndex")
        require(not any(ord(c) < 32 for c in source), "company_config_source", path.name, "Source path metadata must not contain control characters")
        # This is provenance supplied by the trusted controller, not an input
        # path to follow. No company data is loaded from a package or sourceIndex.
        require(isinstance(config["sourceSha256"], str) and SHA256.fullmatch(config["sourceSha256"]), "company_config_hash", path.name, "Source index hash must be lowercase SHA256")
        source_as_of = text(config["sourceAsOf"], "company-universe.sourceAsOf")
        require(bool(re.fullmatch(r"(?:\d{8}|\d{4}-\d{2}-\d{2})", source_as_of)), "company_config_date", path.name, "Source catalogue date must be YYYY-MM-DD or YYYYMMDD")
        try:
            source_date = datetime.strptime(source_as_of, "%Y%m%d").date() if len(source_as_of) == 8 else date.fromisoformat(source_as_of)
        except ValueError:
            raise PackageError("company_config_date", path.name, "Invalid source catalogue calendar date") from None
        # Catalogue refresh dates may advance; the research cutoff above and
        # parse_date() for every package fact remain fixed at 2026-10-02.
        today_in_china = datetime.now(timezone(timedelta(hours=8))).date()
        require(source_date <= today_in_china, "company_config_date", path.name, "Source catalogue date is later than the current UTC+8 calendar date")
        try:
            generated = datetime.fromisoformat(text(config["generatedAt"], "company-universe.generatedAt").replace("Z", "+00:00"))
            require(generated.tzinfo is not None and generated.utcoffset() is not None and generated.timestamp() <= time.time() + 300, "company_config_time", path.name, "Configuration generation time must have a timezone and not be unexpectedly future")
        except ValueError as error:
            if isinstance(error, PackageError):
                raise
            raise PackageError("company_config_time", path.name, "Expected an ISO generation time with timezone") from None
        require(isinstance(config["companies"], list) and bool(config["companies"]), "company_config_companies", path.name, "Company configuration must have a nonempty companies list")
        companies = {}
        for index, row in enumerate(config["companies"]):
            p = f"company-universe.companies[{index}]"
            shape(row, {"code", "name"}, set(), p)
            code, name = row["code"], row["name"]
            require(isinstance(code, str) and COMPANY_CODE.fullmatch(code), "company_config_code", p, "Use a full six-digit code ending .SH, .SZ or .BJ")
            require(code not in companies, "company_config_duplicate", p, "Duplicate company code")
            require(isinstance(name, str) and bool(name.strip()) and name == name.strip() and not any(ord(c) < 32 for c in name), "company_config_name", p, "Company name must be nonempty canonical text")
            companies[code] = name
        return companies, {"mode": "trusted_config", "sha256": hashlib.sha256(first).hexdigest(), "sourceSha256": config["sourceSha256"], "sourceAsOf": config["sourceAsOf"], "count": len(companies)}
    except (OSError, TypeError, KeyError, OverflowError) as error:
        raise PackageError("company_config_unreadable", path.name, type(error).__name__ + ": trusted company configuration could not be checked safely") from None


def load_companies(root=None):
    """Load current trusted names. Default root is this tool's directory, never a bundle.

    No config means the original five-company fallback. Any existing invalid
    config raises PackageError. No module reload is needed after atomic replace.
    An explicit root is for a trusted controller/test, not untrusted package data.
    """
    return _companies_snapshot(root)[0]


class _LiveCompanies(Mapping):
    """Compatibility view; validation takes one explicit snapshot per operation."""
    def __getitem__(self, code):
        return load_companies()[code]

    def __iter__(self):
        return iter(load_companies())

    def __len__(self):
        return len(load_companies())


COMPANIES = _LiveCompanies()


def source_url(value, path):
    value = text(value, path)
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
        valid = parsed.scheme == "https" and host and parsed.username is None and parsed.password is None
        valid = valid and not any(c.isspace() or ord(c) < 32 or c == "\\" for c in value)
        if host:
            try:
                valid = valid and ipaddress.ip_address(host).is_global
            except ValueError:
                valid = valid and "." in host and not host.lower().endswith((".local", ".localhost", ".internal"))
        require(bool(valid) and (port is None or 0 < port < 65536), "source_url", path, "Expected a public HTTPS URL without credentials; reachability is NOT checked")
    except ValueError as error:
        if isinstance(error, PackageError):
            raise
        raise PackageError("source_url", path, "Malformed HTTPS URL") from None


def content_tier(reader):
    tier = reader.get("contentTier")
    require("contentTier" not in reader or tier == "L", "content_tier", "reader.contentTier", "Only explicit L or the unmarked legacy seven-question contract is supported")
    return tier


def reader_claim_ids(reader):
    """All claims exposed in public answers and the business diagram."""
    nodes = list(reader["answers"])
    if reader.get("contentTier") == "L":
        model = reader["businessModel"]
        nodes += [flow[key] for flow in model["flows"] for key in ("buyer", "work", "income")]
        nodes += model.get("notes", [])
    return {cid.strip() for node in nodes for cid in node["claimIds"]}


def validate_business_model(model, claims):
    shape(model, {"flows"}, {"notes"}, "reader.businessModel")
    require(isinstance(model["flows"], list) and bool(model["flows"]), "business_model", "reader.businessModel.flows", "At least one evidenced business flow is required")
    identifiers, used = set(), set()
    def node(value, path):
        shape(value, {"text", "claimIds"}, set(), path)
        text(value["text"], path + ".text")
        refs = set(string_list(value["claimIds"], path + ".claimIds", nonempty=True))
        require(refs <= claims.keys(), "missing_claim", path, "Business diagram refers to an absent claim")
        used.update(refs)
    for index, flow in enumerate(model["flows"]):
        path = f"reader.businessModel.flows[{index}]"
        shape(flow, {"id", "buyer", "work", "income"}, set(), path)
        identifier = text(flow["id"], path + ".id")
        require(identifier not in identifiers, "duplicate_id", path, "Duplicate business flow id")
        identifiers.add(identifier)
        for key in ("buyer", "work", "income"):
            node(flow[key], path + "." + key)
    require(isinstance(model.get("notes", []), list), "business_model", "reader.businessModel.notes", "Expected a notes list")
    for index, note in enumerate(model.get("notes", [])):
        node(note, f"reader.businessModel.notes[{index}]")
    return used


def validate_payload(bodies, hashes, code, manifest_entries, warnings, companies=None):
    companies = load_companies() if companies is None else companies
    reader, evidence, sources = (parse_json(bodies[name], name) for name in ("reader.json", "evidence.json", "sources.json"))
    shape(reader, {"schemaVersion", "code", "name", "asOf", "tagline", "introduction", "answers"}, {"audioScript", "contentTier", "businessModel"}, "reader.json")
    tier = content_tier(reader)
    require(("businessModel" in reader) == (tier == "L"), "business_model", "reader.businessModel", "Business model is required for L and unavailable in unmarked legacy packages")
    shape(evidence, {"schemaVersion", "companyCode", "cutoff", "claims"}, set(), "evidence.json")
    shape(sources, {"schemaVersion", "sources"}, set(), "sources.json")
    require(reader["code"] == evidence["companyCode"] == code and reader["name"] == companies[code], "company_identity", "reader/evidence", "Company code and selected short name must agree with this package")
    as_of = parse_date(reader["asOf"], "reader.asOf")
    require(parse_date(evidence["cutoff"], "evidence.cutoff") == CUTOFF, "cutoff", "evidence.cutoff", "Evidence cutoff must be 2026-10-02")
    for field in ("tagline", "introduction"):
        text(reader[field], "reader." + field)
    if "audioScript" in reader:
        require(isinstance(reader["audioScript"], str), "schema", "reader.audioScript", "Expected a string")
        if not reader["audioScript"].strip():
            warnings.append({"code": "empty_audio_script", "path": "reader.audioScript"})
    require(isinstance(sources["sources"], list) and bool(sources["sources"]), "schema", "sources.sources", "At least one source is required")
    source_ids, published_dates = set(), []
    for index, source in enumerate(sources["sources"]):
        p = f"sources.sources[{index}]"
        shape(source, {"id", "title", "publisher", "publishedAt", "reportPeriod", "url", "readLocations"}, {"localPath", "sha256"}, p)
        sid = text(source["id"], p + ".id")
        require(sid not in source_ids, "duplicate_id", p + ".id", "Duplicate source id")
        source_ids.add(sid)
        text(source["title"], p + ".title"); text(source["publisher"], p + ".publisher")
        published = parse_date(source["publishedAt"], p + ".publishedAt")
        published_dates.append(published)
        parse_date(source["reportPeriod"], p + ".reportPeriod")
        require(published <= as_of, "date_after_asof", p + ".publishedAt", "A cited source cannot be disclosed after reader.asOf")
        source_url(source["url"], p + ".url")
        string_list(source["readLocations"], p + ".readLocations", nonempty=True)
        if "sha256" in source:
            require(isinstance(source["sha256"], str) and SHA256.fullmatch(source["sha256"]), "hash_format", p + ".sha256", "Expected lowercase SHA256")
        if "localPath" in source:
            local = safe_relative(source["localPath"], p + ".localPath")
            require(local in manifest_entries and local in hashes and local not in REQUIRED_FILES | MARKERS, "source_file", p + ".localPath", "Local original must be a separately listed package file")
            if "sha256" in source:
                require(source["sha256"] == hashes[local], "source_hash", p + ".sha256", "Local original hash does not match")
        elif "sha256" in source:
            warnings.append({"code": "external_source_hash_not_verified", "path": p})
    require(isinstance(evidence["claims"], list) and bool(evidence["claims"]), "schema", "evidence.claims", "At least one evidenced claim is required")
    claims, used_sources = {}, set()
    for index, claim in enumerate(evidence["claims"]):
        p = f"evidence.claims[{index}]"
        shape(claim, {"id", "questionId", "claim", "claimType", "sourceIds", "citations"}, {"limitations"}, p)
        cid = text(claim["id"], p + ".id")
        require(cid not in claims, "duplicate_id", p + ".id", "Duplicate claim id")
        require(claim["questionId"] in QUESTIONS and claim["claimType"] in CLAIM_TYPES, "claim_type", p, "Unknown questionId or claimType")
        text(claim["claim"], p + ".claim")
        refs = set(string_list(claim["sourceIds"], p + ".sourceIds", nonempty=True))
        require(refs <= source_ids, "missing_source", p, "Claim refers to an absent source")
        require(isinstance(claim["citations"], list) and bool(claim["citations"]), "citation", p, "At least one section and excerpt citation is required")
        cited = set()
        for pos, citation in enumerate(claim["citations"]):
            cp = f"{p}.citations[{pos}]"
            shape(citation, {"sourceId", "section", "excerpt"}, {"pdfPage"}, cp)
            sid = text(citation["sourceId"], cp + ".sourceId")
            require(sid in refs, "citation_source", cp, "Citation source must be in this claim's sourceIds")
            text(citation["section"], cp + ".section"); text(citation["excerpt"], cp + ".excerpt")
            if "pdfPage" in citation:
                require(type(citation["pdfPage"]) is int and citation["pdfPage"] > 0, "citation", cp, "pdfPage must be a positive integer")
            cited.add(sid)
        require(cited == refs, "citation_source", p, "Every claim sourceId must have a section/excerpt citation")
        if "limitations" in claim:
            if isinstance(claim["limitations"], list):
                string_list(claim["limitations"], p + ".limitations")
            else:
                text(claim["limitations"], p + ".limitations")
        claims[cid] = claim["questionId"]; used_sources |= refs
    expected_questions = {"Q1", "Q2"} if tier == "L" else QUESTIONS
    require(isinstance(reader["answers"], list) and len(reader["answers"]) == len(expected_questions), "questions", "reader.answers", "L requires exactly Q1/Q2; unmarked legacy packages require all seven answers")
    questions, used_claims, gaps = set(), set(), []
    for index, answer in enumerate(reader["answers"]):
        p = f"reader.answers[{index}]"
        shape(answer, {"questionId", "text", "claimIds"}, set(), p)
        q = answer["questionId"]
        require(isinstance(q, str) and q in expected_questions and q not in questions, "questions", p, "Each required question must occur exactly once")
        questions.add(q); answer_text = text(answer["text"], p + ".text")
        refs = string_list(answer["claimIds"], p + ".claimIds", nonempty=tier == "L")
        require(all(cid in claims for cid in refs), "missing_claim", p, "Answer refers to an absent claim")
        require(all(claims[cid] == q for cid in refs), "question_claim_mismatch", p, "Answer and cited claim must have the same questionId")
        used_claims.update(refs)
        if not refs:
            warnings.append({"code": "answer_without_claim", "path": p, "questionId": q})
        if not refs or re.search(r"待补|未知|未披露|未找到|暂无|不适用|缺少依据", answer_text):
            gaps.append(q)
    if tier == "L":
        used_claims.update(validate_business_model(reader["businessModel"], claims))
        require(as_of == max(published_dates), "asof_latest_disclosure", "reader.asOf", "L asOf must equal the latest adopted source disclosure date")
    if len(gaps) >= 4:
        warnings.append({"code": "possible_gap_flood", "questions": gaps, "message": "Heuristic only; human review must distinguish real non-disclosure from incomplete work"})
    if set(claims) - used_claims:
        warnings.append({"code": "unused_claims", "ids": sorted(set(claims) - used_claims)})
    if source_ids - used_sources:
        warnings.append({"code": "unused_sources", "ids": sorted(source_ids - used_sources)})
    try:
        require(bool(bodies["读者稿.md"].decode("utf-8-sig").strip()), "reader_draft", "读者稿.md", "Reader draft must not be empty")
    except UnicodeDecodeError:
        raise PackageError("reader_draft", "读者稿.md", "Reader draft must be UTF-8") from None
    return {"answers": len(expected_questions), "claims": len(claims), "sources": len(source_ids), "questionsWithPossibleGaps": gaps}


def envelope(bundle):
    return {"schemaVersion": 1, "jobId": JOB_ID, "bundle": str(bundle), "checkedAt": datetime.now(timezone.utc).isoformat(),
            "mechanical_only": True, "requires_semantic_review": True, "no_deploy": True,
            "reviewReady": False, "mechanicalPassed": False, "status": "pending", "errors": [], "warnings": [],
            "limitations": ["HTTPS syntax only; no network reachability or publisher identity verification.",
                            "References and hashes do not prove facts, dates, calculations, quotations, source scope or publication rights.",
                            "Re-run after every edit and immediately before any separate promotion; no project files are written."]}


def check_bundle(bundle, settle_seconds=0.2):
    bundle = Path(os.path.abspath(bundle))
    report = envelope(bundle)
    try:
        require(0 <= settle_seconds <= 5, "argument", "settle_seconds", "Use 0..5 seconds")
        companies, universe = _companies_snapshot()
        report["companyUniverse"] = universe
        directory_guard(bundle)
        code = bundle.parent.name
        require(code in companies, "company_identity", "bundle", "Bundle parent must be an allowed company code in the trusted universe")
        safe_relative(bundle.name, "bundle version")
        first = collect(bundle)
        if "ready.json" not in first:
            report["warnings"].append({"code": "not_ready", "message": "Completion marker absent; package not inspected as complete"})
            return report
        require(stat.S_ISREG(first["ready.json"][0]), "unsafe_path", "ready.json", "Completion marker must be a regular file")
        hashes, bodies = read_tree(bundle, first)
        time.sleep(settle_seconds)
        second = collect(bundle)
        second_hashes, _ = read_tree(bundle, second)
        if first != second or hashes != second_hashes:
            raise PackageError("unstable_package", "bundle", "Package changed between the two complete hash snapshots", "pending")
        require(REQUIRED_FILES | MARKERS <= hashes.keys(), "missing_file", "bundle", "Completed bundle must contain reader/evidence/sources JSON, 读者稿.md, manifest.json and ready.json")
        manifest, ready = (parse_json(bodies[name], name) for name in ("manifest.json", "ready.json"))
        shape(manifest, {"schemaVersion", "jobId", "code", "files"}, set(), "manifest.json")
        shape(ready, {"schemaVersion", "jobId", "code", "manifestSha256", "completedAt"}, {"producer"}, "ready.json")
        require(manifest["jobId"] == ready["jobId"] == JOB_ID and manifest["code"] == ready["code"] == code, "company_identity", "manifest/ready", "jobId/code disagree with the selected pilot package")
        require(ready["manifestSha256"] == hashes["manifest.json"], "manifest_hash", "ready.manifestSha256", "Completion marker does not bind these exact manifest bytes")
        try:
            completed = datetime.fromisoformat(text(ready["completedAt"], "ready.completedAt").replace("Z", "+00:00"))
            require(completed.tzinfo is not None and completed.utcoffset() is not None, "date", "ready.completedAt", "Completion time must include a timezone")
            require(completed.timestamp() <= time.time() + 300, "date", "ready.completedAt", "Completion time is unexpectedly in the future")
        except ValueError as error:
            if isinstance(error, PackageError):
                raise
            raise PackageError("date", "ready.completedAt", "Expected ISO completion timestamp with timezone") from None
        require(isinstance(manifest["files"], list) and bool(manifest["files"]), "schema", "manifest.files", "Expected a nonempty file manifest")
        entries, aliases = {}, set()
        for index, row in enumerate(manifest["files"]):
            p = f"manifest.files[{index}]"
            shape(row, {"path", "sha256"}, set(), p)
            name = safe_relative(row["path"], p + ".path")
            require(name not in MARKERS and name.casefold() not in aliases, "manifest_path", p, "Duplicate/marker manifest entry")
            require(isinstance(row["sha256"], str) and SHA256.fullmatch(row["sha256"]), "hash_format", p, "Expected lowercase SHA256")
            aliases.add(name.casefold()); entries[name] = row["sha256"]
        require(set(entries) == set(hashes) - MARKERS and REQUIRED_FILES <= entries.keys(), "manifest_coverage", "manifest.files", "Manifest must cover every payload file exactly once; no missing or extra files")
        require(all(hashes[name] == digest for name, digest in entries.items()), "payload_hash", "manifest.files", "Payload bytes differ from signed manifest")
        require(first["ready.json"][2] >= max(value[2] for name, value in first.items() if name != "ready.json" and stat.S_ISREG(value[0])), "ready_not_last", "ready.json", "A payload/manifest was written after ready; producer must rebuild hashes and write ready last")
        report["counts"] = validate_payload(bodies, hashes, code, entries, report["warnings"], companies)
        tier = content_tier(parse_json(bodies["reader.json"], "reader.json"))
        if tier == "L":
            require("producer" in ready, "producer", "ready.producer", "L requires the producing identity and leased run UUID")
            shape(ready["producer"], {"id", "runId"}, set(), "ready.producer")
            text(ready["producer"]["id"], "ready.producer.id")
            try:
                require(str(uuid.UUID(ready["producer"]["runId"])) == ready["producer"]["runId"], "producer", "ready.producer.runId", "Use a canonical run UUID")
            except (ValueError, AttributeError):
                raise PackageError("producer", "ready.producer.runId", "Use a canonical run UUID") from None
            report.update(contentTier="L", producer=ready["producer"], rendererSha256=hashlib.sha256(Path(__file__).with_name("build_candidate.py").read_bytes()).hexdigest())
        else:
            require("producer" not in ready, "producer", "ready.producer", "Producer metadata is reserved for explicitly marked L packages")
        final_companies, final_universe = _companies_snapshot()
        require(companies == final_companies and universe == final_universe, "company_config_drift", "company-universe.json", "Trusted company configuration changed during package validation")
        report.update(status="awaiting_semantic_review", mechanicalPassed=True, code=code, version=bundle.name,
                      manifestSha256=hashes["manifest.json"], readySha256=hashes["ready.json"],
                      verifiedPayloadHashes=entries, stableSnapshots=2)
    except PackageError as error:
        report["status"] = error.status
        report["errors"].append({"code": error.code, "path": error.path, "message": str(error)})
    except (OSError, TypeError, KeyError, OverflowError) as error:
        report["status"] = "invalid"
        report["errors"].append({"code": "unreadable_or_malformed", "path": "bundle", "message": type(error).__name__ + ": package could not be checked safely"})
    return report


def scan_root(root, settle_seconds=0.2):
    root = Path(os.path.abspath(root))
    result = envelope(root)
    result.update(status="scan_complete", packages=[])
    inbox = root / "inbox"
    try:
        directory_guard(root)
        companies, universe = _companies_snapshot()
        result["companyUniverse"] = universe
        if not inbox.exists():
            result["warnings"].append({"code": "inbox_missing"})
        else:
            directory_guard(inbox)
            for company in sorted(inbox.iterdir()):
                directory_guard(company)
                require(company.name in companies, "company_identity", "inbox", "Unknown company directory in trusted universe")
                for version in sorted(company.iterdir()):
                    result["packages"].append(check_bundle(version, settle_seconds))
        final_companies, final_universe = _companies_snapshot()
        require(companies == final_companies and universe == final_universe, "company_config_drift", "company-universe.json", "Trusted company configuration changed during scan")
    except (PackageError, OSError) as error:
        result["errors"].append({"code": getattr(error, "code", "unreadable_inbox"), "path": "inbox", "message": str(error) if isinstance(error, PackageError) else "Inbox could not be scanned safely"})
    result["counts"] = {state: sum(p["status"] == state for p in result["packages"]) for state in ("awaiting_semantic_review", "pending", "invalid")}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--root", type=Path, help="Pilot root containing inbox/<code>/<version>")
    selection.add_argument("--bundle", type=Path, help="One completed package directory")
    parser.add_argument("--settle-seconds", type=float, default=0.2, help="0..5 seconds between complete read/hash snapshots")
    args = parser.parse_args()
    result = scan_root(args.root, args.settle_seconds) if args.root else check_bundle(args.bundle, args.settle_seconds)
    # ASCII-escaped JSON is lossless and portable through Windows code pages.
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 1 if result["errors"] or any(p["status"] == "invalid" for p in result.get("packages", [])) else 0


if __name__ == "__main__":
    raise SystemExit(main())
