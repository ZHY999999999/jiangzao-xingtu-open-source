"""Linux-only, site-scoped release transaction. Upload separately; never put in webroot.

stage verifies an archive without touching LIVE. activate builds a compatibility view
then atomically switches LIVE. rollback atomically restores the recorded old target.
No nginx configuration, service restart, source data, or other sites are modified.
"""
import argparse
import ctypes
from contextlib import contextmanager
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tarfile
from urllib.request import Request, urlopen

from release_common import CODE, RELEASE, SNAPSHOT, STATIC_EXT, json_bytes, load_json, require, sha256, verify_release, validate_site_version, require_version_progress
from release_capacity import check_capacity, upload_preflight, DEFAULT_RESERVE, DEFAULT_OPERATIONAL, DEFAULT_INODE_RESERVE

LIVE = Path("/var/www/a-share-atlas")
STORE = Path("/var/www/a-share-atlas-releases")
VIEWS = Path("/var/www/a-share-atlas-views")
NGINX = (Path("/etc/nginx/sites-available/a-share-atlas"), Path("/etc/nginx/sites-available/a-share-atlas-domain"))


def atomic_json(path, value):
    temporary = path.with_name(path.name + ".new")
    require(not temporary.exists() and not temporary.is_symlink(), "Existing transaction temporary file: " + str(temporary))
    with temporary.open("xb") as handle:
        handle.write(json_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_dir(path.parent)


def fsync_dir(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def safe_directory(path):
    require(not path.is_symlink(), "Managed directory must not be a symlink: " + str(path))
    path.mkdir(parents=True, exist_ok=True)
    require(path.is_dir(), "Not a directory: " + str(path))
    path.chmod(0o755)


def release_path(release_id):
    require(RELEASE.fullmatch(release_id), "Invalid release id")
    return STORE / release_id


def current_target():
    require(LIVE.exists(), "Live root is missing")
    if LIVE.is_symlink():
        target = LIVE.resolve(strict=True)
        require(target.is_dir() and (target.is_relative_to(VIEWS.resolve()) or target.is_relative_to(STORE.resolve())),
                "Live symlink points outside managed site locations; inspect manually")
        return target
    require(LIVE.is_dir(), "Live root is not a directory")
    return LIVE


def check_nginx():
    result = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    require(result.returncode == 0, "nginx -t failed: " + result.stderr)
    import re
    for path in NGINX:
        text = path.read_text("utf-8")
        roots = re.findall(r"(?m)^\s*root\s+([^;]+);", text)
        require(roots and all(root.strip() == str(LIVE) for root in roots), "Unexpected root in " + str(path))
        require(not re.search(r"\bdisable_symlinks\s+on\b", text), "Nginx blocks symlinks: " + str(path))
    return {str(path): sha256(path) for path in NGINX}


def safe_extract(archive, destination, expected_id, reserve_bytes=DEFAULT_RESERVE,
                 operational_bytes=DEFAULT_OPERATIONAL, inode_reserve=DEFAULT_INODE_RESERVE):
    require(not destination.exists() and not destination.is_symlink(), "Release destination already exists")
    with tarfile.open(archive, "r:gz") as tar:
        members = tar.getmembers()
        names = set()
        for member in members:
            name = member.name
            parts = PurePosixPath(name).parts
            require(member.isfile() and not member.issym() and not member.islnk(), "Archive accepts regular files only")
            require(name not in names and "\\" not in name and not name.startswith("/") and name == str(PurePosixPath(name))
                    and ".." not in parts and all(part not in ("", ".") for part in parts), "Unsafe/duplicate archive path")
            require(name in ("release-manifest.json", "SHA256SUMS") or (len(parts) > 1 and parts[0] == "site"), "Unexpected archive member")
            require(member.size >= 0, "Invalid archive member size")
            names.add(name)
        require({"release-manifest.json", "SHA256SUMS", "site/index.html"} <= names, "Incomplete archive")
        manifest_member = tar.getmember("release-manifest.json")
        require(manifest_member.size < 10 * 1024 * 1024, "Manifest too large")
        manifest = json.loads(tar.extractfile(manifest_member).read())
        require(manifest.get("releaseId") == expected_id, "Archive release id mismatch")
        require(sum(member.size for member in members) <= 2 * 1024**3, "Release exceeds 2 GiB safety bound")
        directories = {"."}
        for name in names:
            directories.update(str(parent) for parent in PurePosixPath(name).parents)
        entries = len(members) + 2 * len(directories) + 16
        capacity = check_capacity([{"path": str(destination.parent),
                                   "bytes": sum(member.size for member in members) + entries * 65536,
                                   "inodes": entries}], reserve_bytes, operational_bytes, inode_reserve)
        destination.mkdir(mode=0o755)
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as source, target.open("xb") as handle:
                shutil.copyfileobj(source, handle)
                handle.flush()
                os.fsync(handle.fileno())
            target.chmod(0o644)
        for folder in destination.rglob("*"):
            if folder.is_dir():
                folder.chmod(0o755)
        fsync_dir(destination)
        return capacity


def stage(archive, digest, release_id, reserve_bytes=DEFAULT_RESERVE,
          operational_bytes=DEFAULT_OPERATIONAL, inode_reserve=DEFAULT_INODE_RESERVE):
    require(len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), "Invalid archive SHA256")
    archive = Path(archive)
    require(not archive.is_symlink() and archive.is_file(), "Invalid incoming archive")
    require(sha256(archive) == digest, "Uploaded archive hash mismatch")
    destination = release_path(release_id)
    capacity = safe_extract(archive, destination, release_id, reserve_bytes, operational_bytes, inode_reserve)
    manifest = verify_release(destination)
    return {"status": "staged_verified", "releaseId": release_id, "validation": manifest["validation"],
            "liveChanged": False, "capacity": capacity}


def hardlink(source, target):
    require(not source.is_symlink() and source.is_file(), "Compatibility source is not a regular file: " + str(source))
    if target.exists():
        require(not target.is_symlink() and sha256(source) == sha256(target), "Immutable asset/snapshot collision: " + str(target))
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    os.link(source, target)  # Fail closed on cross-filesystem; never fall back to a large copy.
    return True


def build_view(release_id, previous):
    package = release_path(release_id)
    view = VIEWS / release_id
    require(not view.exists() and not view.is_symlink(), "Serving view already exists; inspect transaction before retry")
    site = view / "site"
    site.mkdir(parents=True, mode=0o755)
    require(previous.stat().st_dev == site.stat().st_dev, "Legacy root is on another filesystem; hardlink retention unavailable")
    for source in sorted((package / "site").rglob("*")):
        require(not source.is_symlink(), "Unexpected package symlink")
        if source.is_file():
            hardlink(source, site / source.relative_to(package / "site"))
    retained = []
    assets = previous / "assets"
    if assets.is_dir():
        require(not assets.is_symlink(), "Legacy assets directory is a symlink")
        for source in sorted(assets.iterdir()):
            require(source.is_file() and not source.is_symlink() and source.suffix.lower() in STATIC_EXT and not source.name.startswith("."), "Unexpected legacy asset: " + str(source))
            if hardlink(source, site / "assets" / source.name):
                retained.append("assets/" + source.name)
    snapshots = previous / "data/companies/snapshots"
    if snapshots.is_dir():
        require(not snapshots.is_symlink(), "Legacy snapshots directory is a symlink")
        for snapshot in sorted(snapshots.iterdir()):
            require(snapshot.is_dir() and not snapshot.is_symlink() and SNAPSHOT.fullmatch(snapshot.name), "Unexpected legacy snapshot")
            for source in sorted(snapshot.iterdir()):
                require(source.suffix == ".json" and CODE.fullmatch(source.stem), "Unexpected legacy snapshot file")
                relative = "data/companies/snapshots/" + snapshot.name + "/" + source.name
                if hardlink(source, site / relative):
                    retained.append(relative)
    audit = {"releaseId": release_id, "previousTarget": str(previous), "retainedFileCount": len(retained),
             "retainedFiles": [{"path": name, "sha256": sha256(site / name)} for name in retained],
             "retention": "hardlinks to old public assets and snapshots; no old HTML or company index"}
    atomic_json(view / "compatibility-manifest.json", audit)
    for folder in view.rglob("*"):
        if folder.is_dir():
            folder.chmod(0o755)
            fsync_dir(folder)
    fsync_dir(view)
    return site, audit


def exchange(left, right):
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename = libc.renameat2
    except AttributeError as exc:
        raise RuntimeError("renameat2 unavailable; refusing non-atomic first migration") from exc
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(left), -100, os.fsencode(right), 2) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


