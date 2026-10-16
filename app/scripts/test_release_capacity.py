"""Offline capacity admission tests. No network; fixtures retained under diagnostics."""
import io
import json
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import release_capacity as capacity
import release_remote as remote

ROOT = Path(__file__).resolve().parents[2] / "diagnostics/capacity-tests"
ROOT.mkdir(parents=True, exist_ok=True)


class CapacityTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="case-", dir=ROOT))

    def usage(self, free, inodes=1000000):
        return SimpleNamespace(f_bavail=free, f_frsize=1, f_favail=inodes)

    def requests(self, needed=100):
        return [{"path": str(self.root), "bytes": needed, "inodes": 10}]

    def test_exact_reserve_passes_and_warns(self):
        with patch.object(capacity.os, "statvfs", return_value=self.usage(capacity.DEFAULT_RESERVE + 100), create=True):
            row = capacity.check_capacity(self.requests())["filesystems"][0]
        self.assertEqual(row["projectedFreeBytes"], capacity.DEFAULT_RESERVE)
        self.assertTrue(row["operationalWarning"])

    def test_one_byte_below_reserve_blocks(self):
        with patch.object(capacity.os, "statvfs", return_value=self.usage(capacity.DEFAULT_RESERVE + 99), create=True):
            with self.assertRaisesRegex(ValueError, "Insufficient bytes"):
                capacity.check_capacity(self.requests())

    def test_inode_shortage_blocks_with_plenty_of_bytes(self):
        with patch.object(capacity.os, "statvfs", return_value=self.usage(100 * 1024**3, 1033), create=True):
            with self.assertRaisesRegex(ValueError, "Insufficient inodes"):
                capacity.check_capacity(self.requests())

    def test_above_operational_threshold_has_no_warning(self):
        with patch.object(capacity.os, "statvfs", return_value=self.usage(capacity.DEFAULT_OPERATIONAL + 100), create=True):
            row = capacity.check_capacity(self.requests())["filesystems"][0]
        self.assertFalse(row["operationalWarning"])

    def test_upload_same_filesystem_aggregates_both_allocations(self):
        with patch.object(capacity.os, "statvfs", return_value=self.usage(100 * 1024**3), create=True):
            report = capacity.upload_preflight(1000, 2000, 5, 3, incoming=self.root, store=self.root)
        self.assertEqual(len(report["filesystems"]), 1)
        row = report["filesystems"][0]
        self.assertEqual(row["bytes"], 1000 + 1024**2 + 2000 + (5 + 6 + 16) * 65536)
        self.assertEqual(row["inodes"], 8 + 5 + 6 + 16)

    def test_split_filesystems_are_checked_independently(self):
        class Device:
            def __init__(self, number): self.number = number
            def stat(self): return SimpleNamespace(st_dev=self.number)
            def __str__(self): return "device-" + str(self.number)
        with patch.object(capacity, "existing_parent", side_effect=[Device(1), Device(2)]), \
                patch.object(capacity.os, "statvfs", return_value=self.usage(100 * 1024**3), create=True):
            report = capacity.check_capacity([{"path": "/incoming", "bytes": 100, "inodes": 2},
                                              {"path": "/store", "bytes": 200, "inodes": 3}])
        self.assertEqual([row["bytes"] for row in report["filesystems"]], [100, 200])

    def test_one_split_filesystem_shortage_blocks(self):
        class Device:
            def __init__(self, number): self.number = number
            def stat(self): return SimpleNamespace(st_dev=self.number)
            def __str__(self): return "device-" + str(self.number)
        with patch.object(capacity, "existing_parent", side_effect=[Device(1), Device(2)]), \
                patch.object(capacity.os, "statvfs", side_effect=[self.usage(100 * 1024**3), self.usage(10)], create=True):
            with self.assertRaisesRegex(ValueError, "Insufficient bytes on device-2"):
                capacity.check_capacity([{"path": "/incoming", "bytes": 100, "inodes": 2},
                                         {"path": "/store", "bytes": 200, "inodes": 3}])

    def test_reserve_cannot_be_lowered_below_one_gib(self):
        with self.assertRaisesRegex(ValueError, "Reserve"):
            capacity.check_capacity(self.requests(), reserve_bytes=capacity.DEFAULT_RESERVE - 1)

    def test_invalid_requirements_rejected(self):
        for value in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                capacity.upload_preflight(value, 2000, 5, 3, incoming=self.root, store=self.root)

    def make_archive(self):
        archive = self.root / "fixture.tar.gz"
        contents = {"release-manifest.json": json.dumps({"releaseId": "test"}).encode(),
                    "SHA256SUMS": b"fixture", "site/index.html": b"fixture html"}
        with tarfile.open(archive, "w:gz") as output:
            for name, data in contents.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                output.addfile(info, io.BytesIO(data))
        return archive, contents

    def test_actual_archive_sizing(self):
        archive, contents = self.make_archive()
        report = capacity.archive_requirements(archive)
        self.assertEqual(report["payloadBytes"], sum(map(len, contents.values())))
        self.assertEqual(report["fileCount"], 3)
        self.assertEqual(report["directoryCount"], 2)

    def test_extraction_capacity_failure_creates_nothing(self):
        archive, _ = self.make_archive()
        target = self.root / "extracted"
        with patch.object(remote, "check_capacity", side_effect=ValueError("Insufficient bytes")):
            with self.assertRaisesRegex(ValueError, "Insufficient bytes"):
                remote.safe_extract(archive, target, "test")
        self.assertFalse(target.exists())

    def test_extraction_checks_actual_payload_and_entries(self):
        archive, contents = self.make_archive()
        target = self.root / "extracted"
        with patch.object(remote, "check_capacity", return_value={"status": "pass"}) as check, patch.object(remote, "fsync_dir"):
            report = remote.safe_extract(archive, target, "test")
        self.assertEqual(report["status"], "pass")
        request = check.call_args.args[0][0]
        self.assertEqual(request["inodes"], 3 + 2 * 2 + 16)
        self.assertEqual(request["bytes"], sum(map(len, contents.values())) + request["inodes"] * 65536)

    def test_preupload_payload_runs_without_remote_files(self):
        namespace = {"__name__": "release_capacity_check"}
        exec(Path(capacity.__file__).read_text("utf-8"), namespace)
        self.assertTrue(callable(namespace["upload_preflight"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
