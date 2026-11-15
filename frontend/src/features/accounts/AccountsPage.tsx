import { DotsThree, Plus } from '@phosphor-icons/react'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { errorMessage } from '@/api/client'
import {
  useAccounts,
  useDeleteAccount,
  useReconnectAccount,
  useSettings,
  useUpdateAccount,
  type Account,
} from '@/api/hooks'
import { PHOTO_FOR, photos } from '@/assets/photos'
import { formatRelative, formatUntil } from '@/lib/format'
import { Button } from '@/ui/Button/Button'
import { Checkbox } from '@/ui/Checkbox/Checkbox'
import { Dialog } from '@/ui/Dialog/Dialog'
import { EmptyState } from '@/ui/EmptyState/EmptyState'
import { ErrorState } from '@/ui/ErrorState/ErrorState'
import { ProblemMark } from '@/ui/Field/ProblemMark'
import { IconButton } from '@/ui/IconButton/IconButton'
import { Menu, MenuItem, MenuSeparator } from '@/ui/Menu/Menu'
import { PageHeader } from '@/ui/PageHeader/PageHeader'
import { SkeletonRows } from '@/ui/Skeleton/Skeleton'
import { SlotDots, SlotDotsScale } from '@/ui/SlotDots/SlotDots'
import { AccountStatusLabel } from '@/ui/StatusLamp/StatusLamp'
import { Switch } from '@/ui/Switch/Switch'
import { Table, TBody, TD, TH, THead, TR } from '@/ui/Table/Table'
import { TextField } from '@/ui/TextField/TextField'
import { useToast } from '@/ui/Toast/Toast'

import { slotTone } from '../overview/overviewText'
import { shared, useNow } from '../shared/shared'
import styles from './AccountsPage.module.css'
import { AddAccountDialog } from './AddAccountDialog'
import { DialogsImport } from './DialogsImport'