def atomic_selftest():
    """Exercise the exact Linux primitive on isolated, disposable names before LIVE."""
    directory = STORE / ("atomic-probe-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    directory.mkdir(mode=0o700)
    original = directory / "original"
    candidate = directory / "candidate"
    original.mkdir()
    candidate.mkdir()
    (original / "marker").write_text("old", encoding="ascii")
    (candidate / "marker").write_text("new", encoding="ascii")
    temporary = directory / "link"
    temporary.symlink_to(candidate, target_is_directory=True)
    exchange(original, temporary)
    require(original.is_symlink() and (original / "marker").read_text() == "new", "Atomic exchange probe did not activate candidate")
    require(not temporary.is_symlink() and (temporary / "marker").read_text() == "old", "Atomic exchange probe lost original")
    exchange(original, temporary)
    require(not original.is_symlink() and (original / "marker").read_text() == "old" and temporary.is_symlink(), "Atomic exchange probe rollback failed")
    atomic_json(directory / "result.json", {"status": "pass", "liveTouched": False})
    return str(directory)


def set_link(target, temporary):
    require(not temporary.exists() and not temporary.is_symlink(), "Existing switch temporary path: " + str(temporary))
    os.symlink(str(target), str(temporary))
    fsync_dir(temporary.parent)


def probe(site, manifest):
    checks = ["index.html", "data/companies/index.json"]
    if manifest["validation"].get("websiteVersion"):
        checks.append("version.json")
    checks += manifest["validation"]["assetReferences"]
    index = load_json(site / "data/companies/index.json")
    for code in (index["companies"][0]["code"], index["companies"][-1]["code"]):
        checks.append(f"data/companies/snapshots/{index['snapshotId']}/{code}.json")
    for relative in sorted(set(checks)):
        request = Request("http://127.0.0.1:8081/" + relative, headers={"Host": "atlas.thinkpair.cn", "Cache-Control": "no-cache"})
        with urlopen(request, timeout=20) as response:
            content = response.read()
            require(response.status == 200 and hashlib.sha256(content).hexdigest() == sha256(site / relative), "HTTP content mismatch: " + relative)
    return len(set(checks))


def restore(target, release_id):
    require(target.is_dir() and (target.is_relative_to(STORE.resolve()) or target.is_relative_to(VIEWS.resolve())), "Unsafe rollback target")
    require(LIVE.is_symlink(), "Rollback expects managed live symlink")
    temporary = LIVE.with_name(".a-share-atlas.rollback-" + release_id)
    set_link(target, temporary)
    os.replace(temporary, LIVE)
    fsync_dir(LIVE.parent)


def activate(release_id):
    package = release_path(release_id)
    journal_path = STORE / (release_id + ".transaction.json")
    require(not journal_path.exists(), "Transaction already exists; inspect/rollback instead of repeating activation")
    manifest = verify_release(package)
    nginx_before = check_nginx()
    previous = current_target()
    require_version_progress(validate_site_version(previous), manifest["validation"].get("websiteVersion"))
    atomic_probe = atomic_selftest() if not LIVE.is_symlink() else None
    safe_directory(VIEWS)
    site, audit = build_view(release_id, previous)
    temporary = LIVE.with_name(".a-share-atlas.next-" + release_id)
    first = not LIVE.is_symlink()
    legacy = STORE / ("legacy-before-" + release_id)
    require(not legacy.exists() and not legacy.is_symlink(), "Legacy destination collision")
    rollback_target = legacy if first else previous
    journal = {"releaseId": release_id, "status": "prepared", "createdAt": datetime.now(timezone.utc).isoformat(),
               "firstMigration": first, "newTarget": str(site), "previousTarget": str(rollback_target),
               "exchangeTemporary": str(temporary), "nginxHashes": nginx_before,
               "retainedFileCount": audit["retainedFileCount"], "atomicProbe": atomic_probe}
    atomic_json(journal_path, journal)
    set_link(site, temporary)
    switched = False
    try:
        if first:
            exchange(LIVE, temporary)  # LIVE becomes new symlink; temporary becomes intact legacy directory.
            switched = True
            fsync_dir(LIVE.parent)
            os.rename(temporary, legacy)
            fsync_dir(STORE)
        else:
            os.replace(temporary, LIVE)
            switched = True
            fsync_dir(LIVE.parent)
        journal["status"] = "switched"
        atomic_json(journal_path, journal)
        require({str(path): sha256(path) for path in NGINX} == nginx_before, "Nginx configuration changed concurrently")
        journal["httpChecks"] = probe(site, manifest)
        journal["status"] = "active_verified"
        atomic_json(journal_path, journal)
    except Exception as error:
        if switched:
            if first and temporary.is_dir() and not temporary.is_symlink() and not legacy.exists():
                os.rename(temporary, legacy)
            restore(rollback_target, release_id)
            journal["status"] = "automatic_rollback"
        else:
            if temporary.is_symlink():
                temporary.unlink()
            journal["status"] = "not_switched"
        journal["error"] = str(error)
        atomic_json(journal_path, journal)
        raise
    return journal


def rollback(release_id):
    release_path(release_id)
    journal_path = STORE / (release_id + ".transaction.json")
    journal = load_json(journal_path)
    require(journal["releaseId"] == release_id, "Wrong transaction")
    new_target = VIEWS / release_id / "site"
    require(journal["newTarget"] == str(new_target), "Unsafe transaction new target")
    previous = Path(journal["previousTarget"])
    if journal["firstMigration"]:
        legacy = STORE / ("legacy-before-" + release_id)
        require(previous == legacy, "Unexpected legacy target")
        temporary = LIVE.with_name(".a-share-atlas.next-" + release_id)
        # Recover a process/power interruption immediately after RENAME_EXCHANGE.
        if not legacy.exists() and temporary.is_dir() and not temporary.is_symlink():
            os.rename(temporary, legacy)
            fsync_dir(STORE)
    require(current_target() == new_target, "This release is not live; refusing to roll back a different release")
    restore(previous, release_id)
    journal["status"] = "rolled_back"
    journal["rolledBackAt"] = datetime.now(timezone.utc).isoformat()
    atomic_json(journal_path, journal)
    return journal


def inspect():
    return {"liveRoot": str(LIVE), "isSymlink": LIVE.is_symlink(), "target": str(current_target()),
            "freeBytes": shutil.disk_usage(LIVE.parent).free, "nginxHashes": check_nginx()}


def strict_directory(path):
    """Read-only validation: no symlink in the directory or its ancestor chain."""
    require(path.is_absolute() and ".." not in path.parts, "Unsafe managed path: " + str(path))
    for part in (path, *path.parents):
        require(stat.S_ISDIR(part.lstat().st_mode), "Directory or ancestor is not a real directory: " + str(part))
    return path.lstat()


def file_identity(info):
    # atime deliberately excluded: reading a plan may update access times.
    return {"device": info.st_dev, "inode": info.st_ino, "mode": info.st_mode,
            "links": info.st_nlink, "bytes": info.st_size,
            "mtimeNs": info.st_mtime_ns, "ctimeNs": info.st_ctime_ns,
            "blocks": getattr(info, "st_blocks", None)}


def tree_inventory(root):
    """Inventory before any content reads; reject links, mounts and special files."""
    root_info = strict_directory(root)
    result = {"": file_identity(root_info)}
    def visit(directory):
        for path in sorted(directory.iterdir()):
            info = path.lstat()
            require(info.st_dev == root_info.st_dev, "Cross-device candidate: " + str(path))
            require(stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode), "Link/special file in candidate: " + str(path))
            result[path.relative_to(root).as_posix()] = file_identity(info)
            if stat.S_ISDIR(info.st_mode):
                visit(path)
    visit(root)
    return result


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def safe_relative(name):
    require(isinstance(name, str) and bool(name) and "\\" not in name
            and not name.startswith("/") and all(p not in ("", ".", "..") for p in name.split("/")),
            "Unsafe manifest relative path")
    return name


