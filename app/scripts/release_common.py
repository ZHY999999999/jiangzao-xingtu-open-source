"""Dependency-free release validation shared by local packaging and Linux staging."""
import hashlib
import json
import math
import posixpath
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

CODE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")
SNAPSHOT = re.compile(r"^\d{8}-[a-f0-9]{16}$")
RELEASE = re.compile(r"^[0-9]{8}T[0-9]{12}Z-[a-f0-9]{12}$")
STATUS = {"available", "partial", "missing", "review"}
STATIC_EXT = {".js", ".css", ".woff2", ".woff", ".ttf", ".otf", ".png", ".jpg", ".jpeg", ".webp", ".svg", ".ico", ".avif"}
PUBLIC_ADDITIONS = {
    "version.json",
    "favicon.ico", "images/brand/favicon-32.png", "images/brand/favicon-night-32.png",
    "data/market/latest.json",
    "fonts/noise-atlas-display-LICENSE.txt", "fonts/noise-atlas-display-SOURCE.md",
    "images/brand/home-constellation.png", "images/brand/home-constellation-night.png",
    "images/brand/noise-lab-logo.png", "images/brand/noise-lab-logo-night.png",
    "images/company/server-network.png",
    "audio/companies/601138/overview-2025.mp3",
    "audio/companies/601138/overview-2025.metadata.json",
    "audio/companies/601138/overview-2025-126c06fcdd07.mp3",
    "audio/companies/601138/overview-2025-126c06fcdd07.metadata.json",
}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load_json(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f"Duplicate JSON key in {path}: {key}")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError(f"Non-finite JSON number in {path}: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=pairs, parse_constant=invalid)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def fields(value, spec, label):
    require(isinstance(value, dict), f"{label} must be an object")
    for key, kind in spec.items():
        require(key in value and type(value[key]) in (kind if isinstance(kind, tuple) else (kind,)), f"{label}.{key} has wrong/missing type")


def strings(values, label):
    require(isinstance(values, list) and all(isinstance(x, str) for x in values), f"{label} must be strings")


def validate_dossier(dossier, entry, as_of):
    code = entry["code"]
    fields(dossier, {"schemaVersion": int, "code": str, "name": str, "industry": str, "companyType": str,
                    "asOf": str, "profileAsOf": str, "updatedAt": str, "summary": dict, "profile": dict,
                    "timeline": list, "businessModel": list, "competitive": list, "risks": list,
                    "finance": dict, "segments": list, "sources": list, "coverage": dict}, code)
    require(dossier["schemaVersion"] == 1 and dossier["code"] == code and dossier["asOf"] == as_of, f"{code}: identity/schema/date mismatch")
    require(dossier["name"] == entry["name"] and dossier["industry"] == entry["industry"], f"{code}: index identity mismatch")
    require(dossier["companyType"] in {"industrial", "bank", "insurance", "securities", "financial"}, f"{code}: invalid company type")
    fields(dossier["summary"], {"text": str, "products": str, "customers": str, "revenue": str, "sourceIds": list}, code + ".summary")
    fields(dossier["profile"], {"founded": (str, type(None)), "listed": (str, type(None)), "website": (str, type(None)),
                                "intro": str, "mainBusiness": str, "businessScope": str}, code + ".profile")
    source_ids = []
    for source in dossier["sources"]:
        fields(source, {"id": str, "title": str}, code + ".source")
        require(bool(source["id"]), f"{code}: empty source id")
        for key in ("url", "document", "locator", "asOf", "publishedAt", "localRef", "sourceType"):
            if key in source:
                require(isinstance(source[key], str) or (key == "publishedAt" and source[key] is None),
                        f"{code}: source.{key} must be string (publishedAt may be unknown/null)")
        source_ids.append(source["id"])
    require(len(source_ids) == len(set(source_ids)), f"{code}: duplicate source id")
    source_ids = set(source_ids)
    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "sourceIds":
                    strings(child, code + ".sourceIds")
                    require(set(child) <= source_ids, f"{code}: unresolved source reference")
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, float):
            require(math.isfinite(value), f"{code}: non-finite value")
    walk(dossier)
    for section in ("timeline", "businessModel", "competitive", "risks"):
        for claim in dossier[section]:
            fields(claim, {"title": str, "text": str, "kind": str, "sourceIds": list}, code + "." + section)
            require(claim["kind"] in {"fact", "company_statement", "interpretation"}, f"{code}: unknown claim kind")
            if section == "timeline":
                fields(claim, {"date": str}, code + ".timeline")
            if "status" in claim:
                require(claim["status"] in STATUS, f"{code}: invalid claim status")
    finance = dossier["finance"]
    fields(finance, {"currency": str, "unit": str, "annual": list, "quarterly": list, "latest": (dict, type(None)), "notes": list}, code + ".finance")
    require(finance["unit"] == "元", f"{code}: unexpected financial unit")
    strings(finance["notes"], code + ".finance.notes")
    for point in finance["annual"] + finance["quarterly"] + ([finance["latest"]] if finance["latest"] else []):
        fields(point, {"period": str, "annDate": (str, type(None)), "revenueField": (str, type(None)), "sourceIds": list}, code + ".finance.point")
        for key in ("revenue", "netProfit", "operatingCashFlow", "totalAssets", "totalLiabilities", "rdExpense", "capex"):
            require(key in point and type(point[key]) in (int, float, type(None)), f"{code}: invalid financial {key}")
        require(re.fullmatch(r"\d{8}", point["period"]) and point["period"] <= as_of, f"{code}: invalid/future period")
        require(point["annDate"] is None or (re.fullmatch(r"\d{8}", point["annDate"]) and point["annDate"] <= as_of), f"{code}: invalid/future announcement")
        require(point.get("reportType") == "1", f"{code}: nonconsolidated point")
    for group in dossier["segments"]:
        fields(group, {"period": str, "dimension": str, "currency": str, "items": list, "notes": list}, code + ".segments")
        strings(group["notes"], code + ".segments.notes")
        for item in group["items"]:
            fields(item, {"name": str, "sourceIds": list}, code + ".segments.item")
            for key in ("revenue", "cost", "profit", "share"):
                require(key in item and type(item[key]) in (int, float, type(None)), f"{code}: invalid segment {key}")
    require(bool(dossier["coverage"]), f"{code}: empty coverage")
    for value in dossier["coverage"].values():
        fields(value, {"status": str, "note": str}, code + ".coverage")
        require(value["status"] in STATUS, f"{code}: invalid coverage status")
    history = bool(finance["annual"] or finance["quarterly"])
    require(entry["hasHistory"] == history, f"{code}: index history mismatch")
    return history, not bool(dossier["profile"]["mainBusiness"])


