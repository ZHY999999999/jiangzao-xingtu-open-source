#!/usr/bin/env python3
"""NEW FILE for app/scripts/ - attach matched original filings to a company dossier.

This module is additive: it does not touch company_data.py's calculations. It runs
after build_dossier() has produced a dossier and rewrites only the *provenance*
layer, so amounts, nulls, periods, units, quarterly computability and review flags
are carried through untouched.

Public layer (goes into the shipped dossier):
    sources[]      only original filings (sourceType='filing') and, where a real
                   official page exists, company material. Provider records never
                   appear, and no Tushare name or API URL survives.
    sourceIds      finance points, quarterly points (which reference BOTH cumulative
                   reports they were differenced from) and segment groups are
                   re-pointed at the filing identifiers.
Private layer (returned to the caller, written to a ledger outside the dossier):
    the provider rows, their interface/parameters/batch, the version selection and
    the derivation lineage - so the audit trail is kept without leaking it to the
    reader.

Verification levels are preserved verbatim:
    level 2 = document identity and version matched -> the reader gets "read the
              original" together with an explicit note that the numbers were not
              extracted from that PDF;
    level 3 = a specific page was checked against the original.
Anything unmatched keeps its existing text and shows a gap, never a substitute.

------------------------------------------------------------------------------
Evidence degradation (built-in-sources round, defect B4)
------------------------------------------------------------------------------
The first version of this file judged degradation with

    if claim.get('sourceIds'):        # then clear + mark review

*after* the helper `repair()` pass had already emptied every `sourceIds` list that
held a provider reference. The list was therefore always empty by the time it was
tested, the branch never ran, and the dossier ended up with factual assertions
marked `available` and carrying no evidence at all - the "completed but
unsupported" state the audit rejected.

That is fixed here by judging on the *evidence lineage before and after* the
replacement, never on "is the list non-empty":

  * every claim-shaped node (any dict carrying a `sourceIds` list) is recorded
    BEFORE anything is mutated, keyed by a stable structural path;
  * after the replacement the same paths are re-read and each claim is classed by
    whether it ends up with at least one **located** (non-placeholder) source:
        evidence_preserved          at least one real filing still backs it
        newly_lost_evidence         it had evidence, replacement left none
        pre_existing_unsupported    it never had evidence and still has none
        legitimately_no_source      it does not claim support (status not
                                    `available`, or no status field at all)
  * `DEGRADE_PRE_EXISTING` decides whether the pre-existing class is also marked
    `review`. Both classes are always counted and listed separately, with their
    rule, so "what this round caused" is never mixed with "what was already
    unsupported" - the audit's 16,686 stock total must not be attributed to this
    round.
  * narrative / interpretation material (摘要、经营解读、注册与发展事件) may NOT
    borrow the latest annual report as its evidence: outside the structured
    numeric branches (`finance`, `segments`) an unresolvable reference is dropped
    rather than re-pointed, the prose is kept, and the claim is marked review.

A displayed period that no binding matched still resolves - to an explicit gap
object with a machine reason ("原文待补"), never to an empty list. Historical
periods are included: an un-matched displayed history is a stated gap, not a
silence. Nothing here requires the whole history to be filled before the default
window can be repaired.
"""
from collections import defaultdict
import hashlib
import json
import os

SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# One directory contract for the filing release
# ---------------------------------------------------------------------------
# The hand-off describes `catalog/documents.jsonl` at the top of the release, while an
# earlier reader looked for `overlay-sources/*.json`. Those are two different
# contracts and only one can be right, so the layout below IS the contract:
#
#     <release root>/current.json                      -> active version (optional)
#     <release root>/<version>/manifest.json           -> version, hashes, schema
#     <release root>/<version>/catalog/documents.jsonl
#     <release root>/<version>/bindings/bindings.jsonl
#     <release root>/<version>/schema/sources-schema.json
#     <release root>/<version>/matcher.json
#
# `load_release()` resolves the version, re-verifies every manifest hash and reads
# all records from that ONE directory, so the builder, the input fingerprint and the
# release verification cannot drift onto different versions. Nothing degrades
# silently: a missing module, directory, schema or empty catalogue raises.
RELEASE_ARTEFACTS = ('catalog/documents.jsonl', 'bindings/bindings.jsonl',
                     'schema/sources-schema.json', 'matcher.json')


class ReleaseError(ValueError):
    """Raised when the filing release cannot be used as-is."""


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path):
    with open(path, encoding='utf-8') as handle:
        return json.load(handle)


