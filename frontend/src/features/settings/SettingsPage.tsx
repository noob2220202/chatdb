import { useEffect, useState, type FormEvent } from 'react'

import { errorMessage } from '@/api/client'
import {
  useChangePassword,
  useClearTelegramApi,
  useSettings,
  useUpdateSettings,
  type Settings,
} from '@/api/hooks'
import { photos } from '@/assets/photos'
import { Button } from '@/ui/Button/Button'
import { ConfirmDialog } from '@/ui/ConfirmDialog/ConfirmDialog'
import { DefinitionItem, DefinitionList } from '@/ui/DefinitionList/DefinitionList'
import { ErrorState } from '@/ui/ErrorState/ErrorState'
import { ProblemMark } from '@/ui/Field/ProblemMark'
import { NumberField } from '@/ui/NumberField/NumberField'
import { PageHeader } from '@/ui/PageHeader/PageHeader'
import { SectionHead } from '@/ui/SectionHead/SectionHead'
import { Select } from '@/ui/Select/Select'
import { SkeletonText } from '@/ui/Skeleton/Skeleton'
import { Switch } from '@/ui/Switch/Switch'
import { TextField } from '@/ui/TextField/TextField'
import { useToast } from '@/ui/Toast/Toast'

import { shared } from '../shared/shared'
import styles from './SettingsPage.module.css'

const INTERVALS = [30, 60, 90, 180, 300, 600]
const intervalLabel = (seconds: number) => (seconds < 120 ? `${seconds}초` : `${seconds / 60}분`)
const RETENTION = [
  { value: '0', label: '계속 보관' },
  { value: '30', label: '30일' },
  { value: '90', label: '90일' },
  { value: '180', label: '180일' },
  { value: '365', label: '1년' },
]
const ZONES = [
  'Asia/Seoul',
  'Asia/Tokyo',
  'Asia/Shanghai',
  'Asia/Singapore',
  'Europe/London',
  'America/New_York',
  'America/Los_Angeles',
  'UTC',
]
const API_SOURCE = {
  settings: '여기에 저장돼 있어요',
  env: '.env 파일의 값을 쓰고 있어요',
  none: '아직 없어요',
} as const

function FormError({ error }: { error: unknown }) {
  if (!error) return null
  return (
    <p className={shared.formError} role="alert">
      <ProblemMark /> {errorMessage(error)}
    </p>
  )
}

function ApiSection({ settings }: { settings: Settings }) {
  const toast = useToast()
  const update = useUpdateSettings()
  const clear = useClearTelegramApi()
  const [apiId, setApiId] = useState<number | null>(settings.tg_api_id)
  const [apiHash, setApiHash] = useState('')
  const [confirm, setConfirm] = useState(false)
  const dirty = apiHash.trim() !== '' || apiId !== settings.tg_api_id
  const submit = (event: FormEvent) => {
    event.preventDefault()
    update.mutate(
      { tg_api_id: apiId ?? undefined, tg_api_hash: apiHash.trim() || undefined },
      {
        onSuccess: () => {
          toast.show('API 키를 저장했어요')
          setApiHash('')
        },
      },
    )
  }
  return (
    <section id="api" className={styles.section}>
      <SectionHead title="텔레그램 API 키" note={API_SOURCE[settings.tg_api_source]} />
      <p className={styles.lede}>
        텔레그램에 접속하려면 이 프로그램을 알리는 키가 필요해요. my.telegram.org 에 로그인해서 API
        development tools 에서 한 번만 받으면 돼요. 내 계정이 아니라 이 프로그램을 가리키는 값이라,
        계정이 여러 개여도 하나면 충분해요.
      </p>
      <form className={styles.form} onSubmit={submit}>
        <NumberField
          label="api_id"
          value={apiId}
          onValueChange={setApiId}
          min={1}
          placeholder="숫자"
        />
        <TextField
          label="api_hash"
          type="password"
          revealable
          mono
          autoComplete="off"
          placeholder={
            settings.tg_api_hash_set ? '저장됨 — 바꾸려면 새 값을 넣으세요' : '32자리 영문·숫자'
          }
          hint="저장한 뒤에는 다시 보여 주지 않아요."
          value={apiHash}
          onChange={(event) => setApiHash(event.target.value)}
        />
        <FormError error={update.error} />
        <div className={styles.actions}>
          <Button type="submit" variant="solid" loading={update.isPending} disabled={!dirty}>
            저장
          </Button>
          {settings.tg_api_source === 'settings' && (
            <Button variant="quiet" onClick={() => setConfirm(true)}>
              저장된 키 지우기
            </Button>
          )}
        </div>
      </form>
      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="저장된 API 키를 지울까요?"
        consequence="키가 없으면 계정이 텔레그램에 다시 연결하지 못해요. .env 파일에 값이 있으면 그 값을 써요."
        confirmLabel="지우기"
        onConfirm={() =>
          clear
            .mutateAsync()
            .then(() => {
              setApiId(null)
              toast.show('저장된 키를 지웠어요')
            })
            .catch((error) => toast.problem(errorMessage(error)))
        }
      />
    </section>
  )
}

