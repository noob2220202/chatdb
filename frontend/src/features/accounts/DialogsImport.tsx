import { useMemo, useState } from 'react'

import { errorMessage } from '@/api/client'
import { useDialogs, useImportDialogs, type Account } from '@/api/hooks'
import { formatNumber } from '@/lib/format'
import { Button } from '@/ui/Button/Button'
import { Checkbox } from '@/ui/Checkbox/Checkbox'
import { Dialog } from '@/ui/Dialog/Dialog'
import { ErrorState } from '@/ui/ErrorState/ErrorState'
import { SearchField } from '@/ui/SearchField/SearchField'
import { SkeletonRows } from '@/ui/Skeleton/Skeleton'
import { useToast } from '@/ui/Toast/Toast'

import { KIND_LABEL } from '../groups/groupsState'
import { shared } from '../shared/shared'
import styles from './AccountsPage.module.css'

export function DialogsImport({
  account,
  onClose,
}: {
  account: Account | null
  onClose: () => void
}) {
  const toast = useToast()
  const dialogs = useDialogs(account?.id ?? null)
  const importDialogs = useImportDialogs()
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [q, setQ] = useState('')

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase()
    return (dialogs.data ?? []).filter(
      (chat) =>
        !needle ||
        chat.title.toLowerCase().includes(needle) ||
        chat.username?.toLowerCase().includes(needle),
    )
  }, [dialogs.data, q])
  const free = rows.filter((chat) => !chat.already_added)
  const toggle = (id: number) =>
    setPicked((previous) => {
      const next = new Set(previous)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  const close = () => {
    setPicked(new Set())
    setQ('')
    onClose()
  }

  return (
    <Dialog
      open={account !== null}
      onOpenChange={(open) => !open && close()}
      size="lg"
      title="들어가 있는 그룹 불러오기"
      description={`${account?.display_name ?? ''} 계정이 이미 들어가 있는 그룹이에요. 고른 곳을 감시 목록에 넣어요.`}
      footer={
        <div className={shared.dialogFoot}>
          <Button variant="quiet" onClick={close}>
            취소
          </Button>
          <Button
            variant="solid"
            loading={importDialogs.isPending}
            disabled={picked.size === 0}
            onClick={() =>
              account &&
              importDialogs.mutate(
                { accountId: account.id, tgChatIds: [...picked] },
                {
                  onSuccess: (groups) => {
                    toast.show(`${groups.length}곳을 감시 목록에 넣었어요`)
                    close()
                  },
                  onError: (error) => toast.problem(errorMessage(error)),
                },
              )
            }
          >
            {picked.size ? `${picked.size}곳 넣기` : '넣기'}
          </Button>
        </div>
      }
    >
      {dialogs.isLoading ? (
        <SkeletonRows rows={6} density="compact" />
      ) : dialogs.isError ? (
        <ErrorState
          size="inline"
          message={errorMessage(dialogs.error)}
          onRetry={() => void dialogs.refetch()}
        />
      ) : (
        <>
          <div className={styles.dialogsHead}>
            <SearchField
              value={q}
              onValueChange={setQ}
              placeholder="그룹 이름으로 찾기"
              shortcut={false}
            />
            <Button
              size="sm"
              variant="quiet"
              disabled={free.length === 0}
              onClick={() =>
                setPicked(
                  picked.size === free.length
                    ? new Set()
                    : new Set(free.map((chat) => chat.tg_chat_id)),
                )
              }
            >
              {picked.size === free.length && free.length > 0 ? '모두 풀기' : '모두 고르기'}
            </Button>
          </div>
          {rows.length === 0 ? (
            <p className={shared.note}>들어가 있는 그룹이 없어요.</p>
          ) : (
            <ul className={styles.dialogs}>
              {rows.map((chat) => (
                <li key={chat.tg_chat_id}>
                  <Checkbox
                    checked={chat.already_added || picked.has(chat.tg_chat_id)}
                    disabled={chat.already_added}
                    onCheckedChange={() => toggle(chat.tg_chat_id)}
                    label={chat.title}
                    hint={[
                      KIND_LABEL[chat.kind],
                      chat.username ? `@${chat.username}` : null,
                      chat.already_added ? '이미 감시 중이에요' : null,
                    ]
                      .filter(Boolean)
                      .join(' · ')}
                  />
                  <span className={shared.num}>
                    {chat.member_count !== null ? `${formatNumber(chat.member_count)}명` : ''}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Dialog>
  )
}
