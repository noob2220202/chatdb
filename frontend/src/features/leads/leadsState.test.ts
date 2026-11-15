import { describe, expect, it } from 'vitest'

import { periodSince, previewHandles, rangeIds, readView, sortLabel, toFilters } from './leadsState'

describe('수집함 상태', () => {
  it('주소에서 상태를 읽고 이상한 값은 기본값으로 돌린다', () => {
    const view = readView(
      new URLSearchParams('q=kim&status=new&rule_id=3&sort=hit_count&order=asc&page=2&size=100'),
    )
    expect(view).toMatchObject({
      q: 'kim',
      status: 'new',
      ruleId: 3,
      sort: 'hit_count',
      order: 'asc',
      page: 2,
      pageSize: 100,
    })
    const broken = readView(new URLSearchParams('status=nope&sort=x&page=-1&size=7&period=year'))
    expect(broken).toMatchObject({
      status: '',
      sort: 'last_seen',
      order: 'desc',
      page: 1,
      pageSize: 50,
      period: '',
    })
  })

  it('기간을 날짜로 바꾼다', () => {
    const now = new Date(2026, 10, 15, 14, 0)
    expect(periodSince('today', now)).toBe('2026-11-15')
    expect(periodSince('7d', now)).toBe('2026-11-09')
    expect(periodSince('30d', now)).toBe('2026-10-17')
    expect(periodSince('', now)).toBeUndefined()
  })

  it('필터를 만든다', () => {
    const view = readView(new URLSearchParams('q=%20kim%20&status=contacted&group_id=9'))
    expect(toFilters(view)).toMatchObject({
      q: 'kim',
      status: ['contacted'],
      group_id: 9,
      sort: 'last_seen',
      order: 'desc',
    })
  })

  it('범위 선택과 미리보기', () => {
    expect(rangeIds([10, 11, 12, 13], 3, 1)).toEqual([11, 12, 13])
    expect(previewHandles(['a', 'b'])).toBe('@a, @b')
    expect(previewHandles(['a', 'b', 'c', 'd', 'e'])).toBe('@a, @b, @c 외 2명')
    expect(sortLabel('hit_count', 'desc')).toBe('감지 횟수가 많은 순서')
  })
})
