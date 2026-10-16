"""Restore only the exact runtime files recorded by this code snapshot."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def target_path(name):
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name:
        raise ValueError('Unsafe archive path')
    target = ROOT.joinpath(*relative.parts)
    if not target.resolve().is_relative_to(ROOT):
        raise ValueError('Target escapes repository')
    for parent in (target, *target.parents):
        if parent == ROOT.parent:
            break
        if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
            raise ValueError('Linked destination is forbidden')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    manifest = json.loads((ROOT/'docs/runtime-data-manifest.json').read_text(encoding='utf-8'))
    entries = {row['path']: row for row in manifest['files']}
    if len(entries) != len(manifest['files']):
        raise ValueError('Duplicate manifest file')
    with zipfile.ZipFile(args.archive) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(entries):
            raise ValueError('Archive file set differs from this snapshot')
        # Verify the entire input before writing any file. Existing different data
        # is never overwritten; restore into a clean clone instead.
        for name, row in entries.items():
            destination = target_path(name)
            info = archive.getinfo(name)
            if info.file_size != row['bytes']:
                raise ValueError('Length mismatch: ' + name)
            data = archive.read(name)
            if hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError('Checksum mismatch: ' + name)
            if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() != row['sha256']:
                raise ValueError('Different local data preserved: ' + name)
        if not args.check_only:
            for name in entries:
                destination = target_path(name)
                if not destination.exists():
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    temporary = None
                    try:
                        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.restore-', delete=False) as stream:
                            temporary = Path(stream.name)
                            stream.write(archive.read(name))
                            stream.flush()
                            os.fsync(stream.fileno())
                        if hashlib.sha256(temporary.read_bytes()).hexdigest() != entries[name]['sha256']:
                            raise ValueError('Staged file checksum mismatch: ' + name)
                        # Same-volume hard link publishes a complete file and fails
                        # if another process already created the destination.
                        try:
                            os.link(temporary, destination)
                        except FileExistsError:
                            if hashlib.sha256(destination.read_bytes()).hexdigest() != entries[name]['sha256']:
                                raise ValueError('Concurrent local data preserved: ' + name)
                    finally:
                        if temporary is not None:
                            temporary.unlink(missing_ok=True)
    print(json.dumps({'status': 'verified' if args.check_only else 'restored',
                      'files': len(entries), 'companySnapshot': manifest['companySnapshot'],
                      'companyCount': manifest['companyCount']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
