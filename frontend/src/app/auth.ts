/** 로그인 상태와, 그 상태에 따라 어디로 보낼지 정하는 규칙. */
import { useQuery } from '@tanstack/react-query'

import { api, unwrap, type Schemas } from '@/api/client'

export type AuthStatus = Schemas['AuthStatus']

export const AUTH_STATUS_KEY = ['auth', 'status'] as const

export function fetchAuthStatus(): Promise<AuthStatus> {
  return unwrap(api.GET('/api/auth/status'))
}

export function useAuthStatus() {
  return useQuery({ queryKey: AUTH_STATUS_KEY, queryFn: fetchAuthStatus, staleTime: 60_000 })
}

/** 문지기의 판단. wait: 아직 모름 / allow: 그대로 보여 줌 / redirect: 다른 곳으로 */
export type GateDecision = { kind: 'wait' } | { kind: 'allow' } | { kind: 'redirect'; to: string }

type Where = { pathname: string; search?: string; hash?: string }

const AUTH_PATHS = ['/login', '/setup']

/**
 * 로그인 뒤에 돌아갈 곳으로 써도 되는 주소인지 확인한다.
 * 이 사이트 안의 경로만 받는다(밖으로 내보내는 주소, 로그인·설정 화면 자신은 버린다).
 */
export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith('/') || next.startsWith('//') || next.includes('\\')) return '/'
  const path = next.split(/[?#]/)[0] ?? '/'
  if (AUTH_PATHS.includes(path)) return '/'
  return next
}

/** 로그인 화면 주소. 가려던 곳이 첫 화면이 아니면 next 로 기억해 둔다. */
export function loginPath(from: Where): string {
  const target = safeNext(`${from.pathname}${from.search ?? ''}${from.hash ?? ''}`)
  return target === '/' ? '/login' : `/login?next=${encodeURIComponent(target)}`
}

/** 콘솔 안쪽 화면: 로그인해야 볼 수 있다. */
export function decideProtected(status: AuthStatus | undefined, from: Where): GateDecision {
  if (!status) return { kind: 'wait' }
  if (status.setup_required) return { kind: 'redirect', to: '/setup' }
  if (!status.authenticated) return { kind: 'redirect', to: loginPath(from) }
  return { kind: 'allow' }
}

/** 로그인 화면: 비밀번호가 아직 없으면 설정으로, 이미 로그인했으면 가려던 곳으로. */
export function decideLogin(status: AuthStatus | undefined, next: string | null): GateDecision {
  if (!status) return { kind: 'wait' }
  if (status.setup_required) return { kind: 'redirect', to: '/setup' }
  if (status.authenticated) return { kind: 'redirect', to: safeNext(next) }
  return { kind: 'allow' }
}

/** 처음 설정 화면: 비밀번호가 이미 있으면 볼 일이 없다. */
export function decideSetup(status: AuthStatus | undefined): GateDecision {
  if (!status) return { kind: 'wait' }
  if (!status.setup_required) return { kind: 'redirect', to: status.authenticated ? '/' : '/login' }
  return { kind: 'allow' }
}
