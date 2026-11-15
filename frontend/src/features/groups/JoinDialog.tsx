import { useState } from 'react'

import { errorMessage } from '@/api/client'
import { useAccounts, useJoinGroups, type GroupJoinResponse } from '@/api/hooks'
import { Button } from '@/ui/Button/Button'
import { Dialog } from '@/ui/Dialog/Dialog'
import { ProblemMark } from '@/ui/Field/ProblemMark'
import { Select } from '@/ui/Select/Select'
import { StatusLabel } from '@/ui/StatusLamp/StatusLamp'
import { TextArea } from '@/ui/TextArea/TextArea'

import { joinSummary, splitLinks } from '../overview/overviewText'
import { shared } from '../shared/shared'
import styles from './GroupsPage.module.css'
import { OUTCOME } from './groupsState'

const AUTO = 'auto'

export function JoinDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const accounts = useAccounts()
  const join = useJoinGroups()
  const [text, setText] = useState('')
  const [accountId, setAccountId] = useState(AUTO)
  const [result, setResult] = useState<GroupJoinResponse | null>(null)
  const links = splitLinks(text)

  const reset = () => {
    setText('')
    setResult(null)
    join.reset()
  }
  const close = (next: boolean) => {
    if (!next) reset()
    onOpenChange(next)
  }
  const submit = () =>
    join.mutate(
      { links, account_id: accountId === AUTO ? null : Number(accountId) },
      { onSuccess: setResult },
    )

  const options = [
    { value: AUTO, label: '알아서 나눠 넣기', note: '여유가 많은 계정부터' },
    ...(accounts.data ?? []).map((account) => {
      const free = account.max_groups - account.joined_count - account.pending_count
      const usable = account.enabled && !['reauth_required', 'banned'].includes(account.status)
      return {
        value: String(account.id),
        label: account.display_name,
        note: usable ? `${Math.max(0, free)}자리 남음` : '지금은 쓸 수 없어요',
        disabled: !usable || free <= 0,
      }
    }),
  ]

  return (
    <Dialog
      open={open}
      onOpenChange={close}
      size="md"
      title={result ? '넣은 결과' : '그룹 넣기'}
      description={
        result
          ? undefined
          : '링크를 한 줄에 하나씩 붙여 넣으세요. 공개 그룹은 바로 들어가고, 승인이 필요한 곳은 입장 요청을 보내요.'
      }
      footer={
        result ? (
          <div className={shared.dialogFoot}>
            <Button onClick={reset}>더 넣기</Button>
            <Button variant="solid" onClick={() => close(false)}>
              닫기
            </Button>
          </div>
        ) : (
          <div className={shared.dialogFoot}>
            <Button variant="quiet" onClick={() => close(false)}>
              취소
            </Button>
            <Button
              variant="solid"
              loading={join.isPending}
              disabled={!links.length}
              onClick={submit}
            >
              {links.length ? `${links.length}곳 넣기` : '넣기'}
            </Button>
          </div>
        )
      }
    >
      {result ? (
        <>
          <p className={styles.summary}>{joinSummary(result.items)}</p>
          <ul className={styles.results}>
            {result.items.map((item, index) => {
              const outcome = OUTCOME[item.outcome] ?? {
                kind: 'muted' as const,
                label: item.outcome,
              }
              return (
                <li key={`${item.input}-${index}`}>
                  <span className={styles.input}>{item.input}</span>
                  <StatusLabel kind={outcome.kind}>{outcome.label}</StatusLabel>
                  {item.reason && <span className={styles.why}>{item.reason}</span>}
                </li>
              )
            })}
          </ul>
        </>
      ) : (
        <div className={shared.stack}>
          <TextArea
            label="그룹 링크"
            labelAside={links.length ? `${links.length}곳` : undefined}
            mono
            rows={7}
            data-autofocus
            placeholder={'https://t.me/group_name\n@group_name\nhttps://t.me/+AbCdEfGh1234'}
            hint="t.me 링크, @아이디, 초대 링크(t.me/+…)를 넣을 수 있어요."
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <Select
            label="넣을 계정"
            value={accountId}
            onValueChange={setAccountId}
            options={options}
          />
          {join.isError && (
            <p className={shared.formError} role="alert">
              <ProblemMark /> {errorMessage(join.error)}
            </p>
          )}
        </div>
      )}
    </Dialog>
  )
}
