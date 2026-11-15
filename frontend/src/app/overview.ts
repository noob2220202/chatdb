/**
 * 머리띠와 상태 줄이 쓰는 개요 데이터.
 *
 * GET /api/overview 는 아직 schema.d.ts 에 없어서, 여기서 쓰는 필드만 작은 타입으로 적어 둔다.
 * 응답 전체를 그대로 캐시에 넣으므로 개요 화면이 같은 키(["overview"])로 나머지 필드를 읽어도 된다.
 */
import { useQuery } from '@tanstack/react-query'

import { ApiError, UNAUTHORIZED_EVENT } from '@/api/client'
import type { LiveState } from '@/lib/live'

export type AccountStatus =
  'connecting' | 'active' | 'flood_wait' | 'reauth_required' | 'banned' | 'error' | 'offline'

export type ShellOverview = {
  today_new: number
  accounts_connected: number
  accounts_total: number
  groups_monitoring: number
  join_requests_pending: number
  accounts: { id: number; display_name: string; status: AccountStatus }[]
  recent_hits: { created_at: string }[]
}

export const OVERVIEW_KEY = ['overview'] as const

export async function fetchOverview(): Promise<ShellOverview> {
  let response: Response
  try {
    response = await fetch('/api/overview', {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
  } catch {
    throw new ApiError(0, '서버에 연결할 수 없어요. 잠시 뒤에 다시 시도해 주세요.', 'network')
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: string
      code?: string | null
    }
    if (response.status === 401 && body.code === 'unauthorized') {
      window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT))
    }
    throw new ApiError(
      response.status,
      body.detail ?? '상태를 불러오지 못했어요.',
      body.code ?? null,
    )
  }
  return (await response.json()) as ShellOverview
}

export function useShellOverview() {
  return useQuery({ queryKey: OVERVIEW_KEY, queryFn: fetchOverview, refetchInterval: 60_000 })
}

/** 사람이 직접 손봐야 풀리는 계정 상태 */
const NEEDS_ATTENTION: readonly AccountStatus[] = ['reauth_required', 'banned', 'error']

export type ShellSummary = {
  /** 연결되어 받는 중인지. 로고의 램프와 상태 줄의 점이 이것으로 켜진다 */
  receiving: boolean
  /** 확인이 필요한 계정 수 */
  attention: number
  /** 마지막으로 받아 적은 시각(ISO). 없으면 null */
  lastHitAt: string | null
}

/** 개요 데이터와 연결 상태로 머리띠에 필요한 것을 간추린다. */
export function summarizeShell(overview: ShellOverview | undefined, live: LiveState): ShellSummary {
  if (!overview) return { receiving: false, attention: 0, lastHitAt: null }
  const attention = overview.accounts.filter((account) =>
    NEEDS_ATTENTION.includes(account.status),
  ).length
  const lastHitAt = overview.recent_hits.reduce<string | null>(
    (latest, hit) => (latest === null || hit.created_at > latest ? hit.created_at : latest),
    null,
  )
  return {
    receiving: live === 'open' && overview.accounts_connected > 0,
    attention,
    lastHitAt,
  }
}