def exact_tree_files(root, tree, expected):
    actual = {name for name, info in tree.items() if stat.S_ISREG(info["mode"])}
    require(actual == set(expected), "Unknown/missing candidate files: " + str(root))
    directories = {""}
    for name, digest in expected.items():
        safe_relative(name)
        directories.update("" if str(p) == "." else str(p) for p in PurePosixPath(name).parents)
        require(sha256(root / name) == digest, "Candidate hash mismatch: " + str(root / name))
    require({name for name, info in tree.items() if stat.S_ISDIR(info["mode"])} == directories,
            "Unknown candidate directories: " + str(root))


def candidate_inventory(release_id):
    package, view = STORE / release_id, VIEWS / release_id
    trees = {str(root): tree_inventory(root) for root in (package, view)}
    manifest = verify_release(package)
    require(manifest["releaseId"] == release_id, "Candidate manifest identity mismatch")
    package_files = {"site/" + safe_relative(row["path"]): row["sha256"] for row in manifest["files"]}
    package_files.update({name: sha256(package / name) for name in ("release-manifest.json", "SHA256SUMS")})
    exact_tree_files(package, trees[str(package)], package_files)
    compatibility = load_json(view / "compatibility-manifest.json")
    require(compatibility.get("releaseId") == release_id and isinstance(compatibility.get("retainedFiles"), list),
            "Invalid compatibility manifest")
    view_files = {"site/" + safe_relative(row["path"]): row["sha256"] for row in manifest["files"]}
    retained = compatibility["retainedFiles"]
    require(compatibility.get("retainedFileCount") == len(retained), "Compatibility count mismatch")
    for row in retained:
        name = "site/" + safe_relative(row["path"])
        require(name not in view_files, "Duplicate compatibility entry")
        view_files[name] = row["sha256"]
    view_files["compatibility-manifest.json"] = sha256(view / "compatibility-manifest.json")
    exact_tree_files(view, trees[str(view)], view_files)
    require(all(tree_inventory(Path(root)) == tree for root, tree in trees.items()), "Candidate changed during validation")
    return trees


