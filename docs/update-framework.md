# 降噪星图 · 固定更新框架

每一次更新——T+1 市值快照、公司披露增量、板块证据刷新、网站代码改动——都走同一套六步。
步骤由人触发；`app/scripts/update_gate.py` 只做检查和记录，不采集、不发布、不部署。
这份文件是接手入口：新会话、新电脑、新 agent 都从这里开始，不依赖对话记忆。

2026-10-04 所有者已单独授权第一层全索引持续生产、独立验收后滚动发布及同版公开源码同步，范围见 `docs/tasks/l1-company-overview.md`。该任务可以沿用既有授权接续；仍须完成本页的校验、记录及真实发布回读。原始披露增量、付费研究/配音与收费功能不在这项授权内。

## 0. 边界（不随更新类型变化）

- 没有对应所有者授权时，不开启自动采集或自动发布；不伪造数据。已明确授权的第一层持续任务按其任务书、唯一调度、批内机械全检与独立重点抽检执行；共用页面按代表和变化范围验收。
- 代码与数据分离：市值快照独立于代码包，页面每 5 分钟自取；公司快照不可变、按 `snapshotId` 原子切换；板块证据在构建时烘进代码包。
- 公司原文增量链待验收：`docs/project-status.json` 的 `companyIncrementalUpdates` 不是 `accepted` 时，公司增量只做候选与校验，不 `--publish`，不解除 builder/updater 的原文覆盖保护。
- 上传 GitHub 不等于部署。服务器 `stage` / `activate` 需要明确授权、候选验收和上一正式发行的回滚证据。
- 第一层任务沿已核实的统一发布工作区修改源码；原完整项目库保留只读回退。回传须另按授权对照合并，不覆盖。

## 1. 四种更新类型

| 类型 | 门禁名 | 什么时候做 | 产物 | 重新构建 | 升网站版本 |
|---|---|---|---|---|---|
| T+1 市值快照 | `market` | 每个交易日 17:10（Asia/Shanghai）之后 | `app/public/data/market/latest.json` | 否 | 否 |
| 公司披露增量 | `company` | 每日披露窗口；周日自动深检 | `app/public/data/companies/snapshots/<id>/` + `index.json` | 是 | 否 |
| 板块证据刷新 | `evidence` | 成分名单或行情口径变化时 | `app/src/lib/evidence-data.json` | 是 | 是 |
| 网站代码更新 | `code` | 功能、样式、内容改动 | `app/src`、`app/public` 资源、`app/content` | 是 | 是 |

网站版本在实际产品发行摘要改变时升级。1.2.20 统一构建的摘要覆盖根构建配置、`src/**`、完整 `content/**`（含 `company-editorial`、`company-seven-questions` 与 `company-overview`）、`content-selection.json`、公开批准快照、`scripts/**` 构建/校验模块与公共资源；公共大数据只将公司索引纳入产品 revision，其余文件仍由完整 assembly/发行 SHA 清单独立绑定。
`docs`不进入产品revision。用户更新记录只说明可见变化；脚本与测试变化由更新凭据说明，不能把验证流程改善写成虚假的用户功能。任何source/export清单刷新后都要重新核清单与实际字节。

## 2. 六个固定步骤

命令都在 `app/` 目录下执行。每一步写清目的、命令、通过条件、产物。

### 第 1 步 · 接手

目的：知道现在在哪、上一次做到哪、这次能不能开始。

1. 读三份文件：`docs/project-status.json`（数据与版本现状）、`docs/roadmap.json`（开发项与下一项）、`docs/update-log/` 最新一条（上一次更新做了什么、留了什么话）。
2. 跑门禁：

```powershell
python scripts/update_gate.py <market|company|evidence|code> preflight
```

通过条件：工作区干净；`package.json`、`package-lock.json`、`release-history.json` 版本一致；该类型需要的运行数据在；阻断标志已知晓（WARN 会列出）。
FAIL 不绕过。缺数据按 README 用 `scripts/restore_runtime.py` 恢复所有者提供的 `runtime-data.zip`。

