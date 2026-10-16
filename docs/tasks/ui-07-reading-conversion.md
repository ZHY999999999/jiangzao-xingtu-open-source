# ui-07 · 试听与阅读转化面

**owner: local** · 报告到本任务的 PR · 破坏性步骤：无（见 §5）

## 1. 目标

产品简报已选的验证路径是「短内容 → 检索 → 免费档案 → 完整试听」（`docs/product-brief.md` §1、§3、§7），但现在这条路径在页面上有三处断点：

1. 讲解入口只是公司名旁一个 30px 圆形播放钮，没有文字，读者看不出这里有一段约 3 分钟的完整讲解；
2. 讲解播完只剩一行「播放结束」，没有下一步；
3. 5,500 多家没有经营解读的档案只写「经营说明正在逐步补充」，读者不知道已有核读样板可读；目录里也看不出哪家有讲解。

这一轮把三处接起来：**有文字的讲解入口、听完之后的「接着读」、无解读档案通往已核读样板的桥**，并让首页、目录、七问卡片、播放器对讲解的称呼一致。只做阅读路径上的引导，不做注册、付费、会员、埋点（这些在简报里仍是「待所有者决定」）。现在做，是因为 3–5 家样板验证要观察「检索 → 试听」，入口不可见时观察没有意义。

## 2. 边界

**只动这些文件**（`app/` 下）：

| 文件 | 改什么 |
|---|---|
| `src/lib/audio-label.ts`（新建） | 讲解类型与称呼的唯一来源，见 §3.1 |
| `src/components/CompanyAudio.tsx`、`src/styles/company-audio.css` | 讲解入口（§3.2）、听完之后（§3.3） |
| `src/components/CompanyDocument.tsx`、`src/styles/company-reading.css` | 给播放器传下一家与七问锚点；样板桥（§3.4） |
| `src/components/CompanyLibrary.tsx`、`src/styles/company.css` | 目录结果的讲解徽标（§3.5） |
| `src/components/CompanyQuickRead.tsx` | 「语音讲解」层的说明文字改用 §3.1 |
| `src/components/HomeValue.tsx`、`src/styles/home.css` | 样板卡徽标改用 §3.1，不改版式 |
| `vite.config.ts` 的 `virtual:editorial-catalog` 一段、`src/company-memberships.d.ts` 对应声明 | 目录条目加 `durationSeconds`，`audio` 判定改用 §3.1 |
| `scripts/ui-check/scenarios.mjs`、`scripts/ui-check/run.mjs` | 新增 `reading` 场景与两个数据参数（§3.6）；不改已有 27 项断言 |
| `package.json`、`package-lock.json`、`release-history.json` | 只经 `npm run version:patch` 改 |

仓库根下另动：`docs/tasks/evidence/ui-07-reading-conversion/`（`contact-sheet.png`、`report.md`）、`docs/roadmap.json` 的 ui-07 项、`record` 生成的 `docs/update-log/` 与 `docs/project-status.json`。

**不碰**：`content/company-editorial/*.json` 与 `public/audio/`（内容与录音不改）；`src/styles/tokens.css`（只用现有令牌，缺令牌写进「需要决定」）；星图 `App.tsx` 与 `components/atlas/`；运行数据；部署与服务器脚本；不加 npm 依赖。

**不许出现在新增代码里**：任何网络请求、`sendBeacon`、`localStorage` / `sessionStorage` 新键、cookie、表单或输入采集、第三方脚本。简报 §7 的指标与埋点方式待所有者决定，本任务不预埋。

**不许出现在新增文案里**：会员、订阅、解锁、付费、试用、限时、免费领取、收益、涨跌。简报 §3、§4 明确：样板能播放不等于会员权益已建立，试用方式待所有者决定。

**报告里不出现**：主机名、除 `127.0.0.1` 预览地址以外的 IP、密钥或凭据路径、完整项目库的绝对路径。

## 3. 设计

只用 `tokens.css` 现有令牌（颜色、`--fs-*`、`--sp-*`、`--r*`、`--fast`/`--ease`）；字号不低于 `--fs-xs`；可点区域不小于 44×44px；新增动效必须在 `prefers-reduced-motion: reduce` 下关闭。明暗两套主题都靠令牌自动适配，不写主题分支。

### 3.1 讲解称呼：`src/lib/audio-label.ts`