def reclaim_estimate(trees):
    """Only count blocks where EVERY hardlink is in the deletion set."""
    inodes = {}
    logical = 0
    for tree in trees.values():
        for info in tree.values():
            if not stat.S_ISREG(info["mode"]):
                continue
            logical += info["bytes"]
            key = (info["device"], info["inode"])
            row = inodes.setdefault(key, {"count": 0, "info": info})
            require(row["info"] == info, "Hardlink identity changed during inventory")
            row["count"] += 1
    freeable = [row["info"] for row in inodes.values() if row["count"] == row["info"]["links"]]
    blocks_known = all(row["blocks"] is not None for row in freeable)
    return {"logicalFileBytes": logical, "uniqueInodeBytes": sum(row["info"]["bytes"] for row in inodes.values()),
            "reclaimableInodeBytes": sum(row["bytes"] for row in freeable),
            "reclaimableAllocatedBytes": sum(row["blocks"] * 512 for row in freeable) if blocks_known else None,
            "retainedLinkedInodes": len(inodes) - len(freeable),
            "note": "Hardlink-aware file-block estimate, not a guarantee; directory blocks, open files, snapshots, copy-on-write and filesystem metadata affect actual free space."}


def _prune_plan(keep=3):
    require(type(keep) is int and keep >= 3, "keep must be at least 3")
    roots = {str(root): file_identity(strict_directory(root)) for root in (STORE, VIEWS, LIVE.parent)}
    require(LIVE.is_symlink(), "Prune requires an established managed LIVE symlink")
    live = current_target()
    strict_directory(live)
    blockers, retained, protected, journals, top = [], [], {}, {}, {}
    protected_paths = {str(live)}
    def protect_target(raw, reason):
        target = Path(raw)
        require(target.is_absolute() and ".." not in target.parts, "Unsafe transaction target")
        for root in (VIEWS, STORE):
            if target.is_relative_to(root):
                parts = target.relative_to(root).parts
                if len(parts) == 2 and RELEASE.fullmatch(parts[0]) and parts[1] == "site":
                    protected.setdefault(parts[0], []).append(reason)
                    protected_paths.add(str(target))
                    return target
                if root == STORE and len(parts) == 1 and parts[0].startswith("legacy-before-") and RELEASE.fullmatch(parts[0][14:]):
                    protected_paths.add(str(target))
                    return target
        raise ValueError("Unknown transaction target: " + str(target))
    protect_target(str(live), "LIVE")
    live_id = live.parent.name
    for root in (STORE, VIEWS):
        for item in sorted(root.iterdir()):
            identity = file_identity(item.lstat())
            top[str(item)] = identity
            if root == STORE and item.name.endswith(".transaction.json"):
                rid = item.name[:-17]
                try:
                    require(RELEASE.fullmatch(rid) and stat.S_ISREG(identity["mode"]), "Unknown transaction identity")
                    value = load_json(item)
                    require(value.get("releaseId") == rid and value.get("newTarget") == str(VIEWS / rid / "site"), "Transaction path/identity mismatch")
                    state = value.get("status")
                    require(state in {"active_verified", "prepared", "switched", "automatic_rollback", "not_switched", "rolled_back"},
                            "Unknown transaction status")
                    journals[rid] = value
                    top[str(item)]["sha256"] = sha256(item)
                    if state != "active_verified":
                        protected.setdefault(rid, []).append("transaction:" + state)
                    if state in {"prepared", "switched"}:
                        protect_target(value["previousTarget"], "unresolved:" + rid)
                        protect_target(value["newTarget"], "unresolved:" + rid)
                except (ValueError, OSError, KeyError, TypeError) as error:
                    blockers.append(str(item) + ": " + str(error))
            elif item.name.endswith(".transaction.json.new"):
                blockers.append("Unresolved transaction temporary file: " + str(item))
            elif not (RELEASE.fullmatch(item.name) and stat.S_ISDIR(identity["mode"])) and item.name != ".release.lock":
                retained.append({"path": str(item), "reason": "unknown/legacy/probe; never deleted"})
    rollback_target = None
    try:
        require(live_id in journals and journals[live_id]["status"] == "active_verified", "LIVE transaction missing or not active_verified")
        rollback_target = protect_target(journals[live_id]["previousTarget"], "immediate rollback")
        strict_directory(rollback_target)
    except (ValueError, OSError, KeyError, TypeError) as error:
        blockers.append("Immediate rollback cannot be established: " + str(error))
    successful, verified, invalid = [], {}, {}
    for rid, journal in journals.items():
        if journal["status"] == "active_verified":
            try:
                created = datetime.fromisoformat(journal["createdAt"].replace("Z", "+00:00"))
                require(created.tzinfo is not None, "Transaction creation time lacks timezone")
                # A historical success record alone is not a usable retained release.
                inventory = candidate_inventory(rid)
                verified[rid] = inventory
                successful.append((created, rid))
            except (ValueError, TypeError, KeyError) as error:
                invalid[rid] = str(error)
            except OSError as error:
                invalid[rid] = str(error)
    for target, reason in ((live, "LIVE"), (rollback_target, "immediate rollback")):
        if target is not None:
            rid = target.parent.name
            if target != VIEWS / rid / "site" or rid not in verified:
                blockers.append(reason + " has no complete verified release pair: " + str(target))
    for _, rid in sorted(successful, reverse=True)[:keep]:
        protected.setdefault(rid, []).append("recent successful keep=" + str(keep))
    candidates, trees = [], {}
    release_ids = sorted({item.name for root in (STORE, VIEWS) for item in root.iterdir() if RELEASE.fullmatch(item.name)})
    for rid in release_ids:
        if rid in protected:
            continue
        if rid not in journals or journals[rid]["status"] != "active_verified":
            retained.append({"releaseId": rid, "reason": "staged/unknown transaction; retained"})
            continue
        try:
            require(rid in verified, invalid.get(rid, "Release verification unavailable"))
            inventory = verified[rid]
            candidates.append({"releaseId": rid, "paths": list(inventory), "inventoryDigest": fingerprint(inventory)})
            trees.update(inventory)
        except (ValueError, OSError, KeyError, TypeError) as error:
            retained.append({"releaseId": rid, "reason": "incomplete/unknown candidate; retained: " + str(error)})
    tool_hashes = {name: sha256(Path(__file__).with_name(name))
                   for name in ("release_remote.py", "release_common.py", "release_capacity.py")}
    plan = {"schemaVersion": 1, "toolHashes": tool_hashes, "keep": keep, "liveTarget": str(live),
            "rollbackTarget": str(rollback_target) if rollback_target else None,
            "protected": protected, "protectedPaths": sorted(protected_paths), "retained": retained,
            "candidates": candidates, "estimate": reclaim_estimate(trees), "blockers": blockers,
            "inventoryDigest": fingerprint({"roots": roots, "live": file_identity(LIVE.lstat()), "top": top}),
            "boundary": "Only complete active_verified STORE/VIEWS pairs. Immediate rollback only; historical transaction logs retained. Incoming tools and LIVE compatibility content are untouched."}
    plan["planId"] = fingerprint(plan)
    return plan, trees


