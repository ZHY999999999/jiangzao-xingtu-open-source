"""Read-only assembly gate. Selection is not approval; no deployment or writes."""
import sys
sys.dont_write_bytecode = True
from pathlib import Path
import json
import re
import os
import argparse
import uuid

VENDORED = Path(__file__).absolute().parent / 'content_approval'
PUBLICATION = VENDORED / 'publication'
if os.environ.get('ATLAS_APPROVAL_MODE', 'live') == 'live' and os.environ.get('ATLAS_CONTENT_PILOT'):
    # Keep the original checker trust root. Only load the explicit live pilot if
    # every supporting implementation is byte-identical to the reviewed copy.
    live_root = Path(os.environ['ATLAS_CONTENT_PILOT']).absolute()
    for name in ('package_check.py','build_candidate.py','queue_controller.py','publication/preflight.py',
                 'publication/approval_chain.py','publication/project_content.py','publication/projection_storage.py'):
        if (live_root / name).read_bytes() != (VENDORED / name).read_bytes():
            raise ValueError('Live approval implementation differs from reviewed source: ' + name)
    PUBLICATION = live_root / 'publication'
sys.path.insert(0, str(PUBLICATION))
import project_content as projection
chain = projection.chain
APP = Path(__file__).absolute().parents[1]
CODE = re.compile(r"\d{6}\.(?:SH|SZ|BJ)\Z")
ROOT_FILES = ("index.html", "vite.config.ts", "package.json", "package-lock.json", "release-history.json",
              "tsconfig.json", "tsconfig.app.json", "tsconfig.node.json", "content-selection.json")


def need(ok, message):
    if not ok:
        raise ValueError(message)


def read(path):
    return chain.read_file(path)


def parsed(path):
    return chain.checker.parse_json(read(path), str(path.name))


REVIEW_SCOPE_FIELDS = {'reviewScope', 'contentSampled', 'browserObserved', 'batchId',
                      'batchEnvelopeSha256', 'batchReviewSha256', 'batchPageReviewSha256'}


def review_metadata(value):
    """Public identity from a verified adoption, never an approval substitute."""
    scope = {key: value[key] for key in REVIEW_SCOPE_FIELDS if key in value}
    if not scope:
        return {}  # Preserve existing individual-review catalogue bytes.
    individual = {'reviewScope', 'contentSampled', 'browserObserved'}
    if scope.get('reviewScope') == 'individual':
        need(set(scope) == individual and scope['contentSampled'] is True
             and scope['browserObserved'] is True, 'Invalid individual review scope')
    else:
        need(scope.get('reviewScope') == 'sampled_batch' and set(scope) == REVIEW_SCOPE_FIELDS,
             'Incomplete or unknown batch review scope')
        need(type(scope['contentSampled']) is bool and type(scope['browserObserved']) is bool,
             'Review sampling flags must be booleans')
        need(isinstance(scope['batchId'], str) and str(uuid.UUID(scope['batchId'])) == scope['batchId'],
             'Invalid batch identity')
        for key in ('batchEnvelopeSha256', 'batchReviewSha256', 'batchPageReviewSha256'):
            chain.guard.valid_digest(scope[key], key)
    return scope


def app_inputs(app, public_root=None):
    result = {name: chain.sha(read(app / name)) for name in ROOT_FILES}
    for folder in ("src", "content", "scripts"):
        tree, _ = chain.guard.snapshot_tree(app / folder)
        for key in tree:
            parts = [part.casefold() for part in Path(key).parts]
            need('__pycache__' not in parts and Path(key).suffix.casefold() not in {'.pyc', '.pyo'},
                 'Generated Python cache is not a source input: ' + folder + '/' + key)
        result.update({folder + "/" + key: value for key, value in tree.items()})
    tree, _ = chain.guard.snapshot_tree(public_root if public_root is not None else app / "public")
    result.update({"public/" + key: value for key, value in tree.items()})
    if (app / 'content-approval-snapshot.json').exists():
        result['content-approval-snapshot.json'] = chain.sha(read(app / 'content-approval-snapshot.json'))
    return dict(sorted(result.items()))


