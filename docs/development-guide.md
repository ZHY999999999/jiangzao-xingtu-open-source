# 开发、数据恢复与发行说明

> 下方为停服前的开发与发行流程留档。原在线服务已于2026-10-16停止，历史“正式网站”“后续继续建设”不代表当前承诺。以仓库README的开源与运行边界为准。

## 五分钟接手

先读 `AGENTS.md` 和 `docs/project-status.json`。源码在 `app/`；版本变更在 `app/release-history.json`。
日常更新（市值快照、公司增量、板块证据、代码）按 `docs/update-framework.md` 的六步走：开发项与下一步在 `docs/roadmap.json`，每次更新的记录在 `docs/update-log/`，接手先在 `app/` 跑 `python scripts/update_gate.py <类型> preflight`。
此仓库从当前代码建立干净历史，没有继承完整项目库中的私人研究、机器路径配置和旧提交。
停服前最后记录的发行是 2026-10-06 的 1.2.26 / 6ec48bc9b5bc，历史验收包括 185 家概览、14 家七问和 1 份工业富联完整拆解（按公司去重为 186 家）。来源为[当日发行记录](update-log/20261006-code-02.json)，不能据此推断当前仍在线。旧[第一层任务书](tasks/l1-company-overview.md)仅作历史留档，不接续旧队列；当前范围见 `docs/project-status.json`。原完整项目库保持只读，旧库与旧候选不能覆盖本版源码。

## 恢复并运行

需要 Node.js 22、Python 3.11+，以及有权使用且与清单匹配的 `runtime-data.zip`。本仓库不提供数据包下载，也不承诺由所有者发放。
代码与数据分开保存，**只有 clone 不能构建完整网站**。先恢复与当前清单匹配的数据：

1.2.19统一源码的内容批准与公开重建边界见[统一内容构建说明](unified-content-build.md)。普通公开副本恢复后，显式设置 `ATLAS_APPROVAL_MODE=snapshot` 才能重建已记录内容；该输出标为未发布，不能用于正式发行。真实生产构建必须使用当前批准链。

```powershell
python scripts/restore_runtime.py --archive "你的备份目录/runtime-data.zip"
cd app
npm ci
$env:ATLAS_APPROVAL_MODE='snapshot'
npm run build
npm run preview -- --host 127.0.0.1 --port 5181
```

开发使用 `npm run dev -- --host 127.0.0.1 --port 5178`。这些命令默认不采集、不更新、不部署。
首次运行请确保没有设置 `MARKET_UPDATE_ON_START=1` 或 `COMPANY_UPDATE_ON_START=1`。

恢复包包含构建需要的图谱资料、公司目录、一个当前公司快照和市值快照；每个文件的路径和 SHA256 见 `docs/runtime-data-manifest.json`。
它不含原始年报、历史采集缓存、私人笔记和完整数据重建证据。这些仍在原完整项目库中，需另行备份。

## 代码与资料边界

- Git：页面、样式、脚本、依赖清单、字体许可、公开图片/讲解音频及已审核编辑内容。
- 不进 Git：全量结构化资料、公告原件、采集缓存、私人投资研究、凭据、账户文件和服务器配置。
- 原发行选择14份已验七问与1份既有工业富联标杆。第一层生意概览与七问解读分别批准，采用清单以 `app/content-selection.json` 为准；同一家公司可同时具备两层。公司数按代码去重，5,000 多家公司财务覆盖不代表全部解读完成。
- 公司原文增量链仍待验收；保留 builder/updater 的原文覆盖保护，不运行旧链覆盖有效快照。
- 生成静态发行包与公开部署是独立动作；上传 GitHub 不会更新正式网站。

## 测试与发布

恢复数据并安装依赖后：

```powershell
cd app
npx tsc --noEmit -p tsconfig.app.json
python scripts/test_site_version.py
python scripts/release_selftest.py
$env:ATLAS_APPROVAL_MODE='snapshot'
npm run build
```

部署脚本仅保留工具实现，不附带服务器地址或 SSH 凭据。
使用时明确提供 `ATLAS_DEPLOY_SERVER`、`ATLAS_DEPLOY_IDENTITY`，现有服务器端脚本要求 root 权限并校验 SSH host key。
未配置环境、未取得当前发布授权或没有候选验收与回滚证据时，不执行 Stage/Activate。
本仓库未配置 GitHub Actions 自动采集、自动部署或公开 Pages。

## 后续同步

1.2.19起使用本仓库 `scripts/export_source.py` 生成和验证公开源码候选；旧原工程的prepare_github白名单没有覆盖新增内容线，不可用其结果覆盖本版。
先核对候选与真实上线源码，再通过新分支和PR对GitHub做普通增量提交；不要强推，不要向本地克隆来源镜像推送，不要推送原完整项目库的所有分支和历史。
`docs/source-export-manifest.json` 记录公开源码白名单、源文件哈希与导出文件哈希。当前 `scripts/export_source.py` 按清单逐字节复制，所有 `transforms` 均为空；部署环境变量约束已在源码中，不在上传副本中临时转换服务器或密钥默认值。导出仅核对与复制文件，不替代状态确认、内容批准或发布验收。

使用 `python scripts/export_source.py --verify` 核对公开文件清单；包含TypeScript构建脚本、content-selection、生意概览、七问正文、公开批准快照，以及根许可证、贡献说明和 `docs/media/` 中的展示图片、SVG、GIF与MP4。运行数据仍排除。`--write-manifest`只能在审查本地改动后刷新清单；它不授权内容或发布，也不导出私人批准库。更新记录会改变公开文件，须在记录完成后刷新并复核清单。
