import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { SegmentedBar, roundPercents } from './SegmentedBar'

afterEach(cleanup)

describe('roundPercents', () => {
  it('합이 언제나 100이다', () => {
    expect(roundPercents([1904, 1216, 1004, 688])).toEqual([40, 25, 21, 14])
    expect(roundPercents([1, 1, 1])).toEqual([34, 33, 33])
    expect(roundPercents([1, 1, 1]).reduce((a, b) => a + b, 0)).toBe(100)
  })

  it('값이 없으면 모두 0', () => {
    expect(roundPercents([0, 0])).toEqual([0, 0])
    expect(roundPercents([])).toEqual([])
  })
})

describe('SegmentedBar', () => {
  const items = [
    { id: 1, label: '견적 문의', value: 1904, swatch: 0 },
    { id: 2, label: '업체 찾는 사람', value: 1216, swatch: 1 },
    { id: 3, label: '쉬는 규칙', value: 0, swatch: 2 },
  ]

  it('막대의 이름에 모든 조각의 이름·수·비율이 들어 있다', () => {
    const { getByRole } = render(<SegmentedBar items={items} />)
    const label = getByRole('img').getAttribute('aria-label')
    expect(label).toContain('견적 문의 1,904명, 61%')
    expect(label).toContain('업체 찾는 사람 1,216명, 39%')
  })

  it('값이 0인 조각은 그리지 않지만 범례에는 남긴다', () => {
    const { getByRole, getAllByRole } = render(<SegmentedBar items={items} />)
    expect(getByRole('img').children).toHaveLength(2)
    expect(getAllByRole('listitem')).toHaveLength(3)
  })
})
