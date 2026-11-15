import { ArrowRightIcon } from '@phosphor-icons/react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { animate } from 'motion/mini'
import { useEffect, useRef, useState, type FormEvent } from 'react'

import { api, ApiError, errorMessage, unwrap } from '@/api/client'
import { AUTH_STATUS_KEY } from '@/app/auth'
import { Button } from '@/ui/Button/Button'
import { TextField } from '@/ui/TextField/TextField'

import form from './authForm.module.css'
import { AuthLayout } from './AuthLayout'
import { formatCountdown, useCountdown } from './countdown'

type Failure = {
  message: string
  /** wrong: 비밀번호가 틀림 / throttled: 너무 여러 번 틀려 잠김 / other: 그 밖의 문제 */
  kind: 'wrong' | 'throttled' | 'other'
}

const prefersReducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** 로그인. 비밀번호 칸에 들어서면 사진 속 램프에 불이 켜진다. */
export default function LoginPage() {
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const fieldRef = useRef<HTMLDivElement>(null)
  const [password, setPassword] = useState('')
  const [focused, setFocused] = useState(false)
  const [failure, setFailure] = useState<Failure | null>(null)
  const [lockedUntil, setLockedUntil] = useState<number | null>(null)
  const remaining = useCountdown(lockedUntil)
  const throttled = lockedUntil !== null && remaining > 0

  useEffect(() => {
    document.title = '로그인 — ChatDB'
    // 화면이 먼저 보이고, 한 박자 뒤에 칸에 들어서며 불이 켜진다.
    const timer = window.setTimeout(
      () => inputRef.current?.focus(),
      prefersReducedMotion() ? 0 : 450,
    )
    return () => window.clearTimeout(timer)
  }, [])

  const login = useMutation({
    mutationFn: (value: string) =>
      unwrap(api.POST('/api/auth/login', { body: { password: value } })),
    onSuccess: (status) => {
      // 문지기(GuestGate)가 이 값을 보고 가려던 곳으로 보낸다.
      queryClient.setQueryData(AUTH_STATUS_KEY, status)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 429) {
        setLockedUntil(Date.now() + (error.retryAfter ?? 60) * 1000)
        setFailure({ message: error.message, kind: 'throttled' })
        return
      }
      if (error instanceof ApiError && error.status === 401) {
        setFailure({ message: error.message, kind: 'wrong' })
        if (fieldRef.current && !prefersReducedMotion()) {
          animate(
            fieldRef.current,
            {
              transform: [
                'translateX(0)',
                'translateX(-9px)',
                'translateX(7px)',
                'translateX(-5px)',
                'translateX(3px)',
                'translateX(0)',
              ],
            },
            { duration: 0.34, ease: 'easeOut' },
          )
        }
        inputRef.current?.focus()
        inputRef.current?.select()
        return
      }
      setFailure({ message: errorMessage(error), kind: 'other' })
    },
  })

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (login.isPending || throttled) return
    if (!password) {
      setFailure({ message: '비밀번호를 입력해 주세요.', kind: 'other' })
      inputRef.current?.focus()
      return
    }
    login.mutate(password)
  }

  // 잠금이 풀리면 잠금 안내는 거둔다.
  const shownFailure = failure?.kind === 'throttled' && !throttled ? null : failure
  // 틀렸거나 잠겨 있는 동안은 불이 꺼져 있다. 다시 쓰기 시작하면 켜진다.
  const dark = shownFailure?.kind === 'wrong' || throttled
  const lit = (focused || password.length > 0) && !dark

  return (
    <AuthLayout
      title={['찾는 말이 나오면,', '불이 켜져요.']}
      lede={
        <>
          텔레그램 그룹 이백 곳의 대화를 지켜보다가{' '}
          <b>견적을 묻는 사람, 업체를 찾는 사람, 요즘 부쩍 말이 많아진 사람</b>의{' '}
          <span className={form.nowrap}>@아이디를</span> 받아 적어 둬요.
        </>
      }
      lit={lit}
    >
      <form onSubmit={onSubmit} noValidate>
        <div ref={fieldRef}>
          <TextField
            ref={inputRef}
            label="비밀번호"
            labelAside="관리자 한 명만 들어올 수 있어요"
            type="password"
            name="password"
            size="lg"
            mono
            revealable
            autoComplete="current-password"
            placeholder="비밀번호를 입력해 주세요"
            inputClassName={form.password}
            value={password}
            error={shownFailure?.message}
            onChange={(event) => {
              setPassword(event.target.value)
              if (failure && failure.kind !== 'throttled') setFailure(null)
            }}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
          />
        </div>
        <Button
          type="submit"
          variant="solid"
          size="lg"
          block
          className={form.submit}
          loading={login.isPending}
          disabled={throttled}
          trailingIcon={throttled ? undefined : <ArrowRightIcon size={20} aria-hidden="true" />}
        >
          {throttled ? `${formatCountdown(remaining)} 뒤에 다시 시도할 수 있어요` : '로그인'}
        </Button>
        <p className={form.hint}>여러 번 틀리면 잠시 동안 로그인이 막혀요.</p>
      </form>
    </AuthLayout>
  )
}
