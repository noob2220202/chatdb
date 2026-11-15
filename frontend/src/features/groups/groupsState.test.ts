import { describe, expect, it } from 'vitest'

import type { Group } from '@/api/hooks'

import { countTabs, readTab, sortGroups } from './groupsState'

const g = (id: number, status: Group['status'], lead_count = 0, title = `g${id}`) =>
  ({
    id,
    status,
    lead_count,
    display_title: title,
    member_count: id,
    last_message_at: null,
  }) as Group

describe('그룹 상태', () => {
  it('탭을 읽고 센다', () => {
    expect(readTab('requested')).toBe('requested')
    expect(readTab('joining')).toBe('queued')
    expect(readTab('zzz')).toBe('all')
    expect(countTabs([g(1, 'joined'), g(2, 'queued'), g(3, 'joining'), g(4, 'left')])).toEqual({
      all: 4,
      joined: 1,
      requested: 0,
      queued: 2,
      failed: 1,
    })
  })
  it('정렬한다', () => {
    const list = [g(1, 'joined', 5), g(2, 'joined', 9), g(3, 'joined', 1)]
    expect(sortGroups(list, 'leads', true).map((x) => x.id)).toEqual([2, 1, 3])
    expect(sortGroups(list, 'recent', true).map((x) => x.id)).toEqual([1, 2, 3])
  })
})
