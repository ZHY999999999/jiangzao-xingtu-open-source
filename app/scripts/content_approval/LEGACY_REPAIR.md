# L 单写队列中的旧七问表达返修

这是生产协议的公开说明。以下 controller 与测试命令仅在所有者的完整私人生产目录（TASK_ROOT）运行；本仓库的 `content_approval` 是构建所需的校验实现镜像，不含公司原件、队列状态、租约或私人测试辅助文件，不能在此镜像目录启动生产或直接复跑完整私人测试组。公开源码的验证入口为 `app/scripts/test_overview_catalogue.py` 与 `app/scripts/test_catalogue.py`。

本通道只为已有且完成独立内容及实际页面验收的旧七问包生成不可变新版本，修订叙述视角。它不启动 M/H 深化，不迁回旧七问批量调度，不改变 L 冻结索引、L 完成数或工业富联只读边界。

## 领单

仅通过 controller 操作，不手改 queue-state/config。当前有效 L 或其他返修租约必须正常完成或按真实阻断记录后，才能新领返修。

```powershell
python -B queue_controller.py repair-legacy --run-id <本轮UUID> --code 000333.SZ --base-bundle inbox/000333.SZ/v004 --base-manifest <旧包manifest的SHA256> --producer-id /root --reason "仅修订证据边界中的叙述视角，事实及朗读正文保持原字节"
```

可选 `--repair-id <UUID>`；不传时按 run-id、公司和基包确定稳定标识。同 run、同请求重复调用续用同一租约和版本；提交后返回 `already_submitted`，不重新领单。不同 run 不能冒用 repair-id，即使前一租约过期；新的请求会分配新的全局版本号，不复用他人的保留版本。真实阻断的 retry-after 未到不能重开。

基包必须是该公司最新旧七问版本，经过真实机械校验、当前有效独立 review、candidate 和 page-review 全链哈希验收。存在更晚的未审/返修旧七问或未知层级版本时，不能跳过它回退基包。L 版本与旧七问版本分层识别，序号仍取全部层级与保留租约的最大值加一。

仅收到 `assigned` 后，写返回的 `bundlePath`。同一个 `state.lease` 承载返修；`purpose=legacy_reader_voice_repair`、`queueTier=L`、`contentTier=null`。90 分钟租约、`renew --run-id` 和同 run 的 `next` 恢复仍有效。

## 新包与提交

旧包保持原字节。新包保持旧七问 reader/evidence/sources/manifest/ready 合同，reader 不添加 contentTier，ready 不添加 producer。原 PDF 与原音频按实际位置和 SHA 只读复用，不能以来源存在代替实际核读。保留读者稿、reader 的 introduction/answers/audioScript 或音频时，差异审计写清实际字节比较结果。

领单返回 `requiredPayload`，将完整对象写入新包 `producer-repair.json`，列入 manifest：

```json
{
  "schemaVersion": 1,
  "jobId": "atlas-company-pilot-20261002",
  "code": "000333.SZ",
  "producer": {"id": "/root", "runId": "<领单run UUID>"},
  "repair": {
    "purpose": "legacy_reader_voice_repair",
    "repairId": "<领单repair UUID>",
    "leaseId": "<领单lease UUID>",
    "baseBundlePath": "inbox/000333.SZ/v004",
    "baseManifestSha256": "<旧包manifest SHA256>",
    "reason": "<与领单相同的返修原因>"
  }
}
```

仅表达修订也要保留逐项差异记录，例如 `semantic-diff.json` 中记录 claimId、字段/index、before、after；该文件列入新 manifest。来源复用定位/哈希另列入受 manifest 保护的 source-reuse.json。语义及原件核验由独立审稿人完成，不把生产者自检当批准。

封包后运行机械器，再执行：

```powershell
python -B queue_controller.py done --run-id <同一run UUID>
```

`done` 必须核新包确为七问、producer/run/lease/repair 身份全部匹配、基包及其批准/页面未漂移、公司版本集合未被并行改动。失败保留租约；成功将新 manifest、ready、producer-repair 哈希记入独立 `repairReceipts`，只表示提交。随后 `next` 自动回 L，不存在全局切换步骤。返修的 block 只记返修回执，不阻塞对应公司的 L 项。

## 不可变失败版本的明确重试

机械失败或独立 needs_revision/insufficient_evidence 不能通过覆盖原版本修复。使用同一原已批 base，加 `--retry-of <前次失败repairId>` 再领一次新 attempt；返回新的 repairId、leaseId 和全局下一版本。原失败包及其失败证据保持原字节。

