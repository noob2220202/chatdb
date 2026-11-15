/** 활동 기록을 날짜별로 묶는다. */
import type { LogEntry } from '@/api/hooks'
import { formatFullDate } from '@/lib/format'

export type DayGroup = { key: string; label: string; entries: LogEntry[] }

export function groupByDay(entries: readonly LogEntry[], now: Date = new Date()): DayGroup[] {
  const groups: DayGroup[] = []
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  for (const entry of entries) {
    const date = new Date(entry.created_at)
    const key = `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`
    let group = groups[groups.length - 1]
    if (!group || group.key !== key) {
      const diff = Math.round(
        (today - new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()) /
          86_400_000,
      )
      const label =
        diff === 0
          ? `오늘 · ${formatFullDate(date)}`
          : diff === 1
            ? `어제 · ${formatFullDate(date)}`
            : formatFullDate(date)
      group = { key, label, entries: [] }
      groups.push(group)
    }
    group.entries.push(entry)
  }
  return groups
}

export const LEVEL_LAMP = { info: 'done', warning: 'wait', error: 'problem' } as const
export const LEVEL_LABEL = { info: '알림', warning: '주의', error: '문제' } as const
export const CATEGORY_LABEL = {
  account: '계정',
  group: '그룹',
  collect: '수집',
  system: '시스템',
} as const
