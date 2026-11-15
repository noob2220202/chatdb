import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { ApiError, errorMessage } from '@/api/client'
import {
  useCancelLogin,
  useImportSession,
  useImportSessionFile,
  useStartLogin,
  useSubmitLoginCode,
  useSubmitLoginPassword,
  type Account,
  type LoginStart,
} from '@/api/hooks'
import { formatDuration } from '@/lib/format'
import { Button } from '@/ui/Button/Button'
import { Dialog } from '@/ui/Dialog/Dialog'
import { ProblemMark } from '@/ui/Field/ProblemMark'
import { Stepper } from '@/ui/Stepper/Stepper'
import { TextArea } from '@/ui/TextArea/TextArea'
import { TextField } from '@/ui/TextField/TextField'

import { shared, useNow } from '../shared/shared'
import styles from './AccountsPage.module.css'

type Step = 'way' | 'phone' | 'code' | 'password' | 'session' | 'done'
const VIA: Record<string, string> = {
  app: '그 계정의 텔레그램 앱으로 코드를 보냈어요.',
  sms: '문자로 코드를 보냈어요.',
  call: '전화로 코드를 알려 줘요.',
  other: '코드를 보냈어요.',
}

type Props = {
  open: boolean
  onOpenChange: (open: boolean) => void
  demo: boolean
  initialPhone?: string
}

