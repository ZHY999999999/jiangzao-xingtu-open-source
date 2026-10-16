export type Fact = {
  text: string
  sourceIds: string[]
}

export type Lane = {
  id: string
  title: string
  period: string
  headline: string
  facts: { label: string; text: string; sourceIds: string[] }[]
  /** Reviewed plain-language answers. The full facts remain the evidence layer. */
  reader?: {
    headline?: string
    customer: Fact
    delivery: Fact
    work: Fact
  }
}

export type BusinessStudy = {
  asOf: string
  intro: string
  reader?: {
    intro?: string
    tradeIntro?: string
    spendingNote?: string
    position?: Fact
    positionStatus?: string
  }
  lanes: Lane[]
  catalogue: { items: string[]; note: string; sourceIds: string[] }
  materials: Fact
  trade: {
    intro: string
    steps: { title: string; text: string; sourceIds: string[]; reader?: Fact }[]
    gap: string
  }
  spending: {
    title: string
    period: string
    metric: string
    metricLabel: string
    text: string
    sourceIds: string[]
    rows: { label: string; value: string; sourceIds: string[] }[]
    note: string
    reader?: {
      kind: 'cost' | 'expense' | 'investment' | 'inventory'
      answer: Fact
      composition?: {
        /** The common denominator used by every segment. */
        basis: string
        /** Explicit percentages (0–100), never parsed from display text. */
        segments: { label: string; ratio: number; sourceIds: string[] }[]
      }
    }
  }[]
  conditions: {
    title: string
    need: Fact
    company: Fact
    boundary: string
    reader?: { answer: Fact; status?: string }
  }[]
  cashBridge: {
    period: string
    intro: string
    /** Amounts are RMB yuan. The first row is consolidated net profit. */
    rows: { label: string; amount: number; sourceIds: string[] }[]
    result: { label: string; amount: number; sourceIds: string[] }
    companyExplanation: Fact
    reading: string
    boundary: string
    reader?: { answer: Fact }
  }
}
