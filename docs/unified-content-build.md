# 统一公司阅读源码与恢复

## 第一层接入

第一层概览使用 `content/company-overview/<code>.json`，包含公司做什么、收入来自哪里、带证据引用的生意模式图。它与原七问正文分别保存、分别审批；同一家公司可以同时拥有两层，目录的可读公司数只计一次。`content-selection.json` 的 `overviews` 与 `sevenQuestions` 分别绑定对应公开 JSON 的哈希。

概览在公司页先展示；已存在的详细解读保留原资料日期、正文和朗读内容。来源与细节可展开查看。概览没有录音时不生成虚构音频入口；工业富联原标杆保持只读。第一层不能通过填空 Q3–Q7 冒充完整七问，原七问批准也不能折算成第一层完成。

构建同时核对两个层级的当前批准链、页面验收和投影。公共快照中的 `approvedOverview` 只用于不可发布的恢复构建；正式发布仍须使用当前私人批准链。源码导出包含被选择的概览文件、两层选择配置、公开快照及其构建模块。旧详细解读的叙述修订同样需要新版本和独立复核，不能直接修改已批准的公开 JSON。

本说明不证明第一层已经上线。候选页验收、整站装入、真实发布与 Git 同步须分别以实际回执确认。

## 1.2.19 整合起点

统一候选以 main 的 `208cc11d82b059abba44032a6746846b20ee69fc` 为基线，按文件合入独立1.2.16阅读优化、PR13最新审查要求，以及14份已验收七问正文。版本1.2.19是这次整合的标识；是否已经公开发布以真实发行回执为准，本文件不证明上线。

主分支的裸板块代码修复保留。当前七问正文不会加载旧浪潮信息的编辑稿或旧朗读稿；浏览器朗读只连接本页简介及七个答案的原文，不补事实、不估计时长。工业富联保留原有录音与旧标杆状态。首页、听完继续阅读和未完成档案的样板桥使用同一份实际目录和样板顺序。

## 公开源码恢复

`scripts/export_source.py` 的白名单包含 TypeScript 构建模块、`content-selection.json`、全部选定七问JSON、`content-approval-snapshot.json`和必要校验模块。公开快照仅记录内容、来源版本的哈希和公开目录；不含内部审查记录、PDF、研究库、机器路径或凭据。它是已记录版本的重建依据，不是新的审批权。

先在干净副本中执行 `python scripts/export_source.py --verify`，然后按README用既有、哈希匹配的运行数据包恢复。原 `scripts/restore_runtime.py` 保留整包校验、精确文件集合、禁止越界/链接/覆盖等护栏。运行数据包不进入Git。

```powershell
python scripts/restore_runtime.py --archive '<OWNER_RUNTIME_ARCHIVE>'
cd app
npm ci
$env:ATLAS_APPROVAL_MODE='snapshot'
npm run build
```

恢复模式显式验证公共批准快照、正文文件集合、正文SHA、目录SHA与当前公司索引。它产生 `releaseStatus=public-snapshot-unpublished`，不连接私人生产队列，不声称重新审核。正式发行门必须拒绝此模式，不能用它跳过当前批准链。

构建输入必须是干净源码。完整检查会禁止自身及子Python生成字节码；组装门对src、content和scripts中的`__pycache__`、`.pyc`及`.pyo`硬拒绝，大小写均检查，不能把生成缓存算成源码版本或静默忽略。发现旧缓存时先保留失败构建与缓存证据，再把这些自有生成物移出源码树；其他全部输入仍逐字绑定。生产与公开恢复必须分别真实构建，并核产品revision和运行组件的一致性。

源码、运行组件、正文和产品revision均应与对应生产候选逐项比对。恢复模式的发布资格metadata与生产模式不同，因此含有该metadata的编译资源和version.json可能不同；这些差异必须明确列出，不能仅凭版本号或revision宣称完整dist相同。

## 当前批准生产

正式构建由负责生产的协调者提供 `ATLAS_CONTENT_PILOT`，指向具有真实版本包、机械检查、独立事实审查、候选页和页面验收记录的运行库。可用 `ATLAS_PUBLIC_ROOT` 指向已冻结公共目录，默认为app/public；`ATLAS_LEGACY_ROOT`可指定工业富联冻结原件基线。这些机器配置只通过当前进程环境传入，不进源码。

```powershell
$env:ATLAS_APPROVAL_MODE='live'
$env:ATLAS_CONTENT_PILOT='<PRIVATE_CURRENT_PRODUCTION_ROOT>'
$env:ATLAS_PUBLIC_ROOT='<READ_ONLY_FROZEN_PUBLIC>'
python -B scripts/verify_catalogue.py --write-public-snapshot
npm run build -- --outDir '<THIS_RELEASE_DIST>'
```

生成公开快照也必须实际通过原当前批准链；重建模式不能生成新的批准快照。生产构建仍在配置、生成bundle、最终落盘三个阶段重验原门禁，检测全部review JSON及队列漂移，核每份投影与当前批准版本，要求内容只进入对应懒加载chunk，最终再次核落盘字节。没有改变原件检查或批准条件。

候选构建、独立代码审查、真实浏览器验收、正式发行与Git同步分别留证。实现者自测或公开重建通过不等于当前生产批准。网页验收应等待 `.sq-reading` 或实际讲解入口加载完成；`networkidle`不能替代内容已加载的断言。
