/** 규칙을 문장으로 읽어 준다. 목록과 편집 창이 같은 문장을 쓴다. */
import { formatNumber, formatWindow } from '@/lib/format'

export type RuleShape = {
  kind: 'keyword' | 'activity'
  keywords: readonly string[]
  exclude_keywords: readonly string[]
  match_mode: 'any' | 'all'
  min_messages: number | null
  window_hours: number | null
}

const quote = (words: readonly string[]) => words.map((word) => `‘${word}’`).join(', ')

export function ruleSentence(rule: RuleShape): string {
  if (rule.kind === 'activity') {
    if (!rule.min_messages || !rule.window_hours) return '메시지 수와 기간을 정해 주세요.'
    return `한 그룹에서 ${formatWindow(rule.window_hours)} 동안 메시지를 ${formatNumber(rule.min_messages)}개 넘게 보낸 사람을 받아 적어요.`
  }
  if (rule.keywords.length === 0) return '키워드를 하나 이상 넣어 주세요.'
  const how =
    rule.keywords.length === 1
      ? `${quote(rule.keywords)}(이)라는 말이 나오면`
      : rule.match_mode === 'all'
        ? `${quote(rule.keywords)}이(가) 모두 나오면`
        : `${quote(rule.keywords)} 가운데 하나라도 나오면`
  return `${how} 받아 적어요.`
}

export function excludeSentence(rule: RuleShape): string | null {
  if (rule.kind !== 'keyword' || rule.exclude_keywords.length === 0) return null
  return `${quote(rule.exclude_keywords)}이(가) 함께 나오면 건너뛰어요.`
}

/** 쉼표·줄바꿈으로 나눠 키워드를 더한다(중복은 버린다). */
export function addKeywords(current: readonly string[], input: string): string[] {
  const seen = new Set(current.map((word) => word.toLowerCase()))
  const next = [...current]
  for (const raw of input.split(/[,\n]+/)) {
    const word = raw.trim().replace(/\s+/g, ' ')
    if (!word || seen.has(word.toLowerCase())) continue
    seen.add(word.toLowerCase())
    next.push(word.slice(0, 60))
  }
  return next
}

export const WINDOWS = [
  { value: '1', label: '1시간' },
  { value: '6', label: '6시간' },
  { value: '24', label: '24시간' },
  { value: '72', label: '3일' },
  { value: '168', label: '7일' },
  { value: '720', label: '30일' },
]
