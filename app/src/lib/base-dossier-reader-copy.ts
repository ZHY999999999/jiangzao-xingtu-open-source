// Display copy for reviewed legacy dossier sentences only. The frozen source
// data, dates, evidence status and source IDs are not changed. Do not apply this
// mapping to approved overview/seven-question content or original quotations.
type HistoryText = { date: string; title: string; text: string }
type HistoryCopy = HistoryText & { code: string; readerText: string }

const historyCopies: readonly HistoryCopy[] = [
  {
    code: '600588.SH', date: '1988', title: '从财务软件起步',
    text: '本地公司简介将业务起源追溯到1988年的财务软件。这是前身业务沿革的公司表述，不是当前上市主体的注册日期；尚未核读对应历史原件。',
    readerText: '公司简介称，用友的前身业务于1988年从财务软件起步。这不是当前上市主体的注册日期；星图尚未核对相应历史原件。',
  },
  {
    code: '600588.SH', date: '1995-01-18', title: '上市主体注册',
    text: '公司资料记录的注册日期为该日。将这一法律主体节点与前身业务起源分开，避免把两种口径混成同一个创办时间。',
    readerText: '公司资料记载，当前上市主体于1995年1月18日注册。这是法律主体的登记时间，与前身业务起步时间不同。',
  },
  {
    code: '600588.SH', date: '1998', title: '拓展企业管理软件与服务',
    text: '本地简介记载，从这一年开始进入企业管理软件与服务领域。它说明叙述中的业务扩展方向；具体产品版本和转型成效不由这段简介证明。',
    readerText: '公司简介称，用友从1998年开始进入企业管理软件与服务领域。这段简介未说明具体产品版本，也不足以判断转型成效。',
  },
  {
    code: '600588.SH', date: '2001-05-18', title: 'A股上市',
    text: '股票基础资料记录用友于该日上市。云服务转型、重要产品发布和组织调整仍待建立附原始出处的后续年表。',
    readerText: '股票基础资料记载，用友于2001年5月18日上市。星图尚未逐条核对其后云服务转型、重要产品发布和组织调整的原始资料，因此这里还不是完整的发展年表。',
  },
  {
    code: '600036.SH', date: '1987-03-31', title: '主体注册',
    text: '公司资料的setup_date字段记录注册日期为该日。该字段定位法律登记，不应与公司简介记载的开业或成立节点直接合并。',
    readerText: '公司资料记载，主体注册日期为1987年3月31日；这与公司简介中的成立或开业日期是不同口径。',
  },
  {
    code: '600036.SH', date: '1987-04-08', title: '公司简介记载的成立节点',
    text: '本地简介将该日记为成立日。与注册日期并列保留不同口径；由于未核读当时登记和开业原件，本条保留为公司表述。',
    readerText: '公司简介将1987年4月8日记为成立日。星图尚未核对当时的登记和开业原件，因此这一日期仍属于公司自述，与主体注册日期分别理解。',
  },
  {
    code: '600036.SH', date: '2002-04-09', title: 'A股上市',
    text: '股票基础资料及公司简介均记录该日在上海证券交易所挂牌。其他发行数量与历史排名未用于解释当前经营。',
    readerText: '股票基础资料及公司简介均记载，招行于2002年4月9日在上海证券交易所挂牌。',
  },
  {
    code: '600036.SH', date: '2006-09-22', title: '简介记载的H股挂牌',
    text: '本地公司简介记载该日在香港联交所挂牌。此条仅保留已定位的历史叙述，尚未逐项核读原始上市文件。',
    readerText: '公司简介记载，招行于2006年9月22日在香港联交所挂牌；星图尚未逐项核对原始上市文件。',
  },
  {
    code: '000333.SZ', date: '2013-09-18', title: 'A股上市',
    text: '股票基础资料记录美的集团于该日上市。重大收购、海外布局与组织调整尚未形成逐条附有原件来源的历史年表。',
    readerText: '股票基础资料记载，美的集团于2013年9月18日上市。星图尚未逐条核对重大收购、海外布局与组织调整的原始资料，因此这里还不是完整的发展年表。',
  },
  {
    code: '600519.SH', date: '1999-11-20', title: '上市主体注册',
    text: '公司资料字段记录的主体注册日期。它定位的是上市公司法律主体，不能据此推定茅台酒品牌或酿酒历史从这一年开始。',
    readerText: '公司资料记载的上市主体注册日期，不能据此认定茅台酒品牌或酿酒历史始于这一年。',
  },
  {
    code: '688981.SH', date: '2000-04-03', title: '公司主体注册',
    text: '公司资料的注册日期字段记录为该日。这里没有将注册等同于第一座工厂投产，工厂建设、工艺演进和扩产节点仍待原始资料核验。',
    readerText: '公司资料记载的注册日期为该日，不能据此认定第一座工厂也于该日投产。工厂建设、工艺演进和扩产的具体时间，星图尚未依据原始资料核验。',
  },
  {
    code: '601318.SH', date: '2007-03-01', title: 'A股上市',
    text: '股票基础资料记录中国平安于该日在A股上市。保险、银行和资管业务的并购及整合历史，尚未建立逐项可核对的年表。',
    readerText: '股票基础资料记载，中国平安于该日在A股上市。星图尚未逐项核对其保险、银行和资管业务的并购整合历史，因此这里还不是完整的发展年表。',
  },
  {
    code: '600519.SH', date: '2001-08-27', title: 'A股上市',
    text: '股票基础资料记录贵州茅台于该日上市。更早的生产沿革、品牌形成与此后的渠道改革，尚未建立逐项核验的年表。',
    readerText: '股票基础资料记载，贵州茅台于该日上市。星图尚未逐项核对更早的生产沿革、品牌形成与此后的渠道改革，因此这里还不是完整的发展年表。',
  },
]

