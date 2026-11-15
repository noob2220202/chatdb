import { SignOutIcon } from '@phosphor-icons/react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { api, unwrap } from '@/api/client'
import { useLiveState } from '@/lib/live'
import { IconButton } from '@/ui/IconButton/IconButton'
import { Logo } from '@/ui/Logo/Logo'
import { useToast } from '@/ui/Toast/useToast'

import { AUTH_STATUS_KEY, type AuthStatus } from '../auth'
import { LiveBridge } from '../LiveBridge'
import { summarizeShell, useShellOverview } from '../overview'
import styles from './AppShell.module.css'
import { ShellFooter } from './ShellFooter'
import { StatusLine } from './StatusLine'

const SECTIONS = [
  { to: '/', label: '개요' },
  { to: '/leads', label: '수집함' },
  { to: '/rules', label: '수집 규칙' },
  { to: '/groups', label: '그룹' },
  { to: '/accounts', label: '계정' },
  { to: '/logs', label: '활동 기록' },
  { to: '/settings', label: '설정' },
] as const

function sectionTitle(pathname: string): string | null {
  const section = SECTIONS.find(({ to }) =>
    to === '/' ? pathname === '/' : pathname.startsWith(to),
  )
  return section ? section.label : null
}

/** 콘솔의 틀: 머리띠(로고·차례·로그아웃), 상태 줄, 본문, 맨 아래 동기화 줄. */
export function AppShell() {
  const location = useLocation()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const toast = useToast()
  const live = useLiveState()
  const overview = useShellOverview()
  const summary = summarizeShell(overview.data, live)
  const navRef = useRef<HTMLElement>(null)

  const logout = useMutation({
    mutationFn: () => unwrap(api.POST('/api/auth/logout')),
    onSuccess: () => {
      navigate('/login', { replace: true })
      queryClient.setQueryData<AuthStatus>(AUTH_STATUS_KEY, (current) =>
        current ? { ...current, authenticated: false } : current,
      )
      queryClient.removeQueries({ predicate: (query) => query.queryKey[0] !== 'auth' })
    },
    onError: () => toast.problem('로그아웃하지 못했어요. 잠시 뒤에 다시 시도해 주세요.'),
  })

  // 탭 제목과, 좁은 화면의 차례 띠에서 지금 화면이 보이도록 맞춘다.
  useEffect(() => {
    const title = sectionTitle(location.pathname)
    document.title = title ? `${title} — ChatDB` : 'ChatDB'
    const current = navRef.current?.querySelector('[aria-current="page"]')
    if (current instanceof HTMLElement && typeof current.scrollIntoView === 'function') {
      current.scrollIntoView({ block: 'nearest', inline: 'nearest' })
    }
  }, [location.pathname])

  const todayNew = overview.data?.today_new ?? 0

  return (
    <div className={styles.shell}>
      <a className={styles.skip} href="#main">
        본문으로 건너뛰기
      </a>
      <div className={styles.frame}>
        <header className={styles.masthead}>
          <Link className={styles.brand} to="/" aria-label="ChatDB 개요로">
            <Logo lit={summary.receiving} title="" />
          </Link>
          <nav ref={navRef} className={styles.sections} aria-label="주 메뉴">
            {SECTIONS.map(({ to, label }) => (
              <NavLink key={to} to={to} end={to === '/'} className={styles.section}>
                <span className={styles.sectionLabel} data-label={label}>
                  {label}
                </span>
                {to === '/leads' && todayNew > 0 && (
                  <sup className={styles.count} aria-label={`오늘 새로 수집 ${todayNew}명`}>
                    {todayNew > 999 ? '999+' : todayNew}
                  </sup>
                )}
                {to === '/accounts' && summary.attention > 0 && (
                  <span
                    className={styles.attention}
                    aria-label={`확인이 필요한 계정 ${summary.attention}개`}
                  >
                    확인 {summary.attention}
                  </span>
                )}
              </NavLink>
            ))}
          </nav>
          <div className={styles.meta}>
            <button
              type="button"
              className={styles.logout}
              onClick={() => logout.mutate()}
              disabled={logout.isPending}
            >
              로그아웃
              <SignOutIcon aria-hidden="true" />
            </button>
            <IconButton
              label="로그아웃"
              className={styles.logoutIcon}
              onClick={() => logout.mutate()}
              disabled={logout.isPending}
            >
              <SignOutIcon aria-hidden="true" />
            </IconButton>
          </div>
        </header>

        <StatusLine
          overview={overview.data}
          failed={overview.isError && !overview.data}
          summary={summary}
          live={live}
          onRetry={() => void overview.refetch()}
        />
      </div>

      <main id="main" className={styles.main} tabIndex={-1}>
        <div className={styles.frame}>
          <Outlet />
        </div>
      </main>

      <div className={styles.frame}>
        <ShellFooter
          loadedAt={overview.dataUpdatedAt || null}
          failed={overview.isError && !overview.data}
          live={live}
        />
      </div>

      <LiveBridge />
    </div>
  )
}