全站对讲解只有两种叫法，四处（首页样板卡、目录徽标、七问层、播放器入口）都从这里取，不各自拼字符串。

```ts
export type AudioKind = 'recording' | 'script' | 'none'
// url 非空 → recording；否则 browserTts 为真且 transcript 非空 → script；否则 none。
// 与 CompanyAudio 是否渲染的条件一致：kind 为 none 时播放器不出现。
export function audioKind(audio?: { url?: string; transcript?: string; browserTts?: boolean }): AudioKind
// 有限正数才给分钟数：Math.max(1, Math.round(seconds / 60))；否则 null。
export function audioMinutes(seconds?: number): number | null
export function audioLabel(kind: AudioKind, seconds?: number, form?: 'short' | 'long'): string
```

| kind | `short` | `long`（有时长） | `long`（无时长） |
|---|---|---|---|
| `recording` | 录音讲解 | 录音讲解 · 约 3 分钟 | 录音讲解 |
| `script` | 朗读稿 | 讲解稿 · 浏览器朗读 · 约 3 分钟 | 讲解稿 · 浏览器朗读 |
| `none` | 空串 | 空串 | 空串 |

硬规则：「录音」二字只属于 `recording`，即 `audio.url` 非空、真有一段录音文件的讲解。`script`（没有 `url`、只有 transcript、由浏览器朗读）的任何称呼都不许含「录音」，也不许出现在其入口、徽标、七问层或无障碍名里。新断言 R16 会在页面上逐处核对这一点。

`vite.config.ts` 的编辑目录插件改为调用 `audioKind`（可直接相对导入该文件），并输出 `durationSeconds`（取 `audio.durationSeconds`，无则 `null`）。`company-memberships.d.ts` 同步加字段。现有 `audio` 判定（只看 transcript）与播放器条件（要求 browserTts）不一致，以此为准收敛。

### 3.2 讲解入口（播放器收起态）

位置不变：`.cr-name-audio` 里、公司名之后。收起且未播放时，播放按钮 `.ca-play` 从单个圆钮变成**带文字的入口**，整块是同一个 `<button>`：

```
┌──────────────────────────────────┐
│ (▶)  听这家公司的讲解             │
│      录音讲解 · 约 3 分钟          │
└──────────────────────────────────┘
```

- 结构：`.ca-play` 内保留 `.ca-play-disc`，其后加 `<span class="ca-entry"><strong>听这家公司的讲解</strong><small>{audioLabel(kind, duration, 'long')}</small></span>`。只在 `!expanded` 时渲染 `.ca-entry`；展开后按钮回到现在的 44px 圆钮，控制条不变。
- 尺寸：入口 `min-height: 52px`，左右内边距 `--sp-3`，圆钮与文字间距 `--sp-2`；`1px solid var(--line)`、圆角 `var(--r)`、底色 `var(--panel)`；悬停与 `:focus-visible` 时边框 `var(--accent)`。主行 `--fs-sm`、500 字重、`var(--ink)`；次行 `--fs-xs`、`var(--muted)`。
- 无障碍名：收起且空闲时 `aria-label` 为 `听这家公司的讲解，{long 称呼}`（包含可见文字）；加载、播放、出错、播完四种状态沿用现有 `playLabel`。
- 不变量：点击之前 `<audio>` 不带 `src`（现有 `preload="none"` 与「手势后才挂 src」保留）；切换公司仍会卸载播放器。
- ≤600px：`.cr-name-audio .company-audio` 占满一行（`flex-basis: 100%`），入口在公司名下方、宽度 100%；内容左对齐（`justify-content: flex-start`），圆钮贴左、文字紧随，不居中。
- 收起即复位：`collapse()` 除暂停外把 `ended` 与 `error` 清回初始值，使收起后的入口回到空闲态（文字、图标、无障碍名都是「听这家公司的讲解」），不出现可见文字是「听讲解」而无障碍名是「重新播放」的错配。

### 3.3 听完之后：「接着读」

播放结束（录音 `ended` 或朗读 `utterance.onend`）且播放器展开时，在状态行下方出现 `.ca-next`；重新播放、收起播放器或切换公司时消失。

```
接着读
[对照七个答案 ↓]   [查看讲解依据 · 7 条]   [下一家：浪潮信息 · 讲解稿 · 浏览器朗读 →]
```