// These notes describe FinancialHistory's metric scope, not the other reading
// sections on the page. Only an exact full sentence is eligible for replacement.
const financeCopies = new Map<string, string>([
  [
    '每期采用现有来源中截至档案日期已披露的最新合并报表整行；缺失值保留空值，负值不归零。未声称已穷尽实时披露。',
    '截至档案所列日期，各期展示已收录的最新合并报表数据。空白表示资料缺失，负数保留实际符号；这里不保证涵盖所有实时披露。',
  ],
  [
    '资本开支表示购建固定资产、无形资产和其他长期资产支付的现金；未直接采用旧自动计算的自由现金流。',
    '资本开支指购建固定资产、无形资产和其他长期资产支付的现金。这组历史财报未展示自由现金流指标。',
  ],
  [
    '旧资产负债表未保留合并报表类型，资产与负债暂不并入已验证序列，待补原始报表类型。',
    '尚未确认合并报表口径的资产与负债数据，未纳入这里的已验证序列；空白不代表公司没有资产或负债。',
  ],
])

type CoverageCopy = { readerText: string; code?: string } & (
  { text: string; pattern?: never } | { pattern: RegExp; text?: never }
)
const coverageCopies = new Map<string, CoverageCopy>([
  ['balanceSheet', {
    text: '原源缺报表类型的资产负债值未并入已验证序列。',
    readerText: '尚未确认合并报表口径的资产与负债数据，未纳入这里的已验证序列。',
  }],
  ['businessModel', {
    pattern: /^生意运转有 ([0-9]+) 处表述的原文证据仍待核对；保留现有正文。$/,
    readerText: '这组公司档案中，生意运转有 $1 处表述的原文证据仍待核对。',
  }],
  ['competitive', {
    pattern: /^竞争位置有 ([0-9]+) 处表述的原文证据仍待核对；保留现有正文。$/,
    readerText: '这组公司档案中，竞争位置有 $1 处表述的原文证据仍待核对。',
  }],
  ['latestFinancial', {
    pattern: /^现有来源内、截至档案日期已披露的最新一期；原快照筛选截止日为([0-9]{8})。$/,
    readerText: '这里展示已收录资料中截至档案日期披露的最新一期。财报筛选截止日期为 $1。',
  }],
  ['profile', {
    text: '主营资料按其查询日期标注；旧简介和注册资料未记录原采集日。简介中的自述排位未经独立核实。',
    readerText: '主营业务资料标有查询日期；公司简介和注册资料的采集日期未记录。简介中的排名属于公司自述，尚未经星图独立核实。',
  }],
  ['profitReconciliation', {
    pattern: /^([0-9]+)个报告期有利润归属核对记录，其中([0-9]+)期待复核。原值保留，相关单季利润同步标记。$/,
    readerText: '$1 个报告期有利润归属核对记录，其中 $2 期仍待复核。数值取自来源记录，相关单季利润也带有复核提示。',
  }],
  ['research', {
    text: '部分经营解读与历史事件尚未定位到原始报告的页码或章节，已分别标为待核对；本次未改写正文。',
    readerText: '这组公司档案的部分经营解读与历史事件，尚未定位到原始报告的页码或章节；对应内容仍待核对。',
  }],
  ['risks', {
    pattern: /^观察问题有 ([0-9]+) 处表述的原文证据仍待核对；保留现有正文。$/,
    readerText: '这组公司档案中，观察问题有 $1 处表述的原文证据仍待核对。',
  }],
  ['sourceIntegrity', {
    code: '601778.SH',
    text: '可选旧来源缺损，已跳过且未修改原文件；本档案仅使用其余可读来源。legacyBase: 601778.SH.json',
    readerText: '这份档案的部分来源资料缺损，因此所示信息仅来自其余可用资料。',
  }],
  ['summary', {
    text: '公司概览与自述业务描述尚未逐句定位到原始报告；本页保留原文表述，不据此推断新的确定性结论。',
    readerText: '这组公司档案中的公司概览与自述业务描述，尚未逐句定位到原始报告；不能仅据此作出确定性判断。',
  }],
  ['timeline', {
    pattern: /^历史事件有 ([0-9]+) 处表述的原文证据仍待核对；保留现有正文。$/,
    readerText: '这组公司档案中，历史事件有 $1 处表述的原文证据仍待核对。',
  }],
])
const coverageLabels = new Map<string, string>([
  ['competitive', '竞争位置'], ['risks', '观察问题'],
  ['sourceIntegrity', '来源完整性'], ['profitReconciliation', '利润归属核对'],
])

