import clsx from 'clsx'
import { RadioGroup } from 'radix-ui'
import type { ReactNode } from 'react'

import styles from './Segmented.module.css'

export type SegmentedOption<T extends string = string> = {
  value: T
  label: ReactNode
  icon?: ReactNode
  disabled?: boolean
}

export type SegmentedProps<T extends string = string> = {
  value: T
  onValueChange: (value: T) => void
  options: readonly SegmentedOption<T>[]
  /** 묶음의 이름(읽어 주는 이름) */
  'aria-label': string
  size?: 'sm' | 'md'
  /** 가로로 꽉 채우고 칸을 같은 폭으로 */
  block?: boolean
  disabled?: boolean
  className?: string
}

/** 둘에서 다섯 가운데 하나 고르기. 붙어 있는 칸, 고른 칸은 먹색 면. 좌우 화살표로 옮긴다. */
export function Segmented<T extends string = string>({
  value,
  onValueChange,
  options,
  'aria-label': ariaLabel,
  size = 'md',
  block = false,
  disabled = false,
  className,
}: SegmentedProps<T>) {
  return (
    <RadioGroup.Root
      className={clsx(styles.group, styles[size], block && styles.block, className)}
      value={value}
      onValueChange={(next) => onValueChange(next as T)}
      orientation="horizontal"
      aria-label={ariaLabel}
      disabled={disabled}
    >
      {options.map((option) => (
        <RadioGroup.Item
          key={option.value}
          value={option.value}
          disabled={option.disabled}
          className={styles.item}
        >
          {option.icon && <span className={styles.icon}>{option.icon}</span>}
          {option.label}
        </RadioGroup.Item>
      ))}
    </RadioGroup.Root>
  )
}