def allowed_path(relative, snapshot):
    if relative in ("index.html", "data/companies/index.json") or relative in PUBLIC_ADDITIONS:
        return True
    p = Path(relative)
    if len(p.parts) == 2 and p.parts[0] in ("assets", "fonts"):
        return p.suffix.lower() in STATIC_EXT and not p.name.startswith(".")
    return relative.startswith(f"data/companies/snapshots/{snapshot}/") and len(p.parts) == 5 and p.suffix == ".json" and CODE.fullmatch(p.stem) is not None


def file_inventory(site, snapshot):
    result = []
    for item in sorted(site.rglob("*")):
        require(not item.is_symlink(), f"Symlink forbidden in release: {item}")
        if item.is_dir():
            continue
        relative = item.relative_to(site).as_posix()
        require(item.is_file() and allowed_path(relative, snapshot), f"Unexpected/nonpublic release file: {relative}")
        result.append({"path": relative, "bytes": item.stat().st_size, "sha256": sha256(item)})
    # Path ordering depends on the host (WindowsPath folds case; PosixPath does
    # not). Release manifests use exact POSIX path strings and Unicode ordering.
    return canonical_files(result)


def canonical_files(files):
    require(isinstance(files, list), "Manifest files must be a list")
    paths = set()
    for row in files:
        require(isinstance(row, dict) and set(row) == {"path", "bytes", "sha256"}, "Invalid manifest file fields")
        name = row["path"]
        require(isinstance(name, str) and bool(name) and "\\" not in name and not name.startswith("/")
                and all(part not in ("", ".", "..") for part in name.split("/")), "Invalid manifest file path")
        require(name not in paths, "Duplicate manifest file path")
        require(type(row["bytes"]) is int and row["bytes"] >= 0, "Invalid manifest file size")
        require(isinstance(row["sha256"], str) and re.fullmatch(r"[a-f0-9]{64}", row["sha256"]), "Invalid manifest file hash")
        paths.add(name)
    return sorted(files, key=lambda row: row["path"])