def read_jsonl(path):
    records = []
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def _resolve_release_dir(root):
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise ReleaseError('filing release root does not exist: %s' % root)
    if os.path.exists(os.path.join(root, 'manifest.json')):
        return root
    pointer = os.path.join(root, 'current.json')
    if os.path.exists(pointer):
        try:
            version = _load_json(pointer).get('releaseVersion')
        except ValueError as exc:
            raise ReleaseError('current.json is not readable: %s' % exc) from None
        if not version:
            raise ReleaseError('current.json has no releaseVersion: %s' % pointer)
        name = version.replace('/', '_').replace('+', '_')
        target = os.path.join(root, name)
        if not os.path.isdir(target):
            raise ReleaseError('current.json points at a missing release: %s' % name)
        return target
    raise ReleaseError('no manifest.json and no current.json under %s' % root)


def _release_manifest(release_dir):
    manifest_path = os.path.join(release_dir, 'manifest.json')
    try:
        manifest = _load_json(manifest_path)
    except ValueError as exc:
        raise ReleaseError('manifest.json is not valid JSON: %s' % exc) from None
    if not isinstance(manifest, dict) or not manifest.get('releaseVersion'):
        raise ReleaseError('manifest.json has no releaseVersion: %s' % manifest_path)
    if manifest['releaseVersion'].replace('/', '_').replace('+', '_') != \
            os.path.basename(release_dir):
        raise ReleaseError('manifest releaseVersion does not match its directory: %s'
                           % manifest['releaseVersion'])
    return manifest, manifest_path


def release_identity(root):
    """Cheap identity of the active release: which version the reader would see.

    The input fingerprint needs this on every run, so it deliberately does NOT
    re-hash the artefacts - `load_release()` does that before anything is built.
    """
    release_dir = _resolve_release_dir(root)
    manifest, manifest_path = _release_manifest(release_dir)
    return {'releaseVersion': manifest['releaseVersion'], 'releasePath': release_dir,
            'manifestSha256': _sha256_file(manifest_path),
            'semanticFingerprint': manifest.get('semanticFingerprint'),
            'coverageState': manifest.get('coverageState'),
            'matcherVersion': manifest.get('matcherVersion'),
            'builtAt': manifest.get('builtAt')}


def load_release(root):
    """Read and verify ONE filing release version.

    Returns a dict with the records plus the version identity so the caller can
    record which release a dossier was built from.
    """
    release_dir = _resolve_release_dir(root)
    manifest, manifest_path = _release_manifest(release_dir)
    problems = []
    for relative in RELEASE_ARTEFACTS:
        full = os.path.join(release_dir, relative)
        if not os.path.exists(full):
            problems.append('missing:' + relative)
            continue
        expected = (manifest.get('artefacts') or {}).get(relative, {}).get('sha256')
        if not expected:
            problems.append('unhashed:' + relative)
            continue
        actual = _sha256_file(full)
        if actual != expected:
            problems.append('hash-mismatch:' + relative)
    if problems:
        raise ReleaseError('filing release failed integrity check (%s): %s'
                           % (manifest['releaseVersion'], ', '.join(problems)))

    schema = _load_json(os.path.join(release_dir, 'schema', 'sources-schema.json'))
    if schema.get('schemaVersion') != SCHEMA_VERSION:
        raise ReleaseError('unsupported sources schema %r (expected %d)'
                           % (schema.get('schemaVersion'), SCHEMA_VERSION))

    documents = {record['documentId']: record for record
                 in read_jsonl(os.path.join(release_dir, 'catalog', 'documents.jsonl'))}
    bindings = read_jsonl(os.path.join(release_dir, 'bindings', 'bindings.jsonl'))
    by_target = defaultdict(list)
    for binding in bindings:
        by_target[binding['targetId']].append(binding)
    if not documents or not bindings:
        raise ReleaseError('filing release is empty: %s' % release_dir)
    return {
        'releaseVersion': manifest['releaseVersion'],
        'releasePath': release_dir,
        'series': manifest.get('series'),
        'matcherVersion': manifest.get('matcherVersion'),
        'docTypeVersion': manifest.get('docTypeVersion'),
        'semanticFingerprint': manifest.get('semanticFingerprint'),
        'coverageState': manifest.get('coverageState'),
        'manifestSha256': _sha256_file(manifest_path),
        'documents': documents,
        'bindings': dict(by_target),
        'documentCount': len(documents),
        'bindingCount': len(bindings),
        'targetCount': len(by_target),
    }