def prune_plan(keep=3):
    return _prune_plan(keep)[0]


def remove_validated_tree(root, tree, deleted_links=None, guard=None):
    """Linux descriptor-relative deletion; never traverse a symlink after planning."""
    require(os.unlink in os.supports_dir_fd and os.stat in os.supports_dir_fd,
            "Descriptor-relative deletion is unavailable")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    deleted_links = {} if deleted_links is None else deleted_links
    parent_fd = os.open(root.parent, flags)
    try:
        def remove(parent, name, relative):
            expected = tree[relative]
            actual = file_identity(os.stat(name, dir_fd=parent, follow_symlinks=False))
            adjusted = dict(expected)
            deleted = deleted_links.get((expected["device"], expected["inode"]), 0)
            if deleted:
                adjusted["links"] -= deleted
                # unlinking one of our known hardlinks updates inode ctime.
                adjusted["ctimeNs"] = actual["ctimeNs"]
            require(actual == adjusted, "Candidate changed before delete: " + str(root / relative))
            if guard:
                guard()
            if stat.S_ISREG(expected["mode"]):
                os.unlink(name, dir_fd=parent)
                deleted_links[(expected["device"], expected["inode"])] = deleted + 1
                return
            descriptor = os.open(name, flags, dir_fd=parent)
            try:
                require(file_identity(os.fstat(descriptor)) == expected, "Directory replaced while opening")
                prefix = relative + "/" if relative else ""
                children = {key[len(prefix):] for key in tree if key.startswith(prefix) and key != relative and "/" not in key[len(prefix):]}
                require(set(os.listdir(descriptor)) == children, "Directory contents changed before delete")
                for child in sorted(children):
                    # Recheck the anchor before every deletion; dir_fd prevents link traversal.
                    anchor = root.lstat()
                    require((anchor.st_dev, anchor.st_ino) == (tree[""]["device"], tree[""]["inode"]), "Candidate root replaced")
                    remove(descriptor, child, prefix + child)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            require((current.st_dev, current.st_ino) == (expected["device"], expected["inode"]), "Directory replaced before rmdir")
            os.rmdir(name, dir_fd=parent)
        remove(parent_fd, root.name, "")
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)