export function AddAccountDialog({ open, onOpenChange, demo, initialPhone }: Props) {
  const now = useNow(1000)
  const start = useStartLogin()
  const submitCode = useSubmitLoginCode()
  const submitPassword = useSubmitLoginPassword()
  const cancel = useCancelLogin()
  const importSession = useImportSession()
  const importFile = useImportSessionFile()

  const [step, setStep] = useState<Step>('way')
  const [phone, setPhone] = useState('+82 ')
  const [login, setLogin] = useState<LoginStart | null>(null)
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [hint, setHint] = useState<string | null>(null)
  const [session, setSession] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [label, setLabel] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [blockedUntil, setBlockedUntil] = useState<number | null>(null)
  const [account, setAccount] = useState<Account | null>(null)
  const pending = useRef<string | null>(null)

  useEffect(() => {
    if (!open) return
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 바깥 값이 바뀌면 화면의 입력 상태를 거기에 맞춘다
    setStep(initialPhone !== undefined ? 'phone' : 'way')
    setPhone(initialPhone || '+82 ')
    setLogin(null)
    setCode('')
    setPassword('')
    setHint(null)
    setSession('')
    setFile(null)
    setLabel('')
    setError(null)
    setBlockedUntil(null)
    setAccount(null)
  }, [open, initialPhone])

  const close = (next: boolean) => {
    if (!next && pending.current) {
      cancel.mutate(pending.current)
      pending.current = null
    }
    onOpenChange(next)
  }

  const fail = (failure: unknown) => {
    setError(failure)
    if (failure instanceof ApiError && failure.retryAfter)
      setBlockedUntil(Date.now() + failure.retryAfter * 1000)
  }
  const blockedFor = blockedUntil ? Math.ceil((blockedUntil - now.getTime()) / 1000) : 0
  const blocked = blockedFor > 0
  const finish = (result: Account | null | undefined) => {
    pending.current = null
    setAccount(result ?? null)
    setError(null)
    setStep('done')
  }

  const onPhone = (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    start.mutate(phone, {
      onSuccess: (result) => {
        pending.current = result.login_id
        setLogin(result)
        setCode('')
        setStep('code')
      },
      onError: fail,
    })
  }
  const onCode = (event: FormEvent) => {
    event.preventDefault()
    if (!login) return
    setError(null)
    submitCode.mutate(
      { login_id: login.login_id, code: code.trim() },
      {
        onSuccess: (result) => {
          if (result.status === 'password_required') {
            setHint(result.password_hint ?? null)
            setStep('password')
          } else finish(result.account)
        },
        onError: fail,
      },
    )
  }
  const onPassword = (event: FormEvent) => {
    event.preventDefault()
    if (!login) return
    setError(null)
    submitPassword.mutate(
      { login_id: login.login_id, password },
      { onSuccess: (result) => finish(result.account), onError: fail },
    )
  }
  const onSession = (event: FormEvent) => {
    event.preventDefault()
    setError(null)
    const name = label.trim() || undefined
    if (file) importFile.mutate({ file, label: name }, { onSuccess: finish, onError: fail })
    else
      importSession.mutate(
        { session_string: session.trim(), label: name ?? null },
        { onSuccess: finish, onError: fail },
      )
  }

  const expires = login
    ? Math.max(0, Math.ceil((new Date(login.expires_at).getTime() - now.getTime()) / 1000))
    : 0
  const needsApi = error instanceof ApiError && error.code === 'api_credentials'
  const errorLine = error ? (
    <p className={shared.formError} role="alert">
      <ProblemMark />
      <span>
        {errorMessage(error)}
        {blocked && ` ${formatDuration(blockedFor)} 뒤에 다시 할 수 있어요.`}{' '}
        {needsApi && (
          <Link className={shared.link} to="/settings">
            설정으로 가기
          </Link>
        )}
      </span>
    </p>
  ) : null

  const phoneSteps = ['전화번호', '인증 코드', '2단계 비밀번호', '끝']
  const stepIndex = { way: 0, phone: 0, code: 1, password: 2, session: 0, done: 3 }[step]

  return (
    <Dialog
      open={open}
      onOpenChange={close}
      size="md"
      title="계정 추가"
      locked={step !== 'way' && step !== 'done'}
    >
      {step !== 'way' && step !== 'session' && (
        <Stepper steps={phoneSteps} current={stepIndex} aria-label="로그인 단계" />
      )}
      <div className={styles.body}>
        {step === 'way' && (
          <>
            <div className={styles.ways}>
              <button type="button" className={styles.way} onClick={() => setStep('phone')}>
                <b>전화번호로 로그인</b>
                <span>번호를 넣고, 텔레그램이 보내는 인증 코드를 넣어요.</span>
              </button>
              <button type="button" className={styles.way} onClick={() => setStep('session')}>
                <b>세션 불러오기</b>
                <span>이미 가지고 있는 세션 문자열이나 .session 파일을 써요.</span>
              </button>
            </div>
            {demo && (
              <p className={shared.note}>
                ＊ 데모 모드예요. 아무 번호나 넣고 코드는 12345를 쓰면 돼요.
              </p>
            )}
          </>
        )}

        {step === 'phone' && (
          <form className={shared.stack} onSubmit={onPhone}>
            <TextField
              label="전화번호"
              mono
              size="lg"
              data-autofocus
              inputMode="tel"
              autoComplete="off"
              hint="나라 번호까지 넣어 주세요. 인증 코드는 그 계정의 텔레그램 앱으로 와요."
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
            />
            {errorLine}
            <div className={shared.dialogFoot}>
              <Button variant="quiet" onClick={() => close(false)}>
                취소
              </Button>
              <Button
                type="submit"
                variant="solid"
                loading={start.isPending}
                disabled={blocked || phone.replace(/\D/g, '').length < 7}
              >
                코드 받기
              </Button>
            </div>
          </form>
        )}

        {step === 'code' && login && (
          <form className={shared.stack} onSubmit={onCode}>
            <TextField
              label="인증 코드"
              labelAside={
                expires > 0
                  ? `${formatDuration(expires)} 안에 넣어 주세요`
                  : '시간이 지났어요. 코드를 다시 받아 주세요'
              }
              mono
              size="lg"
              data-autofocus
              inputMode="numeric"
              autoComplete="one-time-code"
              hint={`${login.phone} — ${VIA[login.code_via] ?? VIA.other}`}
              value={code}
              onChange={(event) => setCode(event.target.value)}
            />
            {errorLine}
            <div className={shared.dialogFoot}>
              <Button variant="quiet" onClick={() => setStep('phone')}>
                코드 다시 받기
              </Button>
              <Button
                type="submit"
                variant="solid"
                loading={submitCode.isPending}
                disabled={blocked || code.trim().length < 3}
              >
                확인
              </Button>
            </div>
          </form>
        )}

        {step === 'password' && (
          <form className={shared.stack} onSubmit={onPassword}>
            <TextField
              label="2단계 인증 비밀번호"
              type="password"
              revealable
              size="lg"
              data-autofocus
              autoComplete="off"
              hint={
                hint
                  ? `이 계정에 걸어 둔 비밀번호예요. 힌트: ${hint}`
                  : '이 계정에 걸어 둔 2단계 인증 비밀번호를 넣어 주세요.'
              }
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            {errorLine}
            <div className={shared.dialogFoot}>
              <Button variant="quiet" onClick={() => close(false)}>
                취소
              </Button>
              <Button
                type="submit"
                variant="solid"
                loading={submitPassword.isPending}
                disabled={blocked || !password}
              >
                확인
              </Button>
            </div>
          </form>
        )}

        {step === 'session' && (
          <form className={shared.stack} onSubmit={onSession}>
            <TextArea
              label="세션 문자열"
              mono
              rows={4}
              data-autofocus
              spellCheck={false}
              disabled={file !== null}
              placeholder="Telethon StringSession"
              hint="넣은 문자열은 암호화해서 저장하고, 다시 보여 주지 않아요."
              value={session}
              onChange={(event) => setSession(event.target.value)}
            />
            <TextField
              label="또는 .session 파일"
              type="file"
              accept=".session"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            <TextField
              label="이름 (선택)"
              placeholder="목록에서 알아볼 이름"
              maxLength={64}
              value={label}
              onChange={(event) => setLabel(event.target.value)}
            />
            {errorLine}
            <div className={shared.dialogFoot}>
              <Button variant="quiet" onClick={() => setStep('way')}>
                뒤로
              </Button>
              <Button
                type="submit"
                variant="solid"
                loading={importSession.isPending || importFile.isPending}
                disabled={!file && session.trim().length < 20}
              >
                불러오기
              </Button>
            </div>
          </form>
        )}

        {step === 'done' && (
          <>
            <p className={styles.done}>
              {account ? `${account.display_name} 계정을 연결했어요.` : '계정을 연결했어요.'}
            </p>
            <p className={shared.note}>이제 이 계정을 그룹에 넣으면 대화를 듣기 시작해요.</p>
            <div className={shared.dialogFoot}>
              <Button onClick={() => close(false)}>닫기</Button>
              <Button asChild variant="solid">
                <Link to="/groups">그룹 넣으러 가기</Link>
              </Button>
            </div>
          </>
        )}
      </div>
    </Dialog>
  )
}
