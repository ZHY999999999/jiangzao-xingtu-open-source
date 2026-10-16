"""Exact public-code export, including independently reviewed company layers.

Runtime data, private approval/source records and credentials are excluded. This
does not approve changed content, create runtime data or publish anything.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'docs/source-export-manifest.json'
ROOT_FILES = {'.gitattributes','.gitignore','AGENTS.md','README.md'}
APP_FILES = {'index.html','package.json','package-lock.json','release-history.json', 'vite.config.ts',
             'tsconfig.json','tsconfig.app.json','tsconfig.node.json','content-selection.json','content-approval-snapshot.json'}
CODE_SUFFIX = {'.ts','.tsx','.js','.mjs','.py','.ps1','.css','.json','.md','.txt','.yml','.yaml'}


def sha(raw): return hashlib.sha256(raw).hexdigest()


def is_link(path):
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def children(folder):
    if not folder.is_dir() or is_link(folder):
        raise ValueError('Missing or linked source folder: ' + str(folder.relative_to(ROOT)))
    for path in sorted(folder.iterdir()):
        if is_link(path): raise ValueError('Linked source forbidden: ' + str(path.relative_to(ROOT)))
        if path.name in {'__pycache__','ce'}: continue
        if path.is_dir(): yield from children(path)
        elif path.is_file(): yield path
        else: raise ValueError('Special source entry forbidden')


def inputs():
    runtime = {row['path'] for row in json.loads((ROOT/'docs/runtime-data-manifest.json').read_bytes())['files']}
    files = [ROOT/name for name in ROOT_FILES] + [ROOT/'app'/name for name in APP_FILES]
    for folder in ('app/src','app/scripts','scripts','.github','docs'):
        for path in children(ROOT/folder):
            name = path.relative_to(ROOT).as_posix()
            if path == MANIFEST or name in runtime: continue
            if path.suffix in CODE_SUFFIX or (folder == 'docs' and path.suffix == '.png'):
                files.append(path)
    for folder in ('company-editorial','company-seven-questions'):
        files += [p for p in children(ROOT/'app/content'/folder) if p.suffix == '.json']
    overview_folder = ROOT/'app/content/company-overview'
    selection = json.loads((ROOT/'app/content-selection.json').read_bytes())
    if overview_folder.exists() or selection.get('overviews'):
        files += [p for p in children(overview_folder) if p.suffix == '.json']
    # Public product resources already approved in the repository; never public/data.
    for folder in ('audio','images','fonts'):
        files += list(children(ROOT/'app/public'/folder))
    files.append(ROOT/'app/public/favicon.ico')
    result = {}
    for path in files:
        if not path.is_file() or is_link(path): raise ValueError('Missing/linked export input: '+str(path))
        name = path.relative_to(ROOT).as_posix()
        if name in runtime: raise ValueError('Runtime data entered source export: '+name)
        if name in result: raise ValueError('Duplicate source export entry: '+name)
        raw = path.read_bytes()
        result[name] = {'path':name,'sourceSha256':sha(raw),'sha256':sha(raw),'bytes':len(raw),'transforms':[]}
    return {name:result[name] for name in sorted(result)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-manifest',action='store_true')
    parser.add_argument('--verify',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if not any((args.write_manifest,args.verify,args.output)): parser.error('Choose --write-manifest, --verify or --output')
    actual=inputs()
    value={'schemaVersion':1,'files':list(actual.values())}
    if args.write_manifest:
        MANIFEST.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    expected=json.loads(MANIFEST.read_bytes())
    if expected != value: raise ValueError('Public source export manifest is stale; review source changes before refreshing it')
    if args.output:
        target=args.output.resolve()
        if target.exists(): raise ValueError('Export destination exists; preserve it')
        if target.is_relative_to(ROOT): raise ValueError('Export must be outside the source repository')
        target.mkdir(parents=True)
        for name in actual:
            destination=target/name;destination.parent.mkdir(parents=True,exist_ok=True)
            raw=(ROOT/name).read_bytes()
            if sha(raw)!=actual[name]['sha256']: raise ValueError('Source changed while exporting')
            destination.write_bytes(raw)
        (target/'docs/source-export-manifest.json').write_bytes(MANIFEST.read_bytes())
        if inputs()!=actual: raise ValueError('Source changed during export')
    print(json.dumps({'status':'public_source_manifest_verified','files':len(actual),
                      'manifestSha256':sha(MANIFEST.read_bytes()),'exported':bool(args.output),'published':False}))


if __name__=='__main__': main()