def approved_projection(root, app, choice, current):
    code = current['code']
    bodies = projection.read_bound(root, current)
    docs = {n: chain.checker.parse_json(raw, n) for n, raw in bodies.items()}
    projected, fields = projection.project_values(docs, current)
    projection.verify_projection(projected, fields, docs, current, root)
    expected_raw = projection.encoded(projected)
    need(read(app / choice["path"]) == expected_raw, "Selected public JSON differs from currently approved text")
    directory = root / "publication/projections" / code / current["manifestSha256"]
    tree, _ = chain.guard.snapshot_tree(directory)
    need(set(tree) == {"content.json", "mapping.json"}, "Projection pair missing or has extra files")
    need(read(directory / "content.json") == expected_raw, "Projection content differs")
    mapping = parsed(directory / "mapping.json")
    need(mapping.get("schema") == "atlas-company-content-mapping" and mapping.get("schemaVersion") == 1
         and mapping.get("code") == code and mapping.get("bundlePath") == current["bundlePath"]
         and mapping.get("manifestSha256") == current["manifestSha256"] and mapping.get("readySha256") == current["readySha256"]
         and mapping.get("acceptedInputHashes") == current["inputHashes"] and mapping.get("fields") == fields
         and mapping.get("output") == {"path": "content.json", "schema": projected["schema"], "sha256": choice["sha256"]},
         "Projection mapping does not bind this current adoption")
    return {'code': code, 'selectedInput': current, 'projectionHashes': tree}


