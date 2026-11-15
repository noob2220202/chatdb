import { X } from '@phosphor-icons/react'
import { useEffect, useId, useMemo, useState, type KeyboardEvent } from 'react'

import { errorMessage } from '@/api/client'
import { useCreateRule, useGroups, useUpdateRule, type Rule, type RuleKind } from '@/api/hooks'
import { highlight } from '@/lib/highlight'
import { Button } from '@/ui/Button/Button'
import { Checkbox } from '@/ui/Checkbox/Checkbox'
import { Dialog } from '@/ui/Dialog/Dialog'
import { ProblemMark } from '@/ui/Field/ProblemMark'
import { KeywordText } from '@/ui/KeywordText/KeywordText'
import { NumberField } from '@/ui/NumberField/NumberField'
import { Segmented } from '@/ui/Segmented/Segmented'
import { Select } from '@/ui/Select/Select'
import { TextField } from '@/ui/TextField/TextField'
import { useToast } from '@/ui/Toast/Toast'

import { shared } from '../shared/shared'
import styles from './RulesPage.module.css'
import { WINDOWS, addKeywords, excludeSentence, ruleSentence } from './ruleText'

export type RuleDraft = {
  id?: number
  name: string
  kind: RuleKind
  keywords: string[]
  exclude_keywords: string[]
  match_mode: 'any' | 'all'
  min_messages: number | null
  window_hours: number | null
  all_groups: boolean
  group_ids: number[]
}

export const EMPTY_DRAFT: RuleDraft = {
  name: '',
  kind: 'keyword',
  keywords: [],
  exclude_keywords: [],
  match_mode: 'any',
  min_messages: 30,
  window_hours: 24,
  all_groups: true,
  group_ids: [],
}

export function draftOf(rule: Rule): RuleDraft {
  return {
    id: rule.id,
    name: rule.name,
    kind: rule.kind,
    keywords: rule.keywords,
    exclude_keywords: rule.exclude_keywords,
    match_mode: rule.match_mode,
    min_messages: rule.min_messages,
    window_hours: rule.window_hours,
    all_groups: rule.all_groups,
    group_ids: rule.group_ids,
  }
}

function ChipInput({
  label,
  hint,
  values,
  onChange,
  placeholder,
}: {
  label: string
  hint?: string
  values: string[]
  onChange: (values: string[]) => void
  placeholder: string
}) {
  const id = useId()
  const [text, setText] = useState('')
  const commit = (input: string) => {
    onChange(addKeywords(values, input))
    setText('')
  }
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.nativeEvent.isComposing) return
    if ((event.key === 'Enter' || event.key === ',') && text.trim()) {
      event.preventDefault()
      commit(text)
    } else if (event.key === 'Backspace' && !text && values.length) {
      onChange(values.slice(0, -1))
    }
  }
  return (
    <div>
      <label className={styles.label} htmlFor={id}>
        {label}
      </label>
      <div className={styles.chips}>
        {values.map((word) => (
          <span key={word} className={styles.chip}>
            {word}
            <button
              type="button"
              aria-label={`${word} 빼기`}
              onClick={() => onChange(values.filter((each) => each !== word))}
            >
              <X size={11} weight="bold" />
            </button>
          </span>
        ))}
        <input
          id={id}
          value={text}
          placeholder={values.length ? '' : placeholder}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
          onBlur={() => text.trim() && commit(text)}
          onPaste={(event) => {
            const pasted = event.clipboardData.getData('text')
            if (/[,\n]/.test(pasted)) {
              event.preventDefault()
              commit(pasted)
            }
          }}
        />
      </div>
      {hint && <p className={shared.note}>{hint}</p>}
    </div>
  )
}

type Props = { draft: RuleDraft | null; onClose: () => void }