def prune(keep=3, apply=False, plan_id=None):
    """Caller must hold the shared release lock. Fresh plan required for every apply."""
    plan, trees = _prune_plan(keep)
    if not apply:
        require(plan_id is None, "--plan-id requires --apply")
        return {"status": "blocked" if plan["blockers"] else "dry_run", **plan}
    require(plan_id and len(plan_id) == 64 and plan_id == plan["planId"], "Missing or stale plan ID; generate and approve a fresh dry-run")
    require(not plan["blockers"], "Prune blocked: " + "; ".join(plan["blockers"]))
    # Complete prevalidation of ALL candidates before the first destructive action.
    require(all(tree_inventory(Path(root)) == inventory for root, inventory in trees.items()), "Candidates changed before apply")
    completed = []
    removed_paths = []
    deleted_links = {}
    live_identity = file_identity(LIVE.lstat())
    anchors = {str(root): (root.stat().st_dev, root.stat().st_ino) for root in (STORE, VIEWS)}
    protected_anchors = {path: (Path(path).stat().st_dev, Path(path).stat().st_ino) for path in plan["protectedPaths"] if Path(path).exists()}
    def guard():
        require(file_identity(LIVE.lstat()) == live_identity and str(current_target()) == plan["liveTarget"], "LIVE changed during prune")
        for name, identity in {**anchors, **protected_anchors}.items():
            info = strict_directory(Path(name))
            require((info.st_dev, info.st_ino) == identity, "Protected/managed directory changed during prune")
    try:
        for candidate in plan["candidates"]:
            for name in candidate["paths"]:
                remove_validated_tree(Path(name), trees[name], deleted_links, guard)
                removed_paths.append(name)
            completed.append(candidate["releaseId"])
    except (ValueError, OSError) as error:
        return {"status": "partial", "planId": plan_id, "completed": completed, "removedPaths": removed_paths,
                "error": str(error), "boundary": "Stopped immediately. Generate a fresh plan; incomplete pairs are retained for manual review. Transaction logs unchanged."}
    return {"status": "applied", "planId": plan_id, "completed": completed, "removedPaths": removed_paths,
            "estimate": plan["estimate"], "liveTarget": plan["liveTarget"], "rollbackTarget": plan["rollbackTarget"]}


