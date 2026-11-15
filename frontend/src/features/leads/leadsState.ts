/** 수집함의 주소(쿼리 문자열) ↔ 화면 상태. */
import type { LeadFilters, LeadSort, LeadStatus, SortOrder } from '@/api/hooks'

export type Period = '' | 'today' | '7d' | '30d'

export const STATUSES: readonly LeadStatus[] = ['new', 'reviewed', 'contacted', 'excluded']
const SORTS: readonly LeadSort[] = ['last_seen', 'first_seen', 'hit_count', 'username']

export type LeadsView = {
  q: string
  status: LeadStatus | ''
  ruleId?: number
  groupId?: number
  period: Period
  sort: LeadSort
  order: SortOrder
  page: number
  pageSize: number
}

function int(value: string | null): number | undefined {
  if (!value) return undefined
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined
}

export function readView(params: URLSearchParams): LeadsView {
  const status = params.get('status') as LeadStatus | null
  const period = params.get('period') as Period | null
  const sort = params.get('sort') as LeadSort | null
  const size = int(params.get('size'))
  return {
    q: params.get('q') ?? '',
    status: status && STATUSES.includes(status) ? status : '',
    ruleId: int(params.get('rule_id')),
    groupId: int(params.get('group_id')),
    period: period === 'today' || period === '7d' || period === '30d' ? period : '',
    sort: sort && SORTS.includes(sort) ? sort : 'last_seen',
    order: params.get('order') === 'asc' ? 'asc' : 'desc',
    page: int(params.get('page')) ?? 1,
    pageSize: size === 100 ? 100 : 50,
  }
}

function isoDay(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

/** 기간을 "이 날짜부터"로 바꾼다. */
export function periodSince(period: Period, now: Date = new Date()): string | undefined {
  if (!period) return undefined
  const days = period === 'today' ? 0 : period === '7d' ? 6 : 29
  return isoDay(new Date(now.getFullYear(), now.getMonth(), now.getDate() - days))
}

export function toFilters(view: LeadsView, now: Date = new Date()): LeadFilters {
  return {
    q: view.q.trim() || undefined,
    status: view.status ? [view.status] : undefined,
    rule_id: view.ruleId,
    group_id: view.groupId,
    since: periodSince(view.period, now),
    sort: view.sort,
    order: view.order,
  }
}

export function hasFilters(view: LeadsView): boolean {
  return Boolean(view.q.trim() || view.status || view.ruleId || view.groupId || view.period)
}

const SORT_LABEL: Record<LeadSort, [desc: string, asc: string]> = {
  last_seen: ['마지막 감지가 가까운 순서', '마지막 감지가 오래된 순서'],
  first_seen: ['처음 감지가 가까운 순서', '처음 감지가 오래된 순서'],
  hit_count: ['감지 횟수가 많은 순서', '감지 횟수가 적은 순서'],
  username: ['아이디 거꾸로 순서', '아이디 가나다 순서'],
}

export function sortLabel(sort: LeadSort, order: SortOrder): string {
  return SORT_LABEL[sort][order === 'desc' ? 0 : 1]
}

/** shift 로 범위를 고를 때: 두 줄 사이의 id 들 */
export function rangeIds(ids: readonly number[], from: number, to: number): number[] {
  const [start, end] = from <= to ? [from, to] : [to, from]
  return ids.slice(start, end + 1)
}

/** 선택한 아이디 미리보기. "@a, @b 외 3명" */
export function previewHandles(usernames: readonly string[], show = 3): string {
  const head = usernames
    .slice(0, show)
    .map((name) => `@${name}`)
    .join(', ')
  const rest = usernames.length - show
  return rest > 0 ? `${head} 외 ${rest}명` : head
}
