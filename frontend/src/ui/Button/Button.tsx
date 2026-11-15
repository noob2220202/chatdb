import clsx from 'clsx'
import { Slot } from 'radix-ui'
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'

import styles from './Button.module.css'

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  /** solid: 먹색 면(주요 동작) / outline: 먹색 테(기본) / quiet: 밑줄 그은 글자 */
  variant?: 'solid' | 'outline' | 'quiet'
  size?: 'sm' | 'md' | 'lg'
  leadingIcon?: ReactNode
  trailingIcon?: ReactNode
  /** 처리 중. 폭은 그대로 두고 글자 자리에 점 세 개가 차례로 켜진다 */
  loading?: boolean
  /** 가로로 꽉 채운다 */
  block?: boolean
  /** 먹색 면 위에 놓일 때(토스트, 선택 띠) */
  onInk?: boolean
  /** 자식 요소(예: <Link>)에 버튼 모양을 입힌다 */
  asChild?: boolean
}

/** 처리 중 표시: 점 세 개가 차례로 켜진다. 버튼 밖에서도 쓸 수 있다. */
export function LoadingDots({ className }: { className?: string }) {
  return (
    <span className={clsx(styles.dots, className)} aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
  )
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'outline',
    size = 'md',
    leadingIcon,
    trailingIcon,
    loading = false,
    block = false,
    onInk = false,
    asChild = false,
    className,
    children,
    disabled,
    type,
    ...rest
  },
  ref,
) {
  const classes = clsx(
    styles.button,
    styles[variant],
    styles[size],
    block && styles.block,
    onInk && styles.onInk,
    className,
  )
  const leading = leadingIcon ? <span className={styles.icon}>{leadingIcon}</span> : null
  const trailing = trailingIcon ? (
    <span className={clsx(styles.icon, styles.trailing)}>{trailingIcon}</span>
  ) : null

  if (asChild) {
    return (
      <Slot.Root ref={ref} className={classes} {...rest}>
        {leading}
        <Slot.Slottable>{children}</Slot.Slottable>
        {trailing}
      </Slot.Root>
    )
  }

  return (
    <button
      ref={ref}
      type={type ?? 'button'}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      data-loading={loading || undefined}
      {...rest}
    >
      {leading}
      <span className={styles.label}>{children}</span>
      {trailing}
      {loading && (
        <>
          <LoadingDots className={styles.loader} />
          <span className="visually-hidden">처리하고 있어요</span>
        </>
      )}
    </button>
  )
})
