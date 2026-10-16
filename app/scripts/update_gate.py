#!/usr/bin/env python3
"""固定更新协议的门禁：接手前检查、校验、记录。只读取、运行测试、写记录；不采集、不发布、不部署。

用法（在 app/ 目录下执行）：
  python scripts/update_gate.py <market|company|evidence|code> preflight [--allow-dirty]
  python scripts/update_gate.py <type> validate [--static-only]
  python scripts/update_gate.py <type> record --summary "一句话说明" [--pr URL] [--validated static|full]
                                              [--published] [--release-id ID] [--rollback "回滚点"] [--next "下一步"]
  python scripts/update_gate.py <type> record --amend <记录id> [--pr URL] [--release-id ID] [--rollback ...] [--next ...] [--validated static|full]

validate 会把结果写成凭据 diagnostics/update-gate/validate-<type>.json（含 HEAD 与工作区指纹）。
record 只接受凭据里真实达到的级别，树一变凭据即作废；所以顺序是 升版本 → validate → record。

四种更新类型与六个固定步骤的定义见 docs/update-framework.md。
preflight 对应第 1 步「接手」，validate 对应第 3 步「校验」，record 对应第 4 步「记录」。
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
sys.dont_write_bytecode = True
# The same application tree is hashed by production and public-snapshot builds.
# Keep generated Python bytecode out of that tree, including in child checks.
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
REPO = APP.parent
DOCS = REPO / 'docs'
LOG_DIR = DOCS / 'update-log'
ROADMAP = DOCS / 'roadmap.json'
STATUS = DOCS / 'project-status.json'
CN = timezone(timedelta(hours=8))

PY = sys.executable
NODE = shutil.which('node') or 'node'
NPX = shutil.which('npx') or 'npx'
NPM = shutil.which('npm') or 'npm'

# 运行数据：evidence.js 同时导入证据快照与两份关系文件，缺任何一份都无法打包 src/lib。
DATA = {
    'evidence': [APP / 'src' / 'lib' / 'evidence-data.json'],
    'relations': [APP / 'src' / 'lib' / 'industry-relations.json', APP / 'src' / 'lib' / 'supply-chain-relations.json'],
    'companies': [Path(os.environ.get('ATLAS_PUBLIC_ROOT', str(APP / 'public'))) / 'data' / 'companies' / 'index.json'],
    'market': [Path(os.environ.get('ATLAS_PUBLIC_ROOT', str(APP / 'public'))) / 'data' / 'market' / 'latest.json'],
}
# 诊断夹具：只存在于完整项目库的 diagnostics/，不在仓库也不在 runtime-data.zip。
# 依赖它的检查在别的机器上标 BLOCKED，而不是 FAIL。
FIXTURES = {
    'starfield-baseline': [REPO / 'diagnostics' / 'concept-starfield-20260924' / 'backups' / 'atlas.js'],
}
TYPES = {
    'market': {'label': 'T+1 市值快照', 'requires': {'market'}, 'token': True, 'rebuild': False},
    'company': {'label': '公司披露增量', 'requires': {'companies', 'evidence', 'relations'}, 'token': True, 'rebuild': True},
    'evidence': {'label': '板块证据刷新', 'requires': {'evidence', 'relations'}, 'token': True, 'rebuild': True},
    'code': {'label': '网站代码更新', 'requires': set(), 'token': False, 'rebuild': True},
}
ALL = set(TYPES)
LIB = {'evidence', 'relations'}  # 任何打包 src/lib 的检查都需要这两份
# (名称, 命令, 适用类型, 需要的运行数据或夹具)。缺失时标记 BLOCKED，不算通过。
CHECKS = [
    ('发行容量边界', [PY, 'scripts/test_release_capacity.py'], {'code'}, set()),
    ('UI验收工具故障', [NODE, '--experimental-vm-modules', 'scripts/ui-check/selftest.mjs'], {'code'}, set()),
    ('讲解标签与播放状态', [NODE, 'scripts/ui-check/audio-state-selftest.mjs'], {'code'}, set()),
    ('版本一致性', [PY, 'scripts/test_site_version.py'], ALL, set()),
    ('样式契约', [PY, 'scripts/test_styles.py'], {'code'}, set()),
    ('TypeScript', [NODE, str(APP / 'node_modules/typescript/bin/tsc'), '--noEmit', '-p', 'tsconfig.app.json'], {'code'}, set()),
    ('市值快照规则', [PY, 'scripts/test_market_snapshot.py'], {'market'}, set()),
    ('市值合同', [NODE, 'scripts/test_market_cap.mjs'], {'market', 'code'}, set()),
    ('板块索引', [NODE, 'scripts/test_board_index.mjs'], {'evidence', 'code'}, set()),
    ('市值视觉映射', [NODE, 'scripts/test_market_visual.mjs'], {'market', 'code'}, LIB),
    ('公司资料构建', [PY, 'scripts/test_company_data.py'], {'company'}, set()),
    ('公司增量安全', [PY, 'scripts/test_company_updates.py'], {'company'}, {'evidence'}),
    ('公司阅读规则', [NODE, 'scripts/test-company-reading.mjs'], {'company', 'code'}, {'companies'} | LIB),
    ('相关公司', [NODE, 'scripts/test_related_companies.mjs'], {'company', 'evidence'}, {'companies'} | LIB),
    ('分类数据', [PY, 'scripts/test_classification_data.py'], {'evidence'}, set()),
    ('行业关系', [PY, 'scripts/test_industry_relations.py'], {'evidence'}, set()),
    ('行业网络', [NODE, 'scripts/test-industry-network.mjs'], {'evidence', 'code'}, LIB),
    ('分类星图', [NODE, 'scripts/test-classification-graphs.mjs'], {'evidence', 'code'}, LIB),
    ('板块路由', [NODE, 'scripts/test-board-routes.mjs'], {'evidence', 'code'}, LIB),
    ('概念星场', [NODE, 'scripts/test_concept_starfield.mjs'], {'evidence', 'code'}, LIB | {'starfield-baseline'}),
    ('发行自检', [PY, 'scripts/release_selftest.py'], {'code', 'company'}, {'companies', 'market'}),
    ('生产构建', [NPM, 'run', 'build'], {'code', 'company', 'evidence'}, {'companies', 'market'} | LIB),
]
ROADMAP_STATUS = {'pending', 'in_progress', 'done', 'dropped'}
LOG_REQUIRED = {'id', 'type', 'recordedAt', 'summary', 'version', 'validated'}
# validate 把结果写成凭据，record 只接受凭据里真实达到的级别；目录在 diagnostics/ 下，不进仓库。
EVIDENCE_DIR = REPO / 'diagnostics' / 'update-gate'


def say(text=''):
    print(text, flush=True)


def width(text):
    return sum(2 if unicodedata.east_asian_width(ch) in 'WF' else 1 for ch in text)


def row(label, value):
    say(f'  {label}{" " * max(1, 16 - width(label))}{value}')


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    # 仓库按字节保存源文件（.gitattributes: * -text）；改写时沿用该文件原有的换行符。
    newline = '\r\n' if path.exists() and b'\r\n' in path.read_bytes() else '\n'
    text = json.dumps(value, ensure_ascii=False, indent=2) + '\n'
    path.write_bytes(text.replace('\n', newline).encode('utf-8'))


def git(*args):
    try:
        return subprocess.run(['git', *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ''


def data_presence():
    """运行数据与诊断夹具各自全部文件齐备才算在。"""
    return {key for key, paths in {**DATA, **FIXTURES}.items() if all(path.exists() for path in paths)}


def data_summary(key):
    """一行描述某份运行数据的日期与规模；记录与接手都用它，保证口径一致。"""
    try:
        value = load_json(DATA[key][0])
    except (OSError, ValueError):
        return None
    if key == 'evidence':
        return {'tradeDate': value.get('tradeDate'), 'membershipAsOf': value.get('membershipAsOf'),
                'schemaVersion': value.get('schemaVersion'), 'status': value.get('status')}
    if key == 'companies':
        return {'snapshotId': value.get('snapshotId'), 'asOf': value.get('asOf'),
                'total': (value.get('coverage') or {}).get('total')}
    if key == 'market':
        return {'tradeDate': value.get('tradeDate'), 'snapshotId': value.get('snapshotId'),
                'coverage': value.get('coverage')}
    return {'files': len(DATA[key]), 'asOf': value.get('asOf') or value.get('generatedAt') if isinstance(value, dict) else None}


def describe(summary):
    return ' · '.join(f'{k} {v}' for k, v in summary.items() if v is not None) if summary else '无法读取'


def site_versions():
    package = load_json(APP / 'package.json')
    lock = load_json(APP / 'package-lock.json')
    history = load_json(APP / 'release-history.json')
    return {
        'package.json': package['version'],
        'package-lock.json': lock.get('version'),
        'package-lock packages': (lock.get('packages') or {}).get('', {}).get('version'),
        'release-history.json': history[0]['version'] if history else None,
    }, history


def roadmap_items():
    if not ROADMAP.exists():
        return []
    return load_json(ROADMAP).get('items', [])


def log_entries():
    entries = []
    if LOG_DIR.exists():
        for path in sorted(LOG_DIR.glob('*.json')):
            try:
                entries.append((path, load_json(path)))
            except ValueError:
                entries.append((path, None))
    return entries


def tree_fingerprint():
    """HEAD 加上工作区全部改动（含未跟踪文件）的摘要：校验与记录之间树变了，凭据就作废。"""
    digest = hashlib.sha256()
    for part in (git('rev-parse', 'HEAD'), git('status', '--porcelain'), git('diff', 'HEAD')):
        digest.update(part.encode('utf-8')); digest.update(b'\0')
    return digest.hexdigest()[:16]


def evidence_path(kind):
    return EVIDENCE_DIR / f'validate-{kind}.json'


def load_evidence(kind):
    """上一次 validate 的凭据；树已经变了或没跑过都返回 None，并说明原因。"""
    path = evidence_path(kind)
    if not path.exists():
        return None, f'没有 {path.relative_to(REPO)}：先运行 python scripts/update_gate.py {kind} validate'
    try:
        stamp = load_json(path)
    except ValueError:
        return None, f'{path.relative_to(REPO)} 不是合法 JSON，重新运行 validate'
    if stamp.get('fingerprint') != tree_fingerprint():
        return None, '上次校验之后代码或工作区已改动（含升版本），请重新运行 validate 再记录'
    if not stamp.get('passed'):
        return None, f'上次校验未通过（{stamp.get("at")}），修复后重新运行 validate'
    return stamp, ''


def resolve_validated(kind, requested):
    """把 --validated 和凭据对齐：没给就用凭据级别；给了不能高于凭据。"""
    stamp, reason = load_evidence(kind)
    if stamp is None:
        return None, None, reason
    level = stamp.get('level')
    if requested and requested == 'full' and level != 'full':
        return None, None, f'凭据只有 {level} 级（{len(stamp.get("blocked", []))} 项被阻断），不能记录为 full；在有运行数据的机器上完整校验后再记'
    return requested or level, stamp, ''


# ── 第 1 步 · 接手 ────────────────────────────────────────────────────────────
def preflight(kind, args):
    cfg = TYPES[kind]
    fails, warns = [], []
    say(f'== 接手 · {cfg["label"]} · {datetime.now(CN).strftime("%Y-%m-%d %H:%M")} (Asia/Shanghai)')

    branch, head = git('rev-parse', '--abbrev-ref', 'HEAD'), git('rev-parse', '--short', 'HEAD')
    dirty = [line for line in git('status', '--porcelain').splitlines() if line.strip()]
    row('分支', f'{branch or "?"} @ {head or "?"}' + (f' · {len(dirty)} 处未提交' if dirty else ' · 工作区干净'))
    if dirty:
        (warns if args.allow_dirty else fails).append(f'工作区有 {len(dirty)} 处未提交改动。接手时先提交或放弃；确有必要可加 --allow-dirty')

    versions, history = site_versions()
    if len(set(versions.values())) != 1:
        fails.append('网站版本不一致：' + '，'.join(f'{k}={v}' for k, v in versions.items()))
    row('网站版本', f'v{versions["package.json"]} · 记录日期 {history[0]["date"] if history else "?"}')

    present = data_presence()
    for key in DATA:
        row(f'数据 · {key}', describe(data_summary(key)) if key in present else '缺失')
    for key in FIXTURES:
        row(f'夹具 · {key}', '在' if key in present else '缺失（只在完整项目库的 diagnostics/，依赖它的检查会标 BLOCKED）')
    missing = cfg['requires'] - present
    if missing:
        fails.append(f'缺少运行数据 {sorted(missing)}：按 README 用 scripts/restore_runtime.py 恢复所有者提供的 runtime-data.zip')

    status = load_json(STATUS) if STATUS.exists() else {}
    row('项目状态', f'asOf {status.get("asOf", "?")} · 市值 {status.get("marketTradeDate", "?")} · '
                    f'公司快照 {status.get("companySnapshot", "?")}（{status.get("companyCount", "?")} 家）')
    if kind == 'company' and status.get('companyIncrementalUpdates') != 'accepted':
        warns.append(f'公司原文增量链状态为 {status.get("companyIncrementalUpdates")}：本次只能产生候选并校验，不得 --publish，'
                     '也不得解除 builder/updater 的原文覆盖保护')

    if cfg['token']:
        has_token = bool(os.environ.get('TUSHARE_TOKEN'))
        row('TUSHARE_TOKEN', '已设置' if has_token else '未设置')
        if not has_token:
            warns.append('第 2 步「取得」需要 TUSHARE_TOKEN；只做校验或记录可以不设')
    if kind == 'code' and not (APP / 'node_modules').exists():
        warns.append('node_modules 缺失：校验前先在 app/ 执行 npm ci')

    items = roadmap_items()
    active = [item for item in items if item.get('status') == 'in_progress']
    queued = [item for item in items if item.get('status') == 'pending']
    row('进行中', '；'.join(f'{i["id"]} {i["title"]}' for i in active) or '无')
    row('下一项', f'{queued[0]["id"]} {queued[0]["title"]}' if queued else '无')
    entries = [(p, e) for p, e in log_entries() if e]
    if entries:
        path, last = entries[-1]
        row('上次记录', f'{last.get("id")} · {last.get("summary", "")[:60]}')
    else:
        row('上次记录', '尚无 docs/update-log 记录')

    say()
    for text in warns:
        say(f'  WARN  {text}')
    for text in fails:
        say(f'  FAIL  {text}')
    say(f'== 接手 {"通过" if not fails else "未通过"}；下一步：{"第 2 步「取得」只产生候选，不发布" if not fails else "先处理上面的 FAIL"}')
    return 0 if not fails else 1


# ── 第 3 步 · 校验 ────────────────────────────────────────────────────────────
def check_docs():
    problems = []
    seen = set()
    for item in roadmap_items():
        for key in ('id', 'title', 'status'):
            if not item.get(key):
                problems.append(f'roadmap.json：条目缺少 {key}：{item}')
        if item.get('status') not in ROADMAP_STATUS:
            problems.append(f'roadmap.json：{item.get("id")} 的 status 必须是 {sorted(ROADMAP_STATUS)}')
        if item.get('id') in seen:
            problems.append(f'roadmap.json：重复 id {item.get("id")}')
        seen.add(item.get('id'))
    for path, entry in log_entries():
        if entry is None:
            problems.append(f'update-log：{path.name} 不是合法 JSON')
            continue
        missing = LOG_REQUIRED - set(entry)
        if missing:
            problems.append(f'update-log：{path.name} 缺少字段 {sorted(missing)}')
        if entry.get('id') != path.stem:
            problems.append(f'update-log：{path.name} 的 id 应为 {path.stem}')
        if entry.get('type') not in TYPES:
            problems.append(f'update-log：{path.name} 的 type 必须是 {sorted(TYPES)}')
        if not re.fullmatch(r'\d{8}-(market|company|evidence|code)-\d{2}', path.stem):
            problems.append(f'update-log：{path.name} 文件名应为 YYYYMMDD-<类型>-NN.json')
    return problems


def validate(kind, args):
    cfg = TYPES[kind]
    present = data_presence()
    say(f'== 校验 · {cfg["label"]}' + ('（--static-only：允许跳过需要运行数据的检查）' if args.static_only else ''))
    results = []
    for name, command, types, requires in CHECKS:
        if kind not in types:
            continue
        missing = requires - present
        if missing:
            reason = ' '.join(filter(None, [f'缺少数据 {sorted(missing & set(DATA))}' if missing & set(DATA) else '',
                                            f'缺少夹具 {sorted(missing & set(FIXTURES))}' if missing & set(FIXTURES) else '']))
            results.append((name, 'BLOCKED', reason, 0.0))
            row(name, f'BLOCKED  {reason}')
            continue
        started = time.monotonic()
        try:
            proc = subprocess.run(command, cwd=APP, capture_output=True, text=True, encoding='utf-8', errors='replace')
            code, output = proc.returncode, (proc.stdout + proc.stderr)
        except OSError as exc:
            code, output = 127, str(exc)
        elapsed = time.monotonic() - started
        state = 'PASS' if code == 0 else 'FAIL'
        results.append((name, state, output, elapsed))
        row(name, f'{state}  {elapsed:.1f}s  {" ".join(Path(part).name if os.sep in part else part for part in command)}')
        if state == 'FAIL':
            for line in output.strip().splitlines()[-15:]:
                say(f'      {line}')

    problems = check_docs()
    row('记录结构', 'PASS' if not problems else 'FAIL')
    for problem in problems:
        say(f'      {problem}')

    failed = [r for r in results if r[1] == 'FAIL'] or problems
    blocked = [r for r in results if r[1] == 'BLOCKED']
    passed = not failed and (not blocked or args.static_only)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    write_json(evidence_path(kind), {
        'type': kind, 'at': datetime.now(CN).isoformat(timespec='seconds'),
        'commit': git('rev-parse', '--short', 'HEAD') or None, 'fingerprint': tree_fingerprint(),
        'level': 'static' if blocked else 'full', 'passed': passed, 'staticOnly': args.static_only,
        'passedChecks': [r[0] for r in results if r[1] == 'PASS'], 'blocked': [r[0] for r in results if r[1] == 'BLOCKED'],
        'failed': [r[0] for r in results if r[1] == 'FAIL'] + (['记录结构'] if problems else []),
    })
    say()
    if failed:
        say('== 校验未通过：先修复 FAIL，再重跑')
        return 1
    if blocked and not args.static_only:
        say('== 校验未完成：有检查因缺少运行数据被阻断。恢复数据后重跑；若本机不会有数据，加 --static-only，并在记录里注明 validated=static')
        return 1
    if blocked:
        say(f'== 静态校验通过（{len(blocked)} 项需在有运行数据的机器上补跑：{"、".join(r[0] for r in blocked)}）；凭据已写入 {evidence_path(kind).relative_to(REPO)}')
        return 0
    say(f'== 完整校验通过；凭据已写入 {evidence_path(kind).relative_to(REPO)}')
    return 0


# ── 第 4 步 · 记录 ────────────────────────────────────────────────────────────
def record(kind, args):
    cfg = TYPES[kind]
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    status = load_json(STATUS) if STATUS.exists() else {}
    now = datetime.now(CN)

    if args.amend:
        path = LOG_DIR / f'{args.amend}.json'
        if not path.exists():
            say(f'没有记录 {args.amend}')
            return 1
        entry = load_json(path)
        for key in ('pr', 'release_id', 'rollback', 'next'):
            value = getattr(args, key)
            if value:
                entry['releaseId' if key == 'release_id' else key] = value
        if args.validated:
            # 补记校验级别也要有凭据：在完整校验过的那台机器、同一棵树上运行。
            level, stamp, reason = resolve_validated(kind, args.validated)
            if level is None:
                say(reason)
                return 1
            entry['validated'] = level
            entry['validatedAt'], entry['validatedCommit'] = stamp['at'], stamp.get('commit')
        entry['amendedAt'] = now.isoformat(timespec='seconds')
        write_json(path, entry)
        say(f'已补充记录 {path.relative_to(REPO)}')
        return 0

    if not args.summary:
        say('record 需要 --summary；补充已有记录请用 --amend <记录id>')
        return 1
    if kind == 'company' and args.published and status.get('companyIncrementalUpdates') != 'accepted':
        say('公司原文增量链待验收，不能把公司增量记录为已发布')
        return 1
    validated, stamp, reason = resolve_validated(kind, args.validated)
    if validated is None:
        say(reason)
        return 1
    if kind != 'code' and validated == 'static':
        say('数据更新必须完整校验后才能记录；validated=static 只适用于没有运行数据的代码改动')
        return 1

    date = now.strftime('%Y%m%d')
    sequence = len(list(LOG_DIR.glob(f'{date}-{kind}-*.json'))) + 1
    entry_id = f'{date}-{kind}-{sequence:02d}'
    versions, _ = site_versions()
    present = data_presence()
    entry = {
        'id': entry_id,
        'type': kind,
        'label': cfg['label'],
        'recordedAt': now.isoformat(timespec='seconds'),
        'summary': args.summary,
        'version': versions['package.json'],
        'branch': git('rev-parse', '--abbrev-ref', 'HEAD') or None,
        'commit': git('rev-parse', '--short', 'HEAD') or None,
        'pr': args.pr,
        'validated': validated,
        'validatedAt': stamp['at'],
        'validatedCommit': stamp.get('commit'),
        'rollback': args.rollback,
        'next': args.next,
        'data': {key: data_summary(key) for key in sorted(present & set(DATA))},
    }
    if kind != 'code':
        entry['published'] = bool(args.published)
    if args.release_id:
        entry['releaseId'] = args.release_id
    write_json(LOG_DIR / f'{entry_id}.json', entry)

    # project-status.json 只刷新本仓库能证明的字段；导出工具在下次同步时会按完整项目库重算其余字段。
    status['asOf'] = now.strftime('%Y%m%d-%H%M%S')
    status['sourceVersion'] = versions['package.json']
    if args.published and kind == 'market' and 'market' in present:
        market = data_summary('market') or {}
        status['marketTradeDate'] = market.get('tradeDate')
        status['marketCoverage'] = market.get('coverage')
    if args.published and kind == 'company' and 'companies' in present:
        companies = data_summary('companies') or {}
        status['companySnapshot'], status['companyAsOf'], status['companyCount'] = companies.get('snapshotId'), companies.get('asOf'), companies.get('total')
    if args.published and kind == 'evidence' and 'evidence' in present:
        evidence = data_summary('evidence') or {}
        status['evidenceTradeDate'], status['evidenceMembershipAsOf'] = evidence.get('tradeDate'), evidence.get('membershipAsOf')
    status['lastUpdateLog'] = entry_id
    write_json(STATUS, status)
    say(f'已写入 {LOG_DIR.relative_to(REPO)}/{entry_id}.json，并刷新 docs/project-status.json（asOf、sourceVersion、lastUpdateLog{"、数据字段" if args.published else ""}）')
    say('下一步：第 5 步「交付」。代码走 PR 并在创建后用 --amend 补 --pr；数据发布、服务器 stage/activate 仍需单独授权。')
    return 0


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, ValueError):
        pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('type', choices=sorted(TYPES))
    parser.add_argument('stage', choices=['preflight', 'validate', 'record'])
    parser.add_argument('--allow-dirty', action='store_true', help='preflight：允许工作区有未提交改动')
    parser.add_argument('--static-only', action='store_true', help='validate：本机没有运行数据时，接受静态检查子集')
    parser.add_argument('--summary', help='record：一句话说明本次更新')
    parser.add_argument('--pr', help='record：PR 链接')
    parser.add_argument('--validated', choices=['static', 'full'], help='record：本次校验级别；默认取 validate 凭据里的级别，不能高于凭据')
    parser.add_argument('--published', action='store_true', help='record：数据已在本地 --publish（不含部署）')
    parser.add_argument('--release-id', help='record：正式发行 id（release_remote activate 之后）')
    parser.add_argument('--rollback', help='record：回滚点，例如上一发行 id 或上一 PR 的合并提交')
    parser.add_argument('--next', help='record：留给下一次接手的一句话')
    parser.add_argument('--amend', metavar='记录id', help='record：补充已有记录的 pr / release-id / rollback / next / validated')
    args = parser.parse_args()
    stage = {'preflight': preflight, 'validate': validate, 'record': record}[args.stage]
    return stage(args.type, args)


if __name__ == '__main__':
    sys.exit(main())
