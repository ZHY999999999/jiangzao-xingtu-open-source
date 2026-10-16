import type { SevenQuestionContent } from './company-seven-questions'
import type { CompanyAudioAsset } from '../components/CompanyAudio'
import type { EditorialSource } from './company-editorial'

/** No old script, synthesized fact or duration estimate: read this exact visible text. */
export function sevenQuestionTranscript(content: SevenQuestionContent): string {
  return [content.introduction, ...content.answers.map(answer => answer.text)].join('\n\n')
}

export function sevenQuestionAudio(content: SevenQuestionContent, contentSha256: string): CompanyAudioAsset {
  return { transcript: sevenQuestionTranscript(content), sourceIds: content.sources.map(source => `seven:${source.id}`),
    browserTts: true, contentVersion: contentSha256 }
}

/** Prefix IDs so a financial-snapshot source can never replace a seven-question citation. */
export function sevenQuestionAudioSources(content: SevenQuestionContent): EditorialSource[] {
  return content.sources.map(source => ({ id: `seven:${source.id}`, title: source.title, url: source.url,
    publishedAt: source.publishedAt, reportPeriod: source.reportPeriod, issuer: source.publisher,
    locator: '经营解读对应的报告；各问题下可查看原文节选、章节定位与具体说明。' }))
}