```powershell
python -B queue_controller.py repair-legacy --run-id <本轮UUID> --code 000333.SZ --base-bundle inbox/000333.SZ/v004 --base-manifest <原已批base的SHA256> --producer-id /root --reason "修复上一版明确指出的表达问题" --retry-of <失败repairId>
```

有效旧租约仍须先用真实原因 block 或正常 done；不抢占。重试只允许三种可核依据：已经封包且机械检查真实失败；真实匹配的独立 needs_revision/insufficient_evidence；或已到 retry-after 的明确 block 回执。客观机械失败允许领取修复新版本，原来的阻断等待不冒充新版本已经通过。有效但 awaiting_review 的版本、已批准版本、未知新版本不能用 retry-of 绕过。

controller 将失败包全部文件的稳定快照 SHA、失败性质与匹配审核哈希写入 failureChain。新 payload 的 repair 增加 `retryOf`、`failedBundlePath`、`failedPackageSha256` 三个字段，仍直接采用领单返回的 requiredPayload。领取、提交和审查采用时再次核对失败链；旧失败包或其失败依据漂移则拒绝。只允许跳过这条可追溯失败链中的具体版本，其他更晚旧七问/未知层级继续阻断。

retry 仍以原已批 base 做事实及朗读保留比较；独立附页 semanticDiff.reason 还须说明对前次实际错误的逐项修复。sidecar 结构不另加 retry 字段，新 manifest 已绑定含失败链指向的 producer-repair.json，控制器真实提交回执绑定同一 payload 哈希。通过新版本的普通独立审查、三项附页及真实页面验收后，照常 next 返回 L。

## 独立审查附页

旧版 `review.json` 合同保持不变，不直接加入 checks。同目录额外写严格结构 `repair-review.json`：

```json
{
  "schemaVersion": 1,
  "jobId": "atlas-company-pilot-20261002",
  "code": "000333.SZ",
  "bundlePath": "inbox/000333.SZ/v006",
  "manifestSha256": "<新包manifest SHA256>",
  "baseBundlePath": "inbox/000333.SZ/v004",
  "baseManifestSha256": "<旧包manifest SHA256>",
  "producer": {"id": "/root", "runId": "<领单run UUID>"},
  "leaseId": "<领单lease UUID>",
  "repairId": "<领单repair UUID>",
  "reviewSha256": "<同目录review.json实际字节SHA256>",
  "reviewer": "<实际独立审稿人，与review.json一致且不等于作者>",
  "reviewedAt": "<不早于review.json的带时区实际时间>",
  "checks": {
    "narratorAudience": {"decision": "passed", "reason": "<实际说话关系判断>"},
    "comprehension": {"decision": "passed", "reason": "<实际阅读判断>"},
    "factualFidelity": {"decision": "passed", "reason": "<实际原件及语义核验>"}
  },
  "semanticDiff": {
    "decision": "passed",
    "reason": "<逐项差异核对结果及差异文件路径/SHA>",
    "changedPaths": ["evidence.json"],
    "factsUnchanged": true,
    "sourceReuse": "<实际原件路径、SHA和复用核验结果>",
    "audioDisposition": "<实际朗读正文/音频保留或变更情况>"
  }
}
```

changedPaths 中各项必须是新 manifest 中存在的安全相对路径；不要求把新增运行元数据伪称为正文修改。发现事实需要改变、表达未通过或差异未核完，应在普通 review.json 返回 needs_revision 或 insufficient_evidence，不填写虚假的 passed。

`queue.find_review` 对带 producer-repair.json 的新包强制核真实 done 回执和附页。附页缺失、未通过、自审、绑定错或被删改都不能返回有效 approved；已保留为返修的版本删掉 producer-repair.json 也不能回落为旧历史合同。后来有效 review 的附页失效不能回退较早的通过记录。无返修标记且未被返修租约保留的历史旧包保持原合同。

build_candidate 本身不创建或认证审批。实际生成前须用 queue/approval_chain 检查当前批准链；后续链仍须调用 find_review，并保存其 repairReviewPath/repairReviewSha256。新候选生成后仍做真实桌面、窄屏、展开证据页面检查，绑定新的 HTML 哈希；附页不能替代 page-review、整站装入或发布验收。

## 隔离回归

```powershell
python -B -m unittest test_package_check test_build_candidate test_queue_controller test_queue_legacy_repair
```

全部用临时目录及明确标注的合成夹具。运行这些测试不会领取真实公司、更新真实 queue-state/config、批准真实稿件或改动任何旧包。
