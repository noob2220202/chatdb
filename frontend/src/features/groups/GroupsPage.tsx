import { DotsThree, Plus } from '@phosphor-icons/react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { errorMessage } from '@/api/client'
import {
  useAccounts,
  useDeleteGroup,
  useGroups,
  useRetryGroup,
  useSettings,
  useUpdateGroup,
  type Group,
} from '@/api/hooks'
import { PHOTO_FOR, photos } from '@/assets/photos'
import { formatDuration, formatNumber, formatRelative, formatUntil } from '@/lib/format'
import { Button } from '@/ui/Button/Button'
import { Checkbox } from '@/ui/Checkbox/Checkbox'
import { Dialog } from '@/ui/Dialog/Dialog'
import { EmptyState } from '@/ui/EmptyState/EmptyState'
import { ErrorState } from '@/ui/ErrorState/ErrorState'
import { IconButton } from '@/ui/IconButton/IconButton'
import { Menu, MenuItem, MenuSeparator } from '@/ui/Menu/Menu'
import { PageHeader } from '@/ui/PageHeader/PageHeader'
import { SearchField } from '@/ui/SearchField/SearchField'
import { Select } from '@/ui/Select/Select'
import { SkeletonRows } from '@/ui/Skeleton/Skeleton'
import { GroupStatusLabel } from '@/ui/StatusLamp/StatusLamp'
import { Switch } from '@/ui/Switch/Switch'
import { Table, TBody, TD, TH, THead, TR } from '@/ui/Table/Table'
import { Tabs } from '@/ui/Tabs/Tabs'
import { useToast } from '@/ui/Toast/Toast'

import { shared, useNow, useUrlState } from '../shared/shared'
import styles from './GroupsPage.module.css'
import { JoinDialog } from './JoinDialog'
import {
  KIND_LABEL,
  TAB_STATUSES,
  countTabs,
  readTab,
  sortGroups,
  type GroupSort,
  type GroupTab,
} from './groupsState'

const ALL = 'all'

