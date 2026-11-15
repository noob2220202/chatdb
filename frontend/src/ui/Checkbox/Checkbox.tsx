import clsx from 'clsx'
import { Checkbox as RadixCheckbox } from 'radix-ui'
import { forwardRef, type ReactNode } from 'react'

import styles from './Checkbox.module.css'

export type CheckboxProps = {
  /** true / false / 'indeterminate'(일부만 고름) */
  checked: boolean | 'indeterminate'
  onCheckedChange: (checked: boolean) => void
  /** 옆에 적는 이름. 없으면 aria-label 을 꼭 준다 */
  label?: ReactNode
  /** 이름 아래 도움말 */
  hint?: ReactNode
  disabled?: boolean
  /** 먹색 면 위에 놓일 때(선택 띠) */
  onInk?: boolean
  id?: string
  name?: string
  value?: string
  'aria-label'?: string
  className?: string
  /** data-* 속성은 체크 칸에 그대로 붙는다 */
  [key: `data-${string}`]: string | undefined
}

/** 네모난 먹색 체크 칸. 일부만 고른 상태(가로줄)까지 있다. */
export const Checkbox = forwardRef<HTMLButtonElement, CheckboxProps>(function Checkbox(
  {
    checked,
    onCheckedChange,
    label,
    hint,
    disabled,
    onInk = false,
    id,
    name,
    value,
    'aria-label': ariaLabel,
    className,
    ...dataAttributes
  },
  ref,
) {
  const box = (
    <RadixCheckbox.Root
      ref={ref}
      id={id}
      name={name}
      value={value}
      className={clsx(styles.box, onInk && styles.onInk, !label && className)}
      checked={checked}
      onCheckedChange={(next) => onCheckedChange(next === true)}
      disabled={disabled}
      aria-label={ariaLabel}
      {...dataAttributes}
    >
      <svg className={styles.glyph} viewBox="0 0 15 15" aria-hidden="true" focusable="false">
        {checked === 'indeterminate' ? (
          <path d="M3.5 7.5h8" />
        ) : checked ? (
          <path d="M3.4 7.7l2.9 2.9 5.3-6.1" />
        ) : null}
      </svg>
    </RadixCheckbox.Root>
  )
  if (!label) return box
  return (
    <label className={clsx(styles.wrap, className)} data-disabled={disabled || undefined}>
      {box}
      <span className={styles.text}>
        <span className={styles.label}>{label}</span>
        {hint && <span className={styles.hint}>{hint}</span>}
      </span>
    </label>
  )
})