| 动作 | 元素 | 行为 | 何时隐藏 |
|---|---|---|---|
| 对照七个答案 | `<a class="ca-next-quickread" href="#cq-title">` | 用现有 `jumpTo` 滚到七问卡片标题；焦点随之移动 | 从不 |
| 查看讲解依据 · N 条 | `<button class="ca-next-sources">` | 调 `onSources(audio.sourceIds)`，打开现有资料出处抽屉 | 无 `onSources` 或 `sourceIds` 为空 |
| 下一家：{名称} · {short 称呼} | `<a class="ca-next-company" href="#/company/{code}">` | 普通路由跳转 | 目录里除当前公司外没有别家 |

- 「下一家」由 `CompanyDocument` 计算后经新 prop `nextCompany?: { code; name; audio; durationSeconds }` 传入：取 `virtual:editorial-catalog` 中当前公司之后的第一项，到末尾则回到开头，排除当前公司。播放器本身不读目录。
- 版式：标题「接着读」`--fs-xs`、`var(--muted)`；三个动作横排、`gap: var(--sp-2)`、可换行；每个动作 `min-height: 44px`、文字 `--fs-sm`、颜色 `var(--accent)`、无底色，悬停底色 `var(--accent-soft)`。≤600px 竖排、每项占满一行。
- `.ca-next` 不加 `role="status"`，避免与现有状态行重复播报；状态行仍报「播放结束」。

### 3.4 样板桥：无解读档案通往已核读公司

只在 `!EDITORIAL_CODES.has(company.code)` 时渲染（按代码判定，不看 `editorial` 加载状态，避免加载中闪现或加载失败误显）。位置：`#company-overview` 末尾，即 `cr-content-gap` 段之后；不挤占七问卡片。

```
经营解读 · 逐家补充
这家公司的七个问题还没有完成核读。已有 {catalog.length} 家完成核读，可以先看一份完整档案是什么样子。
┌──────────────────────┐ ┌──────────────────────┐
│ 601138               │ │ 000977               │
│ 工业富联              │ │ 浪潮信息              │
│ {tagline，最多两行}    │ │ {tagline，最多两行}    │
│ 录音讲解 · 约 3 分钟  ↗ │ │ 讲解稿 · 浏览器朗读 …  ↗ │
└──────────────────────┘ └──────────────────────┘
```

- 结构：`<aside class="cr-sample-bridge" aria-labelledby="cr-sample-bridge-title">`，标题 `<h2 id="cr-sample-bridge-title">` 即「经营解读 · 逐家补充」；卡片是 `<a class="cr-sample-card" href="#/company/{code}">`，最多 3 张，按目录顺序取，排除当前公司。
- 版式：`grid-template-columns: repeat(auto-fill, minmax(240px, 1fr))`、`gap: var(--sp-4)`；卡片 `var(--panel)` 底、`1px solid var(--line)`、`var(--r-lg)` 圆角、`--sp-4` 内边距。代码 `var(--mono)` `--fs-xs` `var(--muted)`；名称 `--fs-lg` 600；tagline `--fs-sm` `var(--muted)` 两行截断；底行左为 `long` 称呼（`var(--accent)`，无讲解则写「经营解读」），右为「阅读档案」与 `IconArrowUpRight`。悬停边框 `var(--accent)`。
- ≤600px：单列；卡片收成一行（代码 + 名称 + 箭头，`min-height: 56px`），隐藏 tagline 与称呼。
- 目录为空（`catalog.length === 0`）时整块不渲染。

### 3.5 目录与首页徽标

- 公司目录结果（`CompanyResult`）：现有「经营解读」徽标之后，按目录映射追加第二个 `<em class="cl-audio-badge">{short 称呼}</em>`；样式复用现有 `.cl-result-industry em`。紧凑态（档案页内的相关公司搜索）同样显示。
- 首页样板卡（`HomeValue`）：`.hv-sample-code em` 文字改为 `long` 称呼，版式不动。
- 七问卡片底部「语音讲解」层的说明改为 `long` 称呼；无讲解仍写「暂无」。

### 3.6 `ui-check` 新场景 `reading`

`run.mjs` 新增两个参数并写进 `data`：`--plain`（默认 `000001.SZ`，必须是没有经营解读的公司）与 `--tts`（默认 `000977.SZ`，讲解为浏览器朗读的公司）；录音公司沿用 `--company`（默认 `601138.SH`）。`--only` 自动接受 `reading`。已有 `desktop`、`mobile` 场景与 27 项断言不改。

