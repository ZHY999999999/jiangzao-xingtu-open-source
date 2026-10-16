"""Package a completed dist; copy exactly one complete company snapshot. No network."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

from release_common import SNAPSHOT, allowed_path, json_bytes, load_json, require, sha256, validate_site, verify_release

APP = Path(__file__).resolve().parents[1]


def build(dist, output, expected):
    dist, output = Path(dist).resolve(), Path(output).resolve()
    index = load_json(dist / "data/companies/index.json")
    snapshot = index.get("snapshotId", "")
    require(SNAPSHOT.fullmatch(snapshot), "Invalid active snapshot")
    active = dist / "data/companies/snapshots" / snapshot
    require(active.is_dir(), "Incomplete dist: active company snapshot is missing; finish npm run build first")
    selected = []
    ignored = []
    for source in sorted(dist.rglob("*")):
        require(not source.is_symlink(), f"Symlink in dist forbidden: {source}")
        if source.is_dir():
            continue
        name = source.relative_to(dist).as_posix()
        parts = name.split("/")
        if len(parts) >= 5 and parts[:3] == ["data", "companies", "snapshots"] and parts[3] != snapshot:
            ignored.append(name)
            continue
        require(source.is_file() and allowed_path(name, snapshot), f"Unexpected dist file; do not package it: {name}")
        selected.append((source, name))
    selected.sort(key=lambda item: item[1])
    initial = [(name, sha256(source), source.stat().st_size) for source, name in selected]
    fingerprint = hashlib.sha256(json_bytes(initial)).hexdigest()[:12]
    release_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + fingerprint
    directory = output / release_id
    directory.mkdir(parents=True, exist_ok=False)
    site = directory / "site"
    for source, name in selected:
        target = site / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    summary, files = validate_site(site, expected)
    require([(row["path"], row["sha256"], row["bytes"]) for row in files] == initial,
            "dist changed while packaging; rebuild and retry after all writers finish")
    manifest = {"formatVersion": 1, "releaseId": release_id,
                "createdAt": datetime.now(timezone.utc).isoformat(), "validation": summary, "files": files}
    (directory / "release-manifest.json").write_bytes(json_bytes(manifest))
    (directory / "SHA256SUMS").write_text("".join(row["sha256"] + "  site/" + row["path"] + "\n" for row in files), encoding="utf-8", newline="\n")
    verify_release(directory)
    archive = output / (release_id + ".tar.gz")
    with tarfile.open(archive, "w:gz", compresslevel=6) as tar:
        for item in sorted(directory.rglob("*")):
            if not item.is_file():
                continue
            info = tar.gettarinfo(str(item), arcname=item.relative_to(directory).as_posix())
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o644
            info.mtime = 0
            with item.open("rb") as handle:
                tar.addfile(info, handle)
    digest = sha256(archive)
    (output / (archive.name + ".sha256")).write_text(digest + "  " + archive.name + "\n", encoding="ascii")
    report = {"status": "pass", "releaseId": release_id, "archive": str(archive), "archiveSha256": digest,
              "archiveBytes": archive.stat().st_size, "unpackedBytes": summary["totalBytes"],
              "companyCount": summary["companyCount"], "snapshotId": snapshot,
              "fileCount": summary["fileCount"], "excludedHistoricalFiles": len(ignored),
              "excludedHistoricalSnapshots": sorted({name.split('/')[3] for name in ignored}),
              "deploymentPerformed": False}
    if summary.get("websiteVersion"):
        report["websiteVersion"] = summary["websiteVersion"]
    (output / (release_id + ".report.json")).write_bytes(json_bytes(report))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=APP / "dist")
    parser.add_argument("--output", type=Path, default=APP.parent / "diagnostics/release")
    parser.add_argument("--expected-companies", type=int, required=True, help="Independent expected listed-company count; prevents silently dropping entries")
    parser.add_argument("--verify", type=Path, help="Verify an existing unpacked release instead of packaging")
    args = parser.parse_args()
    result = verify_release(args.verify)["validation"] if args.verify else build(args.dist, args.output, args.expected_companies)
    require(result["companyCount"] == args.expected_companies, "Verified release company count differs from independently expected count")
    print(json.dumps(result, ensure_ascii=True, indent=2))
