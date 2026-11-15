import clsx from 'clsx'
import { Switch as RadixSwitch } from 'radix-ui'
import { forwardRef, type ReactNode } from 'react'

import styles from './Switch.module.css'

export type SwitchProps = {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  /** 옆에 적는 이름. 없으면 aria-label 을 꼭 준다 */
  label?: ReactNode
  /** 이름 아래 도움말 */
  hint?: ReactNode
  /** 켜짐·꺼짐을 글자로도 적는다. 예: ['켜짐', '꺼짐'] */
  stateLabels?: readonly [on: string, off: string]
  disabled?: boolean
  id?: string
  name?: string
  'aria-label'?: string
  className?: string
  /** data-* 속성은 레버에 그대로 붙는다 */
  [key: `data-${string}`]: string | undefined
}

/**
 * 두 자리 레버. 교환대의 키처럼 가는 홈 위에서 손잡이가 좌우로 움직인다.
 * 꺼짐: 빈 홈 + 빈 손잡이(왼쪽) / 켜짐: 찬 홈 + 찬 손잡이(오른쪽).
 */
export const Switch = forwardRef<HTMLButtonElement, SwitchProps>(function Switch(
  {
    checked,
    onCheckedChange,
    label,
    hint,
    stateLabels,
    disabled,
    id,
    name,
    'aria-label': ariaLabel,
    className,
    ...dataAttributes
  },
  ref,
) {
  const lever = (
    <RadixSwitch.Root
      ref={ref}
      id={id}
      name={name}
      className={clsx(styles.lever, !label && !stateLabels && className)}
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-label={ariaLabel}
      {...dataAttributes}
    >
      <RadixSwitch.Thumb className={styles.knob} />
    </RadixSwitch.Root>
  )
  if (!label && !stateLabels) return lever
  return (
    <label className={clsx(styles.wrap, className)} data-disabled={disabled || undefined}>
      {lever}
      {stateLabels && (
        <span className={styles.state} data-on={checked || undefined} aria-hidden="true">
          {checked ? stateLabels[0] : stateLabels[1]}
        </span>
      )}
      {label && (
        <span className={styles.text}>
          <span className={styles.label}>{label}</span>
          {hint && <span className={styles.hint}>{hint}</span>}
        </span>
      )}
    </label>
  )
})