`reading` 场景的断言（名称照抄，便于逐项对照）与截图：

| # | 视口 / 主题 | 断言 | 判定 |
|---|---|---|---|
| R1 | 1440 / 浅 | 讲解入口有文字 | `#/company/{company}` 上 `.ca-play .ca-entry` 文本含「听这家公司的讲解」与「录音讲解 · 约」 |
| R2 | 同上 | 入口命中区 ≥44px | `.ca-play` 宽高均 ≥ 44 |
| R3 | 同上 | 点击前不加载录音 | `.company-audio audio` 无 `src` 属性 |
| — | | 截图 `reading-entry-light` | |
| R4 | 同上 | 真实播放开始 | 点击 `.ca-play` 后 15s 内 `audio.paused === false` 且 `currentTime > 0` |
| R5 | 同上 | 播完出现「接着读」 | 把 `currentTime` 设为 `duration - 0.5` 后 15s 内 `.ca-next` 可见，且含三项动作 |
| R6 | 同上 | 下一家指向另一家已核读公司 | `.ca-next-company` 的 `href` 为 `#/company/<code>`，`<code>` ≠ 当前且在首页样板列表中 |
| R7 | 同上 | 讲解依据可打开 | 点击 `.ca-next-sources` 后 `.cr-source-drawer[open]` 内 `.cr-source-card` ≥ 1；关闭抽屉 |
| — | | 截图 `reading-ended-light`（抽屉关闭后） | |
| R8 | 同上 | 对照七个答案 | 点击 `.ca-next-quickread` 后 `#cq-title` 顶部在视口内 |
| R9 | 1440 / 深 | 朗读稿入口 | `#/company/{tts}` 上 `.ca-entry` 含「讲解稿 · 浏览器朗读」，且页面无 `.company-audio audio` 元素 |
| — | | 截图 `reading-tts-dark` | |
| R10 | 1440 / 浅 | 无解读档案有样板桥 | `#/company/{plain}` 上 `.cr-sample-bridge` 可见，卡片 1–3 张，每张 `href` 指向样板公司且不等于 `{plain}` |
| R11 | 同上 | 有解读档案无样板桥 | `#/company/{company}` 上没有 `.cr-sample-bridge` |
| — | | 截图 `reading-plain-bridge-light` | |
| R12 | 1440 / 浅 | 目录显示讲解徽标 | `#/companies` 上 `{company}` 结果含「录音讲解」，`{tts}` 结果含「朗读稿」 |
| R13 | 390 / 深 | 手机 · 入口占满一行 | `.ca-play` 与 `.cr-name-audio` 宽度差 ≤ 1px，且 `.ca-play` 顶部在 `h1` 底部之下 |
| R14 | 390 / 深 | 手机 · 播完无横向溢出 | 重复 R4–R5 后 `.ca-next` 可见且 `scrollWidth ≤ 390` |
| — | | 截图 `mobile-reading-ended-dark` | |
| R15 | 390 / 浅 | 手机 · 样板桥单列无溢出 | `#/company/{plain}` 上卡片 `x` 坐标全部相同且 `scrollWidth ≤ 390` |
| — | | 截图 `mobile-plain-bridge-light` | |
| R16 | 1440 / 浅 | 朗读稿不称录音 | 讲解为 `script` 的 `{tts}` 在四处都不含「录音」：档案页 `.ca-play` 的文本与 `aria-label`、`.cq-layers`、`#/companies` 上它的目录结果、`#/home` 上指向它的样板卡；同时录音公司 `{company}` 的 `.ca-entry` 含「录音讲解」 |

- 播放用 `page.click`（CDP 鼠标事件，算用户手势）。**不许**用 `dispatchEvent(new Event('ended'))` 之类绕过真实播放；无头 Chrome 确实无法出声播放时，R4/R5/R14 记 `[ ]` 并在报告第一行写 `状态：BLOCKED`，在「需要决定」给选项。
- 「样板公司」集合从页面取（`#/home` 上 `.hv-sample-list a` 的 `href`），R6、R10 用它判定，不写死 `--company`/`--tts` 两家；新增样板后断言不应因此失败。
- 场景结束前把主题恢复为浅色、清除本场景改过的媒体模拟（`Emulation.setEmulatedMedia` 传空 `features`），不影响后续场景。
- 合计 27 + 16 = 43 项，截图 10 + 6 = 16 张，拼图仍为 4 列。