### 第 2 步 · 取得（只产生候选）

| 类型 | 命令 | 说明 |
|---|---|---|
| `market` | `python scripts/update-market-snapshot.py` | 不带 `--publish`。候选与校验结果留在 `../diagnostics/market-updates/`，不碰 `latest.json` |
| `company` | `python scripts/check-company-updates.py` | 不带 `--publish`。候选 overlay 在 `../diagnostics/company-updates/`；需要 `ATLAS_KNOWLEDGE_ROOT` 或默认知识库路径 |
| `evidence` | 先复制当前 `src/lib/evidence-data.json` 到 `../diagnostics/evidence/<日期>/` 作为回滚点，再 `python scripts/refresh-data.py --trade-date YYYYMMDD --financial-period YYYYMMDD` | 核心输入失败时保留旧快照；成功即替换，没有独立候选模式，所以回滚点要先留 |
| `code` | 在 `cursor/<说明>` 或自定义分支上改动，不直接改 `main` | UI 改动先在本机预览或静态样板页核对明暗两套主题 |

三种数据类型都只用环境变量 `TUSHARE_TOKEN`，不写入磁盘，不从其他目录找凭据。

### 第 3 步 · 校验

```powershell
python scripts/update_gate.py <type> validate
```

门禁按类型运行现有测试（版本一致性、样式契约、TypeScript、市值/公司/分类规则、发行自检、生产构建），并检查 `roadmap.json` 与 `update-log/` 的结构。需要运行数据而数据不在的检查标记 `BLOCKED`，不算通过。

没有运行数据的机器（例如云端 clone）加 `--static-only`：静态子集通过即可继续，但记录只能是 `validated=static`，完整校验必须在完整项目库机器上补跑后才能发布。数据类更新不接受 `static`。

每次运行都会把结果写成凭据 `diagnostics/update-gate/validate-<type>.json`（级别、通过与否、HEAD、工作区指纹、各检查结果）。第 4 步的 `record` 只认这份凭据：没有凭据、凭据未通过、或校验之后代码/工作区又改过（包括升版本）都会被拒绝。所以代码改动的顺序是 **升版本 → validate → record**。

UI 改动另外跑 `node scripts/ui-check/run.mjs --base http://127.0.0.1:5181/ --plain 000014.SZ`（先完成对应模式的真实构建，再启动预览）：原桌面/手机27项与reading16项合计43项，另有统一版专项复位、七问、来源与动态样板验收。原16张截图拼成`contact-sheet.png`，结果在`diagnostics/ui-check/<时间戳>/`。样板集合从实际首页读取；`--plain`必须是当前没有深读的档案，不能继续写死已完成的000001。所有通过数以本版真实运行报告为准，不继承旧候选的历史通过记录。需要Chrome/Edge与Node 22；Windows用`--chrome`指定浏览器。只有静态样板或模拟媒体状态时，不宣称实际网站和真实播放已验收。

### 第 4 步 · 记录

1. 代码改动触及发行摘要范围时先升版本：`npm run version:patch -- "一句话更新说明"`（同时写入 `release-history.json`），然后回到第 3 步重新 `validate`，让凭据覆盖升版本后的树。
2. 写更新记录：

```powershell
python scripts/update_gate.py <type> record --summary "一句话说明" [--validated static|full] [--published] [--rollback "回滚点"] [--next "给下一次接手的话"]
```

`--validated` 不写就取凭据里的级别；写了不能高于凭据（凭据是 static 就记不了 full）。
产物：`docs/update-log/YYYYMMDD-<type>-NN.json`（含 `validatedAt`、`validatedCommit`）；`docs/project-status.json` 刷新 `asOf`、`sourceVersion`、`lastUpdateLog`，数据已 `--published` 时再刷新对应的数据字段。
3. 手工改 `docs/roadmap.json`：本项 `pending → in_progress → done`，填 `pr`、`version`、`updateLog`。
4. 在别的机器补跑了完整校验，要把记录从 static 提到 full：在那台机器、同一棵树上 `validate` 通过后，`record --amend <记录id> --validated full`。直接改 JSON 不留 `validatedAt`/`validatedCommit`，门禁的记录结构检查不会拦，但下一个接手的人无从核对。