export default function GroupsPage() {
  const toast = useToast()
  const now = useNow(15_000)
  const url = useUrlState()
  const tab = readTab(url.get('status'))
  const accountId = url.num('account')
  const q = url.get('q')
  const [sort, setSort] = useState<{ key: GroupSort; desc: boolean }>({ key: 'recent', desc: true })
  const [joinOpen, setJoinOpen] = useState(false)
  const [removing, setRemoving] = useState<Group | null>(null)
  const [leave, setLeave] = useState(false)

  const groups = useGroups()
  const accounts = useAccounts()
  const settings = useSettings()
  const update = useUpdateGroup()
  const retry = useRetryGroup()
  const remove = useDeleteGroup()
  const fail = (error: unknown) => toast.problem(errorMessage(error))

  const all = useMemo(() => groups.data ?? [], [groups.data])
  const counts = useMemo(() => countTabs(all), [all])
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase()
    const filtered = all.filter(
      (group) =>
        (tab === 'all' || TAB_STATUSES[tab].includes(group.status)) &&
        (!accountId || group.account_id === accountId) &&
        (!needle ||
          [group.display_title, group.public_username, group.source_link].some((value) =>
            value?.toLowerCase().includes(needle),
          )),
    )
    return sortGroups(filtered, sort.key, sort.desc)
  }, [all, tab, accountId, q, sort])

  const flip = (key: GroupSort) =>
    setSort((previous) => ({ key, desc: previous.key === key ? !previous.desc : true }))
  const sortOf = (key: GroupSort) => (sort.key === key ? (sort.desc ? 'desc' : 'asc') : 'none')

  const interval = settings.data?.join_interval_seconds
  const header = (
    <PageHeader
      title="그룹"
      count={groups.data ? `${formatNumber(all.length)}곳` : undefined}
      summary={
        groups.data
          ? `가입됨 ${counts.joined} · 승인 기다리는 중 ${counts.requested} · 대기열 ${counts.queued} · 실패 ${counts.failed}`
          : undefined
      }
      aside={
        <Button variant="solid" leadingIcon={<Plus />} onClick={() => setJoinOpen(true)}>
          그룹 넣기
        </Button>
      }
    />
  )

  return (
    <div className={shared.page}>
      {header}
      {groups.isError ? (
        <ErrorState message={errorMessage(groups.error)} onRetry={() => void groups.refetch()} />
      ) : groups.isLoading ? (
        <SkeletonRows rows={10} density="compact" />
      ) : all.length === 0 ? (
        <EmptyState
          size="page"
          photo={photos[PHOTO_FOR.groups]}
          title="아직 넣은 그룹이 없어요"
          description={
            accounts.data && accounts.data.length === 0
              ? '그룹에 들어갈 계정이 먼저 있어야 해요.'
              : '링크를 붙여 넣으면 계정이 차례로 들어가서 대화를 듣기 시작해요.'
          }
          action={
            accounts.data && accounts.data.length === 0 ? (
              <Button asChild variant="solid">
                <Link to="/accounts">계정 연결하러 가기</Link>
              </Button>
            ) : (
              <Button variant="solid" onClick={() => setJoinOpen(true)}>
                그룹 넣기
              </Button>
            )
          }
        />
      ) : (
        <>
          <div className={shared.filters}>
            <SearchField
              className={shared.grow}
              value={q}
              onValueChange={(value) => url.set({ q: value })}
              placeholder="그룹 이름이나 링크로 찾기"
              aria-label="그룹 찾기"
            />
            <Select
              variant="bare"
              prefix="계정"
              aria-label="계정"
              value={accountId ? String(accountId) : ALL}
              onValueChange={(value) => url.set({ account: value === ALL ? null : value })}
              options={[
                { value: ALL, label: '전체' },
                ...(accounts.data ?? []).map((account) => ({
                  value: String(account.id),
                  label: account.display_name,
                })),
              ]}
            />
          </div>
          <Tabs<GroupTab>
            aria-label="상태"
            value={tab}
            onValueChange={(value) => url.set({ status: value === 'all' ? null : value })}
            items={[
              { value: 'all', label: '전체', count: counts.all },
              { value: 'joined', label: '가입됨', count: counts.joined },
              { value: 'requested', label: '승인 기다리는 중', count: counts.requested },
              { value: 'queued', label: '대기열', count: counts.queued },
              { value: 'failed', label: '실패·나감', count: counts.failed },
            ]}
          />
          {interval && (counts.queued > 0 || tab === 'queued') && (
            <p className={`${shared.note} ${styles.queueNote}`}>
              ＊ 계정마다 {formatDuration(interval)}에 한 곳씩 차례로 들어가요. 텔레그램이 요청을
              제한하면 그만큼 더 기다려요.
            </p>
          )}
          {rows.length === 0 ? (
            <EmptyState
              photo={photos[PHOTO_FOR.noResults]}
              title="조건에 맞는 그룹이 없어요"
              description="찾는 말이나 탭을 바꿔 보세요."
            />
          ) : (
            <Table
              density="compact"
              columns={[null, 96, 84, 250, 96, 76, 110, 92, 44]}
              minWidth={1120}
              stickyTop={0}
              aria-label="그룹"
            >
              <THead>
                <TR>
                  <TH sort={sortOf('title')} onSort={() => flip('title')}>
                    그룹
                  </TH>
                  <TH>계정</TH>
                  <TH align="end" sort={sortOf('members')} onSort={() => flip('members')}>
                    인원
                  </TH>
                  <TH>상태</TH>
                  <TH align="end">받은 메시지</TH>
                  <TH align="end" sort={sortOf('leads')} onSort={() => flip('leads')}>
                    수집
                  </TH>
                  <TH sort={sortOf('last')} onSort={() => flip('last')}>
                    마지막 메시지
                  </TH>
                  <TH>감시</TH>
                  <TH aria-label="할 일" />
                </TR>
              </THead>
              <TBody>
                {rows.map((group) => {
                  const again = group.next_attempt_at
                    ? formatUntil(group.next_attempt_at, now)
                    : null
                  const detail =
                    group.kind === 'channel' && group.status === 'joined'
                      ? '채팅이 없어 수집되지 않아요'
                      : again
                        ? `${again}에 다시 시도해요`
                        : group.status !== 'joined'
                          ? group.status_detail
                          : null
                  return (
                    <TR key={group.id} muted={group.status === 'left'}>
                      <TD truncate>
                        <span className={styles.title}>{group.display_title}</span>
                        <span className={shared.sub}>
                          {group.kind ? `${KIND_LABEL[group.kind]} · ` : ''}
                          <span className={shared.num}>
                            {group.public_username
                              ? `@${group.public_username}`
                              : (group.source_link ?? '불러온 그룹')}
                          </span>
                        </span>
                      </TD>
                      <TD truncate dim>
                        {group.account_name}
                      </TD>
                      <TD align="end" mono dim>
                        {group.member_count !== null ? formatNumber(group.member_count) : '—'}
                      </TD>
                      <TD truncate>
                        <GroupStatusLabel status={group.status} />
                        {detail && <span className={shared.sub}>{detail}</span>}
                      </TD>
                      <TD align="end" mono dim>
                        {formatNumber(group.messages_seen)}
                      </TD>
                      <TD align="end" mono>
                        {group.lead_count > 0 ? (
                          <Link className={shared.link} to={`/leads?group_id=${group.id}`}>
                            {formatNumber(group.lead_count)}
                          </Link>
                        ) : (
                          '0'
                        )}
                      </TD>
                      <TD dim>
                        {group.last_message_at ? formatRelative(group.last_message_at, now) : '—'}
                      </TD>
                      <TD>
                        {group.status === 'joined' && (
                          <Switch
                            aria-label={`${group.display_title} 감시`}
                            checked={group.monitoring}
                            onCheckedChange={(monitoring) =>
                              update.mutate({ id: group.id, monitoring }, { onError: fail })
                            }
                          />
                        )}
                      </TD>
                      <TD align="end">
                        <Menu
                          align="end"
                          trigger={
                            <IconButton
                              label={`${group.display_title} 할 일`}
                              size="sm"
                              hideTooltip
                            >
                              <DotsThree />
                            </IconButton>
                          }
                        >
                          {(group.status === 'failed' || group.status === 'left') &&
                            group.link_kind !== 'existing' && (
                              <MenuItem
                                onSelect={() =>
                                  retry.mutate(group.id, {
                                    onSuccess: () => toast.show('다시 가입 대기열에 넣었어요'),
                                    onError: fail,
                                  })
                                }
                              >
                                다시 시도
                              </MenuItem>
                            )}
                          {group.lead_count > 0 && (
                            <MenuItem>
                              <Link to={`/leads?group_id=${group.id}`}>
                                여기서 받아 적은 사람 보기
                              </Link>
                            </MenuItem>
                          )}
                          <MenuSeparator />
                          <MenuItem
                            onSelect={() => {
                              setLeave(false)
                              setRemoving(group)
                            }}
                          >
                            목록에서 지우기
                          </MenuItem>
                        </Menu>
                      </TD>
                    </TR>
                  )
                })}
              </TBody>
            </Table>
          )}
        </>
      )}

      <JoinDialog open={joinOpen} onOpenChange={setJoinOpen} />

      <Dialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        size="sm"
        title="이 그룹을 목록에서 지울까요?"
        description={`‘${removing?.display_title ?? ''}’ 을(를) 더 듣지 않아요. 여기서 이미 받아 적은 사람은 수집함에 그대로 남아요.`}
        footer={
          <div className={shared.dialogFoot}>
            <Button variant="quiet" onClick={() => setRemoving(null)}>
              취소
            </Button>
            <Button
              variant="solid"
              loading={remove.isPending}
              onClick={() =>
                removing &&
                remove.mutate(
                  { id: removing.id, leave },
                  {
                    onSuccess: () => {
                      toast.show('그룹을 지웠어요')
                      setRemoving(null)
                    },
                    onError: fail,
                  },
                )
              }
            >
              지우기
            </Button>
          </div>
        }
      >
        {removing?.status === 'joined' && (
          <Checkbox
            checked={leave}
            onCheckedChange={setLeave}
            label="텔레그램에서도 이 그룹에서 나가기"
            hint="끄면 계정은 그룹에 그대로 남고, 콘솔에서만 빠져요."
          />
        )}
      </Dialog>
    </div>
  )
}
