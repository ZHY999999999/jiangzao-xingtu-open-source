"""Independent Linux fixture QA. No production paths or external network.

Usage: python3 prune_independent_qa.py --candidate /tmp/.../app/scripts
Creates only a fresh /tmp/atlas-prune-independent-qa-* workspace and retains it
for examination. Imports the reviewed candidate, then replaces all managed
paths before invoking any operation. One HTTP check binds only 127.0.0.1 at a
random port and serves fixture LIVE; no nginx or production HTTP is used.
"""
import argparse
import contextlib
import errno
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import importlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import ProxyHandler, build_opener


ARGS = None
ROOT = None
remote = None
common = None
LOOPBACK_REQUESTS = []


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(common.json_bytes(value))


def rid(n):
    return f"20261001T{n:012d}Z-{n:012x}"


def fingerprint(root):
    """Ignore atime, but retain inode/link/content and namespace evidence."""
    out = {}
    for parent, directories, files in os.walk(root, followlinks=False):
        for name in sorted(directories + files):
            p = Path(parent) / name
            s = p.lstat()
            row = [s.st_mode, s.st_dev, s.st_ino, s.st_size,
                   s.st_nlink, s.st_mtime_ns]
            if p.is_symlink():
                row.append(os.readlink(p))
            elif stat.S_ISREG(s.st_mode):
                row.append(hashlib.sha256(p.read_bytes()).hexdigest())
            out[str(p.relative_to(root))] = row
    return out


class Fixture:
    def __init__(self, name, nonlinear=False):
        self.root = ROOT / name
        self.root.mkdir()
        self.store = self.root / "store"
        self.views = self.root / "views"
        self.live = self.root / "live"
        self.incoming = self.root / "incoming"
        for p in (self.store, self.views, self.incoming):
            p.mkdir()
        (self.store / ".release.lock").touch()
        remote.STORE, remote.VIEWS, remote.LIVE = self.store, self.views, self.live
        self.legacy = self.store / ("legacy-before-" + rid(1))
        self.legacy.mkdir()
        (self.legacy / "assets").mkdir()
        (self.legacy / "index.html").write_text("legacy", encoding="utf-8")
        previous = self.legacy
        for n in range(1, 7):
            self.package(n)
            if nonlinear and n == 6:
                previous = self.views / rid(1) / "site"
            site, audit = remote.build_view(rid(n), previous)
            save(self.tx(n), {"releaseId": rid(n), "status": "active_verified",
                 "createdAt": "2026-10-01T00:00:00+00:00", "firstMigration": n == 1,
                 "newTarget": str(site), "previousTarget": str(previous),
                 "retainedFileCount": audit["retainedFileCount"],
                 "exchangeTemporary": str(self.root / (".next-" + rid(n))),
                 "nginxHashes": {}, "atomicProbe": None})
            previous = site
        self.live.symlink_to(previous, target_is_directory=True)

    def tx(self, n):
        return self.store / (rid(n) + ".transaction.json")

    def package(self, n):
        package = self.store / rid(n)
        site = package / "site"
        (site / "assets").mkdir(parents=True)
        version = {"version": f"1.0.{n}", "date": "2026-10-01", "revision": f"{n:012x}",
                   "changes": [f"fixture {n}"]}
        version["history"] = [{key: version[key] for key in ("version", "date", "changes")}]
        save(site / "version.json", version)
        (site / "index.html").write_text(
            f'<meta name="application-version" content="1.0.{n}+{n:012x}">'
            f'<script type="module" src="/assets/app-{n}.js"></script>', encoding="utf-8")
        (site / "assets" / f"app-{n}.js").write_text(f'console.log("fixture-{n}");', encoding="utf-8")
        # Equal bytes are deliberately separate inodes across releases.
        (site / "favicon.ico").write_bytes(b"I" * 4096)
        code = "000001.SZ"
        doc = {"schemaVersion": 1, "code": code, "name": "QA fixture",
               "industry": "Fixture", "companyType": "industrial", "asOf": "20261001",
               "profileAsOf": "20261001", "updatedAt": "2026-10-01", 
               "summary": {"text": f"fixture-{n}", "products": "test", "customers": "test", "revenue": "test", "sourceIds": []},
               "profile": {"founded": None, "listed": None, "website": None,
                           "intro": "test", "mainBusiness": "test", "businessScope": "test"},
               "timeline": [], "businessModel": [], "competitive": [], "risks": [],
               "finance": {"currency": "CNY", "unit": "元", "annual": [], "quarterly": [], "latest": None, "notes": []},
               "segments": [], "sources": [], "coverage": {"overview": {"status": "available", "note": "test"}}}
        raw = common.json_bytes(doc)
        snapshot = "20261001-" + hashlib.sha256(code.encode("ascii") + raw).hexdigest()[:16]
        p = site / "data/companies/snapshots" / snapshot / (code + ".json")
        p.parent.mkdir(parents=True)
        p.write_bytes(raw)
        save(site / "data/companies/index.json", {"schemaVersion": 1, "generatedAt": "2026-10-01",
             "asOf": "20261001", "snapshotId": snapshot,
             "coverage": {"total": 1, "basic": 1, "financialHistory": 0, "deep": 0, "missingProfiles": 0},
             "companies": [{"code": code, "name": "QA fixture", "industry": "Fixture",
                            "summary": "test", "hasHistory": False, "depth": "basic", "updatedAt": "2026-10-01"}]})
        summary, files = common.validate_site(site, 1)
        save(package / "release-manifest.json", {"formatVersion": 1, "releaseId": rid(n),
             "companySnapshot": snapshot, "validation": summary, "files": files})
        (package / "SHA256SUMS").write_text("".join(
            row["sha256"] + "  site/" + row["path"] + "\n" for row in files), encoding="utf-8")
        common.verify_release(package)

    def update_tx(self, n, **values):
        obj = common.load_json(self.tx(n))
        obj.update(values)
        save(self.tx(n), obj)

    def plan(self):
        return remote.prune_plan(keep=3)

    def apply(self, plan):
        return remote.prune(keep=3, apply=True, plan_id=plan["planId"])

    def cli(self, *args):
        # The child patches all paths before main(); no production default is used.
        code = ("import sys; from pathlib import Path; "
                "sys.path.insert(0,sys.argv[1]); import release_remote as r; "
                "root=Path(sys.argv[2]); "
                "r.STORE=root/'store'; r.VIEWS=root/'views'; r.LIVE=root/'live'; "
                "sys.argv=[r.__file__]+sys.argv[3:]; r.main()")
        return subprocess.run([sys.executable, "-c", code, str(ARGS.candidate.resolve()),
                               str(self.root), *args], text=True, capture_output=True, timeout=30)

    def protected_digest(self):
        # Unlinking old aliases legitimately reduces st_nlink in retained views.
        return {str(p): {key: value[:4] + value[5:] for key, value in fingerprint(p).items()}
                for p in (self.live.resolve(), Path(common.load_json(self.tx(6))["previousTarget"]))}


