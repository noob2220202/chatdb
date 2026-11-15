/** 개요 화면의 문장과 "살펴볼 일"을 데이터에서 만든다. */
import type { Account, Overview, Settings } from '@/api/hooks'
import { formatCount, formatUntil } from '@/lib/format'

export function heroDeck(overview: Overview): string {
  const last = overview.series[overview.series.length - 1]
  const yesterday =
    overview.yesterday_new > 0
      ? `어제는 ${formatCount(overview.yesterday_new, '명')}이었어요.`
      : '어제는 받아 적은 사람이 없었어요.'
  if (!last || overview.today_new === 0) return `${yesterday} 오늘은 아직 받아 적은 사람이 없어요.`
  return `${yesterday} 오늘은 키워드로 ${formatCount(last.keyword, '명')}, 활발한 유저로 ${formatCount(last.activity, '명')}을 찾았어요.`
}

export type Attention = {
  key: string
  kind: 'problem' | 'wait' | 'pending'
  text: string
  to: string
  action: string
}

const PROBLEM: Record<string, string> = {
  reauth_required: '다시 로그인이 필요해요',
  banned: '계정이 정지됐어요',
  error: '연결이 끊겼어요',
}

export function attentionList(
  overview: Overview,
  settings: Settings | undefined,
  now: Date = new Date(),
): Attention[] {
  const list: Attention[] = []
  if (settings && settings.tg_api_source === 'none' && !settings.demo) {
    list.push({
      key: 'api',
      kind: 'problem',
      text: '텔레그램 API 키가 아직 없어요',
      to: '/settings',
      action: '설정에서 넣기',
    })
  }
  for (const account of overview.accounts) {
    const problem = PROBLEM[account.status]
    if (problem) {
      list.push({
        key: `a${account.id}`,
        kind: 'problem',
        text: `${account.display_name} — ${problem}`,
        to: '/accounts',
        action: '계정에서 처리하기',
      })
    } else if (account.status === 'flood_wait') {
      const until = account.flood_until ? formatUntil(account.flood_until, now) : null
      list.push({
        key: `a${account.id}`,
        kind: 'wait',
        text: `${account.display_name} — 텔레그램이 요청을 잠시 막았어요. ${until ? `${until}에 다시 시작해요` : '곧 다시 시작해요'}`,
        to: '/accounts',
        action: '계정 보기',
      })
    }
  }
  if (overview.join_requests_pending > 0) {
    list.push({
      key: 'req',
      kind: 'pending',
      text: `입장 요청 ${overview.join_requests_pending}건이 관리자 승인을 기다려요`,
      to: '/groups?status=requested',
      action: '그룹에서 보기',
    })
  }
  if (overview.join_queue > 0) {
    list.push({
      key: 'queue',
      kind: 'pending',
      text: `그룹 ${overview.join_queue}곳이 가입 차례를 기다려요`,
      to: '/groups?status=queued',
      action: '대기열 보기',
    })
  }
  if (overview.accounts_total > 0 && overview.rule_totals.length === 0) {
    list.push({
      key: 'rules',
      kind: 'problem',
      text: '수집 규칙이 아직 없어서 아무도 받아 적지 않아요',
      to: '/rules',
      action: '규칙 만들기',
    })
  }
  return list
}

/** 붙여 넣은 글에서 링크를 한 줄씩 떼어 낸다. */
export function splitLinks(text: string): string[] {
  return [
    ...new Set(
      text
        .split(/[\s,]+/)
        .map((part) => part.trim())
        .filter(Boolean),
    ),
  ]
}

export function joinSummary(items: readonly { outcome: string }[]): string {
  const count = (outcome: string) => items.filter((item) => item.outcome === outcome).length
  const parts: string[] = []
  if (count('queued')) parts.push(`${count('queued')}곳을 가입 대기열에 넣었어요`)
  if (count('duplicate')) parts.push(`${count('duplicate')}곳은 이미 있어요`)
  if (count('invalid')) parts.push(`${count('invalid')}곳은 링크를 읽을 수 없어요`)
  if (count('no_capacity')) parts.push(`${count('no_capacity')}곳은 넣을 자리가 없어요`)
  return parts.join('. ') + '.'
}

export function slotTone(account: Pick<Account, 'status'>): 'normal' | 'wait' | 'problem' {
  if (account.status === 'flood_wait' || account.status === 'connecting') return 'wait'
  if (account.status === 'active') return 'normal'
  return 'problem'
}