### 第 5 步 · 交付

| 类型 | 动作 |
|---|---|
| `code` | 每个逻辑改动一个提交 → push → 按 `.github/PULL_REQUEST_TEMPLATE.md` 建 PR → `python scripts/update_gate.py code record --amend <记录id> --pr <URL>` |
| `market` / `company` | 完整校验通过后再跑一次取得命令并加 `--publish`（本地原子替换，不部署）→ `record --published` |
| `evidence` | 校验通过 → 进入代码发行（证据随代码包一起发布） |

发行到服务器（任何类型，需所有者授权）：`npm run build` → `python scripts/release_bundle.py --expected-companies <独立核对的上市公司数>` → 上传发行包 → `release_remote.py stage --archive … --sha256 …` → 验收 → `release_remote.py activate --release-id …` → `record --amend <记录id> --release-id <id> --rollback <上一发行 id>`。
前提：`ATLAS_DEPLOY_SERVER`、`ATLAS_DEPLOY_IDENTITY` 已配置，服务器端脚本要求 root 并校验 SSH host key，上一正式发行仍可 `rollback`。

### 第 6 步 · 收尾

- `docs/roadmap.json`：本项标 `done`；下一项保持 `pending`，或标 `in_progress` 并在 `notes` 写接手提示。
- `docs/update-log/` 该条的 `next` 字段写给下一次接手的一句话（`record --amend <id> --next "…"`）。
- 保留上一正式发行与回滚证据；不删 `diagnostics/` 里的候选与日志。
- 回传本机完整项目库时对照合并；本版统一源码使用 `scripts/export_source.py` 白名单，包含 TypeScript 构建脚本、selection、生意概览、七问和公开批准快照。旧 `prepare_github.py` 白名单不能覆盖本版。

## 3. 文件约定

### `docs/roadmap.json`

开发项清单。字段：`id`（`<领域>-<序号>-<短名>`，领域取 `ui` / `ops` / `data`）、`area`、`title`、`status`（`pending` / `in_progress` / `done` / `dropped`）、`acceptance`（可核对的验收条件，逐条）、`pr`、`version`、`updateLog`、`notes`。
顺序即优先级；`preflight` 会打印进行中的项和第一个 `pending` 项。

### `docs/update-log/`

每次更新一条，文件名 `YYYYMMDD-<type>-NN.json`，由 `record` 生成。必有字段：`id`、`type`、`recordedAt`、`summary`、`version`、`validated`；另有 `validatedAt`、`validatedCommit`（来自校验凭据）、`branch`、`commit`、`pr`、`rollback`、`next`、`data`（记录时各份运行数据的日期与规模），数据类还有 `published`，正式发行后有 `releaseId`。
历史记录不改写，只用 `--amend` 补 `pr` / `releaseId` / `rollback` / `next` / `validated`。

### `diagnostics/update-gate/`

`validate` 的凭据，每种类型一个文件，在仓库之外（`diagnostics/` 不进 Git）。它绑定运行时的 HEAD 与工作区指纹，只对本机、本树有效；换机器或改了文件就要重新 `validate`。

### `docs/project-status.json`

`record` 只刷新本仓库能证明的字段：`asOf`、`sourceVersion`、`lastUpdateLog`，以及已发布数据的 `marketTradeDate`、`marketCoverage`、`companySnapshot`、`companyAsOf`、`companyCount`、`evidenceTradeDate`、`evidenceMembershipAsOf`。
`publicVersionLastRecorded`、`publicReleaseLastRecorded`、`publicRevisionLastRecorded` 由当前发布协调者依据同一发行的真实 Verify 回执与独立公网验收记录同步；三类第一层数量分别依据内容与候选批准、整站验收及公开发行证据更新。`scripts/export_source.py` 只生成、核对和逐字节复制公开源码白名单，不重算线上状态，不批准内容或发行；旧 `prepare_github.py` 不是本版导出与状态确认入口。

