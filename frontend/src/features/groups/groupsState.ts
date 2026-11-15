/** 그룹 화면의 탭·정렬 계산. */
import type { Group, GroupStatus } from '@/api/hooks'

export type GroupTab = 'all' | 'joined' | 'requested' | 'queued' | 'failed'

export const TAB_STATUSES: Record<GroupTab, readonly GroupStatus[]> = {
  all: [],
  joined: ['joined'],
  requested: ['requested'],
  queued: ['queued', 'joining'],
  failed: ['failed', 'left'],
}

export function readTab(value: string): GroupTab {
  if (value === 'joining') return 'queued'
  if (value === 'left') return 'failed'
  return value in TAB_STATUSES ? (value as GroupTab) : 'all'
}

export function countTabs(groups: readonly Group[]): Record<GroupTab, number> {
  const counts: Record<GroupTab, number> = {
    all: groups.length,
    joined: 0,
    requested: 0,
    queued: 0,
    failed: 0,
  }
  for (const group of groups) {
    for (const tab of ['joined', 'requested', 'queued', 'failed'] as const) {
      if (TAB_STATUSES[tab].includes(group.status)) counts[tab] += 1
    }
  }
  return counts
}

export type GroupSort = 'recent' | 'title' | 'members' | 'leads' | 'last'

export function sortGroups(groups: readonly Group[], sort: GroupSort, desc: boolean): Group[] {
  if (sort === 'recent') return [...groups]
  const value = (group: Group): string | number => {
    if (sort === 'title') return group.display_title
    if (sort === 'members') return group.member_count ?? -1
    if (sort === 'leads') return group.lead_count
    return group.last_message_at ?? ''
  }
  const sorted = [...groups].sort((a, b) => {
    const x = value(a)
    const y = value(b)
    return typeof x === 'string' && typeof y === 'string'
      ? x.localeCompare(y, 'ko')
      : Number(x) - Number(y)
  })
  return desc ? sorted.reverse() : sorted
}

export const KIND_LABEL: Record<string, string> = {
  group: '그룹',
  supergroup: '슈퍼그룹',
  channel: '채널',
}

export const OUTCOME: Record<string, { kind: 'ok' | 'muted' | 'problem' | 'wait'; label: string }> =
  {
    queued: { kind: 'ok', label: '대기열에 넣음' },
    duplicate: { kind: 'muted', label: '이미 있음' },
    invalid: { kind: 'problem', label: '읽을 수 없는 링크' },
    no_capacity: { kind: 'wait', label: '자리가 없음' },
  }
