import { Plus } from '@phosphor-icons/react'
import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'

import { errorMessage } from '@/api/client'
import {
  useAddBlocklist,
  useBlocklist,
  useDeleteRule,
  useRemoveBlocklist,
  useRules,
  useUpdateRule,
  type Rule,
} from '@/api/hooks'
import { PHOTO_FOR, photos } from '@/assets/photos'
import { formatDay, formatNumber, formatRelative } from '@/lib/format'
import { Button } from '@/ui/Button/Button'
import { ConfirmDialog } from '@/ui/ConfirmDialog/ConfirmDialog'
import { EmptyState } from '@/ui/EmptyState/EmptyState'
import { ErrorState } from '@/ui/ErrorState/ErrorState'
import { PageHeader } from '@/ui/PageHeader/PageHeader'
import { RuleSwatch } from '@/ui/RuleSwatch/RuleSwatch'
import { SectionHead } from '@/ui/SectionHead/SectionHead'
import { SkeletonText } from '@/ui/Skeleton/Skeleton'
import { Switch } from '@/ui/Switch/Switch'
import { TextField } from '@/ui/TextField/TextField'
import { useToast } from '@/ui/Toast/Toast'

import { shared, useNow, useSwatchIndex } from '../shared/shared'
import { EMPTY_DRAFT, RuleEditor, draftOf, type RuleDraft } from './RuleEditor'
import styles from './RulesPage.module.css'
import { excludeSentence, ruleSentence } from './ruleText'

const QUICK: RuleDraft[] = [
  { ...EMPTY_DRAFT, name: '견적을 묻는 사람', keywords: ['견적', '외주'] },
  {
    ...EMPTY_DRAFT,
    name: '요즘 활발한 사람',
    kind: 'activity',
    min_messages: 30,
    window_hours: 24,
  },
]

