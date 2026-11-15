import { describe, expect, it } from 'vitest'

import { formatCountdown, secondsUntil } from './countdown'

describe('formatCountdown', () => {
  it('1분이 안 되면 초만 적는다', () => {
    expect(formatCountdown(32)).toBe('32초')
    expect(formatCountdown(0.2)).toBe('1초')
    expect(formatCountdown(-3)).toBe('0초')
  })

  it('1분이 넘으면 분과 초를 함께 적는다', () => {
    expect(formatCountdown(245)).toBe('4분 5초')
    expect(formatCountdown(300)).toBe('5분')
  })
})

describe('secondsUntil', () => {
  it('남은 시간을 올림한 초로 돌려준다', () => {
    expect(secondsUntil(10_500, 10_000)).toBe(1)
    expect(secondsUntil(70_000, 10_000)).toBe(60)
  })

  it('지났거나 정해지지 않았으면 0 이다', () => {
    expect(secondsUntil(10_000, 10_001)).toBe(0)
    expect(secondsUntil(null, 10_000)).toBe(0)
  })
})