## 4. 步骤

命令都在 `app/` 下执行。

1. **接手与基线**。`git fetch origin <本分支> && git checkout <本分支>`。本分支叠在 PR #11 的分支上（任务模板、`ui-check` 与产品简报在那里）；若 PR #11 已合并，先 `git merge origin/main` 再继续。`docs/roadmap.json` 可能与 #11 收口时的重排冲突：冲突时整份以 main 为准（`git checkout --theirs docs/roadmap.json`），合并完成后再按本分支原内容补登 ui-07 条目（字段与 acceptance 不改，`pr` 仍为 #13），JSON 能解析、门禁 `check_docs` 无报错后单独提交。不要手工逐行拼两边的排序。记下此刻的 head SHA 作为 `<基线>`，写进报告 1，之后各轮沿用。然后`python scripts/update_gate.py code preflight`，缺数据按 README 用 `scripts/restore_runtime.py` 恢复；`npm run build && npm run preview -- --host 127.0.0.1 --port 5181`，跑 `node scripts/ui-check/run.mjs --base http://127.0.0.1:5181/`，应为 27/27 PASS。基线报告留在本地 `diagnostics/ui-check/<时间戳>/`，不提交。核对 `--plain` 默认的 `000001.SZ` 在本机公司索引里且不在 `content/company-editorial/`；不符就换一家并在报告里写明。
2. **先写断言**。按 §3.6 改 `run.mjs` 与 `scenarios.mjs`，不改任何页面代码，再跑一次 `ui-check`：已有 27 项仍 PASS，新的 R1–R16 中依赖新界面的项应为 FAIL（R3、R11 这类现状即成立的可以 PASS）。逐项记下哪些 FAIL，证明断言真的在测东西。
3. **统一称呼**。新建 `src/lib/audio-label.ts`（§3.1），改编辑目录插件与类型声明，接入首页样板卡、目录徽标、七问层（§3.5）。`npx tsc --noEmit -p tsconfig.app.json`、`npm run build`（覆盖 `vite.config.ts`）与 `python scripts/test_styles.py` 通过。
4. **讲解入口**。按 §3.2 改 `CompanyAudio.tsx` 与 `company-audio.css`、`company-reading.css` 中 `.cr-name-audio` 的手机规则。重新构建预览、跑 `ui-check`。

**停点 1**：推一次，发 `## 报告 1`。验收里 R1–R4、R9、R12、R13、R16 应已 PASS，R5–R8、R10、R14、R15 仍 FAIL 属预期，逐项写明；附第 2 步「断言先失败」的清单。设计师回 `## 审查 1` 后再继续。

5. **接着读**。按 §3.3 改 `CompanyAudio.tsx`（新 prop、`.ca-next`）、`CompanyDocument.tsx`（计算 `nextCompany`）、`company-audio.css`。
6. **样板桥**。按 §3.4 改 `CompanyDocument.tsx` 与 `company-reading.css`。
7. **完整 UI 验收**。`python scripts/test_styles.py`、`npx tsc --noEmit -p tsconfig.app.json` 通过后重新构建预览，跑完整 `ui-check`：43 项全部 PASS、0 SKIP、控制台错误 0。把 `contact-sheet.png` 与 `report.md` 复制到 `docs/tasks/evidence/ui-07-reading-conversion/`（只保留这一轮最终的一份），原尺寸截图留本地。

**停点 2**：推一次，发 `## 报告 2`，把 `report.md` 全文贴进报告。设计师只看拼图做 UI 审查，回 `## 审查 2`：通过，或逐条需改（需改则回到第 5–7 步，修完再发 `## 报告 3`，编号顺延）。

8. **收口**（仅在审查结论为「通过」之后）。`npm run version:patch -- "公司档案：讲解入口有文字，听完可接着读，无解读档案可直达已核读样板"`；版本号变了网站代码就变了，所以重新构建并再跑一次 `ui-check`，用新拼图替换 evidence 目录里的旧拼图。
9. **最终门禁**。`python scripts/update_gate.py code validate`（有运行数据跑完整；没有则加 `--static-only` 并在报告写明待补跑项）。FAIL 不绕过。
10. **记录与 roadmap**。`python scripts/update_gate.py code record --summary "<同第 8 步>" --rollback "revert 本 PR；上一网站版本 <升级前版本号>" --next "<给下一次接手的话>"`；`docs/roadmap.json` 的 ui-07 改 `done`，填 `pr`、`version`、`updateLog`，`notes` 写真机未验项。推送后 `record --amend <记录 id> --pr <本 PR URL>`，再推一次。

