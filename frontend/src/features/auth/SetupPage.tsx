import { ArrowRightIcon } from '@phosphor-icons/react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { api, ApiError, errorMessage, unwrap } from '@/api/client'
import { AUTH_STATUS_KEY } from '@/app/auth'
import { Button } from '@/ui/Button/Button'
import { FieldMessage } from '@/ui/Field/Field'
import { TextField } from '@/ui/TextField/TextField'

import form from './authForm.module.css'
import { AuthLayout } from './AuthLayout'
import { MIN_PASSWORD_LENGTH, validateSetup, type SetupErrors } from './validateSetup'

/** 처음 설정. 관리자 비밀번호가 아직 없을 때 한 번만 나온다. */
export default function SetupPage() {
  const queryClient = useQueryClient()
  const passwordRef = useRef<HTMLInputElement>(null)
  const confirmRef = useRef<HTMLInputElement>(null)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [focused, setFocused] = useState(false)
  const [errors, setErrors] = useState<SetupErrors>({})

  useEffect(() => {
    document.title = '처음 설정 — ChatDB'
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const timer = window.setTimeout(() => passwordRef.current?.focus(), reduced ? 0 : 450)
    return () => window.clearTimeout(timer)
  }, [])

  const setup = useMutation({
    mutationFn: (value: string) =>
      unwrap(api.POST('/api/auth/setup', { body: { password: value } })),
    onSuccess: (status) => {
      // 문지기(GuestGate)가 이 값을 보고 개요로 보낸다.
      queryClient.setQueryData(AUTH_STATUS_KEY, status)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'already_setup') {
        setErrors({ form: error.message, alreadySetup: true })
        return
      }
      if (error instanceof ApiError && error.status === 422) {
        setErrors({ password: `${MIN_PASSWORD_LENGTH}자 이상, 200자 이하로 정해 주세요.` })
        passwordRef.current?.focus()
        return
      }
      setErrors({ form: errorMessage(error) })
    },
  })

  const onSubmit = (event: FormEvent) => {
    event.preventDefault()
    if (setup.isPending) return
    const found = validateSetup(password, confirm)
    setErrors(found)
    if (found.password) passwordRef.current?.focus()
    else if (found.confirm) confirmRef.current?.focus()
    else setup.mutate(password)
  }

  const lit = focused || password.length > 0

  return (
    <AuthLayout
      title={['처음이네요.', '열쇠를 정할게요.']}
      lede={
        <>
          혼자 쓰는 콘솔이라 계정을 만들지 않아요. <b>비밀번호 하나</b>가 열쇠예요. 지금 정해 두면
          다음부터는 그 비밀번호로 들어와요.
        </>
      }
      lit={lit}
    >
      <form
        onSubmit={onSubmit}
        noValidate
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
      >
        <div className={form.pair}>
          <TextField
            ref={passwordRef}
            label="비밀번호"
            labelAside={`${MIN_PASSWORD_LENGTH}자 이상`}
            type="password"
            name="new-password"
            size="lg"
            mono
            revealable
            autoComplete="new-password"
            placeholder="새 비밀번호"
            inputClassName={form.password}
            value={password}
            error={errors.password}
            onChange={(event) => {
              setPassword(event.target.value)
              if (errors.password) setErrors({})
            }}
          />
          <TextField
            ref={confirmRef}
            label="한 번 더"
            type="password"
            name="confirm-password"
            size="lg"
            mono
            revealable
            autoComplete="new-password"
            placeholder="똑같이 한 번 더"
            inputClassName={form.password}
            value={confirm}
            error={errors.confirm}
            onChange={(event) => {
              setConfirm(event.target.value)
              if (errors.confirm) setErrors({})
            }}
          />
        </div>
        <Button
          type="submit"
          variant="solid"
          size="lg"
          block
          className={form.submit}
          loading={setup.isPending}
          trailingIcon={<ArrowRightIcon size={20} aria-hidden="true" />}
        >
          비밀번호 정하고 시작하기
        </Button>
        {errors.form ? (
          <div className={form.hint}>
            <FieldMessage error={errors.form} />
            {errors.alreadySetup && (
              <p>
                <Link to="/login">로그인 화면으로 가기</Link>
              </p>
            )}
          </div>
        ) : (
          <p className={form.hint}>비밀번호는 나중에 설정에서 바꿀 수 있어요.</p>
        )}
      </form>
    </AuthLayout>
  )
}
