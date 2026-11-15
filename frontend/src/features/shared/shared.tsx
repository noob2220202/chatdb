/** 여러 화면이 같이 쓰는 작은 부품과 훅. */
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { useRules, type FeedItem, type Hit } from '@/api/hooks'
import { formatNumber, formatWindow } from '@/lib/format'
import { buildSwatchIndex } from '@/lib/ruleSwatch'
import { KeywordText } from '@/ui/KeywordText/KeywordText'
import { RuleSwatch } from '@/ui/RuleSwatch/RuleSwatch'

import styles from './shared.module.css'

/** 일정 간격으로 지금 시각을 새로 준다(남은 시간, "3분 전" 갱신용). */
export function useNow(intervalMs = 30_000): Date {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), intervalMs)
    return () => window.clearInterval(timer)
  }, [intervalMs])
  return now
}

/** 규칙 id → 무늬 번호. 모든 화면에서 같은 규칙은 같은 무늬다. */
export function useSwatchIndex(): Map<number, number> {
  const { data } = useRules()
  return useMemo(() => buildSwatchIndex((data ?? []).map((rule) => rule.id)), [data])
}

type HitLike = Pick<
  Hit | FeedItem,
  'kind' | 'rule_id' | 'rule_name' | 'keywords' | 'excerpt' | 'message_count' | 'window_hours'
>

/** 활동량 감지를 한 문장으로. "24시간 동안 메시지 41개" */
export function activitySentence(hit: Pick<HitLike, 'message_count' | 'window_hours'>): string {
  const window = hit.window_hours ? formatWindow(hit.window_hours) : '최근'
  const count = hit.message_count ? `${formatNumber(hit.message_count)}개` : '여러 개'
  return `${window} 동안 메시지 ${count}`
}

/** 규칙 무늬 + 이름 */
export function RuleName({
  hit,
  swatches,
  muted,
}: {
  hit: Pick<HitLike, 'rule_id' | 'rule_name'>
  swatches: Map<number, number>
  muted?: boolean
}) {
  const index = hit.rule_id !== null ? (swatches.get(hit.rule_id) ?? -1) : -1
  return (
    <span className={styles.rule}>
      <RuleSwatch index={index} muted={muted} />
      <span className={styles.ruleName}>{hit.rule_name}</span>
    </span>
  )
}

/** 감지 내용: 키워드면 발췌 문장(키워드 강조), 활동량이면 문장 */
export function HitText({
  hit,
  variant,
  muted,
  maxLines,
}: {
  hit: HitLike
  variant: 'quote' | 'table'
  muted?: boolean
  maxLines?: number
}) {
  if (hit.kind === 'activity') return <span>{activitySentence(hit)}</span>
  if (!hit.excerpt) {
    return <span className={styles.quiet}>‘{hit.keywords.join('’, ‘')}’ 가 나왔어요</span>
  }
  return (
    <KeywordText
      text={hit.excerpt}
      keywords={hit.keywords}
      variant={variant}
      quoted
      muted={muted}
      maxLines={maxLines}
    />
  )
}

/** URL 쿼리 문자열을 화면 상태로 쓴다. 빈 값은 주소에서 뺀다. */
export function useUrlState() {
  const [params, setParams] = useSearchParams()
  const set = (changes: Record<string, string | number | null | undefined>, replace = true) => {
    const next = new URLSearchParams(params)
    for (const [key, value] of Object.entries(changes)) {
      if (value === null || value === undefined || value === '') next.delete(key)
      else next.set(key, String(value))
    }
    setParams(next, { replace })
  }
  const num = (key: string): number | undefined => {
    const raw = params.get(key)
    if (raw === null || raw === '') return undefined
    const parsed = Number(raw)
    return Number.isInteger(parsed) ? parsed : undefined
  }
  return { params, set, num, get: (key: string) => params.get(key) ?? '' }
}

/** 입력이 멈춘 뒤에 값을 넘긴다. */
export function useDebounced<T>(value: T, delay = 250): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay)
    return () => window.clearTimeout(timer)
  }, [value, delay])
  return debounced
}

/** 글자를 입력하는 중인지(단축키를 무시해야 하는지) */
export function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  return (
    target.isContentEditable ||
    ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) ||
    target.getAttribute('role') === 'combobox'
  )
}

export { styles as shared }