def verify(root, app, legacy_root, public_root=None):
    """Explicit paths are for isolated tests; CLI uses only fixed sibling paths."""
    capture = lambda: app_inputs(app) if public_root is None else app_inputs(app, public_root)
    public = public_root if public_root is not None else app / "public"
    before = capture()
    selection = parsed(app / "content-selection.json")
    need(set(selection) in ({"schemaVersion", "indexSha256", "legacy", "sevenQuestions"}, {"schemaVersion", "indexSha256", "legacy", "sevenQuestions", "overviews"})
         and selection["schemaVersion"] == 1, "Invalid selection; it cannot declare approval")
    index_raw = read(public / "data/companies/index.json")
    need(chain.sha(index_raw) == selection["indexSha256"], "Selected index hash differs")
    index = chain.checker.parse_json(index_raw, "company index")
    need(index.get("schemaVersion") == 1 and isinstance(index.get("companies"), list)
         and re.fullmatch(r"[\w-]+", index.get("snapshotId", "")), "Invalid company index")
    companies = {}
    for row in index["companies"]:
        need(isinstance(row, dict) and CODE.fullmatch(row.get("code", ""))
             and isinstance(row.get("name"), str) and row["name"].strip()
             and row["code"] not in companies, "Invalid or duplicate company identity")
        companies[row["code"]] = row["name"]
    need(index["coverage"]["total"] == len(companies), "Index count differs from its company set")
    financial_history = index["coverage"].get("financialHistory")
    need(type(financial_history) is int and 0 <= financial_history <= len(companies),
         "Invalid financial-history coverage count")
    selected, documents = {}, {}
    for kind, folder in (("legacy", "company-editorial"), ("sevenQuestions", "company-seven-questions")):
        rows = selection[kind]
        need(isinstance(rows, list), "Selection must be a list")
        expected = set()
        for row in rows:
            need(isinstance(row, dict) and set(row) == {"code", "sha256"}
                 and CODE.fullmatch(row.get("code", "")), "Invalid selected company")
            code = row["code"]
            chain.guard.valid_digest(row["sha256"], "selected content")
            need(code not in selected, "Duplicate or mixed legacy/seven-question company")
            path = f"content/{folder}/{code}.json"
            need(before.get(path) == row["sha256"], "Selected content is missing or changed: " + code)
            item = parsed(app / path)
            need(item.get("code") == code and item.get("name") == companies.get(code), "Content/index identity differs")
            need(all(isinstance(item.get(k), str) and item[k].strip() for k in ("name", "tagline")), "Content headline is invalid")
            selected[code] = {"kind": kind, "path": path, "sha256": row["sha256"]}
            documents[code] = item
            expected.add(code + ".json")
        folder_path = app / 'content' / folder
        actual = chain.guard.snapshot_tree(folder_path)[0] if folder_path.exists() else {}
        need(set(actual) == expected, "Actual module set differs from exact content selection")

    codes = sorted(c for c, row in selected.items() if row["kind"] == "sevenQuestions")
    accepted = chain.check_selection(root, codes, shared_observation=True) if codes else None
    if codes:
        need(accepted["status"] == "verified_for_conversion_inputs", "Current approval rejected: " + json.dumps(accepted["errors"]))
    entries, adoption = [], []
    legacy_inputs = {}
    for code in sorted(selected):
        choice, item = selected[code], documents[code]
        if choice["kind"] == "legacy":
            baseline_raw = read(legacy_root / choice["path"])
            legacy_inputs[choice["path"]] = chain.sha(baseline_raw)
            need(legacy_inputs[choice["path"]] == choice["sha256"], "Legacy content differs from frozen baseline")
            need(all(isinstance(item.get(k), list) for k in ("products", "customers", "process", "costs", "sources", "financeNotes", "evidenceGaps"))
                 and isinstance(item.get("revenueMix"), dict)
                 and isinstance(item.get("reportBasis"), str) and isinstance(item.get("createdAt"), str), "Damaged legacy content")
            entry = {"kind": "legacy-editorial", "status": "legacy-content", "createdAt": item["createdAt"],
                     "headline": item.get("readingSummary", {}).get("headline", ""), "reportBasis": item["reportBasis"],
                     "audio": "recording" if item.get("audio", {}).get("url") else "script" if item.get("audio", {}).get("transcript") else "none",
                     "gaps": len(item["evidenceGaps"]), "durationSeconds": item.get("audio", {}).get("durationSeconds")}
        else:
            current = next(x for x in accepted["acceptedInputs"] if x["code"] == code)
            adoption.append(approved_projection(root, app, choice, current))
            entry = {"kind": "seven-questions", "status": "release-reviewed-seven", "asOf": item["asOf"],
                     "headline": "", "reportBasis": "资料截止 " + item["asOf"], "audio": "script"}
        entries.append({"code": code, "name": item["name"], "tagline": item["tagline"], "contentSha256": choice["sha256"], **entry})
    overview_choices, overview_documents = {}, {}
    need(isinstance(selection.get('overviews', []), list), 'Overview selection must be a list')
    for row in selection.get('overviews', []):
        need(isinstance(row, dict) and set(row) == {'code', 'sha256'} and CODE.fullmatch(row.get('code', '')),
             'Invalid selected overview')
        code = row['code']; chain.guard.valid_digest(row['sha256'], 'selected overview')
        need(code not in overview_choices, 'Duplicate overview company')
        path = f'content/company-overview/{code}.json'
        need(before.get(path) == row['sha256'], 'Selected overview is missing or changed: ' + code)
        item = parsed(app / path)
        need(item.get('code') == code and item.get('name') == companies.get(code), 'Overview/index identity differs')
        need(item.get('schema') == 'atlas-company-overview' and item.get('contentTier') == 'L', 'Selected overview has wrong tier')
        overview_choices[code] = {'path': path, 'sha256': row['sha256']}
        overview_documents[code] = item
    overview_path = app / 'content/company-overview'
    overview_tree = chain.guard.snapshot_tree(overview_path)[0] if overview_path.exists() else {}
    need(overview_tree == {c + '.json': v['sha256'] for c, v in overview_choices.items()},
         'Actual overview module set differs from exact content selection')
    overview_codes = sorted(overview_choices)
    overview_accepted = chain.check_selection(root, overview_codes, 'L', shared_observation=True) if overview_codes else None
    overview_adoption = []
    if overview_codes:
        need(overview_accepted['status'] == 'verified_for_conversion_inputs',
             'Current overview approval rejected: ' + json.dumps(overview_accepted['errors']))
        by_code = {entry['code']: entry for entry in entries}
        for code in overview_codes:
            choice, item = overview_choices[code], overview_documents[code]
            current = next(x for x in overview_accepted['acceptedInputs'] if x['code'] == code)
            overview_adoption.append(approved_projection(root, app, choice, current))
            metadata = {'asOf': item['asOf'], 'contentSha256': choice['sha256'], 'tagline': item['tagline'],
                        **review_metadata(current)}
            if code not in by_code:
                by_code[code] = {'code': code, 'name': item['name'], 'tagline': item['tagline'],
                    'contentSha256': choice['sha256'], 'kind': 'business-overview',
                    'status': 'release-reviewed-overview', 'asOf': item['asOf'],
                    'headline': '', 'reportBasis': '资料截止 ' + item['asOf'], 'audio': 'none'}
            by_code[code]['overview'] = metadata
        entries = [by_code[code] for code in sorted(by_code)]
    public = {"schemaVersion": 1, "index": {"sha256": selection["indexSha256"], "snapshotId": index["snapshotId"], "asOf": index["asOf"]},
              "counts": {"readable": len(entries), "legacy": len(selection["legacy"]), "reviewedSeven": len(codes)},
              "coverage": {"total": len(companies), "financialHistory": index["coverage"]["financialHistory"]}, "entries": entries}
    if 'overviews' in selection:
        public['counts']['reviewedOverview'] = len(overview_codes)
    public["catalogueSha256"] = chain.sha(chain.canonical(public))
    if codes:
        # Same-operation proof only: re-read current controls, all bytes and directory shapes.
        chain.checkpoint_selection(root, accepted, codes)
        for entry in adoption:
            directory = root / "publication/projections" / entry["code"] / entry["selectedInput"]["manifestSha256"]
            need(chain.guard.snapshot_tree(directory)[0] == entry["projectionHashes"], "Projection changed during assembly")
    if overview_codes:
        chain.checkpoint_selection(root, overview_accepted, overview_codes, 'L')
        for entry in overview_adoption:
            directory = root / 'publication/projections' / entry['code'] / entry['selectedInput']['manifestSha256']
            need(chain.guard.snapshot_tree(directory)[0] == entry['projectionHashes'], 'Overview projection changed during assembly')
    need(before == capture(), "Application inputs changed during assembly")
    for path, sha in legacy_inputs.items():
        need(chain.sha(read(legacy_root / path)) == sha, "Frozen legacy changed during assembly")
    tools = {p.name: chain.sha(read(p)) for p in [Path(__file__), Path(projection.__file__)]}
    return {"status": "verified_local_assembly_inputs", "noDeploy": True, "readyForPublication": False,
            "catalogue": public, "applicationInputs": before, "legacyInputs": legacy_inputs,
            "approvalBindingId": accepted["bindingId"] if accepted else None,
            "approvalToolHashes": accepted["toolHashes"] if accepted else chain.tool_hashes(),
            "toolHashes": tools, "adoptions": adoption,
            **({'overviewAdoptions': overview_adoption,
                'overviewApprovalBindingId': overview_accepted['bindingId'] if overview_accepted else None} if 'overviews' in selection else {})}