def asset_references(site):
    references = set()
    class Assets(HTMLParser):
        def handle_starttag(self, tag, attrs):
            for key, value in attrs:
                if value and key in ("src", "href"):
                    references.add(("index.html", value))
    Assets().feed((site / "index.html").read_text("utf-8"))
    for item in sorted((site / "assets").glob("*")):
        if item.suffix not in (".js", ".css"):
            continue
        relative = item.relative_to(site).as_posix()
        content = item.read_text("utf-8")
        if "data/market/latest.json" in content:
            references.add((relative, "/data/market/latest.json"))
        if item.suffix == ".css":
            for value in re.findall(r"url\(\s*['\"]?([^)'\"\s]+)", content):
                references.add((relative, value))
        else:
            for value in re.findall(r'''["']([^"'\s]+\.(?:js|css|woff2?|ttf|png|svg|webp|jpg|jpeg|ico|mp3)(?:[?#][^"'\s]*)?)["']''', content):
                if value.startswith(("/", "./", "../", "assets/", "fonts/")):
                    references.add((relative, value))
    resolved = set()
    for source, url in references:
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        path = unquote(parsed.path)
        if path.startswith("/"):
            path = path.lstrip("/")
        elif path.startswith(("assets/", "fonts/")):
            pass  # Vite dependency maps are relative to the application's base.
        else:
            path = posixpath.normpath(posixpath.join(posixpath.dirname(source), path))
        require(not path.startswith("../") and (site / path).is_file(), f"Missing asset: {source} -> {url}")
        resolved.add(path)
    require(any(path.endswith(".js") for path in resolved), "No JavaScript entry found")
    return sorted(resolved)


def validate_market(site):
    path = site / "data/market/latest.json"
    if not path.exists():
        return
    data = load_json(path)
    fields(data, {"schemaVersion": int, "tradeDate": str, "coverage": dict, "stocks": dict, "source": dict}, "market")
    require(data["schemaVersion"] == 1 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["tradeDate"]), "Invalid market schema/date")
    valued = 0
    for code, row in data["stocks"].items():
        require(CODE.fullmatch(code) and isinstance(row, dict) and "mv" in row, "Invalid market company")
        value = row["mv"]
        require(value is None or (type(value) in (int, float) and math.isfinite(value) and value >= 0), "Invalid market value")
        valued += value is not None
    require(data["coverage"] == {"listed":len(data["stocks"]), "valued":valued, "missing":len(data["stocks"])-valued}, "Market coverage mismatch")
    require(data["source"].get("field") == "total_mv" and data["source"].get("unit") == "亿元", "Unexpected market field/unit")


def validate_site_version(site):
    """Legacy releases remain verifiable; new metadata must agree with its HTML."""
    site = Path(site)
    markers = []
    class VersionMeta(HTMLParser):
        def handle_starttag(self, tag, attrs):
            data = dict(attrs)
            if tag == "meta" and data.get("name") == "application-version":
                markers.append(data.get("content"))
    VersionMeta().feed((site / "index.html").read_text("utf-8"))
    path = site / "version.json"
    if not path.exists():
        require(not markers, "HTML version exists but version.json is missing")
        return None
    version = load_json(path)
    fields(version, {"version": str, "date": str, "revision": str, "changes": list, "history": list}, "website version")
    require(re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version["version"]), "Invalid website version")
    require(re.fullmatch(r"[a-f0-9]{12}", version["revision"]), "Invalid website revision")
    require(markers == [version["version"] + "+" + version["revision"]], "HTML and website version disagree")
    require(version["history"] and version["history"][0] == {key: version[key] for key in ("version", "date", "changes")}, "Website version history mismatch")
    previous = None
    for entry in version["history"]:
        fields(entry, {"version": str, "date": str, "changes": list}, "version history")
        require(re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", entry["version"]), "Invalid history version")
        number = tuple(map(int, entry["version"].split(".")))
        require(previous is None or number < previous, "Version history must be unique and descending")
        previous = number
        require(re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["date"]), "Invalid version date")
        require(entry["changes"] and all(isinstance(x, str) and x.strip() for x in entry["changes"]), "Empty version notes")
    return {key: version[key] for key in ("version", "date", "revision")}