function CollectSection({ settings }: { settings: Settings }) {
  const toast = useToast()
  const update = useUpdateSettings()
  const [draft, setDraft] = useState(settings)
  // eslint-disable-next-line react-hooks/set-state-in-effect -- 바깥 값이 바뀌면 화면의 입력 상태를 거기에 맞춘다
  useEffect(() => setDraft(settings), [settings])
  const dirty =
    draft.max_groups_per_account !== settings.max_groups_per_account ||
    draft.join_interval_seconds !== settings.join_interval_seconds ||
    draft.store_excerpts !== settings.store_excerpts ||
    draft.retention_days !== settings.retention_days ||
    draft.timezone !== settings.timezone
  const patch = (changes: Partial<Settings>) =>
    setDraft((previous) => ({ ...previous, ...changes }))
  const intervals = INTERVALS.includes(draft.join_interval_seconds)
    ? INTERVALS
    : [...INTERVALS, draft.join_interval_seconds].sort((a, b) => a - b)
  const submit = (event: FormEvent) => {
    event.preventDefault()
    update.mutate(
      {
        max_groups_per_account: draft.max_groups_per_account,
        join_interval_seconds: draft.join_interval_seconds,
        store_excerpts: draft.store_excerpts,
        retention_days: draft.retention_days,
        timezone: draft.timezone,
      },
      { onSuccess: () => toast.show('저장했어요') },
    )
  }
  return (
    <section id="collect" className={styles.section}>
      <SectionHead title="수집" />
      <form className={styles.form} onSubmit={submit} style={{ paddingTop: 'var(--s-4)' }}>
        <NumberField
          label="계정당 그룹 수"
          unit="곳"
          min={1}
          max={500}
          hint="계정 하나가 들어갈 수 있는 그룹 수예요. 그룹을 넣을 때 이 수를 넘기지 않아요."
          value={draft.max_groups_per_account}
          onValueChange={(value) => value !== null && patch({ max_groups_per_account: value })}
        />
        <Select
          label="그룹 가입 간격"
          hint="계정마다 이 간격으로 한 곳씩 들어가요. 텔레그램이 요청을 제한하면 그 시간만큼 더 기다려요."
          value={String(draft.join_interval_seconds)}
          onValueChange={(value) => patch({ join_interval_seconds: Number(value) })}
          options={intervals.map((seconds) => ({
            value: String(seconds),
            label: intervalLabel(seconds),
          }))}
        />
        <Switch
          label="키워드가 나온 문장 저장"
          hint="끄면 문장은 저장하지 않고, 누가 어떤 키워드에 걸렸는지만 남겨요."
          checked={draft.store_excerpts}
          onCheckedChange={(store_excerpts) => patch({ store_excerpts })}
        />
        <Select
          label="감지 기록 보관"
          hint="이 기간이 지난 감지 기록은 지워요. 받아 적은 사람은 남아요."
          value={String(draft.retention_days)}
          onValueChange={(value) => patch({ retention_days: Number(value) })}
          options={
            RETENTION.some((option) => option.value === String(draft.retention_days))
              ? RETENTION
              : [
                  ...RETENTION,
                  { value: String(draft.retention_days), label: `${draft.retention_days}일` },
                ]
          }
        />
        <Select
          label="시간대"
          hint="‘오늘’을 나누는 기준이에요."
          value={draft.timezone}
          onValueChange={(timezone) => patch({ timezone })}
          options={(ZONES.includes(draft.timezone) ? ZONES : [draft.timezone, ...ZONES]).map(
            (zone) => ({ value: zone, label: zone }),
          )}
        />
        <FormError error={update.error} />
        <div className={styles.actions}>
          <Button type="submit" variant="solid" loading={update.isPending} disabled={!dirty}>
            저장
          </Button>
        </div>
      </form>
    </section>
  )
}