def public_snapshot(result, selection):
    """Public immutable identity only. Never a current production approval."""
    result = {'schemaVersion': 1, 'purpose': 'reproduce-recorded-content-only-not-current-approval',
        'selection': selection, 'catalogue': result['catalogue'],
        'approvedSeven': [{'code': row['code'], 'manifestSha256': row['selectedInput']['manifestSha256'],
                          'contentSha256': row['projectionHashes']['content.json']} for row in result['adoptions']],
        **({'approvedOverview': [{'code': row['code'], 'manifestSha256': row['selectedInput']['manifestSha256'],
                                 'contentSha256': row['projectionHashes']['content.json'],
                                 **review_metadata(row['selectedInput'])}
                                for row in result['overviewAdoptions']]} if 'overviews' in selection else {})}
    return result


def verify_snapshot(app, public_root):
    """Reconstruct recorded public bytes. No private approval can be inferred."""
    before = app_inputs(app, public_root)
    snapshot = parsed(app / 'content-approval-snapshot.json')
    fields = {'schemaVersion', 'purpose', 'selection', 'catalogue', 'approvedSeven'}
    need(set(snapshot) in (fields, fields | {'approvedOverview'}) and snapshot['schemaVersion'] == 1
         and snapshot['purpose'] == 'reproduce-recorded-content-only-not-current-approval', 'Invalid public snapshot')
    selection = parsed(app / 'content-selection.json')
    selection_fields = {'schemaVersion', 'indexSha256', 'legacy', 'sevenQuestions'}
    need(set(selection) in (selection_fields, selection_fields | {'overviews'}) and selection['schemaVersion'] == 1,
         'Invalid recorded selection')
    need(selection == snapshot['selection'], 'Public snapshot selection changed')
    need(('overviews' in selection) == ('approvedOverview' in snapshot), 'Overview snapshot identity missing')
    index_raw = read(public_root / 'data/companies/index.json')
    need(chain.sha(index_raw) == selection['indexSha256'], 'Restored company index differs from recorded content')
    index = chain.checker.parse_json(index_raw, 'index')
    catalogue = snapshot['catalogue']
    digest = dict(catalogue); expected = digest.pop('catalogueSha256')
    need(chain.sha(chain.canonical(digest)) == expected, 'Public catalogue digest differs')
    need(catalogue['index'] == {'sha256': selection['indexSha256'], 'snapshotId': index['snapshotId'], 'asOf': index['asOf']},
         'Public catalogue index differs')
    chosen, modules = {}, {}
    for kind, folder in (('legacy', 'company-editorial'), ('sevenQuestions', 'company-seven-questions'), ('overviews', 'company-overview')):
        rows = selection.get(kind, [])
        need(isinstance(rows, list), 'Invalid recorded selection list')
        group = {}
        for row in rows:
            need(set(row) == {'code', 'sha256'} and CODE.fullmatch(row.get('code', '')) and row['code'] not in group,
                 'Duplicated or invalid recorded content')
            chain.guard.valid_digest(row['sha256'], 'recorded content')
            group[row['code']] = row['sha256']
        chosen[kind] = group
        directory = app / 'content' / folder
        files = chain.guard.snapshot_tree(directory)[0] if directory.exists() else {}
        need(files == {code + '.json': digest for code, digest in group.items()}, 'Public content bytes or file set changed')
        for code in group:
            modules[(kind, code)] = parsed(directory / (code + '.json'))
    need(not set(chosen['legacy']) & set(chosen['sevenQuestions']), 'Duplicated public content')
    overview_scopes = {}
    for key, label in (('sevenQuestions', 'approvedSeven'), ('overviews', 'approvedOverview')):
        if key not in selection: continue
        approved = snapshot[label]
        need(isinstance(approved, list) and all(isinstance(row, dict) for row in approved)
             and [row.get('code') for row in approved] == sorted(chosen[key]), 'Invalid recorded adoption identity')
        for row in approved:
            scope = review_metadata(row) if key == 'overviews' else {}
            need(set(row) == {'code', 'manifestSha256', 'contentSha256'} | set(scope)
                 and isinstance(row['manifestSha256'], str) and re.fullmatch(r'[a-f0-9]{64}', row['manifestSha256'])
                 and row['contentSha256'] == chosen[key][row['code']], 'Invalid recorded adoption identity')
            if key == 'overviews': overview_scopes[row['code']] = scope
    codes = set().union(*[set(group) for group in chosen.values()])
    entries = catalogue['entries']
    need([row['code'] for row in entries] == sorted(codes), 'Public catalogue entries differ')
    for entry in entries:
        need(not REVIEW_SCOPE_FIELDS.intersection(entry), 'Review scope belongs to overview metadata')
        code = entry['code']
        kind = 'legacy' if code in chosen['legacy'] else 'sevenQuestions' if code in chosen['sevenQuestions'] else 'overviews'
        item = modules[(kind, code)]
        need(entry['contentSha256'] == chosen[kind][code] and entry['name'] == item['name'] and entry['tagline'] == item['tagline'],
             'Public headline/content binding differs')
        expected_kind = {'legacy':'legacy-editorial', 'sevenQuestions':'seven-questions', 'overviews':'business-overview'}[kind]
        need(entry['kind'] == expected_kind, 'Recorded tier classification differs')
        if code in chosen['overviews']:
            overview = modules[('overviews', code)]
            need(entry.get('overview') == {'asOf':overview['asOf'], 'contentSha256':chosen['overviews'][code],
                                          'tagline':overview['tagline'], **overview_scopes[code]},
                 'Recorded overview binding differs')
        else:
            need('overview' not in entry, 'Unexpected overview metadata')
    counts = {'readable':len(codes), 'legacy':len(chosen['legacy']), 'reviewedSeven':len(chosen['sevenQuestions'])}
    if 'overviews' in selection: counts['reviewedOverview'] = len(chosen['overviews'])
    need(catalogue['counts'] == counts, 'Recorded counts differ')
    need(catalogue['coverage'] == {'total':len(index['companies']), 'financialHistory':index['coverage']['financialHistory']}, 'Recorded coverage differs')
    need(before == app_inputs(app, public_root), 'Inputs changed during snapshot reconstruction')
    return {'status':'verified_local_assembly_inputs', 'approvalMode':'public-snapshot', 'noDeploy':True,
            'readyForPublication':False, 'catalogue':catalogue, 'applicationInputs':before,
            'approvalBindingId':None, 'approvalToolHashes':{}, 'toolHashes':{}, 'adoptions':[], 'legacyInputs':{},
            **({'overviewAdoptions':[], 'overviewApprovalBindingId':None} if 'overviews' in selection else {})}