# Reader-facing text per machine gap reason.
GAP_BY_REASON = {
    'notice_about_report_only': '该报告期只有关于报告的公告（说明会、提示性公告等），没有报告正文',
    'summary_version_only': '该报告期只有摘要版本，没有报告正文',
    'cancelled_version_only': '该报告期只有已取消版本，没有有效版本',
    'foreign_version_only': '该报告期只有 H 股/外文版本，口径未证明一致，不作为 A 股原文',
    'correction_notice_only': '该报告期只有更正公告，没有可对应的报告正文',
    'no_announcement_for_company_on_these_dates': '该报告期尚未找到对应的原始报告',
    'no_positive_report_candidate': '该报告期只有公告目录候选，报告身份未通过正向判定',
    'non_report_candidate_only': '该期的候选都是摘要、公告一类的非正文文件，没有报告正文',
    'announcement_dates_not_in_cache': '公告日期不在本地公告目录缓存范围内，尚未核对',
    'version_anchor_not_matched': '该报告期有公告候选，但披露日与档案采用的版本不一致，未强行绑定',
    'multiple_distinct_reports_of_the_same_period': '同一报告期存在多份不同文件，无法确定唯一原文',
    'ambiguous_same_title_different_attachment': '同日同标题但附件不同，无法确定唯一原文',
    'no_matching_report_category': '该报告期只有公告目录候选，报告类别未匹配',
    'title_year_does_not_match_period': '公告标题年份与报告期不一致，未强行绑定',
    'target_has_no_announcement_date': '该报告期缺少公告日期，无法定位原文',
    'pre_listing_period': '上市前期间，须以招股说明书或上市公告书为准，尚未补齐',
    'unknown_report_kind': '报告期类型无法判定',
    'comparison_period_announcement_date_unknown': '比较期缺少披露日期，无法定位原文',
    'comparison_period_not_disclosed_in_this_table': '比较期在该数据表中没有已披露行，无法定位原文',
    'comparison_disclosure_after_as_of': '比较期的披露日已超过资料截止日，尚不能作为原文',
    'current_disclosure_after_as_of': '本期披露日已超过资料截止日，尚不能作为原文',
    'not_in_this_rounds_target_scope': '该报告期尚未进入本轮原文匹配范围，已列为待补',
    'unmatched': '原始资料待补',
}

VERSION_RELATION_TEXT = {
    'superseded': '该文件是更新前/更正前的旧版本，已被后续版本取代；如以更新版为准请改看对应文件',
    'revision': '该文件是修订/更正后的版本',
}

# Statuses that already do NOT claim "a locatable source supports this".
NOT_CLAIMING_SUPPORT = ('review', 'partial', 'missing', 'pending', 'unavailable',
                        'not_applicable', 'draft', 'unknown')

# Claim classes of the evidence ledger.
CLASS_PRESERVED = 'evidence_preserved'
CLASS_NEWLY_LOST = 'newly_lost_evidence'
CLASS_PRE_EXISTING = 'pre_existing_unsupported'
CLASS_LEGITIMATE = 'legitimately_no_source'

# See the module docstring. One-line switch if the owner decides that flags which
# were already unsupported before this round must be left exactly as they were.
DEGRADE_PRE_EXISTING = True

# Structure paths whose numeric nodes may re-point a provider reference at the
# period's own filing. Everything else is narrative and must not borrow evidence.
NUMERIC_ROOTS = ('finance', 'segments')

# Narrative sections whose reader-facing coverage flag has to follow the claims.
NARRATIVE_ROOTS = ('summary', 'timeline', 'businessModel', 'competitive', 'risks')

CLASS_RULES = {
    CLASS_PRESERVED: ('替换后仍至少有一条已定位（非占位）的原始报告支持；状态保持不变，'
                      '不因来源返修升级等级。'),
    CLASS_NEWLY_LOST: ('替换前有出处、替换后没有任何已定位来源：本次替换造成证据不足，'
                       'available 一律降为 review，并在资料出处保留明确缺口对象。'),
    CLASS_PRE_EXISTING: ('替换前后都没有出处：属于本轮回填之前就存在的无依据断言，'
                         '本轮不静默改动、但单独计数并列出；由本轮决定是否同样降级。'),
    CLASS_LEGITIMATE: ('本来就不声明需要出处（状态不是 available，或该节点没有状态字段），'
                       '例如纯数值容器与派生结果；不作改动。'),
}