### `.github/PULL_REQUEST_TEMPLATE.md`

固定四段：改了什么 / 怎么验的 / 用户可见影响 / 回滚方式。每段都要填，没有就写「无」。

### 校验脚本与数据依赖

| 脚本 | 需要的运行数据 |
|---|---|
| `test_site_version.py`、`test_styles.py`、`tsc`、`test_market_cap.mjs`、`test_market_snapshot.py`、`test_company_data.py`、`test_classification_data.py`、`test_industry_relations.py` | 无 |
| `test_company_updates.py` | `src/lib/evidence-data.json` |
| `test_market_visual.mjs`、`test-industry-network.mjs`、`test-classification-graphs.mjs`、`test-board-routes.mjs` | `src/lib/evidence-data.json` + `src/lib/industry-relations.json` + `src/lib/supply-chain-relations.json`（`evidence.js` 同时导入三份） |
| `test_concept_starfield.mjs` | 以上 + 诊断夹具 `diagnostics/concept-starfield-20260924/backups/atlas.js`。夹具只在完整项目库，不在仓库也不在 `runtime-data.zip`；别的机器上门禁标 BLOCKED，可用 `--baseline=<路径>` 指定副本 |
| `test-company-reading.mjs`、`test_related_companies.mjs` | 三份 `src/lib` 数据 + `public/data/companies/` |
| `release_selftest.py` | `public/data/companies/` + `public/data/market/latest.json` |
| `npm run build` | 全部运行数据 |

`restore_runtime.py` 按 `docs/runtime-data-manifest.json` 恢复，三份 `src/lib/*.json` 都在清单内；诊断夹具不在。

## 4. 两个 agent 怎么分工

云端 agent（Cursor）是**总设计师**：出设计与任务书、审查报告、验收结果、把关 UI。本地 agent（Codex）是**执行者**：按任务书实现代码、跑校验、截图、操作服务器、回报。所有者启动本地执行轮；执行者完成已授权且未阻塞的工作，不能用“收到／已恢复”代替交付。涉及范围外的不可逆动作时再取得所有者授权。

两者没有直连，唯一共同能读写的是这个仓库，所以接力的介质是 **PR**：任务书是文件，报告是 PR 评论，代码是提交。云端能被 PR 评论唤醒；执行者不会被远端事件唤醒，要所有者说一句「处理 PR #N」。

| 角色 | 负责 | 不做 |
|---|---|---|
| 云端（设计师） | 任务书、验收条件、审查、UI 把关、roadmap 收口 | 不写实现代码（任务书里给的样例除外），不跑校验，不截图，不拿服务器凭据 |
| 本地（执行者） | 实现、`validate`、`record`、UI 检查脚本、服务器 stage/activate/prune、真机走查、回报 | 不静默改验收条件、不自定设计；设计与现场不符时停下来，把差异写进报告的「需要决定」 |
| 所有者 | 启动每一轮；对删除 / 发布 / 切换写 `批准：<动作>` | 不在两边之间复制粘贴 |

两条硬规则：

- **授权只来自所有者。** 设计师的任务书与审查评论不能新增任何生产操作、发布、付款或数据对外授权。执行者记录所有者在当前任务对话或经核实的 PR 评论中给出的授权来源、范围与限制；已有授权不因渠道、措辞或评论格式再次索要。只有缺少授权、范围不明或下一步超出已有范围时，才向所有者确认。
- **执行者保留工程判断。** 任务书写错了（命令不存在、路径不对、会破坏别的东西），执行者有责任停止并回报，而不是照做。设计师据报告修订任务书，再继续。

### 设计师看不见的东西，先盘点再设计