def candidate_ids(plan):
    return {item["releaseId"] if isinstance(item, dict) else item for item in plan["candidates"]}


@contextlib.contextmanager
def fixture_http(live):
    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(live)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


class PruneTests(unittest.TestCase):
    def fixture(self, nonlinear=False):
        return Fixture(self._testMethodName, nonlinear=nonlinear)

    def test_dry_run_is_read_only_and_repeatable(self):
        f = self.fixture()
        before = fingerprint(f.root)
        p1, p2 = f.plan(), f.plan()
        self.assertEqual(p1["planId"], p2["planId"])
        self.assertEqual(before, fingerprint(f.root))
        self.assertEqual(candidate_ids(p1), {rid(1), rid(2), rid(3)})

    def test_nonlinear_rollback_survives_apply_and_real_restore(self):
        f = self.fixture(nonlinear=True)
        plan = f.plan()
        self.assertEqual(candidate_ids(plan), {rid(2), rid(3)})
        before = f.protected_digest()
        journals = {p.name: p.read_bytes() for p in f.store.glob("*.transaction.json")}
        target = Path(common.load_json(f.tx(6))["previousTarget"])
        current_bytes = {name: (f.live / name).read_bytes() for name in ("index.html", "version.json")}
        target_bytes = {name: (target / name).read_bytes() for name in current_bytes}
        self.assertNotEqual(current_bytes["version.json"], target_bytes["version.json"])
        opener = build_opener(ProxyHandler({}))
        with fixture_http(f.live) as base:
            def check_http(stage, expected):
                for name, content in expected.items():
                    with opener.open(base + "/" + name, timeout=5) as response:
                        self.assertEqual(response.status, 200)
                        actual = response.read()
                    self.assertEqual(actual, content, stage + ": " + name)
                    LOOPBACK_REQUESTS.append({"stage": stage, "path": name, "status": 200,
                                              "sha256": hashlib.sha256(actual).hexdigest()})
            check_http("before_prune", current_bytes)
            result = f.apply(plan)
            self.assertEqual(result["status"], "applied", result)
            self.assertEqual(before, f.protected_digest())
            self.assertEqual(journals, {p.name: p.read_bytes() for p in f.store.glob("*.transaction.json")})
            for n in (2, 3):
                self.assertFalse((f.store / rid(n)).exists())
                self.assertFalse((f.views / rid(n)).exists())
            check_http("after_prune", current_bytes)
            remote.rollback(rid(6))
            self.assertEqual(f.live.resolve(), target)
            check_http("after_real_rollback", target_bytes)

    def test_unknown_staged_and_incoming_are_untouched(self):
        f = self.fixture()
        f.package(7)
        (f.store / "unknown").mkdir()
        (f.store / "unknown/payload").write_text("do not delete")
        (f.incoming / "ongoing-upload").write_text("incomplete")
        protected = {str(p): fingerprint(p) for p in (f.store / rid(7), f.store / "unknown", f.incoming, f.legacy)}
        f.apply(f.plan())
        self.assertEqual(protected, {str(Path(p)): fingerprint(Path(p)) for p in protected})

    def test_unresolved_transaction_protects_referenced_old_target(self):
        f = self.fixture()
        f.package(7)
        save(f.tx(7), {"releaseId": rid(7), "status": "prepared", "firstMigration": False,
             "newTarget": str(f.views / rid(7) / "site"),
             "previousTarget": str(f.views / rid(2) / "site")})
        plan = f.plan()
        self.assertNotIn(rid(2), candidate_ids(plan))

    def test_wrong_plan_id_changes_nothing(self):
        f = self.fixture()
        plan = f.plan()
        before = fingerprint(f.root)
        plan["planId"] = "f" * 64
        with self.assertRaises(Exception):
            f.apply(plan)
        self.assertEqual(before, fingerprint(f.root))

    def test_live_switch_invalidates_plan(self):
        f = self.fixture()
        plan = f.plan()
        f.live.unlink()
        f.live.symlink_to(f.views / rid(2) / "site", target_is_directory=True)
        before = fingerprint(f.root)
        with self.assertRaises(Exception):
            f.apply(plan)
        self.assertEqual(before, fingerprint(f.root))

    def test_transaction_change_invalidates_plan(self):
        f = self.fixture()
        plan = f.plan()
        f.update_tx(2, status="prepared")
        before = fingerprint(f.root)
        with self.assertRaises(Exception):
            f.apply(plan)
        self.assertEqual(before, fingerprint(f.root))

    def test_candidate_inode_replacement_invalidates_plan(self):
        f = self.fixture()
        plan = f.plan()
        target = f.store / rid(2) / "site/index.html"
        raw = target.read_bytes()
        target.unlink()
        target.write_bytes(raw)
        before = fingerprint(f.root)
        with self.assertRaises(Exception):
            f.apply(plan)
        self.assertEqual(before, fingerprint(f.root))

    def test_symlink_outside_tree_is_never_followed(self):
        f = self.fixture()
        outside = f.root / "outside"
        outside.mkdir()
        (outside / "valuable").write_text("must survive")
        target = f.store / rid(2) / "site/unexpected-link"
        target.symlink_to(outside, target_is_directory=True)
        before = fingerprint(outside)
        plan = f.plan()
        self.assertNotIn(rid(2), candidate_ids(plan))
        self.assertEqual(before, fingerprint(outside))

    def test_candidate_root_replaced_with_symlink_invalidates_plan(self):
        f = self.fixture()
        plan = f.plan()
        victim = f.store / rid(2)
        moved = f.root / "relocated-old-release"
        victim.rename(moved)
        victim.symlink_to(moved, target_is_directory=True)
        before = fingerprint(f.root)
        with self.assertRaises(Exception):
            f.apply(plan)
        self.assertEqual(before, fingerprint(f.root))

    def test_cli_dry_run_preserves_store_permissions(self):
        f = self.fixture()
        f.store.chmod(0o700)
        before = fingerprint(f.root)
        result = f.cli("prune", "--keep", "3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(f.store.stat().st_mode & 0o777, 0o700)
        self.assertEqual(before, fingerprint(f.root))

    def test_cli_lock_contention_changes_nothing(self):
        import fcntl
        f = self.fixture()
        before = fingerprint(f.root)
        with (f.store / ".release.lock").open("r+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = f.cli("prune", "--keep", "3")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(before, fingerprint(f.root))

    def test_orphan_unresolved_transaction_protects_old_target(self):
        f = self.fixture()
        save(f.tx(7), {"releaseId": rid(7), "status": "switched", "firstMigration": False,
             "newTarget": str(f.views / rid(7) / "site"),
             "previousTarget": str(f.views / rid(2) / "site")})
        plan = f.plan()
        self.assertNotIn(rid(2), candidate_ids(plan))

    def test_partial_unlink_failure_preserves_live_and_rollback(self):
        f = self.fixture(nonlinear=True)
        plan = f.plan()
        protected = f.protected_digest()
        original_unlink = os.unlink
        calls = []

        def fail_after_first(*args, **kwargs):
            calls.append(str(args[0]))
            if len(calls) == 2:
                raise OSError(errno.EIO, "independent QA injected disk I/O failure")
            return original_unlink(*args, **kwargs)

        with patch.object(remote.os, "supports_dir_fd", os.supports_dir_fd | {fail_after_first}), \
                patch.object(remote.os, "unlink", new=fail_after_first):
            try:
                result = f.apply(plan)
            except Exception:
                result = None
        self.assertGreaterEqual(len(calls), 2, "Fault did not reach actual unlink path")
        self.assertEqual(protected, f.protected_digest())
        if result is not None:
            self.assertEqual(result.get("status"), "partial", result)
        fresh = f.plan()
        self.assertNotIn(rid(2), candidate_ids(fresh), "Partially removed release must be retained for examination")
        remote.rollback(rid(6))
        self.assertEqual(f.live.resolve(), f.views / rid(1) / "site")

    def test_external_hardlink_excluded_from_allocated_reclaim(self):
        f = self.fixture()
        target = f.store / rid(2) / "site/index.html"
        before_plan = f.plan()
        blocks = target.stat().st_blocks * 512
        external = f.root / "external-index.html"
        raw = target.read_bytes()
        os.link(target, external)
        plan = f.plan()
        self.assertEqual(before_plan["estimate"]["reclaimableAllocatedBytes"] -
                         plan["estimate"]["reclaimableAllocatedBytes"], blocks)
        # Independently enumerate actual candidate filesystem aliases.
        by_inode = {}
        for candidate in plan["candidates"]:
            for root in candidate["paths"]:
                for parent, dirs, files in os.walk(root, followlinks=False):
                    for name in files:
                        info = (Path(parent) / name).lstat()
                        if stat.S_ISREG(info.st_mode):
                            row = by_inode.setdefault((info.st_dev, info.st_ino), [info, 0])
                            row[1] += 1
        expected = sum(s.st_blocks * 512 for s, aliases in by_inode.values() if aliases == s.st_nlink)
        self.assertEqual(plan["estimate"]["reclaimableAllocatedBytes"], expected)
        self.assertGreater(plan["estimate"]["retainedLinkedInodes"], 0)
        f.apply(plan)
        self.assertEqual(external.read_bytes(), raw)
        self.assertEqual(external.stat().st_nlink, 1)

    def test_identical_bytes_different_inodes_remain_distinct(self):
        f = self.fixture()
        first = f.store / rid(1) / "site/favicon.ico"
        second = f.store / rid(2) / "site/favicon.ico"
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertNotEqual(first.stat().st_ino, second.stat().st_ino)
        p1 = f.plan()
        external = f.root / "retained-icon.ico"
        os.link(first, external)
        p2 = f.plan()
        self.assertEqual(p1["estimate"]["reclaimableAllocatedBytes"] - p2["estimate"]["reclaimableAllocatedBytes"],
                         first.stat().st_blocks * 512)
        self.assertGreaterEqual(p2["estimate"]["reclaimableAllocatedBytes"], second.stat().st_blocks * 512)

    def test_mid_delete_directory_symlink_substitution_cannot_reach_live(self):
        f = self.fixture(nonlinear=True)
        plan = f.plan()
        protected = f.protected_digest()
        target = f.store / rid(2) / "site"
        moved = f.root / "site-moved-during-open"
        original_open = os.open
        injected = []

        def switch_before_open(path, flags, *args, **kwargs):
            if path == "site" and kwargs.get("dir_fd") is not None and not injected:
                injected.append(True)
                target.rename(moved)
                target.symlink_to(f.live.resolve(), target_is_directory=True)
            return original_open(path, flags, *args, **kwargs)

        with patch.object(remote.os, "open", new=switch_before_open):
            result = f.apply(plan)
        self.assertTrue(injected, "Fault must reach descriptor-relative candidate directory open")
        self.assertEqual(result["status"], "partial", result)
        self.assertEqual(protected, f.protected_digest())
        self.assertTrue(target.is_symlink())

    def test_missing_live_payload_blocks_apply(self):
        f = self.fixture()
        (f.live / "index.html").unlink()
        plan = f.plan()
        self.assertTrue(plan["blockers"], "An existing directory is not proof of a valid LIVE release")
        before = fingerprint(f.root)
        with self.assertRaises(Exception):
            f.apply(plan)
        self.assertEqual(before, fingerprint(f.root))

    def test_missing_rollback_payload_blocks_apply(self):
        f = self.fixture(nonlinear=True)
        (f.views / rid(1) / "site/index.html").unlink()
        plan = f.plan()
        self.assertTrue(plan["blockers"], "An existing directory is not proof of a viable rollback")
        before = fingerprint(f.root)
        with self.assertRaises(Exception):
            f.apply(plan)
        self.assertEqual(before, fingerprint(f.root))

    def test_damaged_newer_releases_do_not_displace_three_complete_keepers(self):
        f = self.fixture(nonlinear=True)
        for n in (4, 5):
            (f.views / rid(n) / "site/index.html").unlink()
        plan = f.plan()
        self.assertFalse(plan["blockers"], plan["blockers"])
        for n in (1, 2, 3, 6):
            self.assertNotIn(rid(n), candidate_ids(plan))
        for n in (2, 3, 6):
            self.assertIn(rid(n), plan["protected"], "keep3 must count three complete successful releases")

    def test_completed_apply_requires_fresh_plan_for_retry(self):
        f = self.fixture()
        plan = f.plan()
        result = f.apply(plan)
        self.assertEqual(result["status"], "applied", result)
        before = fingerprint(f.root)
        with self.assertRaises(Exception):
            f.apply(plan)
        self.assertEqual(before, fingerprint(f.root))
        fresh = f.plan()
        self.assertEqual(fresh["candidates"], [])
        self.assertFalse(fresh["blockers"], fresh["blockers"])


def main():
    global ARGS, ROOT, remote, common
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    ARGS = parser.parse_args()
    if sys.platform != "linux":
        raise SystemExit("Linux required: no Windows results may be represented as Linux deletion/locking QA")
    candidate = ARGS.candidate.resolve(strict=True)
    if not (candidate / "release_remote.py").is_file() or not (candidate / "release_common.py").is_file():
        raise SystemExit("Candidate must point to the reviewed isolated scripts directory")
    ROOT = Path(tempfile.mkdtemp(prefix="atlas-prune-independent-qa-", dir="/tmp"))
    sys.path.insert(0, str(candidate))
    remote = importlib.import_module("release_remote")
    common = importlib.import_module("release_common")
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PruneTests))
    report = {"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "passed": result.wasSuccessful(), "fixtureRoot": str(ROOT), "networkUsed": bool(LOOPBACK_REQUESTS),
              "networkScope": "loopbackOnly", "externalNetworkUsed": False,
              "loopbackHTTP": LOOPBACK_REQUESTS,
              "productionPathsUsed": False, "platform": sys.platform,
              "sourceHashes": {name: hashlib.sha256((candidate / name).read_bytes()).hexdigest()
                               for name in ("release_remote.py", "release_common.py", "release_capacity.py")}}
    save(ROOT / "qa-result.json", report)
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
