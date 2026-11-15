import { ArrowSquareOut, Copy } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'

import { errorMessage } from '@/api/client'
import { useBulkLeads, useDeleteLead, useLead, useUpdateLead, type LeadStatus } from '@/api/hooks'
import { formatDateTime } from '@/lib/format'
import { Button } from '@/ui/Button/Button'
import { ConfirmDialog } from '@/ui/ConfirmDialog/ConfirmDialog'
import { Drawer } from '@/ui/Drawer/Drawer'
import { ErrorState } from '@/ui/ErrorState/ErrorState'
import { IconButton } from '@/ui/IconButton/IconButton'
import { Segmented } from '@/ui/Segmented/Segmented'
import { SkeletonText } from '@/ui/Skeleton/Skeleton'
import { LEAD_STATUS } from '@/ui/StatusLamp/StatusLamp'
import { TextArea } from '@/ui/TextArea/TextArea'
import { useToast } from '@/ui/Toast/Toast'

import { HitText, RuleName, shared } from '../shared/shared'
import styles from './LeadsPage.module.css'
import { STATUSES } from './leadsState'

type Props = { leadId: number | null; swatches: Map<number, number>; onClose: () => void }

export function LeadDrawer({ leadId, swatches, onClose }: Props) {
  const toast = useToast()
  const { data: lead, isLoading, isError, refetch } = useLead(leadId)
  const update = useUpdateLead()
  const bulk = useBulkLeads()
  const remove = useDeleteLead()
  const [note, setNote] = useState('')
  const [saved, setSaved] = useState(false)
  const [confirm, setConfirm] = useState<'block' | 'delete' | null>(null)

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- 바깥 값이 바뀌면 화면의 입력 상태를 거기에 맞춘다
    setNote(lead?.note ?? '')
    setSaved(false)
  }, [lead?.id, lead?.note])

  const fail = (error: unknown) => toast.problem(errorMessage(error))

  const saveNote = () => {
    if (!lead || note === (lead.note ?? '')) return
    update.mutate({ id: lead.id, note }, { onSuccess: () => setSaved(true), onError: fail })
  }

  const copy = async () => {
    if (!lead) return
    try {
      await navigator.clipboard.writeText(`@${lead.username}`)
      toast.show(`@${lead.username} 을 복사했어요`)
    } catch {
      toast.problem('복사하지 못했어요. 브라우저에서 복사 권한을 확인해 주세요.')
    }
  }

  return (
    <>
      <Drawer
        open={leadId !== null}
        onOpenChange={(open) => !open && onClose()}
        eyebrow="받아 적은 사람"
        title={lead ? lead.display_name : '불러오는 중'}
        width={520}
      >
        {isLoading && <SkeletonText lines={8} />}
        {isError && <ErrorState size="inline" onRetry={() => void refetch()} />}
        {lead && (
          <>
            <p className={styles.detailHandle}>
              @{lead.username}
              <IconButton label="@아이디 복사" onClick={() => void copy()}>
                <Copy />
              </IconButton>
            </p>
            <p className={shared.note}>
              <a
                className={shared.link}
                href={`https://t.me/${lead.username}`}
                target="_blank"
                rel="noopener noreferrer"
              >
                텔레그램에서 프로필 보기 <ArrowSquareOut size={12} aria-hidden />
              </a>
            </p>

            <section className={styles.block}>
              <h3>상태</h3>
              <Segmented<LeadStatus>
                aria-label="상태"
                size="sm"
                value={lead.status}
                onValueChange={(status) =>
                  update.mutate({ id: lead.id, status }, { onError: fail })
                }
                options={STATUSES.map((value) => ({ value, label: LEAD_STATUS[value].label }))}
              />
            </section>

            <section className={styles.block}>
              <dl className={styles.meta}>
                <dt>처음 감지</dt>
                <dd>{formatDateTime(lead.first_seen_at)}</dd>
                <dt>마지막 감지</dt>
                <dd>{formatDateTime(lead.last_seen_at)}</dd>
                <dt>감지 횟수</dt>
                <dd className={shared.num}>{lead.hit_count}번</dd>
                <dt>감지된 그룹</dt>
                <dd>{lead.group_titles.length ? lead.group_titles.join(', ') : '—'}</dd>
              </dl>
            </section>

            <section className={styles.block}>
              <TextArea
                label="메모"
                labelAside={saved ? <span className={styles.saved}>저장했어요</span> : undefined}
                value={note}
                rows={3}
                autoGrow
                maxLength={2000}
                placeholder="이 사람에 대해 적어 둘 것"
                onChange={(event) => {
                  setNote(event.target.value)
                  setSaved(false)
                }}
                onBlur={saveNote}
              />
            </section>

            <section className={styles.block}>
              <h3>감지 기록</h3>
              <ol className={styles.timeline}>
                {lead.hits.map((hit) => (
                  <li key={hit.id}>
                    <time dateTime={hit.created_at}>{formatDateTime(hit.created_at)}</time>
                    <span className={styles.where}>
                      <RuleName hit={hit} swatches={swatches} />
                      <span>{hit.group_title ?? '지워진 그룹'}</span>
                    </span>
                    <HitText hit={hit} variant="quote" />
                  </li>
                ))}
              </ol>
            </section>

            <section className={styles.block}>
              <div className={styles.danger}>
                {lead.status !== 'excluded' && (
                  <Button size="sm" onClick={() => setConfirm('block')}>
                    제외 목록에 올리기
                  </Button>
                )}
                <Button size="sm" variant="quiet" onClick={() => setConfirm('delete')}>
                  수집함에서 지우기
                </Button>
              </div>
            </section>
          </>
        )}
      </Drawer>

      <ConfirmDialog
        open={confirm === 'block'}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="제외 목록에 올릴까요?"
        consequence="이 사람은 앞으로 키워드를 말하거나 활발해져도 다시 받아 적지 않아요."
        confirmLabel="제외하기"
        onConfirm={() =>
          lead &&
          bulk
            .mutateAsync({ ids: [lead.id], action: 'block' })
            .then(() => toast.show(`@${lead.username} 을 제외 목록에 올렸어요`))
            .catch(fail)
        }
      />
      <ConfirmDialog
        open={confirm === 'delete'}
        onOpenChange={(open) => !open && setConfirm(null)}
        title="수집함에서 지울까요?"
        consequence="감지 기록과 메모가 함께 지워져요. 나중에 다시 감지되면 새로 받아 적어요."
        confirmLabel="지우기"
        onConfirm={() =>
          lead &&
          remove
            .mutateAsync(lead.id)
            .then(() => {
              toast.show(`@${lead.username} 을 지웠어요`)
              onClose()
            })
            .catch(fail)
        }
      />
    </>
  )
}