def _report_kind_label(period):
    return {'0331': '一季报', '0630': '中报', '0930': '三季报',
            '1231': '年报'}.get(str(period)[4:], '报告')


def _gap_text(reason):
    return GAP_BY_REASON.get(reason or 'unmatched', GAP_BY_REASON['unmatched'])


def _filing_source(binding, document, as_of):
    level = binding.get('verificationLevel') or 1
    # A located attachment and an accessible URL do not prove the adopted version.
    pending = (level < 2 or bool(binding.get('versionDivergence'))
               or bool(binding.get('gapOrConflictReason')))
    locator_parts = ['%s · 报告期 %s' % (document.get('reportKind'), document.get('reportPeriod'))]
    if document.get('publishDate'):
        locator_parts.append('披露 %s' % document['publishDate'])
    if pending:
        locator_parts.append('报告候选，版本待核；不作为本期数值已获原文支持的证明')
        if binding.get('gapOrConflictReason'):
            locator_parts.append(_gap_text(binding['gapOrConflictReason']))
    elif level == 3 and binding.get('pageSection'):
        locator_parts.append('已核对 %s' % binding['pageSection'])
        locator_parts.append('该处具体数值/语句已与原文核对')
    else:
        locator_parts.append('文档身份与版本已匹配；数值未从该 PDF 逐项提取')
    if binding.get('gapOrConflictReason') == 'matched_outside_dossier_announcement_date':
        locator_parts.append('匹配日期与档案内公告日期相差不少于一天')
    if document.get('versionRelation', '').startswith('correction-of:'):
        locator_parts.append('该文档为更正/补充公告')
    # The version difference must be visible to the reader, not just stored in a field:
    # a pre-update filing and its revised text are different documents, and a target
    # whose adopted disclosure date differs from the selected one must say so.
    relation = VERSION_RELATION_TEXT.get(document.get('versionRelation') or '')
    if relation:
        locator_parts.append(relation)
    divergence = binding.get('versionDivergence') or {}
    if divergence.get('reason') == 'version_date_evidenced':
        locator_parts.append(
            '档案采用的版本日期为 %s，与本文件披露日 %s 不同；本文件是该报告期内唯一通过'
            '身份/报告期/类别判定的报告，差异据此如实记录，不代表版本日期已匹配'
            % (divergence.get('anchor'), divergence.get('selectedDate')))
    url = document.get('finalUrl') or document.get('originalUrl')
    return {
        'id': document['documentId'],          # already namespaced as filing-<hash>
        'title': document.get('title'),
        'url': url,
        'sourceType': 'filing',
        'publishedAt': document.get('publishDate'),
        'asOf': as_of,
        'locator': '；'.join(part for part in locator_parts if part) + '。',
        'document': '',
        'issuer': document.get('issuer'),
        'platform': document.get('platform'),
        'reportPeriod': document.get('reportPeriod'),
        'reportKind': document.get('reportKind'),
        'verificationLevel': level,
        'candidate': pending,
        'gapReason': binding.get('gapOrConflictReason'),
        'versionDivergence': binding.get('versionDivergence'),
        'pageSection': binding.get('pageSection'),
        'verifiedStatement': binding.get('statement') if level == 3 else None,
        'accountingStandard': document.get('accountingStandard'),
        'currency': document.get('currency'),
        'versionRelation': document.get('versionRelation'),
        # Only a linked, actually readable original may be presented as openable.
        # An HTTP 200 that served HTML, or a permanent 404, must not become a
        # button that pretends to be the original.
        'accessStatus': document.get('accessStatus') or 'unchecked',
        'checkedAt': document.get('checkedAt'),
        'available': _link_available(document),
        'pending': pending,
    }


def _link_available(document):
    status = document.get('accessStatus') or 'unchecked'
    if status in ('permanently_unavailable', 'html_instead_of_pdf', 'not_a_pdf',
                  'refused_unsafe_redirect'):
        return False
    return bool(document.get('finalUrl') or document.get('originalUrl'))


def _gap_source(binding, as_of):
    reason = binding.get('gapOrConflictReason') or 'unmatched'
    return {
        'id': 'gap-%s' % binding['targetId'].replace('@', '-'),
        'title': ('%s · %s' % (binding.get('reportKind'), binding.get('period'))),
        'url': None,
        'sourceType': 'filing',
        'asOf': as_of,
        'locator': _gap_text(reason),
        'document': '',
        'reportPeriod': binding.get('period'),
        'reportKind': binding.get('reportKind'),
        'verificationLevel': 1,
        'gapReason': reason,
        'pending': True,
    }


