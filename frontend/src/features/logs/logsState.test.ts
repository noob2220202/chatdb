import { describe, expect, it } from 'vitest'

import type { LogEntry } from '@/api/hooks'

import { groupByDay } from './logsState'

describe('활동 기록 묶기', () => {
  it('날짜별로 묶고 오늘·어제를 표시한다', () => {
    const now = new Date(2026, 10, 15, 14, 0)
    const at = (d: number, h: number) =>
      ({ created_at: new Date(2026, 10, d, h).toISOString() }) as LogEntry
    const groups = groupByDay([at(15, 13), at(15, 9), at(14, 22), at(10, 8)], now)
    expect(groups.map((group) => group.entries.length)).toEqual([2, 1, 1])
    expect(groups[0]?.label.startsWith('오늘')).toBe(true)
    expect(groups[1]?.label.startsWith('어제')).toBe(true)
    expect(groups[2]?.label).toBe('2026년 11월 10일 화요일')
  })
})
