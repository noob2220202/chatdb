import { describe, expect, it } from 'vitest'

import {
  formatAxisDay,
  formatCount,
  formatDateTime,
  formatDelta,
  formatDuration,
  formatIsoDay,
  formatNumber,
  formatRelative,
  formatUntil,
  formatWindow,
} from './format'

const now = new Date(2026, 10, 15, 14, 14, 0)
const ago = (ms: number) => new Date(now.getTime() - ms)
const MIN = 60_000
const HOUR = 60 * MIN

describe('format', () => {
  it('숫자', () => {
    expect(formatNumber(4812)).toBe('4,812')
    expect(formatCount(128, '명')).toBe('128명')
  })

  it('상대 시각', () => {
    expect(formatRelative(ago(10_000), now)).toBe('방금')
    expect(formatRelative(ago(3 * MIN), now)).toBe('3분 전')
    expect(formatRelative(ago(2 * HOUR), now)).toBe('2시간 전')
    expect(formatRelative(ago(20 * HOUR), now)).toBe('20시간 전')
    expect(formatRelative(ago(30 * HOUR), now)).toBe('어제')
    expect(formatRelative(ago(3 * 24 * HOUR), now)).toBe('3일 전')
    expect(formatRelative(new Date(2026, 9, 1, 9, 0), now)).toBe('10월 1일')
    expect(formatRelative(new Date(2025, 9, 1, 9, 0), now)).toBe('2025년 10월 1일')
  })

  it('날짜와 시각', () => {
    expect(formatDateTime(ago(5 * MIN), now)).toBe('오늘 오후 2:09')
    expect(formatDateTime(new Date(2026, 10, 14, 9, 5), now)).toBe('어제 오전 9:05')
    expect(formatDateTime(new Date(2026, 10, 9, 21, 30), now)).toBe('11월 9일 오후 9:30')
  })

  it('기간', () => {
    expect(formatDuration(40)).toBe('40초')
    expect(formatDuration(14 * 60)).toBe('14분')
    expect(formatDuration(80 * 60)).toBe('1시간 20분')
    expect(formatDuration(51 * 3600)).toBe('2일 3시간')
    expect(formatUntil(new Date(now.getTime() + 14 * MIN), now)).toBe('14분 뒤')
    expect(formatUntil(ago(MIN), now)).toBeNull()
    expect(formatWindow(24)).toBe('24시간')
    expect(formatWindow(168)).toBe('7일')
  })

  it('차트 축과 증감', () => {
    expect(formatAxisDay('2026-11-09')).toBe('11/9')
    expect(formatIsoDay('2026-11-15')).toBe('11월 15일 (일)')
    expect(formatDelta(128, 105)).toBe('어제보다 23명 많아요')
    expect(formatDelta(90, 105)).toBe('어제보다 15명 적어요')
    expect(formatDelta(5, 5)).toBe('어제와 같아요')
  })
})
