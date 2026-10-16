"""Read-only Linux capacity checks, shared by pre-upload and extraction.

May be sent over SSH stdin/command text before uploading the release tools.
No directories or files are created by this module.
"""
import json
import os
from pathlib import Path
import tarfile

DEFAULT_RESERVE = 1024**3
DEFAULT_OPERATIONAL = 6 * 1024**3
DEFAULT_INODE_RESERVE = 1024


def existing_parent(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Capacity path must be absolute")
    while not path.exists() and not path.is_symlink():
        path = path.parent
    for item in (path, *path.parents):
        if item.is_symlink() or not item.is_dir():
            raise ValueError("Unsafe capacity path: " + str(item))
    return path


def check_capacity(requests, reserve_bytes=DEFAULT_RESERVE, operational_bytes=DEFAULT_OPERATIONAL,
                   inode_reserve=DEFAULT_INODE_RESERVE):
    """Group allocations by filesystem; count links as directory entries, not inodes.

    requests: [{path, bytes, inodes}]. bytes must include allocation overhead.
    This is a point-in-time admission check, not a reservation against other apps.
    """
    if (type(reserve_bytes) is not int or reserve_bytes < DEFAULT_RESERVE
            or type(operational_bytes) is not int or operational_bytes < reserve_bytes
            or type(inode_reserve) is not int or inode_reserve < 1):
        raise ValueError("Reserve must be >= 1 GiB; operational threshold >= reserve; inode reserve positive")
    grouped = {}
    for request in requests:
        if any(type(request[key]) is not int or request[key] < 0 for key in ("bytes", "inodes")):
            raise ValueError("Capacity requirements must be nonnegative integers")
        path = existing_parent(request["path"])
        device = path.stat().st_dev
        row = grouped.setdefault(device, {"device": device, "path": str(path), "bytes": 0, "inodes": 0})
        row["bytes"] += request["bytes"]
        row["inodes"] += request["inodes"]
    results = []
    failures = []
    for row in grouped.values():
        usage = os.statvfs(row["path"])
        free = usage.f_bavail * usage.f_frsize
        available_inodes = usage.f_favail
        after = free - row["bytes"]
        row.update(freeBytes=free, freeInodes=available_inodes, projectedFreeBytes=after,
                   requiredFreeBytes=row["bytes"] + reserve_bytes,
                   requiredFreeInodes=row["inodes"] + inode_reserve,
                   operationalWarning=after < operational_bytes)
        if free < row["requiredFreeBytes"]:
            failures.append("Insufficient bytes on " + row["path"])
        if available_inodes < row["requiredFreeInodes"]:
            failures.append("Insufficient inodes on " + row["path"])
        results.append(row)
    report = {"status": "blocked" if failures else "pass", "filesystems": results,
              "reserveBytes": reserve_bytes, "operationalThresholdBytes": operational_bytes,
              "inodeReserve": inode_reserve, "failures": failures,
              "warning": "Point-in-time check; other workloads can consume space after this check."}
    if failures:
        raise ValueError(json.dumps(report, sort_keys=True))
    return report


def upload_preflight(archive_bytes, payload_bytes, file_count, directory_count,
                     reserve_bytes=DEFAULT_RESERVE, operational_bytes=DEFAULT_OPERATIONAL,
                     inode_reserve=DEFAULT_INODE_RESERVE,
                     incoming="/var/tmp/a-share-atlas-release", store="/var/www/a-share-atlas-releases"):
    values = (archive_bytes, payload_bytes, file_count, directory_count)
    if any(type(value) is not int or value < 1 for value in values):
        raise ValueError("Positive archive/payload/file/directory estimates required")
    # 64 KiB per file/dir is deliberately conservative for allocation and metadata;
    # a second directory tree is needed by activation's hardlink serving view.
    overhead = (file_count + 2 * directory_count + 16) * 65536
    return check_capacity([
        {"path": incoming, "bytes": archive_bytes + 1024**2, "inodes": 8},
        {"path": store, "bytes": payload_bytes + overhead,
         "inodes": file_count + 2 * directory_count + 16},
    ], reserve_bytes, operational_bytes, inode_reserve)


def archive_requirements(archive):
    """Local read-only sizing of actual archive entries, not a report estimate."""
    from pathlib import PurePosixPath
    with tarfile.open(archive, "r:gz") as stream:
        members = stream.getmembers()
    directories = {"."}
    names = set()
    for member in members:
        name = member.name
        if (not member.isfile() or member.size < 0 or name in names or "\\" in name
                or name.startswith("/") or any(part in ("", ".", "..") for part in name.split("/"))):
            raise ValueError("Unsafe archive member during sizing")
        names.add(name)
        directories.update(str(parent) for parent in PurePosixPath(name).parents)
    if not members:
        raise ValueError("Empty archive")
    return {"archiveBytes": Path(archive).stat().st_size,
            "payloadBytes": sum(member.size for member in members),
            "fileCount": len(members), "directoryCount": len(directories)}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    print(json.dumps(archive_requirements(parser.parse_args().archive), sort_keys=True))