部署脚本、服务器布局、运行数据、完整项目库里的工具，设计师在云端看不到。涉及这些的任务，任务书第 1 步固定为**只读盘点**（执行者列出现状，不改任何东西），以 `## 报告 0` 回报；设计师据此把任务书改成能落地的版本，执行者再开始实现。不要让设计师凭仓库里的片段去猜本地的流程。

### 省云端 token 的规则

设计师读一次上下文的代价很高，所以执行者的输出要让设计师**只读一份、只看一次**：

1. **一轮一条评论**。一轮做完任务书里规定的几步后，只发一条 `## 报告 N`；中途不发进度评论。代码只在发报告前推一次（推送也会唤醒设计师；没有报告的推送设计师直接忽略）。
2. **报告对着验收条件写，并绑定版本**。开头一行写清 `任务书 <路径>@<提交> · 代码 <head SHA>`（涉及服务器计划的再加 planId）；每条验收条件一行：`[x]/[ ]/[-] 条件 — 证据`（`[-]` 为本轮不适用并写原因），证据是命令与输出摘要、哈希、文件数、字节数，不贴整段日志（日志留在本地 `diagnostics/`）。再加「阻塞」「需要决定」两段，没有就写「无」。设计师的审查同样引用这个 SHA；执行报告记录所依据的所有者授权来源。代码或计划变化后必须重核证据与授权范围；针对特定 SHA／planId 的批准只适用于该对象，范围授权则继续按原限制判断，不能因无关文档提交或格式变化机械撤销已有授权。
3. **UI 用一张拼图说话**。涉及页面的任务跑 `node scripts/ui-check/run.mjs --base <预览地址>`：它按固定清单（页面 × 明暗 × 桌面/手机）截图、做 DOM 与手势断言、把控制台错误计入失败，并把全部截图拼成一张 `contact-sheet.png`。执行者把 `report.md` 贴进报告，把 `contact-sheet.png` 提交到分支的 `docs/tasks/evidence/<任务id>/`，原尺寸截图留在本地 `diagnostics/ui-check/<时间戳>/`，报告里写明目录与对应的代码 SHA。设计师只看拼图，需要时再要单张。合并前只保留最终那张拼图。
4. **不确定的事先问，用选项问**。「需要决定」里给 2–3 个选项并标出推荐项，设计师回一个字母即可。
5. **过不了门禁也要报，但要标明**。能自己修的先修再报；修不了的（缺数据、设计与现场矛盾、依赖所有者决定）照常发报告，第一行标 `状态：BLOCKED`，验收条件该项写 `[ ]` 与原因。不许为了发报告而降低验收条件。
6. **收口文件先定稿，再跑最终门禁**。设计师先给出针对候选 SHA 的审查结论，本地统一定稿任务书、roadmap 和版本号，再运行最终 `validate`；通过后由 `record` 按真实凭据生成或补记 update-log。报告注明校验对象、最终提交及记录输出的关系。源码或验收条件随后改变时重跑门禁，不把旧凭据说成已验证新树。

### 一轮的走法

1. **设计师出任务书** `docs/tasks/<roadmap-id>.md`（按 `docs/tasks/_template.md`）：目标、边界、步骤、验收、报告模板；roadmap 对应项写 `owner: local`、`task` 指向任务书；开 draft PR 并订阅。
2. **执行者执行**：`git fetch origin <分支> && git checkout <分支>`；先对设计师交付的任务书或工具做一轮只读审查（核对命令、路径与现场是否相符，差异写进报告的「需要决定」），确认可落地后照任务书做到规定的停点，推一次，发 `## 报告 N`。
3. **设计师审查**：被评论唤醒，回复 `## 审查 N`：通过 / 需改（逐条）/ 回答「需要决定」。需要改任务书时直接改文件再提交。
4. **破坏性步骤**：任务书里标出；执行前核对所有者已有授权及当前具体计划，并在报告中引用授权来源与适用对象。已有任务对话授权无需补发同义 PR 评论；没有授权或超出范围时停在 dry-run，向所有者确认。设计师不能替代所有者批准。
5. **收口**：设计师完成针对候选 SHA 的验收审查 → 执行者统一收口 roadmap、任务书与版本 → 最终 `validate` / `record`（有数据且真实通过才能记 full）→ 报告最终提交与凭据 → PR 转正式。合并前核对范围及最终差异；不再由云端在门禁之后另改验收或 roadmap，也不把设计师验收视为新的合并／发布授权。