export default function AccountsPage() {
  const toast = useToast()
  const now = useNow(15_000)
  const accounts = useAccounts()
  const settings = useSettings()
  const update = useUpdateAccount()
  const reconnect = useReconnectAccount()
  const remove = useDeleteAccount()
  const fail = (error: unknown) => toast.problem(errorMessage(error))

  const [adding, setAdding] = useState<{ phone?: string } | null>(null)
  const [importing, setImporting] = useState<Account | null>(null)
  const [renaming, setRenaming] = useState<Account | null>(null)
  const [name, setName] = useState('')
  const [removing, setRemoving] = useState<Account | null>(null)
  const [logOut, setLogOut] = useState(false)

  const list = accounts.data ?? []
  const connected = list.filter(
    (account) => account.status === 'active' || account.status === 'flood_wait',
  ).length
  const demo = settings.data?.demo ?? false
  const noApi = settings.data ? settings.data.tg_api_source === 'none' && !demo : false

  return (
    <div className={shared.page}>
      <PageHeader
        title="계정"
        count={accounts.data ? `${list.length}개 가운데 ${connected}개 연결됨` : undefined}
        summary="내 텔레그램 계정이에요. 계정마다 그룹에 들어가서 대화를 들어요."
        aside={
          <Button
            variant="solid"
            leadingIcon={<Plus />}
            disabled={noApi}
            onClick={() => setAdding({})}
          >
            계정 추가
          </Button>
        }
      />
      {noApi && (
        <p className={styles.notice}>
          <ProblemMark />
          텔레그램 API 키가 아직 없어요. 계정을 연결하려면 먼저 설정에서 넣어 주세요.
          <Link className={shared.link} to="/settings">
            설정으로 가기
          </Link>
        </p>
      )}

      {accounts.isError ? (
        <ErrorState
          message={errorMessage(accounts.error)}
          onRetry={() => void accounts.refetch()}
        />
      ) : accounts.isLoading ? (
        <SkeletonRows rows={6} />
      ) : list.length === 0 ? (
        <EmptyState
          size="page"
          photo={photos[PHOTO_FOR.accounts]}
          title="아직 연결한 계정이 없어요"
          description="내 텔레그램 계정을 연결하면, 그 계정이 그룹에 들어가서 대화를 듣기 시작해요."
          action={
            !noApi && (
              <Button variant="solid" onClick={() => setAdding({})}>
                계정 추가
              </Button>
            )
          }
        />
      ) : (
        <Table columns={[44, 210, null, 110, 230, 120, 92, 44]} minWidth={1080} aria-label="계정">
          <THead>
            <TR>
              <TH>번호</TH>
              <TH>계정</TH>
              <TH>
                <SlotDotsScale capacity={list[0]?.max_groups ?? 20} />
              </TH>
              <TH align="end">그룹</TH>
              <TH>상태</TH>
              <TH>마지막 연결</TH>
              <TH>켜기</TH>
              <TH aria-label="할 일" />
            </TR>
          </THead>
          <TBody>
            {list.map((account, index) => {
              const until = account.flood_until ? formatUntil(account.flood_until, now) : null
              const detail =
                account.status === 'flood_wait'
                  ? `텔레그램이 요청을 잠시 막았어요.${until ? ` ${until}에 다시 시작해요.` : ''}`
                  : account.status !== 'active'
                    ? account.status_detail
                    : null
              const relogin = account.status === 'reauth_required'
              return (
                <TR key={account.id}>
                  <TD mono dim>
                    {String(index + 1).padStart(2, '0')}
                  </TD>
                  <TD truncate>
                    <span className={styles.name}>{account.display_name}</span>
                    <span className={`${shared.sub} ${shared.num}`}>
                      {[account.phone_masked, account.username ? `@${account.username}` : null]
                        .filter(Boolean)
                        .join(' · ')}
                    </span>
                  </TD>
                  <TD>
                    <SlotDots
                      joined={account.joined_count}
                      pending={account.pending_count}
                      capacity={account.max_groups}
                      tone={slotTone(account)}
                    />
                  </TD>
                  <TD align="end" mono>
                    {account.joined_count}/{account.max_groups}
                    {account.pending_count > 0 && (
                      <span className={shared.sub}>기다리는 중 {account.pending_count}</span>
                    )}
                  </TD>
                  <TD>
                    <AccountStatusLabel status={account.enabled ? account.status : 'offline'} />
                    {detail && account.enabled && <span className={shared.sub}>{detail}</span>}
                    {relogin && (
                      <button
                        type="button"
                        className={shared.link}
                        onClick={() => setAdding({ phone: '' })}
                      >
                        다시 로그인하기
                      </button>
                    )}
                  </TD>
                  <TD dim>
                    {account.last_connected_at
                      ? formatRelative(account.last_connected_at, now)
                      : '—'}
                  </TD>
                  <TD>
                    <Switch
                      aria-label={`${account.display_name} 켜기`}
                      checked={account.enabled}
                      onCheckedChange={(enabled) =>
                        update.mutate({ id: account.id, enabled }, { onError: fail })
                      }
                    />
                  </TD>
                  <TD align="end">
                    <Menu
                      align="end"
                      trigger={
                        <IconButton label={`${account.display_name} 할 일`} size="sm" hideTooltip>
                          <DotsThree />
                        </IconButton>
                      }
                    >
                      <MenuItem
                        onSelect={() => {
                          setName(account.label ?? '')
                          setRenaming(account)
                        }}
                      >
                        이름 바꾸기
                      </MenuItem>
                      <MenuItem
                        disabled={!account.enabled}
                        onSelect={() =>
                          reconnect.mutate(account.id, {
                            onSuccess: () =>
                              toast.show(`${account.display_name} 계정을 다시 연결하고 있어요`),
                            onError: fail,
                          })
                        }
                      >
                        다시 연결
                      </MenuItem>
                      <MenuItem onSelect={() => setAdding({ phone: '' })}>다시 로그인</MenuItem>
                      <MenuItem
                        disabled={account.status !== 'active'}
                        onSelect={() => setImporting(account)}
                      >
                        들어가 있는 그룹 불러오기
                      </MenuItem>
                      <MenuSeparator />
                      <MenuItem
                        onSelect={() => {
                          setLogOut(false)
                          setRemoving(account)
                        }}
                      >
                        계정 지우기
                      </MenuItem>
                    </Menu>
                  </TD>
                </TR>
              )
            })}
          </TBody>
        </Table>
      )}

      <AddAccountDialog
        open={adding !== null}
        onOpenChange={(open) => !open && setAdding(null)}
        demo={demo}
        initialPhone={adding?.phone}
      />
      <DialogsImport account={importing} onClose={() => setImporting(null)} />

      <Dialog
        open={renaming !== null}
        onOpenChange={(open) => !open && setRenaming(null)}
        size="sm"
        title="이름 바꾸기"
        footer={
          <div className={shared.dialogFoot}>
            <Button variant="quiet" onClick={() => setRenaming(null)}>
              취소
            </Button>
            <Button
              variant="solid"
              loading={update.isPending}
              onClick={() =>
                renaming &&
                update.mutate(
                  { id: renaming.id, label: name.trim() },
                  { onSuccess: () => setRenaming(null), onError: fail },
                )
              }
            >
              저장
            </Button>
          </div>
        }
      >
        <TextField
          label="목록에서 보일 이름"
          hint="비워 두면 텔레그램 이름을 그대로 써요."
          maxLength={64}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </Dialog>

      <Dialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        size="sm"
        title="이 계정을 지울까요?"
        description={`${removing?.display_name ?? ''} 계정과 그 계정의 그룹 ${removing?.joined_count ?? 0}곳이 목록에서 빠져요. 이미 받아 적은 사람은 수집함에 그대로 남아요.`}
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
                  { id: removing.id, logOut },
                  {
                    onSuccess: () => {
                      toast.show('계정을 지웠어요')
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
        <Checkbox
          checked={logOut}
          onCheckedChange={setLogOut}
          label="텔레그램에서도 이 세션 로그아웃하기"
          hint="켜면 이 콘솔이 쓰던 로그인이 텔레그램에서도 끊겨요. 계정 자체는 그대로예요."
        />
      </Dialog>
    </div>
  )
}