**停点 3**：发 `## 报告 N`（最终）：写清 validate 的级别与凭据对应的提交、record 生成的记录 id、最终 head SHA；然后把 PR 转为正式。不部署、不 stage。

## 5. 破坏性步骤

无。本任务只改网站代码与验收脚本，不连接服务器、不删除文件、不发布数据。`version:patch` 可随 revert 撤回，不需要所有者批准。合并后是否发行到服务器是另一项动作，需要所有者另行授权，不在本任务范围。

## 6. 验收

- [ ] `src/lib/audio-label.ts` 是讲解称呼的唯一来源：`git grep -n "有录音讲解\|讲解稿 · 浏览器朗读\|录音约" -- app/src` 只命中 `audio-label.ts`
- [ ] 编辑目录插件的 `audio` 判定与播放器渲染条件一致：两家样板在首页、目录、七问层、播放器入口的称呼相同（R1、R9、R12 与拼图可核）
- [ ] 有 `audio.url` 的称「录音讲解」，只有 transcript 的称「讲解稿 · 浏览器朗读」/「朗读稿」，后者四处均不含「录音」（R16）
- [ ] 讲解入口有文字、命中区 ≥44px、点击前不挂 `src`（R1–R3）；真实播放可开始（R4）
- [ ] 播完出现「接着读」三项动作，下一家指向另一家样板，依据抽屉可打开，七问锚点可达（R5–R8）
- [ ] 无解读档案出现样板桥（1–3 张、不含自身），有解读档案不出现（R10、R11）
- [ ] 390px 明暗两套下入口占满一行、播完与样板桥均无横向溢出（R13–R15）
- [ ] 已有 27 项断言未改动且全部 PASS：`git diff <基线>..HEAD -- app/scripts/ui-check/scenarios.mjs` 只有新增的 `reading` 场景
- [ ] 新增代码无网络请求与存储：`git diff <基线>..HEAD -- app/src app/index.html | grep '^+' | grep -E "fetch\(|sendBeacon|localStorage|sessionStorage|document\.cookie|<script"` 无输出
- [ ] 新增文案无商业承诺用语：`git diff <基线>..HEAD -- app/src | grep '^+' | grep -E "会员|订阅|解锁|付费|试用|限时|免费领取|收益|涨跌"` 无输出
- [ ] 未触碰边界外文件：`git diff --name-only <基线>..HEAD` 只列出 §2 表内文件
- [ ] `python scripts/test_styles.py` 与 `npx tsc --noEmit -p tsconfig.app.json` 通过
- [ ] `ui-check` 全部 PASS（43/43、0 SKIP、控制台错误 0），contact-sheet 已提交到 `docs/tasks/evidence/ui-07-reading-conversion/`，`report.md` 同目录，且对应收口后的代码 SHA
- [ ] 已升版本并写入 `release-history.json`；`code validate` 在升版本后的树上通过，级别（full / static）如实写进 `record`
- [ ] `docs/roadmap.json` 的 ui-07 为 `done`，`pr`、`version`、`updateLog` 已填

`<基线>` 指第 1 步记下的分支 head（执行开始前、任何代码改动之前）。

## 7. 报告模板

```
## 报告 N
任务书 docs/tasks/ui-07-reading-conversion.md@<提交> · 代码 <head SHA>
（BLOCKED 时本行之前加一行：状态：BLOCKED）
数据参数：--company 601138.SH --tts 000977.SZ --plain <实际使用的代码>
ui-check：<PASS 数>/<总数> PASS · <SKIP 数> SKIP · 控制台错误 <数> · 本地目录 diagnostics/ui-check/<时间戳>/
验收：
- [x] 条件 — 证据（命令 + 输出摘要 / 断言编号 / 文件数）
- [ ] 条件 — 未做 / 原因
- [-] 条件 — 本轮不适用 / 原因
阻塞：无
需要决定：无（或：A … / B …（推荐）/ C …）
```