@contextmanager
def release_lock(create=True):
    import fcntl
    flags = os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0)
    descriptor = os.open(STORE / ".release.lock", flags, 0o644)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "Unsafe release lock file")
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("inspect")
    sub.add_parser("selftest")
    staging = sub.add_parser("stage")
    staging.add_argument("--archive", required=True)
    staging.add_argument("--sha256", required=True)
    preflight = sub.add_parser("preflight")
    for name in ("archive-bytes", "payload-bytes", "file-count", "directory-count"):
        preflight.add_argument("--" + name, required=True, type=int)
    for action in (staging, preflight):
        action.add_argument("--reserve-bytes", type=int, default=DEFAULT_RESERVE)
        action.add_argument("--operational-bytes", type=int, default=DEFAULT_OPERATIONAL)
        action.add_argument("--inode-reserve", type=int, default=DEFAULT_INODE_RESERVE)
    pruning = sub.add_parser("prune", help="Read-only plan by default; only complete old successful releases")
    pruning.add_argument("--keep", type=int, default=3)
    pruning.add_argument("--apply", action="store_true")
    pruning.add_argument("--plan-id")
    for action in (staging, sub.add_parser("verify"), sub.add_parser("activate"), sub.add_parser("rollback")):
        action.add_argument("--release-id", required=True)
    args = parser.parse_args()
    require(sys.platform == "linux" and sys.version_info >= (3, 9), "Linux and Python 3.9+ required")
    require(os.geteuid() == 0, "Run via the authorized root SSH connection")
    if args.action == "inspect":
        result = inspect()
    elif args.action == "preflight":
        result = upload_preflight(args.archive_bytes, args.payload_bytes, args.file_count, args.directory_count,
                                  args.reserve_bytes, args.operational_bytes, args.inode_reserve)
    elif args.action == "prune":
        strict_directory(STORE)
        with release_lock(create=False):
            result = prune(args.keep, args.apply, args.plan_id)
    else:
        safe_directory(STORE)
        with release_lock():
            if args.action == "selftest":
                result = {"status": "pass", "probe": atomic_selftest(), "liveTouched": False}
            elif args.action == "stage":
                result = stage(args.archive, args.sha256, args.release_id,
                               args.reserve_bytes, args.operational_bytes, args.inode_reserve)
            elif args.action == "verify":
                result = verify_release(release_path(args.release_id))["validation"]
            elif args.action == "activate":
                result = activate(args.release_id)
            else:
                result = rollback(args.release_id)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    if result.get("status") in {"blocked", "partial"}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
