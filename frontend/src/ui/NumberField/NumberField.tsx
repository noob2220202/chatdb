import { MinusIcon, PlusIcon } from '@phosphor-icons/react'
import { forwardRef, useState, type KeyboardEvent, type ReactNode } from 'react'

import { Field } from '@/ui/Field/Field'

import styles from './NumberField.module.css'

export type NumberFieldProps = {
  /** 비어 있으면 null */
  value: number | null
  onValueChange: (value: number | null) => void
  min?: number
  max?: number
  /** 화살표·버튼 한 번에 바뀌는 크기. 기본 1 */
  step?: number
  /** 숫자 뒤에 붙는 단위("명", "시간", "곳") */
  unit?: string
  label?: ReactNode
  labelAside?: ReactNode
  hint?: ReactNode
  error?: ReactNode
  placeholder?: string
  disabled?: boolean
  id?: string
  name?: string
  'aria-label'?: string
  className?: string
}

/** 값을 범위 안으로 넣는다. */
export function clampNumber(value: number, min?: number, max?: number): number {
  let next = value
  if (min !== undefined && next < min) next = min
  if (max !== undefined && next > max) next = max
  return next
}

/** 입력한 글자를 숫자로 읽는다. 숫자가 아니면 null. */
export function parseNumber(text: string): number | null {
  const cleaned = text.replace(/[,\s]/g, '')
  if (cleaned === '' || cleaned === '-') return null
  const parsed = Number(cleaned)
  return Number.isFinite(parsed) ? parsed : null
}

/** 숫자 입력 칸. 모노 숫자, 단위, 줄이기·늘리기 버튼. 위·아래 화살표로도 바꾼다. */
export const NumberField = forwardRef<HTMLInputElement, NumberFieldProps>(function NumberField(
  {
    value,
    onValueChange,
    min,
    max,
    step = 1,
    unit,
    label,
    labelAside,
    hint,
    error,
    placeholder,
    disabled = false,
    id,
    name,
    'aria-label': ariaLabel,
    className,
  },
  ref,
) {
  // 쓰는 동안에는 적은 글자를 그대로 보여 주고, 칸을 떠날 때 범위에 맞춘다.
  const [draft, setDraft] = useState<string | null>(null)
  const shown = draft ?? (value === null ? '' : String(value))

  const commit = (next: number | null) => {
    onValueChange(next === null ? null : clampNumber(next, min, max))
  }

  const nudge = (direction: 1 | -1) => {
    const base = value ?? (direction === 1 ? (min ?? 0) - step : (max ?? 0) + step)
    const next = clampNumber(base + direction * step, min, max)
    setDraft(null)
    onValueChange(next)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      nudge(1)
    } else if (event.key === 'ArrowDown') {
      event.preventDefault()
      nudge(-1)
    }
  }

  const atMin = min !== undefined && value !== null && value <= min
  const atMax = max !== undefined && value !== null && value >= max

  return (
    <Field
      label={label}
      labelAside={labelAside}
      hint={hint}
      error={error}
      id={id}
      className={className}
    >
      {(ids) => (
        <div
          className={styles.shell}
          data-invalid={ids.invalid || undefined}
          data-disabled={disabled || undefined}
        >
          <input
            ref={ref}
            id={ids.id}
            name={name}
            type="text"
            inputMode="numeric"
            role="spinbutton"
            autoComplete="off"
            className={styles.input}
            value={shown}
            placeholder={placeholder}
            disabled={disabled}
            aria-label={ariaLabel}
            aria-valuenow={value ?? undefined}
            aria-valuemin={min}
            aria-valuemax={max}
            aria-valuetext={value !== null && unit ? `${value}${unit}` : undefined}
            aria-invalid={ids.invalid || undefined}
            aria-describedby={ids.describedBy}
            onFocus={(event) => {
              setDraft(shown)
              event.target.select()
            }}
            onChange={(event) => {
              const text = event.target.value.replace(/[^\d.,-]/g, '')
              setDraft(text)
              const parsed = parseNumber(text)
              // 쓰는 도중에는 범위를 강제하지 않는다(예: 최소 10인데 "1"을 먼저 치는 경우).
              if (parsed === null) onValueChange(null)
              else if (
                (min === undefined || parsed >= min) &&
                (max === undefined || parsed <= max)
              ) {
                onValueChange(parsed)
              }
            }}
            onBlur={() => {
              if (draft !== null) commit(parseNumber(draft))
              setDraft(null)
            }}
            onKeyDown={onKeyDown}
          />
          {unit && <span className={styles.unit}>{unit}</span>}
          <span className={styles.steps}>
            <button
              type="button"
              tabIndex={-1}
              className={styles.step}
              aria-label="줄이기"
              disabled={disabled || atMin}
              onClick={() => nudge(-1)}
            >
              <MinusIcon size={12} aria-hidden="true" />
            </button>
            <button
              type="button"
              tabIndex={-1}
              className={styles.step}
              aria-label="늘리기"
              disabled={disabled || atMax}
              onClick={() => nudge(1)}
            >
              <PlusIcon size={12} aria-hidden="true" />
            </button>
          </span>
        </div>
      )}
    </Field>
  )
})