def _pending_source(period, reason, as_of):
    return {
        'id': 'gap-%s-%s' % (period, reason or 'unmatched'),
        'title': '%s · %s' % (_report_kind_label(period), period),
        'url': None,
        'sourceType': 'filing',
        'asOf': as_of,
        'locator': _gap_text(reason),
        'document': '',
        'reportPeriod': period,
        'reportKind': _report_kind_label(period),
        'verificationLevel': 1,
        'gapReason': reason or 'unmatched',
        'pending': True,
    }


PREVIOUS_END = {'0630': '0331', '0930': '0630', '1231': '0930'}


def _claims(node, path=()):
    """Every dict that carries a `sourceIds` list, with a structural path.

    The path is positional, so it stays comparable as long as no list is
    reordered - this module only ever rewrites values in place.
    """
    if isinstance(node, dict):
        if isinstance(node.get('sourceIds'), list):
            yield path, node
        for key, value in node.items():
            if key == 'sourceIds':
                continue
            yield from _claims(value, path + (str(key),))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _claims(item, path + (index,))


def _path_label(path):
    out = ''
    for part in path:
        out += '[%d]' % part if isinstance(part, int) else ('.' + part if out else part)
    return out or 'root'


def _walk_dossier(dossier):
    """Claims of the whole dossier, each path seeded with its top-level key.

    `sources` is skipped: it is the reader-facing source list itself, not a claim.
    """
    for key, value in dossier.items():
        if key == 'sources':
            continue
        yield from _claims(value, (key,))