function Blocklist() {
  const toast = useToast()
  const blocklist = useBlocklist()
  const add = useAddBlocklist()
  const remove = useRemoveBlocklist()
  const [text, setText] = useState('')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    const usernames = text.split(/[\s,]+/).filter(Boolean)
    if (!usernames.length) return
    add.mutate(
      { usernames },
      {
        onSuccess: (created) => {
          toast.show(
            created.length
              ? `${created.length}개를 제외 목록에 올렸어요`
              : '이미 모두 목록에 있어요',
          )
          setText('')
        },
        onError: (error) => toast.problem(errorMessage(error)),
      },
    )
  }
  return (
    <section className={styles.section}>
      <SectionHead
        level={2}
        title="받아 적지 않을 아이디"
        note={blocklist.data ? `${blocklist.data.length}개` : undefined}
      />
      <form className={styles.blockForm} onSubmit={submit}>
        <TextField
          label="아이디 넣기"
          mono
          placeholder="@아이디 (띄어쓰기나 쉼표로 여러 개)"
          hint="여기 있는 아이디는 키워드를 말해도 받아 적지 않아요. 내 계정은 넣지 않아도 알아서 빠져요."
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
        <Button type="submit" loading={add.isPending} disabled={!text.trim()}>
          올리기
        </Button>
      </form>
      {blocklist.data && blocklist.data.length > 0 ? (
        <ul className={styles.block}>
          {blocklist.data.map((entry) => (
            <li key={entry.id}>
              <span className={shared.handle}>@{entry.username}</span>
              <span className={shared.note}>
                {formatDay(entry.created_at)}에 올림{entry.note ? ` · ${entry.note}` : ''}
              </span>
              <Button
                size="sm"
                variant="quiet"
                onClick={() =>
                  remove.mutate(entry.id, {
                    onError: (error) => toast.problem(errorMessage(error)),
                  })
                }
              >
                빼기
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        blocklist.data && <p className={shared.note}>아직 제외한 아이디가 없어요.</p>
      )}
    </section>
  )
}

export default function RulesPage() {
  const toast = useToast()
  const now = useNow()
  const rules = useRules()
  const swatches = useSwatchIndex()
  const update = useUpdateRule()
  const remove = useDeleteRule()
  const [draft, setDraft] = useState<RuleDraft | null>(null)
  const [removing, setRemoving] = useState<Rule | null>(null)
  const fail = (error: unknown) => toast.problem(errorMessage(error))
  const list = rules.data ?? []

  return (
    <div className={shared.page}>
      <PageHeader
        title="수집 규칙"
        count={rules.data ? `${list.length}개` : undefined}
        summary="어떤 사람을 받아 적을지 정해요. 규칙마다 무늬가 하나씩 붙고, 어느 화면에서나 같은 무늬로 보여요."
        aside={
          <Button variant="solid" leadingIcon={<Plus />} onClick={() => setDraft(EMPTY_DRAFT)}>
            규칙 만들기
          </Button>
        }
      />
      {rules.isError ? (
        <ErrorState message={errorMessage(rules.error)} onRetry={() => void rules.refetch()} />
      ) : rules.isLoading ? (
        <SkeletonText lines={8} />
      ) : list.length === 0 ? (
        <EmptyState
          size="page"
          photo={photos[PHOTO_FOR.rules]}
          title="아직 규칙이 없어요"
          description="규칙이 있어야 받아 적기 시작해요. 아래에서 골라 바로 시작해도 돼요."
          action={
            <span className={styles.quick}>
              {QUICK.map((quick) => (
                <Button key={quick.name} onClick={() => setDraft(quick)}>
                  {quick.name}
                </Button>
              ))}
            </span>
          }
        />
      ) : (
        <ul className={styles.ledger}>
          {list.map((rule) => {
            const exclude = excludeSentence(rule)
            return (
              <li key={rule.id} className={rule.enabled ? undefined : styles.resting}>
                <span className={styles.swatch}>
                  <RuleSwatch index={swatches.get(rule.id) ?? -1} size={16} muted={!rule.enabled} />
                </span>
                <h2 className={styles.name}>
                  {rule.name}
                  <small>
                    {rule.kind === 'keyword' ? '키워드' : '활발한 유저'} ·{' '}
                    {rule.all_groups ? '모든 그룹' : `고른 그룹 ${rule.group_ids.length}곳`}
                    {!rule.enabled && ' · 꺼 둠'}
                  </small>
                </h2>
                <div className={styles.side}>
                  <Switch
                    aria-label={`${rule.name} 켜기`}
                    checked={rule.enabled}
                    onCheckedChange={(enabled) =>
                      update.mutate({ id: rule.id, enabled }, { onError: fail })
                    }
                  />
                  <Button size="sm" onClick={() => setDraft(draftOf(rule))}>
                    고치기
                  </Button>
                  <Button size="sm" variant="quiet" onClick={() => setRemoving(rule)}>
                    지우기
                  </Button>
                </div>
                <span />
                <p className={styles.sentence}>
                  {ruleSentence(rule)} {exclude}
                </p>
                <span />
                <p className={styles.figures}>
                  <Link to={`/leads?rule_id=${rule.id}`} className={shared.link}>
                    수집 {formatNumber(rule.lead_count)}명
                  </Link>
                  <span>감지 {formatNumber(rule.hit_count)}번</span>
                  <span>
                    {rule.last_hit_at
                      ? `마지막 감지 ${formatRelative(rule.last_hit_at, now)}`
                      : '아직 감지 없음'}
                  </span>
                </p>
              </li>
            )
          })}
        </ul>
      )}

      <Blocklist />
      <RuleEditor draft={draft} onClose={() => setDraft(null)} />
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`‘${removing?.name ?? ''}’ 규칙을 지울까요?`}
        consequence="규칙을 지워도 이미 받아 적은 사람은 수집함에 그대로 남아요."
        confirmLabel="지우기"
        onConfirm={() => {
          if (!removing) return
          return remove
            .mutateAsync(removing.id)
            .then(() => {
              toast.show('규칙을 지웠어요')
            })
            .catch(fail)
        }}
      />
    </div>
  )
}
