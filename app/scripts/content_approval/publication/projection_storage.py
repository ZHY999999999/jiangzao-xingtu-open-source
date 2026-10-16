"""Bounded cooperative storage for offline projections. Windows local NTFS only.

No cleanup, overwrite, copy fallback, PID ownership or approval decision lives here.
The caller must freshly verify its approval chain before and after promotion.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes
import errno
import os
from pathlib import Path
import re
import stat
import uuid

import preflight as guard

MAX_COMPANY_ATTEMPTS = 3
MAX_TOTAL_ATTEMPTS = 32
MAX_ATTEMPT_BYTES = 8 * 1024 * 1024
CODE = re.compile(r"[0-9]{6}\.(?:SZ|SH|BJ)\Z")
ATTEMPT = re.compile(r"[0-9a-f]{32}\Z")
FILES = {"content.json", "mapping.json"}


class StorageError(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.details = details


def require(ok, code, message, details=None):
    if not ok:
        raise StorageError(code, message, details)


def supported_platform():
    require(os.name == "nt", "unsupported_storage_platform",
            "Atomic no-clobber promotion is implemented only for Windows local NTFS; no rename/copy fallback")


def directory(path):
    path = guard.guarded_path(path)
    require(stat.S_ISDIR(path.lstat().st_mode), "unsafe_filesystem", "Expected a real directory")
    return path


def child(parent, name):
    guard.relative_name(name)
    require("/" not in name, "unsafe_path", "Expected one directory component")
    directory(parent)
    path = parent / name
    try:
        path.mkdir()
    except FileExistsError:
        pass
    return directory(path)


def directory_id(path):
    info = directory(path).lstat()
    # Archive/indexing flags and parent timestamps are metadata, not object
    # identity. directory() independently rejects reparse points on every call.
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


@contextmanager
def lock(root, name):
    """Persistent empty lock file, OS-owned byte zero; no initialization race."""
    supported_platform()
    import msvcrt
    guard.relative_name(name)
    require("/" not in name, "unsafe_path", "Expected one lock name")
    parent = child(directory(root / "publication"), "projection-locks")
    path = parent / name
    if os.path.lexists(path):
        guard.guarded_path(path)
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 1,
                "unsafe_filesystem", "Lock must be a regular, non-hardlinked empty/one-byte file")
    # O_CREAT does not replace existing contents. A byte can be locked beyond EOF.
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o600)
    acquired = False
    try:
        os.set_inheritable(fd, False)
        guard.guarded_path(path)
        opened = os.fstat(fd)
        current = path.lstat()
        require(stat.S_ISREG(opened.st_mode) and opened.st_nlink == 1 and opened.st_size <= 1
                and guard.same_opened_file(current, opened),
                "unsafe_filesystem", "Lock path and opened file identity differ")
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError as error:
            # Only an actual byte-lock conflict is busy; open/permission failures
            # above are not turned into ownership or approval claims.
            if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise StorageError("busy", "A cooperative projection lock is held: " + name) from error
            raise
        acquired = True
        guard.guarded_path(path)
        require(guard.same_opened_file(path.lstat(), os.fstat(fd)), "unsafe_filesystem", "Lock identity changed")
        yield
    finally:
        try:
            if acquired:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(fd)


def inventory(root):
    """Count every retained attempt, including empty/partial/old complete ones.

    Other companies can still write their two files while the short allocation
    lock is held. Their directory already reserves a full byte-budget slot.
    No full-tree stability/approval claim is made by this quota observation.
    """
    base = root / "publication/projection-attempts"
    if not os.path.lexists(base):
        return []
    directory(base)
    rows = []
    for company in sorted(base.iterdir()):
        require(CODE.fullmatch(company.name), "unsafe_attempt_inventory", "Unknown company directory in attempts")
        directory(company)
        for attempt in sorted(company.iterdir()):
            require(ATTEMPT.fullmatch(attempt.name), "unsafe_attempt_inventory", "Unknown attempt directory name")
            directory(attempt)
            size = 0
            names = []
            for path in sorted(attempt.iterdir()):
                guard.guarded_path(path)
                info = path.lstat()
                require(path.name in FILES and stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                        "unsafe_attempt_inventory", "Attempt has an unknown, linked or nonregular member")
                size += info.st_size
                names.append(path.name)
            require(size <= MAX_ATTEMPT_BYTES, "unsafe_attempt_inventory", "An existing attempt exceeds its byte budget")
            rows.append({"code": company.name, "path": attempt.relative_to(root).as_posix(),
                         "logicalBytesObserved": size, "filesObserved": names})
    return rows


def matching_attempt(root, code, expected):
    for row in inventory(root):
        if row["code"] != code or set(row["filesObserved"]) != FILES:
            continue
        path = root / row["path"]
        tree, _ = guard.snapshot_tree(path)
        if tree == expected:
            return path
    return None


def allocate_attempt(root, code, expected_bytes):
    require(CODE.fullmatch(code), "unsafe_path", "Expected a full company code")
    require(expected_bytes <= MAX_ATTEMPT_BYTES, "attempt_size_exceeded",
            "Projection is too large for an attempt; no text is truncated",
            {"requiredBytes": expected_bytes, "maximumBytes": MAX_ATTEMPT_BYTES})
    with lock(root, "attempt-quota.lock"):
        rows = inventory(root)
        count = sum(row["code"] == code for row in rows)
        require(count < MAX_COMPANY_ATTEMPTS and len(rows) < MAX_TOTAL_ATTEMPTS,
                "attempt_quota_exceeded", "Retained attempts fill the quota; no automatic cleanup",
                {"companyAttempts": count, "totalAttempts": len(rows), "retainedAttempts": rows})
        parent = child(child(root / "publication", "projection-attempts"), code)
        path = parent / uuid.uuid4().hex
        path.mkdir()  # Exactly one exclusive allocation; a collision is an error.
        directory(path)
        return path


def _kernel32():
    supported_platform()
    return ctypes.WinDLL("kernel32", use_last_error=True)


def local_ntfs_volume(path):
    """Conservative support boundary; never silently accept network/FAT moves."""
    kernel = _kernel32()
    volume = ctypes.create_unicode_buffer(32768)
    kernel.GetVolumePathNameW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    kernel.GetVolumePathNameW.restype = ctypes.c_int
    require(kernel.GetVolumePathNameW(str(path), volume, len(volume)), "unsupported_storage_volume", "Cannot identify volume")
    kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    kernel.GetDriveTypeW.restype = ctypes.c_uint32
    require(kernel.GetDriveTypeW(volume.value) == 3, "unsupported_storage_volume", "Only a local fixed volume is supported")
    fs = ctypes.create_unicode_buffer(64)
    kernel.GetVolumeInformationW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
    kernel.GetVolumeInformationW.restype = ctypes.c_int
    require(kernel.GetVolumeInformationW(volume.value, None, 0, None, None, None, fs, len(fs))
            and fs.value.upper() == "NTFS", "unsupported_storage_volume", "Only the tested local NTFS storage contract is supported")
    return volume.value.casefold()


def _native_move_no_replace(source, target):
    kernel = _kernel32()
    kernel.MoveFileExW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
    kernel.MoveFileExW.restype = ctypes.c_int
    # 0: neither REPLACE_EXISTING nor COPY_ALLOWED. In particular an empty
    # destination directory may not be replaced. No exists()+rename fallback.
    if not kernel.MoveFileExW(str(source), str(target), 0):
        error = ctypes.get_last_error()
        raise StorageError("promotion_failed", "Windows refused no-clobber directory promotion", {"winError": error})


def promote_no_replace(source, target):
    supported_platform()
    source_id = directory_id(source)
    source_parent_id = directory_id(source.parent)
    target_parent_id = directory_id(target.parent)
    require(source_id[0] == target_parent_id[0]
            and local_ntfs_volume(source) == local_ntfs_volume(target.parent),
            "cross_volume_promotion", "Promotion requires the same local NTFS volume")
    if os.path.lexists(target):
        guard.guarded_path(target)  # The native primitive still decides no-clobber.
    observed = [directory_id(source), directory_id(source.parent), directory_id(target.parent)]
    require([source_id, source_parent_id, target_parent_id] == observed,
            "output_drift", "Promotion directory identity changed",
            {"before": [source_id, source_parent_id, target_parent_id], "after": observed})
    _native_move_no_replace(source, target)
    require(not os.path.lexists(source) and directory_id(target) == source_id,
            "output_drift", "Promoted directory identity does not match its attempt")