def apply_filing_sources(dossier, code, catalog, bindings, as_of):
    """Return (dossier, lineage). `catalog` maps documentId -> document record;
    `bindings` maps targetId -> list of binding records for this company."""
    # ---- 1. evidence lineage BEFORE any replacement -------------------------
    before = {}
    for path, node in _walk_dossier(dossier):
        before[path] = {'sourceIds': list(node.get('sourceIds') or []),
                        'status': node.get('status')}

    provider_sources = dossier.get('sources') or []
    lineage = {
        'schemaVersion': SCHEMA_VERSION,
        'code': code,
        'providerSources': provider_sources,
        'providerSourceCount': len(provider_sources),
        'interface': sorted({str(s.get('title', '')).split(' ')[1] for s in provider_sources
                             if str(s.get('title', '')).startswith('Tushare ')
                             and len(str(s.get('title', '')).split(' ')) > 1}),
        'asOf': as_of,
        'note': ('本文件是私有血缘：接口、参数、原始行与版本选择保留在此，'
                 '不进入面向读者的资料出处。'),
    }

    company_bindings = defaultdict(list)
    for target_id, items in bindings.items():
        for item in items:
            if item.get('ts_code') == code:
                company_bindings[target_id].append(item)

    # Comparison-period dependencies recorded by the matcher, per target period and
    # per table: a derived single quarter must point at BOTH cumulative reports it
    # was differenced from, and the pair has to be the pair the numbers came from.
    deps_by_period = defaultdict(list)
    for target_id, items in company_bindings.items():
        period = str(target_id).split('@', 1)[-1]
        for item in items:
            for dep in item.get('dependencies') or []:
                if dep.get('forPeriod'):
                    deps_by_period[period].append(dep)

    sources, by_period, seen_ids, valid, pending_ids = [], {}, set(), set(), set()
    source_by_id = {}

    # Pre-existing filing sources (the two already in the product, plus any that
    # carry page-level evidence) are KEPT: profitReconciliation and other shipped
    # text already reference them, and deleting them would both break those
    # references and destroy existing verified evidence.
    # Copies avoid changing the private pre-replacement evidence list when a new
    # catalog observation refreshes the public source's access state.
    preserved = [dict(s) for s in provider_sources if s.get('sourceType') == 'filing']
    preserved_ids = {s.get('id') for s in preserved if s.get('id')}

    def add(source):
        """One document may legitimately support several periods (a correction can
        cover two, an annual report carries both the annual and the Q4 point), but
        it must still appear ONCE in the source list: validate_dossier rejects
        duplicate ids, and a duplicated entry would also inflate the reader's list."""
        if source['id'] in seen_ids:
            previous = source_by_id[source['id']]
            # Refresh observations and binding status without erasing existing
            # page-level evidence or a manually supplied locator.
            for field in ('accessStatus', 'available', 'checkedAt', 'asOf', 'url',
                          'pending', 'candidate', 'gapReason', 'versionDivergence'):
                if field in source:
                    previous[field] = source[field]
            old_level = previous.get('verificationLevel') or 1
            preserve_content = (old_level >= 3 or bool(previous.get('pageSection'))
                                or bool(previous.get('verifiedStatement'))
                                or bool(previous.get('contentVerificationLocator'))
                                or ('verificationLevel' not in previous
                                    and bool(previous.get('locator'))))
            if preserve_content:
                previous.setdefault('contentVerificationLocator', previous.get('locator'))
                previous['locator'] = '%s；既有内容核验：%s' % (
                    source['locator'], previous.get('contentVerificationLocator') or '')
                if old_level < 3 and 'verificationLevel' in source:
                    previous['verificationLevel'] = source['verificationLevel']
            else:
                for field in ('verificationLevel', 'locator', 'pageSection', 'verifiedStatement'):
                    if field in source:
                        previous[field] = source[field]
            if previous.get('pending'):
                pending_ids.add(source['id'])
            else:
                pending_ids.discard(source['id'])
            return source['id']
        seen_ids.add(source['id'])
        sources.append(source)
        source_by_id[source['id']] = source
        valid.add(source['id'])
        if source.get('pending'):
            pending_ids.add(source['id'])
        return source['id']

    for source in preserved:
        if source.get('id'):
            observed = catalog.get(source['id'])
            if observed:
                source.update(accessStatus=observed.get('accessStatus') or 'unchecked',
                              available=_link_available(observed),
                              checkedAt=observed.get('checkedAt'), asOf=as_of)
            add(source)

    for target_id in sorted(company_bindings):
        items = company_bindings[target_id]
        current = next((i for i in items if i.get('role') == 'current'), None)
        if current and current.get('documentId'):
            document = catalog.get(current['documentId'])
            if document:
                source = _filing_source(current, document, as_of)
                by_period.setdefault(current['period'], {})['current'] = add(source)
        elif current:
            source = _gap_source(current, as_of)
            by_period.setdefault(current.get('period'), {})['gap'] = add(source)
        for extra in items:
            if extra.get('role') == 'correction' and extra.get('documentId'):
                document = catalog.get(extra['documentId'])
                if document:
                    source = _filing_source(extra, document, as_of)
                    by_period.setdefault(extra.get('period'), {})['correction'] = add(source)

    def ensure_period(period, reason='not_in_this_rounds_target_scope'):
        """Resolve a displayed period to a source id, creating an explicit gap
        object when nothing matched. A displayed period never resolves to nothing.

        Keyed lookup, not `entry['current']`: a period may legitimately be present
        with only a `correction` entry, and indexing would raise there.
        """
        entry = by_period.get(period) or {}
        if entry.get('current') or entry.get('gap'):
            return entry.get('current') or entry.get('gap')
        source = _pending_source(period, reason, as_of)
        by_period.setdefault(period, {})['gap'] = add(source)
        return by_period[period]['gap']

    def prior_of(period):
        suffix = str(period)[4:]
        if suffix in PREVIOUS_END:
            return str(period)[:4] + PREVIOUS_END[suffix]
        return None

    def keep_existing_filing_refs(node, replacement):
        # Keep only citations the original numeric node already carried. A stored
        # page review must not be discarded just because the new binding is pending.
        existing = [sid for sid in node.get('sourceIds') or [] if sid in preserved_ids]
        return list(dict.fromkeys(existing + replacement))

    def resolve(period, deps=(), derive=False):
        """Source ids backing a displayed period.

        A **derived single quarter** is the difference of two cumulative rows, so it
        references BOTH its own report and the comparison-period report it was
        differenced against. An annual cumulative point, an as-published Q1 point and
        a period-end balance row are NOT differenced: they reference only their own
        report. `derive` is what makes that distinction - the earlier version applied
        the comparison fallback to every period and so attached a comparison-period
        placeholder to plain annual points.
        """
        ids = [ensure_period(period)]
        matched_any = False
        for dep in deps:
            if str(dep.get('forPeriod') or '') != str(period):
                continue
            prior = dep.get('period')
            if prior:
                matched_any = True
                ids.append(ensure_period(prior, dep.get('gap') or
                                         'not_in_this_rounds_target_scope'))
        if derive and not matched_any:
            prior = prior_of(period)
            if prior:
                ids.append(ensure_period(prior))
        return list(dict.fromkeys(i for i in ids if i))

    finance = dossier.get('finance') or {}
    for kind in ('annual', 'quarterly'):
        for point in finance.get(kind) or []:
            period = str(point.get('period') or '')
            if not period:
                point['sourceIds'] = []
                continue
            if kind == 'quarterly':
                point['sourceIds'] = keep_existing_filing_refs(
                    point, resolve(period, deps_by_period.get(period, []), derive=True))
            else:
                point['sourceIds'] = keep_existing_filing_refs(point, resolve(period))
    if finance.get('latest'):
        finance['latest']['sourceIds'] = keep_existing_filing_refs(
            finance['latest'], resolve(str(finance['latest'].get('period') or '')))
    for group in dossier.get('segments') or []:
        group_sources = resolve(str(group.get('period') or ''))
        for item in group.get('items') or []:
            item['sourceIds'] = keep_existing_filing_refs(item, list(group_sources))
    # profitReconciliation rows reference the interface rows for their period; the
    # reader must see the period's original report instead, and the note text itself
    # is left untouched.
    for row in (finance.get('profitReconciliation') or []):
        row['sourceIds'] = keep_existing_filing_refs(row, resolve(str(row.get('period') or '')))

    # ---- 2. no borrowing outside the numeric branches -----------------------
    # `summary`, the timeline and the interpretation sections must not be propped up
    # by "the most recent annual report": that report does not evidence a particular
    # sentence, and re-pointing it there invents support. Outside finance/segments an
    # unresolvable reference is dropped, the prose stays, and the claim is marked
    # review by the classifier below.
    def repair(node, path=(), fallback_period=None):
        if isinstance(node, dict):
            period = node.get('period') or node.get('reportPeriod') or fallback_period
            ids = node.get('sourceIds')
            if isinstance(ids, list):
                borrow_ok = bool(path) and path[0] in NUMERIC_ROOTS
                repaired = []
                for sid in ids:
                    if sid in valid:
                        repaired.append(sid)
                        continue
                    if borrow_ok:
                        replacement = resolve(str(period), deps_by_period.get(str(period), [])) \
                            if period else []
                        for item in replacement:
                            if item not in repaired:
                                repaired.append(item)
                node['sourceIds'] = repaired
            for key, value in node.items():
                if key != 'sourceIds':
                    repair(value, path + (str(key),), period)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                repair(item, path + (index,), fallback_period)

    for key, value in dossier.items():
        if key == 'sources':
            continue
        repair(value, (key,), None)

    dossier['sources'] = sources

    # ---- 3. classify by real lineage, not by "list is non-empty" -----------
    ledger = defaultdict(list)
    class_counts = defaultdict(int)
    narrative_unsupported = defaultdict(int)
    coverage_changes = []

    def classify(path, node):
        record = before.get(path) or {'sourceIds': [], 'status': None}
        after_ids = list(node.get('sourceIds') or [])
        located = [sid for sid in after_ids if sid in valid and sid not in pending_ids]
        before_status = record.get('status')
        if located:
            klass, reason = CLASS_PRESERVED, None
        elif before_status == 'available':
            if record.get('sourceIds'):
                klass, reason = CLASS_NEWLY_LOST, None
            else:
                klass, reason = CLASS_PRE_EXISTING, None
        elif before_status is None:
            klass, reason = CLASS_LEGITIMATE, 'no_status_field'
        elif before_status in NOT_CLAIMING_SUPPORT:
            klass, reason = CLASS_LEGITIMATE, 'already_not_available'
        else:
            klass, reason = CLASS_LEGITIMATE, 'status_not_claiming_support'
        class_counts[klass] += 1
        if klass in (CLASS_NEWLY_LOST, CLASS_PRE_EXISTING) and path and \
                path[0] in NARRATIVE_ROOTS:
            narrative_unsupported[path[0]] += 1
        degrade = klass == CLASS_NEWLY_LOST or (
            klass == CLASS_PRE_EXISTING and DEGRADE_PRE_EXISTING)
        changed_status = False
        if degrade and before_status == 'available':
            node['status'] = 'review'
            changed_status = True
        if klass != CLASS_PRESERVED:
            ledger[klass].append({
                'path': _path_label(path),
                'cause': 'this-round-replacement' if klass == CLASS_NEWLY_LOST else (
                    'pre-existing' if klass == CLASS_PRE_EXISTING else reason),
                'reason': reason,
                'statusBefore': before_status,
                'statusAfter': node.get('status'),
                'statusChanged': changed_status,
                'sourcesBefore': record.get('sourceIds'),
                'sourcesAfter': after_ids,
                'locatedAfter': located,
            })

    for path, node in _walk_dossier(dossier):
        if path == ('summary',):
            continue                 # summary has no per-claim status; handled below
        classify(path, node)

    # `summary` carries sourceIds but no status field: its reader-facing flag is
    # coverage['summary'], so the lineage is reflected there instead. The overview
    # text must not borrow the latest annual report either.
    summary = dossier.get('summary') or {}
    if isinstance(summary.get('sourceIds'), list):
        summary_before = (before.get(('summary',)) or {}).get('sourceIds') or []
        summary_located = [sid for sid in summary['sourceIds']
                           if sid in valid and sid not in pending_ids]
        if not summary_located:
            klass = CLASS_NEWLY_LOST if summary_before else CLASS_PRE_EXISTING
            degrade = klass == CLASS_NEWLY_LOST or DEGRADE_PRE_EXISTING
            class_counts[klass] += 1
            narrative_unsupported['summary'] += 1
            ledger[klass].append({
                'path': 'summary',
                'cause': 'this-round-replacement' if klass == CLASS_NEWLY_LOST
                         else 'pre-existing',
                'reason': 'summary_text_not_located',
                'statusBefore': 'available', 'statusAfter': 'review',
                'statusChanged': bool(degrade), 'sourcesBefore': summary_before,
                'sourcesAfter': list(summary['sourceIds']), 'locatedAfter': []})
            if degrade:
                summary['note'] = ('公司自述业务描述来自登记与披露资料；具体表述尚未逐页定位到原文，'
                                   '原文核对状态见资料出处。')
                dossier.setdefault('coverage', {})['summary'] = {
                    'status': 'review',
                    'note': ('公司概览与自述业务描述尚未逐句定位到原始报告；'
                             '本页保留原文表述，不据此推断新的确定性结论。'),
                }
                coverage_changes.append({'key': 'summary', 'status': 'review'})
        else:
            class_counts[CLASS_PRESERVED] += 1

    # ---- 4. reader-facing coverage flags follow the claims -----------------
    coverage = dossier.setdefault('coverage', {})
    if narrative_unsupported:
        detail = '、'.join('%s %d 处' % (key, value)
                          for key, value in sorted(narrative_unsupported.items()))
        coverage['research'] = {
            'status': 'review',
            'note': ('经营解读与历史事件尚未定位到原始报告的页码或章节（%s），已标为待核对；'
                     '本次只补充原文出处，未改写任何解读内容。' % detail),
        }
        coverage_changes.append({'key': 'research', 'status': 'review'})
    matched = sum(1 for s in sources
                  if (s.get('verificationLevel') or 1) >= 2 and not s.get('pending'))
    pending = sum(1 for s in sources if s.get('pending'))
    coverage['sources'] = {
        'status': 'available' if matched and not pending else ('partial' if matched else 'missing'),
        'note': ('已匹配 %d 份原始报告，%d 个展示期间的原文仍待补（显示为“原文待补”）。'
                 '匹配只代表文档身份与版本一致，不代表数值已从原文逐项提取。'
                 % (matched, pending)),
    }
    coverage_changes.append({'key': 'sources', 'status': coverage['sources']['status']})

    lineage['publicSourceIds'] = [s['id'] for s in sources]
    lineage['preservedFilingSources'] = [s.get('id') for s in preserved]
    lineage['matchedDocuments'] = matched
    lineage['pendingDocuments'] = pending
    lineage['evidenceLedger'] = {
        'schemaVersion': 1,
        'rule': CLASS_RULES,
        'degradePreExisting': DEGRADE_PRE_EXISTING,
        'counts': {CLASS_PRESERVED: class_counts.get(CLASS_PRESERVED, 0),
                   CLASS_NEWLY_LOST: class_counts.get(CLASS_NEWLY_LOST, 0),
                   CLASS_PRE_EXISTING: class_counts.get(CLASS_PRE_EXISTING, 0),
                   CLASS_LEGITIMATE: class_counts.get(CLASS_LEGITIMATE, 0)},
        'byClass': {key: ledger.get(key, []) for key in
                    (CLASS_NEWLY_LOST, CLASS_PRE_EXISTING, CLASS_LEGITIMATE)},
        'narrativeUnsupported': dict(narrative_unsupported),
        'coverageChanges': coverage_changes,
    }
    return dossier, lineage
