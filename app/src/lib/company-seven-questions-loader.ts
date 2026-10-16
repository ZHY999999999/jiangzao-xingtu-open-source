import { validateSevenQuestions } from './company-seven-questions'
import type { SevenQuestionContent } from './company-seven-questions'

const modules = import.meta.glob<{ default: unknown }>('../../content/company-seven-questions/*.json')
export const SEVEN_QUESTION_CODES = new Set(Object.keys(modules).map(path => path.split('/').pop()!.replace(/\.json$/, '')))
export async function loadSevenQuestions(code: string): Promise<SevenQuestionContent | null> {
  const loader = modules[`../../content/company-seven-questions/${code}.json`]
  return loader ? validateSevenQuestions((await loader()).default, code) : null
}
