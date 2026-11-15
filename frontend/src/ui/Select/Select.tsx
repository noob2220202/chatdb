import { CaretDownIcon, CheckIcon } from '@phosphor-icons/react'
import clsx from 'clsx'
import { Select as RadixSelect } from 'radix-ui'
import type { ReactNode } from 'react'

import { Field } from '@/ui/Field/Field'

import styles from './Select.module.css'

export type SelectOption = {
  /** 빈 문자열은 쓸 수 없다. "전체" 같은 항목에는 'all' 같은 값을 준다 */
  value: string
  label: string
  /** 항목 오른쪽의 흐린 보조 글(개수 등) */
  note?: string
  disabled?: boolean
}

export type SelectProps = {
  value: string | undefined
  onValueChange: (value: string) => void
  options: SelectOption[]
  placeholder?: string
  /** 값 앞에 붙는 흐린 머리말. 필터 줄에서 "규칙 전체" 처럼 쓴다 */
  prefix?: string
  /** underline: 밑줄 있는 입력 칸 모양(폼) / bare: 줄 없이(필터 줄) */
  variant?: 'underline' | 'bare'
  label?: ReactNode
  labelAside?: ReactNode
  hint?: ReactNode
  error?: ReactNode
  disabled?: boolean
  /** 펼친 목록을 어느 쪽에 맞출지 */
  align?: 'start' | 'end'
  'aria-label'?: string
  id?: string
  name?: string
  className?: string
}

/** 하나 고르기. 펼친 목록은 떠 있는 종이 면에 먹색 테, 가는 괘선으로 나눈다. */
export function Select({
  value,
  onValueChange,
  options,
  placeholder = '고르기',
  prefix,
  variant = 'underline',
  label,
  labelAside,
  hint,
  error,
  disabled = false,
  align = 'start',
  'aria-label': ariaLabel,
  id,
  name,
  className,
}: SelectProps) {
  const renderControl = (
    ids: { id?: string; describedBy?: string; invalid?: boolean },
    controlClassName?: string,
  ) => (
    <RadixSelect.Root value={value} onValueChange={onValueChange} disabled={disabled} name={name}>
      <RadixSelect.Trigger
        id={ids.id}
        className={clsx(styles.trigger, styles[variant], controlClassName)}
        aria-label={ariaLabel}
        aria-describedby={ids.describedBy}
        aria-invalid={ids.invalid || undefined}
      >
        {prefix && <span className={styles.prefix}>{prefix}</span>}
        <span className={styles.value}>
          <RadixSelect.Value placeholder={placeholder} />
        </span>
        <RadixSelect.Icon className={styles.caret}>
          <CaretDownIcon size={11} aria-hidden="true" />
        </RadixSelect.Icon>
      </RadixSelect.Trigger>
      <RadixSelect.Portal>
        <RadixSelect.Content
          className={styles.content}
          position="popper"
          sideOffset={4}
          align={align}
        >
          <RadixSelect.Viewport className={styles.viewport}>
            {options.map((option) => (
              <RadixSelect.Item
                key={option.value}
                value={option.value}
                disabled={option.disabled}
                className={styles.item}
              >
                <RadixSelect.ItemIndicator className={styles.check}>
                  <CheckIcon size={12} aria-hidden="true" />
                </RadixSelect.ItemIndicator>
                <RadixSelect.ItemText>{option.label}</RadixSelect.ItemText>
                {option.note && <span className={styles.note}>{option.note}</span>}
              </RadixSelect.Item>
            ))}
          </RadixSelect.Viewport>
        </RadixSelect.Content>
      </RadixSelect.Portal>
    </RadixSelect.Root>
  )

  if (!label && !hint && !error && !labelAside) return renderControl({ id }, className)

  return (
    <Field
      label={label}
      labelAside={labelAside}
      hint={hint}
      error={error}
      id={id}
      className={className}
    >
      {(ids) => renderControl(ids)}
    </Field>
  )
}