def main():
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--write-public-snapshot', action='store_true', help='Requires the live current approval chain; never accepts snapshot replay')
        args = parser.parse_args()
        public_root = Path(os.environ.get('ATLAS_PUBLIC_ROOT', str(APP / 'public'))).absolute()
        mode = os.environ.get('ATLAS_APPROVAL_MODE', 'live')
        need(mode in {'live', 'snapshot'}, 'Unknown approval mode')
        if mode == 'snapshot':
            need(not args.write_public_snapshot, 'A reconstruction cannot create approved snapshots')
            result = verify_snapshot(APP, public_root)
        else:
            need(bool(os.environ.get('ATLAS_CONTENT_PILOT')), 'Live approval requires ATLAS_CONTENT_PILOT; use explicit snapshot mode only for reconstruction')
            root = Path(os.environ['ATLAS_CONTENT_PILOT']).absolute()
            legacy_root = Path(os.environ.get('ATLAS_LEGACY_ROOT', str(root / 'publication/baseline-rebuild/app'))).absolute()
            result = verify(root, APP, legacy_root, public_root)
            result['approvalMode'] = 'live-current'
            snapshot = public_snapshot(result, parsed(APP / 'content-selection.json'))
            if args.write_public_snapshot:
                destination = APP / 'content-approval-snapshot.json'
                raw = (json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
                if destination.exists(): need(read(destination) == raw, 'Existing public snapshot differs; create a separately reviewed version')
                else: destination.write_bytes(raw)
                result = {'status':'public_snapshot_written_from_current_approval', 'path':str(destination), 'sha256':chain.sha(raw), 'noDeploy':True}
            else:
                need(parsed(APP / 'content-approval-snapshot.json') == snapshot, 'Public snapshot differs from current approvals')
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"status": "rejected", "noDeploy": True, "readyForPublication": False, "error": str(error)}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
