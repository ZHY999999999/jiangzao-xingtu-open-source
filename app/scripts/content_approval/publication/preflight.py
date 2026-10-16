"""Read-only, offline comparison against caller-pinned manifests. Never deploys."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import unicodedata

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
LIMITATIONS = [
    "The supplied path list is a declaration, not independently verified content approval.",
    "Actual bundle/review/adoption/page-review approval-chain validation is not connected.",
    "Conversion into actual website content fields is not connected.",
    "The pinned baseline manifest is checked; an actual fixed application baseline is not verified.",
    "An exclusive publication writer, whole-site release and production readback are not connected.",
    "This is a local plan only; no source project, Git, network, deployment or background process is used.",
    "Inputs must be controlled locally; this is not a sandbox against a hostile concurrent filesystem writer.",
]


class Refused(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require(condition, code, message):
    if not condition:
        raise Refused(code, message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def valid_digest(value, where):
    require(isinstance(value, str) and SHA256.fullmatch(value) is not None,
            "missing_or_invalid_hash", where + " requires an explicit lowercase SHA-256")
    return value


def relative_name(value):
    require(isinstance(value, str) and bool(value), "unsafe_path", "Expected a nonempty POSIX relative file path")
    require(unicodedata.normalize("NFC", value) == value, "unsafe_path", "Paths must use NFC Unicode")
    require(not any(ord(c) < 32 or ord(c) == 127 or c in '\\:<>"|?*' for c in value),
            "unsafe_path", "Control characters, backslashes, drive/ADS syntax and wildcard characters are forbidden")
    parts = value.split("/")
    for part in parts:
        require(part not in {"", ".", ".."} and not part.endswith((" ", ".")),
                "unsafe_path", "Empty, dot, traversal or trailing-dot/space components are forbidden")
        device = part.split(".", 1)[0].upper()
        require(device not in {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
                and re.fullmatch(r"(?:COM|LPT)[1-9¹²³]", device) is None,
                "unsafe_path", "Windows device names are forbidden")
    return value


def validate_names(names):
    aliases, components = {}, {}
    for name in names:
        relative_name(name)
        folded = name.casefold()
        require(folded not in aliases or aliases[folded] == name,
                "path_alias", "Paths must not alias under case-insensitive comparison")
        aliases[folded] = name
        parts = name.split("/")
        for index in range(1, len(parts) + 1):
            prefix = "/".join(parts[:index])
            key = prefix.casefold()
            require(key not in components or components[key] == prefix,
                    "path_alias", "Directory components must not alias under case-insensitive comparison")
            components[key] = prefix
    for folded in aliases:
        parts = folded.split("/")
        require(not any("/".join(parts[:i]) in aliases for i in range(1, len(parts))),
                "path_conflict", "A file cannot also be another file's parent")


def is_link(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


def identity(info):
    # Windows lstat has reported directory size 4096 -> 0 with all other
    # identity fields unchanged. It is not a file-content length; retain every
    # other field and the separate member/byte snapshots for drift detection.
    # Regular-file size and non-Windows directory size remain strict.
    size = None if os.name == "nt" and stat.S_ISDIR(info.st_mode) else info.st_size
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, size,
            info.st_mtime_ns, info.st_ctime_ns, getattr(info, "st_file_attributes", 0))


def same_opened_file(path_info, opened_info):
    left, right = identity(path_info), identity(opened_info)
    # On this Windows Python, lstat ctime is creation time while fstat ctime
    # is change time. Compare portable identity fields across the APIs, then
    # compare each API's complete snapshot against itself before/after reading.
    indices = (0, 1, 2, 3, 4, 5, 7) if os.name == "nt" else range(len(left))
    return all(left[index] == right[index] for index in indices)


def guarded_path(path):
    # No resolve(): resolving a link before checking it would conceal the link.
    path = Path(os.path.abspath(path))
    for item in list(reversed(path.parents)) + [path]:
        info = item.lstat()
        require(not is_link(info), "unsafe_filesystem", "Symlinks and reparse points/junctions are forbidden")
        if item != path:
            require(stat.S_ISDIR(info.st_mode), "unsafe_filesystem", "An input ancestor is not a directory")
    return path


def read_regular(path, keep_bytes=True):
    path = guarded_path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
            "unsafe_filesystem", "Only regular, non-hardlinked files are accepted")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    chunks = []
    hasher = hashlib.sha256()
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        require(same_opened_file(before, opened), "input_drift", "File identity changed while opening")
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
            if keep_bytes:
                chunks.append(chunk)
        require(identity(os.fstat(stream.fileno())) == identity(opened), "input_drift", "File changed while reading")
    guarded_path(path)
    require(identity(path.lstat()) == identity(before), "input_drift", "File identity changed after reading")
    return b"".join(chunks) if keep_bytes else hasher.hexdigest(), identity(before)


def parse_manifest(raw, member):
    def pairs(rows):
        value = {}
        for key, item in rows:
            require(key not in value, "invalid_manifest", "Duplicate JSON keys are forbidden")
            value[key] = item
        return value

    def nonfinite(_):
        raise Refused("invalid_manifest", "Non-finite JSON numbers are forbidden")

    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs, parse_constant=nonfinite)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Refused("invalid_manifest", "Expected UTF-8 JSON object") from error
    require(isinstance(value, dict) and set(value) == {"schemaVersion", member}
            and type(value["schemaVersion"]) is int and value["schemaVersion"] == 1,
            "invalid_manifest", "Manifest requires exactly schemaVersion=1 and " + member)
    mapping = value[member]
    require(isinstance(mapping, dict), "invalid_manifest", member + " must map exact relative file paths to SHA-256")
    validate_names(mapping)
    for name, value_hash in mapping.items():
        valid_digest(value_hash, member + ": " + name)
    return mapping


def snapshot_tree(directory):
    root = guarded_path(directory)
    require(stat.S_ISDIR(root.lstat().st_mode), "unsafe_filesystem", "Candidate must be a directory")
    hashes, inventory = {}, {}
    pending = [root]
    while pending:
        folder = pending.pop()
        guarded_path(folder)
        info = folder.lstat()
        require(stat.S_ISDIR(info.st_mode), "input_drift", "Candidate directory changed type")
        relative = folder.relative_to(root).as_posix()
        inventory[relative] = identity(info)
        children = sorted(folder.iterdir(), key=lambda item: item.name)
        require(folder == root or bool(children), "empty_directory", "Nested empty directories are outside the file manifest")
        for child in children:
            name = child.relative_to(root).as_posix()
            relative_name(name)
            info = child.lstat()
            require(not is_link(info), "unsafe_filesystem", "Candidate contains a symlink or reparse point/junction")
            if stat.S_ISDIR(info.st_mode):
                pending.append(child)
            else:
                value_hash, file_identity = read_regular(child, keep_bytes=False)
                hashes[name] = value_hash
                inventory[name] = file_identity
        require(identity(folder.lstat()) == inventory[relative], "input_drift", "Directory changed during inventory")
    validate_names(hashes)
    return hashes, inventory


def preflight(baseline, baseline_sha256, candidate, approved_paths, approved_paths_sha256,
              *, removed_paths=None, removed_paths_sha256=None):
    result = {"schemaVersion": 1, "status": "rejected", "localPlanOnly": True,
              "readyForPublication": False, "noDeploy": True, "errors": [], "limitations": LIMITATIONS.copy()}
    try:
        valid_digest(baseline_sha256, "baseline_sha256")
        valid_digest(approved_paths_sha256, "approved_paths_sha256")
        # An omitted removal manifest preserves the original no-deletion contract.
        has_removals = removed_paths is not None
        require(has_removals or removed_paths_sha256 is None, "removal_manifest_missing",
                "A removal-list hash must accompany its explicit manifest path")
        if has_removals:
            valid_digest(removed_paths_sha256, "removed_paths_sha256")
        baseline_raw, baseline_identity = read_regular(baseline)
        paths_raw, paths_identity = read_regular(approved_paths)
        require(digest(baseline_raw) == baseline_sha256, "baseline_hash_mismatch", "Pinned baseline bytes have changed")
        require(digest(paths_raw) == approved_paths_sha256, "path_list_hash_mismatch", "Pinned path-list bytes have changed")
        before = parse_manifest(baseline_raw, "files")
        allowed = parse_manifest(paths_raw, "changes")
        removals = {}
        if has_removals:
            removals_raw, removals_identity = read_regular(removed_paths)
            require(digest(removals_raw) == removed_paths_sha256, "removal_list_hash_mismatch",
                    "Pinned removal-list bytes have changed")
            removals = parse_manifest(removals_raw, "removals")
        validate_names(list(before) + list(allowed) + list(removals))
        require(not (set(allowed) & set(removals)), "conflicting_declaration",
                "A path cannot be declared as both new content and removed")
        for name, expected_old in removals.items():
            require(name in before, "removal_not_in_baseline",
                    "A removal must name an exact file in the pinned baseline: " + name)
            require(before[name] == expected_old, "removal_hash_mismatch",
                    "Removal differs from the pre-saved baseline file hash: " + name)
        first, first_inventory = snapshot_tree(candidate)
        second, second_inventory = snapshot_tree(candidate)
        require(first == second and first_inventory == second_inventory, "input_drift", "Candidate changed between complete snapshots")
        require(read_regular(baseline) == (baseline_raw, baseline_identity), "input_drift", "Baseline changed during preflight")
        require(read_regular(approved_paths) == (paths_raw, paths_identity), "input_drift", "Path list changed during preflight")
        if has_removals:
            require(read_regular(removed_paths) == (removals_raw, removals_identity),
                    "input_drift", "Removal list changed during preflight")
        validate_names(list(before) + list(allowed) + list(removals) + list(first))
        removed = sorted(set(before) - set(first))
        if not has_removals:
            require(not removed, "deletion_not_supported", "The default contract rejects missing baseline files; no removal manifest was supplied")
        else:
            require(not (set(removals) & set(first)), "removal_still_present",
                    "Every declared removal must already be absent from the candidate tree")
            require(set(removed) == set(removals), "unlisted_removal",
                    "Missing baseline files differ from the exact removal declaration")
        for name, expected in allowed.items():
            require(name in first, "expected_file_missing", "An explicitly listed content file is absent: " + name)
            require(first[name] == expected, "content_hash_mismatch", "Content differs from its declared expected hash: " + name)
        changes = []
        for name in sorted(first):
            if before.get(name) == first[name]:
                continue
            require(name in allowed, "unlisted_change", "Changed or added file is not in the exact path list: " + name)
            changes.append({"path": name, "kind": "modified" if name in before else "added",
                            "beforeSha256": before.get(name), "afterSha256": first[name]})
        # These are descriptions of an already-observed tree difference, never delete operations.
        changes.extend({"path": name, "kind": "removed", "beforeSha256": removals[name],
                        "afterSha256": None} for name in removed)
        changes.sort(key=lambda row: row["path"])
        plan = {"baselineManifestSha256": baseline_sha256, "declaredPathListSha256": approved_paths_sha256,
                "candidateTreeSha256": digest(canonical(first)), "candidateFileCount": len(first), "changes": changes}
        if has_removals:
            plan["declaredRemovalListSha256"] = removed_paths_sha256
        result.update(status="local_plan" if changes else "no_release", planId=digest(canonical(plan)), **plan)
    except Refused as error:
        result["errors"].append({"code": error.code, "message": str(error)})
    except (OSError, TypeError, ValueError, OverflowError):
        result["errors"].append({"code": "unreadable_input", "message": "An input could not be read safely"})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--baseline-sha256")
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--approved-paths", required=True, type=Path)
    parser.add_argument("--approved-paths-sha256")
    parser.add_argument("--removed-paths", type=Path,
                        help="Optional exact removal manifest; omission preserves rejection of every missing baseline file")
    parser.add_argument("--removed-paths-sha256",
                        help="Required raw-byte SHA-256 when --removed-paths is supplied")
    args = parser.parse_args(argv)
    result = preflight(args.baseline, args.baseline_sha256, args.candidate,
                       args.approved_paths, args.approved_paths_sha256,
                       removed_paths=args.removed_paths, removed_paths_sha256=args.removed_paths_sha256)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 1 if result["status"] == "rejected" else 0


if __name__ == "__main__":
    raise SystemExit(main())
