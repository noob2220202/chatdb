import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { TrendChart, findPeak, niceScale, type TrendPoint } from './TrendChart'

afterEach(cleanup)

const WEEK: TrendPoint[] = [
  { date: '2026-11-09', keyword: 52, activity: 22 },
  { date: '2026-11-10', keyword: 61, activity: 30 },
  { date: '2026-11-11', keyword: 44, activity: 22 },
  { date: '2026-11-12', keyword: 83, activity: 37 },
  { date: '2026-11-13', keyword: 97, activity: 46 },
  { date: '2026-11-14', keyword: 68, activity: 29 },
  { date: '2026-11-15', keyword: 89, activity: 39 },
]

describe('niceScale', () => {
  it('깔끔한 수로 끝나는 눈금을 고른다', () => {
    expect(niceScale(97)).toEqual({ top: 100, ticks: [25, 50, 75, 100] })
    expect(niceScale(9)).toEqual({ top: 10, ticks: [2, 4, 6, 8, 10] })
    expect(niceScale(3)).toEqual({ top: 3, ticks: [1, 2, 3] })
    expect(niceScale(61)).toEqual({ top: 75, ticks: [25, 50, 75] })
    expect(niceScale(1280).top).toBeGreaterThanOrEqual(1280)
  })

  it('눈금은 언제나 정수다', () => {
    for (let max = 1; max <= 400; max++) {
      const { top, ticks } = niceScale(max)
      expect(top).toBeGreaterThanOrEqual(max)
      expect(ticks.every(Number.isInteger)).toBe(true)
    }
  })

  it('값이 없어도 눈금을 돌려준다', () => {
    expect(niceScale(0).ticks).toHaveLength(4)
  })
})

describe('findPeak', () => {
  it('키워드 감지가 가장 많았던 날을 찾는다', () => {
    expect(findPeak(WEEK)).toEqual({ date: '2026-11-13', value: 97, index: 4 })
  })

  it('같은 값이 둘이거나 모두 0이면 없다고 한다', () => {
    expect(findPeak([WEEK[0]!, { ...WEEK[1]!, keyword: 52 }])).toBeNull()
    expect(findPeak(WEEK.map((point) => ({ ...point, keyword: 0 })))).toBeNull()
    expect(findPeak([])).toBeNull()
  })
})

describe('TrendChart', () => {
  it('같은 내용을 표로도 담는다', () => {
    const { container } = render(
      <TrendChart data={WEEK} today="2026-11-15" title="최근 7일 수집 추이" />,
    )
    const table = container.querySelector('table')
    expect(table?.querySelector('caption')?.textContent).toBe('최근 7일 수집 추이')
    expect(table?.querySelectorAll('tbody tr')).toHaveLength(7)
    expect(table?.querySelector('tbody tr:last-child')?.textContent).toBe('11월 15일 (일)89명39명')
  })

  it('가장 많았던 날을 각주로 적는다', () => {
    const { container } = render(<TrendChart data={WEEK} today="2026-11-15" />)
    expect(container.textContent).toContain(
      '금요일(11월 13일)에 키워드 감지가 97명으로 가장 많았어요.',
    )
  })

  it('데이터가 없으면 그 사실을 말한다', () => {
    const { container } = render(<TrendChart data={[]} />)
    expect(container.textContent).toContain('아직 그릴 추이가 없어요')
    expect(container.querySelector('table')).toBeNull()
  })

  it('모두 0이면 선 대신 문장을 보여 준다', () => {
    const quiet = WEEK.map((point) => ({ ...point, keyword: 0, activity: 0 }))
    const { container } = render(<TrendChart data={quiet} today="2026-11-15" />)
    expect(container.textContent).toContain('이 기간에는 받아 적은 사람이 없었어요')
    expect(container.textContent).not.toContain('가장 많았어요')
  })
})