function PasswordSection() {
  const toast = useToast()
  const change = useChangePassword()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [again, setAgain] = useState('')
  const mismatch = again !== '' && next !== again
  const submit = (event: FormEvent) => {
    event.preventDefault()
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          toast.show('비밀번호를 바꿨어요')
          setCurrent('')
          setNext('')
          setAgain('')
        },
      },
    )
  }
  return (
    <section id="password" className={styles.section}>
      <SectionHead title="비밀번호" />
      <form className={styles.form} onSubmit={submit} style={{ paddingTop: 'var(--s-4)' }}>
        <TextField
          label="현재 비밀번호"
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
        />
        <TextField
          label="새 비밀번호"
          type="password"
          revealable
          autoComplete="new-password"
          hint="8자 이상으로 정해 주세요."
          value={next}
          onChange={(event) => setNext(event.target.value)}
        />
        <TextField
          label="한 번 더"
          type="password"
          autoComplete="new-password"
          error={mismatch ? '두 비밀번호가 서로 달라요.' : undefined}
          value={again}
          onChange={(event) => setAgain(event.target.value)}
        />
        <FormError error={change.error} />
        <div className={styles.actions}>
          <Button
            type="submit"
            variant="solid"
            loading={change.isPending}
            disabled={!current || next.length < 8 || next !== again}
          >
            비밀번호 바꾸기
          </Button>
        </div>
      </form>
    </section>
  )
}

function AboutSection({ settings }: { settings: Settings }) {
  return (
    <section id="about" className={styles.section}>
      <SectionHead title="정보" />
      <DefinitionList>
        <DefinitionItem term="버전" value={`ChatDB ${settings.version}`} mono />
        <DefinitionItem
          term="하는 일"
          value="듣고 받아 적기만 해요"
          help="그룹 대화에서 찾는 말이 나오면 그 사람의 @아이디를 적어 둬요. 누구에게도 메시지를 보내지 않아요."
        />
        {settings.demo && (
          <DefinitionItem
            term="데모 모드"
            value="켜져 있어요"
            help="텔레그램에 접속하지 않고 가짜 대화로 움직여요. 보이는 계정·그룹·사람은 모두 지어낸 것이에요."
          />
        )}
        <DefinitionItem
          term="글자"
          value="본명조 · 프리텐다드 · IBM 플렉스 모노"
          help="모두 SIL 오픈 폰트 라이선스예요."
        />
      </DefinitionList>
      <SectionHead level={2} title="사진" note="미국 의회도서관 소장 · 저작권 제한 없음" />
      <ul className={styles.credits}>
        {Object.entries(photos).map(([key, photo]) => (
          <li key={key}>
            <img src={photo.src} srcSet={photo.srcSet} alt="" loading="lazy" />
            <span>
              <b>{photo.title}</b>
              {photo.caption} · {photo.credit}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

export default function SettingsPage() {
  const settings = useSettings()
  return (
    <div className={shared.page}>
      <PageHeader title="설정" summary="텔레그램 연결에 필요한 키와, 받아 적는 방식을 정해요." />
      {settings.isError ? (
        <ErrorState
          message={errorMessage(settings.error)}
          onRetry={() => void settings.refetch()}
        />
      ) : !settings.data ? (
        <SkeletonText lines={10} />
      ) : (
        <div className={styles.layout}>
          <nav className={styles.toc} aria-label="설정 차례">
            <a href="#api">텔레그램 API 키</a>
            <a href="#collect">수집</a>
            <a href="#password">비밀번호</a>
            <a href="#about">정보</a>
          </nav>
          <div>
            <ApiSection settings={settings.data} />
            <CollectSection settings={settings.data} />
            <PasswordSection />
            <AboutSection settings={settings.data} />
          </div>
        </div>
      )}
    </div>
  )
}