def require_version_progress(previous, candidate):
    """Data-only releases may keep a version; changed product assets may not."""
    require(candidate is not None, "New releases require version.json")
    if previous is None:
        return
    old = tuple(map(int, previous["version"].split(".")))
    new = tuple(map(int, candidate["version"].split(".")))
    require(new >= old, "Website version must not decrease; use explicit Rollback to restore an old release")
    require(new != old or candidate["revision"] == previous["revision"],
            "Website changed without a version bump; run npm run version:patch before publishing")


def validate_site(site, expected_companies=None):
    site = Path(site)
    index = load_json(site / "data/companies/index.json")
    fields(index, {"schemaVersion": int, "generatedAt": str, "asOf": str, "snapshotId": str, "coverage": dict, "companies": list}, "index")
    require(index["schemaVersion"] == 1 and SNAPSHOT.fullmatch(index["snapshotId"]), "Invalid company index version/snapshot")
    require(re.fullmatch(r"\d{8}", index["asOf"]), "Invalid asOf")
    snapshot = index["snapshotId"]
    require(snapshot.startswith(index["asOf"] + "-"), "Snapshot date differs from index")
    coverage = index["coverage"]
    fields(coverage, {key: int for key in ("total", "basic", "financialHistory", "deep", "missingProfiles")}, "index.coverage")
    entries = index["companies"]
    require(len(entries) > 0 and len(entries) == coverage["total"] == coverage["basic"], "Company total/basic count mismatch")
    if expected_companies is not None:
        require(len(entries) == expected_companies, f"Expected {expected_companies} companies; found {len(entries)}")
    codes = []
    for entry in entries:
        fields(entry, {"code": str, "name": str, "industry": str, "summary": str, "hasHistory": bool, "depth": str, "updatedAt": str}, "index.company")
        require(CODE.fullmatch(entry["code"]) and entry["depth"] in {"basic", "deep"}, "Invalid company code/depth")
        codes.append(entry["code"])
    require(len(codes) == len(set(codes)), "Duplicate company code")
    snapshots = site / "data/companies/snapshots"
    require(snapshots.is_dir() and {p.name for p in snapshots.iterdir()} == {snapshot}, "Release must contain exactly the active snapshot")
    directory = snapshots / snapshot
    require({p.name for p in directory.iterdir()} == {code + ".json" for code in codes}, "Snapshot must contain every indexed company and no extras")
    digest = hashlib.sha256()
    counts = {"financialHistory": 0, "missingProfiles": 0, "deep": 0}
    for entry in sorted(entries, key=lambda row: row["code"]):
        path = directory / (entry["code"] + ".json")
        history, missing = validate_dossier(load_json(path), entry, index["asOf"])
        counts["financialHistory"] += int(history)
        counts["missingProfiles"] += int(missing)
        counts["deep"] += int(entry["depth"] == "deep")
        digest.update(entry["code"].encode("ascii"))
        digest.update(path.read_bytes())
    require(snapshot.endswith(digest.hexdigest()[:16]), "Snapshot content hash mismatch")
    require(all(coverage[key] == value for key, value in counts.items()), "Coverage count mismatch")
    refs = asset_references(site)
    validate_market(site)
    website_version = validate_site_version(site)
    files = file_inventory(site, snapshot)
    summary = {"snapshotId": snapshot, "companyCount": len(entries), "coverage": coverage,
               "assetReferences": refs, "fileCount": len(files), "totalBytes": sum(row["bytes"] for row in files)}
    if website_version is not None:
        summary["websiteVersion"] = website_version
    return summary, files


def verify_release(directory):
    directory = Path(directory)
    manifest = load_json(directory / "release-manifest.json")
    require(manifest.get("formatVersion") == 1 and RELEASE.fullmatch(manifest.get("releaseId", "")), "Invalid release manifest")
    summary, files = validate_site(directory / "site", manifest["validation"]["companyCount"])
    require(canonical_files(files) == canonical_files(manifest["files"]) and summary == manifest["validation"], "Release content differs from manifest")
    # Preserve the written order for already-issued Windows manifests. We verify
    # every row above, then check SHA256SUMS against that exact manifest sequence.
    expected = "".join(row["sha256"] + "  site/" + row["path"] + "\n" for row in manifest["files"])
    require((directory / "SHA256SUMS").read_text("utf-8") == expected, "SHA256SUMS differs from manifest")
    require({p.name for p in directory.iterdir()} == {"site", "release-manifest.json", "SHA256SUMS"}, "Unexpected release metadata")
    return manifest
