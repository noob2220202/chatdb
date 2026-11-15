import clsx from 'clsx'
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'

import { Tooltip } from '@/ui/Tooltip/Tooltip'

import styles from './IconButton.module.css'

export type IconButtonProps = Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  'aria-label' | 'children'
> & {
  /** 버튼의 이름. 읽어 주는 이름이자 풍선에 뜨는 말이다 */
  label: string
  /** 아이콘 하나 */
  children: ReactNode
  /** quiet: 테 없음(기본) / outline: 먹색 테 */
  variant?: 'quiet' | 'outline'
  size?: 'sm' | 'md'
  /** 먹색 면 위에 놓일 때 */
  onInk?: boolean
  /** 풍선을 숨긴다(이름이 바로 옆에 보일 때) */
  hideTooltip?: boolean
  tooltipSide?: 'top' | 'right' | 'bottom' | 'left'
}

/** 아이콘만 있는 버튼. 이름(label)은 꼭 있어야 한다. */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  {
    label,
    children,
    variant = 'quiet',
    size = 'md',
    onInk = false,
    hideTooltip = false,
    tooltipSide = 'bottom',
    className,
    type,
    ...rest
  },
  ref,
) {
  const button = (
    <button
      ref={ref}
      type={type ?? 'button'}
      aria-label={label}
      className={clsx(
        styles.button,
        styles[variant],
        styles[size],
        onInk && styles.onInk,
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
  if (hideTooltip) return button
  return (
    <Tooltip label={label} side={tooltipSide}>
      {button}
    </Tooltip>
  )
})
