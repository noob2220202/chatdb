import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { errorMessage } from '@/api/client'
import { useAccounts, useClearLogs, useLogs, type LogCategory, type LogLevel } from '@/api/hooks'
import { PHOTO_FOR, photos } from '@/assets/photos'
import { formatCount, formatTime } from '@/lib/format'
import { Button } from '@/ui/Button/Button'
import { ConfirmDialog } from '@/ui/ConfirmDialog/ConfirmDialog'
import { EmptyState } from '@/ui/EmptyState/EmptyState'
import { ErrorState } from '@/ui/ErrorState/ErrorState'
import { PageHeader } from '@/ui/PageHeader/PageHeader'
import { Pagination } from '@/ui/Pagination/Pagination'
import { Select } from '@/ui/Select/Select'
import { SkeletonRows } from '@/ui/Skeleton/Skeleton'
import { StatusLabel } from '@/ui/StatusLamp/StatusLamp'
import { Tabs } from '@/ui/Tabs/Tabs'
import { useToast } from '@/ui/Toast/Toast'

import { shared, useNow, useUrlState } from '../shared/shared'
import styles from './LogsPage.module.css'
import { CATEGORY_LABEL, LEVEL_LABEL, LEVEL_LAMP, groupByDay } from './logsState'

const ALL = 'all'
const LEVELS: readonly LogLevel[] = ['info', 'warning', 'error']
const CATEGORIES: readonly LogCategory[] = ['account', 'group', 'collect', 'system']

export default function LogsPage() {
  const toast = useToast()
  const now = useNow(60_000)
  const url = useUrlState()
  const level = LEVELS.find((value) => value === url.get('level'))
  const category = CATEGORIES.find((value) => value === url.get('category'))
  const accountId = url.num('account')
  const page = url.num('page') ?? 1
  const pageSize = url.num('size') === 100 ? 100 : 50
  const [confirm, setConfirm] = useState(false)

  const logs = useLogs({ level, category, account_id: accountId, page, page_size: pageSize })
  const accounts = useAccounts()
  const clear = useClearLogs()
  const days = useMemo(() => groupByDay(logs.data?.items ?? [], now), [logs.data, now])
  const filtered = Boolean(level || category || accountId)

  return (
    <div className={shared.page}>
      <PageHeader
        title="활동 기록"
        count={logs.data ? formatCount(logs.data.total, '줄') : undefined}
        summary="계정 연결, 그룹 가입, 텔레그램의 요청 제한처럼 콘솔이 한 일을 시간 순서로 적어 둬요."
        aside={
          <Button variant="quiet" disabled={!logs.data?.total} onClick={() => setConfirm(true)}>
            기록 비우기
          </Button>
        }
      />
      <div className={shared.filters}>
        <Tabs<LogLevel | typeof ALL>
          aria-label="종류"
          ruled={false}
          value={level ?? ALL}
          onValueChange={(value) => url.set({ level: value === ALL ? null : value, page: null })}
          items={[
            { value: ALL, label: '전체' },
            ...LEVELS.map((value) => ({ value, label: LEVEL_LABEL[value] })),
          ]}
        />
        <span className={shared.spacer} />
        <Select
          variant="bare"
          prefix="분류"
          aria-label="분류"
          value={category ?? ALL}
          onValueChange={(value) => url.set({ category: value === ALL ? null : value, page: null })}
          options={[
            { value: ALL, label: '전체' },
            ...CATEGORIES.map((value) => ({ value, label: CATEGORY_LABEL[value] })),
          ]}
        />
        <Select
          variant="bare"
          prefix="계정"
          aria-label="계정"
          value={accountId ? String(accountId) : ALL}
          onValueChange={(value) => url.set({ account: value === ALL ? null : value, page: null })}
          options={[
            { value: ALL, label: '전체' },
            ...(accounts.data ?? []).map((account) => ({
              value: String(account.id),
              label: account.display_name,
            })),
          ]}
        />
      </div>

      {logs.isError ? (
        <ErrorState message={errorMessage(logs.error)} onRetry={() => void logs.refetch()} />
      ) : logs.isLoading ? (
        <SkeletonRows rows={12} density="compact" />
      ) : days.length === 0 ? (
        filtered ? (
          <EmptyState
            photo={photos[PHOTO_FOR.noResults]}
            title="조건에 맞는 기록이 없어요"
            description="종류나 분류를 바꿔 보세요."
          />
        ) : (
          <EmptyState
            size="page"
            photo={photos[PHOTO_FOR.logs]}
            title="아직 남은 기록이 없어요"
            description="계정을 연결하고 그룹에 들어가기 시작하면 여기에 한 줄씩 적혀요."
          />
        )
      ) : (
        <>
          {days.map((day) => (
            <section key={day.key}>
              <h2 className={styles.day}>{day.label}</h2>
              <ol className={styles.register}>
                {day.entries.map((entry) => (
                  <li key={entry.id}>
                    <time dateTime={entry.created_at}>{formatTime(entry.created_at)}</time>
                    <StatusLabel kind={LEVEL_LAMP[entry.level]}>
                      {LEVEL_LABEL[entry.level]}
                    </StatusLabel>
                    <span className={styles.cat}>{CATEGORY_LABEL[entry.category]}</span>
                    <span>{entry.message}</span>
                    <span className={styles.about}>
                      {entry.account_name && <Link to="/accounts">{entry.account_name}</Link>}
                      {entry.account_name && entry.group_title && ' · '}
                      {entry.group_title && (
                        <Link to={`/groups?q=${encodeURIComponent(entry.group_title)}`}>
                          {entry.group_title}
                        </Link>
                      )}
                    </span>
                  </li>
                ))}
              </ol>
            </section>
          ))}
          <Pagination
            page={page}
            pageSize={pageSize}
            total={logs.data?.total ?? 0}
            unit="줄"
            sortLabel="최근 것부터"
            pending={logs.isFetching}
            onPageChange={(next) => url.set({ page: next === 1 ? null : next }, false)}
            onPageSizeChange={(size) => url.set({ size: size === 50 ? null : size, page: null })}
          />
        </>
      )}

      <ConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        title="활동 기록을 모두 비울까요?"
        consequence="지금까지의 기록이 모두 지워져요. 받아 적은 사람과 계정, 그룹은 그대로예요."
        confirmLabel="비우기"
        onConfirm={() =>
          clear
            .mutateAsync()
            .then(() => {
              toast.show('활동 기록을 비웠어요')
            })
            .catch((error) => toast.problem(errorMessage(error)))
        }
      />
    </div>
  )
}