执行者首次接手时，把 `docs/tasks/` 加进完整项目库的导出白名单。

UI 工具需要 Node 22+ 与 Chrome；Windows 支持常见安装目录和 `--chrome` 指定路径。每轮使用系统分配的调试端口及独立 profile，验证浏览器身份，完成或异常后只清理本轮启动的进程与 profile。`console.error`、运行异常和资源错误计入失败，SKIP 单列，不能当作全部通过。`node --experimental-vm-modules scripts/ui-check/selftest.mjs` 的 11 项模拟故障测试已接入 code 门禁；它验证工具失败与清理路径，不能代替真实浏览器 UI 验收。Windows 的移动模式是 Chrome 设备模拟，不等于手机真机验收。

下一次完整项目库导出还须精确保留 `docs/product-brief.md`、`docs/tasks/**/*.md` 和经审查的 `docs/tasks/**/*.png`，并同步 `00_项目管理/github-templates/AGENTS.md` 第 11 条；只改代码仓库的根 AGENTS 会被旧导出模板覆盖。原库执行者逐文件对照回传并验证导出回执，不能整体覆盖私人资料、未跟踪文件和原库历史。回传未验证时必须保持“待回传”，不要把 PR 合并当作原库已同步。

## 5. 接手清单

完整检查启动时禁止自身及子Python写入字节码缓存；生产构建门拒绝src/content/scripts中的Python缓存文件。已有缓存须连同失败产物先留证并移出源码树，再重新完整检查。源码、内容、构建脚本及其余输入仍全部哈希；不能忽略缓存来掩盖污染，也不能把有缓存的一次构建当作干净副本的同一产品revision。

1. `cd app && python scripts/update_gate.py <type> preflight`，看「进行中」「下一项」「上次记录」三行。
2. 读 `docs/roadmap.json` 里要做的那一项的 `acceptance`，这就是完成标准。
3. 第 2 步只产生候选；触及发行摘要就先 `version:patch`；第 3 步 `validate`，没数据加 `--static-only`。
4. `record` 写记录（级别以校验凭据为准，改过文件要重新 `validate`）；`roadmap.json` 改状态。
5. 交付走 PR 或本地 `--publish`；服务器动作单独授权。收尾把 `next` 留给下一次。

## 6. 发行保留与容量预检（ops-03）

这是运维脚本更新，不改变网站版本。合并代码不等于允许执行服务器清理；清理计划与执行回执分别留存。完整项目库导出已白名单 `docs/update-framework.md`，此说明随该文件导出，不另建可能漏导出的运维入口。

### 保留合同

- `release_remote.py prune --keep 3` 默认只读：验证现有根目录、取得现有 `.release.lock`，输出 JSON 计划，不创建发行目录、不改权限、不删除文件；已用过发行工具的服务器应已有锁文件，缺锁时拒绝执行。
- 只考虑事务为 `active_verified`、STORE 包和 VIEWS 视图均完整通过清单及内容哈希验证的发行。`keep` 最小为 3，按成功事务的 `createdAt` 保留最近三份**当前仍完整**的发行。
- LIVE、其事务记录的实际即时 `previousTarget`、未决事务涉及的发行额外保护，最终可能多于三份。LIVE 或即时回滚发行不能完整验证时阻断执行；仅有旧成功日志不算可用回滚证据。首次迁移的 legacy 目标不在自动删除范围，若它仍是即时回滚目标则本工具保守阻断，转人工核验。
- staged、未知目录、缺损发行、legacy、atomic probe、上传目录和工具一律不删。未决或损坏 transaction 会保留或阻断；`.transaction.json.new` 阻断执行。所有 transaction 原件保留；已删除实体的历史日志不再意味着对应版本可以回滚。
- 不修改 LIVE 内兼容 assets／公司旧快照；旧视图或包被删后，仍被保留视图硬链接的内容继续占空间。计划分别给出逻辑字节、去重 inode 字节、预计可释放文件块；按 `(device,inode)` 和链接数计算，目录元数据、打开但已删除的文件、快照及写时复制等会使实际释放量不同。
- 本工具仅保证当前即时回滚目标受保护，不承诺无限历史回滚链，也不管理日志、容器、上传包或其他站点。