export function baseHistoryReaderText(code: string, event: HistoryText): string {
  if (code === '601138.SH') return event.text
  return historyCopies.find(copy => copy.code === code && copy.date === event.date
    && copy.title === event.title && copy.text === event.text)?.readerText ?? event.text
}

export function baseFinanceReaderNote(code: string, note: string): string {
  if (code === '601138.SH') return note
  return financeCopies.get(note) ?? note
}

export function baseCoverageReaderNote(code: string, field: string, note: string): string {
  if (code === '601138.SH') return note
  const copy = coverageCopies.get(field)
  if (!copy || copy.code && copy.code !== code) return note
  if (copy.text !== undefined) return note === copy.text ? copy.readerText : note
  // JavaScript's $ also accepts a trailing newline. The whole match must equal
  // the full input; numeric captures are copied verbatim without normalization.
  const match = copy.pattern.exec(note)
  return match?.[0] === note ? note.replace(copy.pattern, copy.readerText) : note
}

export function baseCoverageReaderLabel(code: string, field: string): string {
  if (code === '601138.SH') return field
  return coverageLabels.get(field) ?? field
}

const hiddenBaseReadingCoverage = new Set(['summary', 'businessModel', 'competitive', 'risks', 'research'])
export function baseCoverageVisible(code: string, field: string, hasReviewedReading: boolean): boolean {
  // These base prose sections are not rendered when overview/seven is present.
  // Keep the source statuses intact; they are not approval statuses for the new
  // reading. The separately visible base timeline and financial data keep theirs.
  return code === '601138.SH' || !hasReviewedReading || !hiddenBaseReadingCoverage.has(field)
}