export function RuleEditor({ draft: initial, onClose }: Props) {
  const toast = useToast()
  const groups = useGroups({ status: ['joined'] })
  const create = useCreateRule()
  const update = useUpdateRule()
  const [draft, setDraft] = useState<RuleDraft>(EMPTY_DRAFT)
  const [sample, setSample] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [groupQuery, setGroupQuery] = useState('')

  useEffect(() => {
    if (initial) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- 바깥 값이 바뀌면 화면의 입력 상태를 거기에 맞춘다
      setDraft(initial)
      setSample('')
      setError(null)
      setGroupQuery('')
    }
  }, [initial])

  const patch = (changes: Partial<RuleDraft>) =>
    setDraft((previous) => ({ ...previous, ...changes }))
  const editing = draft.id !== undefined
  const sampleHit = useMemo(
    () =>
      sample.trim() !== '' && highlight(sample, draft.keywords).some((segment) => segment.match),
    [sample, draft.keywords],
  )
  const sampleBlocked = useMemo(
    () =>
      sample.trim() !== '' &&
      highlight(sample, draft.exclude_keywords).some((segment) => segment.match),
    [sample, draft.exclude_keywords],
  )
  const shownGroups = (groups.data ?? []).filter((group) =>
    group.display_title.toLowerCase().includes(groupQuery.trim().toLowerCase()),
  )

  const save = () => {
    setError(null)
    const body = {
      name: draft.name,
      enabled: true,
      keywords: draft.kind === 'keyword' ? draft.keywords : [],
      exclude_keywords: draft.kind === 'keyword' ? draft.exclude_keywords : [],
      match_mode: draft.match_mode,
      min_messages: draft.kind === 'activity' ? draft.min_messages : null,
      window_hours: draft.kind === 'activity' ? draft.window_hours : null,
      all_groups: draft.all_groups,
      group_ids: draft.all_groups ? [] : draft.group_ids,
    }
    const done = () => {
      toast.show(editing ? '규칙을 고쳤어요' : '규칙을 만들었어요')
      onClose()
    }
    if (draft.id !== undefined) {
      update.mutate(
        { id: draft.id, ...body, enabled: undefined },
        { onSuccess: done, onError: setError },
      )
    } else {
      create.mutate({ ...body, kind: draft.kind }, { onSuccess: done, onError: setError })
    }
  }

  return (
    <Dialog
      open={initial !== null}
      onOpenChange={(open) => !open && onClose()}
      size="lg"
      title={editing ? '규칙 고치기' : '규칙 만들기'}
      footer={
        <div className={shared.dialogFoot}>
          <Button variant="quiet" onClick={onClose}>
            취소
          </Button>
          <Button variant="solid" loading={create.isPending || update.isPending} onClick={save}>
            {editing ? '저장' : '만들기'}
          </Button>
        </div>
      }
    >
      <div className={shared.stack}>
        {!editing && (
          <Segmented<RuleKind>
            aria-label="규칙 종류"
            value={draft.kind}
            onValueChange={(kind) => patch({ kind })}
            options={[
              { value: 'keyword', label: '키워드를 말한 사람' },
              { value: 'activity', label: '활발하게 채팅하는 사람' },
            ]}
          />
        )}
        <TextField
          label="규칙 이름"
          data-autofocus
          maxLength={80}
          placeholder={draft.kind === 'keyword' ? '예: 견적 문의' : '예: 활발한 유저'}
          value={draft.name}
          onChange={(event) => patch({ name: event.target.value })}
        />

        {draft.kind === 'keyword' ? (
          <>
            <ChipInput
              label="키워드"
              placeholder="키워드를 쓰고 Enter (쉼표로 여러 개)"
              hint="대소문자는 가리지 않아요. ‘업체 추천’처럼 띄어 쓴 키워드는 붙여 쓴 ‘업체추천’도 잡아요."
              values={draft.keywords}
              onChange={(keywords) => patch({ keywords })}
            />
            {draft.keywords.length > 1 && (
              <Segmented<'any' | 'all'>
                aria-label="매칭 방식"
                size="sm"
                value={draft.match_mode}
                onValueChange={(match_mode) => patch({ match_mode })}
                options={[
                  { value: 'any', label: '하나라도 나오면' },
                  { value: 'all', label: '모두 나오면' },
                ]}
              />
            )}
            <ChipInput
              label="제외 키워드 (선택)"
              placeholder="이 말이 함께 나오면 건너뛰어요"
              values={draft.exclude_keywords}
              onChange={(exclude_keywords) => patch({ exclude_keywords })}
            />
          </>
        ) : (
          <>
            <NumberField
              label="메시지 수"
              unit="개 넘게"
              min={2}
              max={10000}
              value={draft.min_messages}
              onValueChange={(min_messages) => patch({ min_messages })}
            />
            <Select
              label="기간"
              value={String(draft.window_hours ?? 24)}
              onValueChange={(value) => patch({ window_hours: Number(value) })}
              options={WINDOWS}
            />
          </>
        )}

        <Segmented<'all' | 'some'>
          aria-label="적용 범위"
          size="sm"
          value={draft.all_groups ? 'all' : 'some'}
          onValueChange={(value) => patch({ all_groups: value === 'all' })}
          options={[
            { value: 'all', label: '모든 그룹에 적용' },
            {
              value: 'some',
              label: `고른 그룹에만${draft.all_groups ? '' : ` (${draft.group_ids.length}곳)`}`,
            },
          ]}
        />
        {!draft.all_groups && (
          <>
            <TextField
              placeholder="그룹 이름으로 찾기"
              aria-label="그룹 찾기"
              value={groupQuery}
              onChange={(event) => setGroupQuery(event.target.value)}
            />
            <div className={styles.scope}>
              {shownGroups.map((group) => (
                <Checkbox
                  key={group.id}
                  label={group.display_title}
                  checked={draft.group_ids.includes(group.id)}
                  onCheckedChange={(checked) =>
                    patch({
                      group_ids: checked
                        ? [...draft.group_ids, group.id]
                        : draft.group_ids.filter((id) => id !== group.id),
                    })
                  }
                />
              ))}
              {shownGroups.length === 0 && <p className={shared.note}>가입된 그룹이 없어요.</p>}
            </div>
          </>
        )}

        <p className={styles.readback}>
          {ruleSentence(draft)} {excludeSentence(draft)}
        </p>

        {draft.kind === 'keyword' && draft.keywords.length > 0 && (
          <div>
            <TextField
              label="문장으로 시험해 보기"
              placeholder="그룹에서 나올 법한 문장을 써 보세요"
              value={sample}
              onChange={(event) => setSample(event.target.value)}
            />
            {sample.trim() !== '' && (
              <p className={shared.note}>
                {sampleBlocked ? (
                  '제외 키워드가 들어 있어서 건너뛰어요.'
                ) : sampleHit ? (
                  <>
                    이렇게 걸려요 —{' '}
                    <KeywordText text={sample} keywords={draft.keywords} variant="table" />
                  </>
                ) : (
                  '이 문장은 걸리지 않아요.'
                )}
              </p>
            )}
          </div>
        )}

        {error !== null && (
          <p className={shared.formError} role="alert">
            <ProblemMark /> {errorMessage(error)}
          </p>
        )}
      </div>
    </Dialog>
  )
}