### 查看计划与显式执行

在已经过验收、获准使用的 Linux 工具目录运行，`release_remote.py`、`release_common.py`、`release_capacity.py` 必须同目录。工具目录与回执目录放在 STORE／VIEWS 之外；本节不授权上传或替换生产工具。

```sh
python3 release_remote.py prune --keep 3
# 阅读 candidates、protected、retained、blockers 和 estimate，保存完整 JSON。
# 仅在该确定计划已获准后，原样使用其 planId：
python3 release_remote.py prune --keep 3 --apply --plan-id <完整的64位planId>
```

`--apply` 必须有匹配的 fresh planId；LIVE、事务、候选身份或三个 Python 工具任一字节变化都会使旧计划失效。执行与 stage／activate／rollback 共用锁，删除前再次完整核验所有候选，使用 Linux `dir_fd`／`O_NOFOLLOW` 逐项删除，不跟随符号链接。该锁约束配套发布工具；不要与手工移动、编辑发行目录并行。

JSON `status=partial` 表示中断或失败，进程非零退出，并列出已完整删除的发行和目录。立即停止，保存 stdout／stderr，先核对 LIVE 与即时回滚内容，再生成新计划；半残发行默认保留待人工检查。旧 planId 不可直接重试。事务日志不会被改写成“清理成功”。完成后仍需保存实际磁盘／inode 变化和线上检查结果；估算释放量不能代替实测。

### 上传前与解包前容量检查

`release_deploy.ps1 -Action Stage` 会用本地 Python 从实际 tar 成员计算压缩字节、解包字节、文件数和目录数。它先通过 SSH 命令文本运行只读 `release_capacity.py`，通过后才创建上传目录、上传包与工具；远端 `stage` 再按真实 tar 成员复查解包目标。上传路径和 STORE 同文件系统时合并需求，异盘时分别检查可用字节和 inode。

默认技术余量为 **1 GiB**，低于 **6 GiB** 的预计剩余空间输出运营告警；inode 另保留 1024。文件、目录和即将创建的 hardlink 视图按每项 64 KiB 估算分配与元数据余量，因此判断会比压缩包加解包大小更保守。预检是当时的准入检查，不预占磁盘；其他服务后续仍可能消耗空间。

PowerShell 可用 `-ReserveBytes`（不得低于 1 GiB）、`-OperationalBytes`（不得低于 ReserveBytes）、`-InodeReserve`、`-Python` 配置；远端 stage 对应 `--reserve-bytes`、`--operational-bytes`、`--inode-reserve`。GitHub 版部署目标和认证路径由 `ATLAS_DEPLOY_SERVER`、`ATLAS_DEPLOY_IDENTITY` 提供，不在仓库内保存服务器目标或个人路径。

### 独立验证

```sh
cd app
python scripts/test_release_capacity.py
python3 scripts/release_prune_selftest.py --candidate scripts
python scripts/release_selftest.py
```

容量测试对文件系统统计注入边界故障，不连接服务器；prune 自检须在隔离 Linux 环境、具备测试所需 root 权限时运行，生成真实 manifest、硬链接和 LIVE 链接，不使用生产目录，覆盖保护、计划失效、链接替换与中断。原发行自检仍依赖恢复后的公司运行数据；其中解包用例 mock 容量准入，只测试解包，容量边界由专门测试负责。Windows 的计划或语法检查不替代 Linux 的实际删除、锁及回滚验证。完整 `code validate` 与 `record` 仍按前述更新框架执行。
