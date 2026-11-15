import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { Navigate, Outlet, useLocation, useSearchParams } from 'react-router-dom'

import { UNAUTHORIZED_EVENT } from '@/api/client'
import { Button } from '@/ui/Button/Button'

import {
  AUTH_STATUS_KEY,
  decideLogin,
  decideProtected,
  decideSetup,
  useAuthStatus,
  type AuthStatus,
} from './auth'
import styles from './AuthGate.module.css'
import { AppShell } from './shell/AppShell'
import { MastheadRule } from './shell/MastheadRule'

/** 로그인 상태를 물어볼 수 없을 때(서버가 꺼져 있을 때) */
function GateError({ onRetry, retrying }: { onRetry: () => void; retrying: boolean }) {
  return (
    <>
      <MastheadRule />
      <div className={styles.error} role="alert">
        <h1 className={styles.title}>서버에 닿지 않아요.</h1>
        <p className={styles.body}>
          ChatDB 서버가 꺼져 있거나 다시 시작하는 중일 수 있어요. 잠시 뒤에 다시 시도해 주세요.
        </p>
        <Button variant="solid" loading={retrying} onClick={onRetry}>
          다시 시도
        </Button>
      </div>
    </>
  )
}

/** 콘솔 안쪽의 문지기. 로그인해야 들어온다. 로그인이 풀리면(UNAUTHORIZED_EVENT) 로그인 화면으로 보낸다. */
export function ProtectedGate() {
  const { data, isError, isFetching, refetch } = useAuthStatus()
  const location = useLocation()
  const queryClient = useQueryClient()

  useEffect(() => {
    const onUnauthorized = () => {
      queryClient.setQueryData<AuthStatus>(AUTH_STATUS_KEY, (current) =>
        current ? { ...current, authenticated: false } : current,
      )
      // 로그인이 풀렸으니 받아 둔 데이터도 버린다.
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== 'auth' })
    }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [queryClient])

  const decision = decideProtected(data, location)
  if (decision.kind === 'wait') {
    return isError ? (
      <GateError onRetry={() => void refetch()} retrying={isFetching} />
    ) : (
      <MastheadRule />
    )
  }
  if (decision.kind === 'redirect') return <Navigate to={decision.to} replace />
  return <AppShell />
}

/** 로그인·처음 설정 화면의 문지기. 볼 일이 없는 사람은 알맞은 곳으로 보낸다. */
export function GuestGate({ kind }: { kind: 'login' | 'setup' }) {
  const { data, isError, isFetching, refetch } = useAuthStatus()
  const [params] = useSearchParams()

  const decision = kind === 'login' ? decideLogin(data, params.get('next')) : decideSetup(data)
  if (decision.kind === 'wait') {
    return isError ? (
      <GateError onRetry={() => void refetch()} retrying={isFetching} />
    ) : (
      <MastheadRule />
    )
  }
  if (decision.kind === 'redirect') return <Navigate to={decision.to} replace />
  return <Outlet />
}
