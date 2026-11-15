import clsx from 'clsx'
import { Popover as RadixPopover } from 'radix-ui'
import type { ReactElement, ReactNode } from 'react'

import styles from './Popover.module.css'

export type PopoverProps = {
  /** 여는 요소(버튼 하나) */
  trigger: ReactElement
  children: ReactNode
  /** 맨 위의 작은 제목 */
  title?: ReactNode
  align?: 'start' | 'center' | 'end'
  side?: 'top' | 'right' | 'bottom' | 'left'
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** 폭(px). 기본 280 */
  width?: number
  'aria-label'?: string
  className?: string
}

/** 누르면 닫히는 요소를 안에 둘 때 감싼다: <PopoverClose asChild><Button>적용</Button></PopoverClose> */
export const PopoverClose = RadixPopover.Close

/** 떠 있는 작은 종이 면. 필터의 세부 조건처럼 메뉴로는 모자란 내용을 담는다. */
export function Popover({
  trigger,
  children,
  title,
  align = 'start',
  side = 'bottom',
  open,
  onOpenChange,
  width = 280,
  'aria-label': ariaLabel,
  className,
}: PopoverProps) {
  return (
    <RadixPopover.Root open={open} onOpenChange={onOpenChange}>
      <RadixPopover.Trigger asChild>{trigger}</RadixPopover.Trigger>
      <RadixPopover.Portal>
        <RadixPopover.Content
          className={clsx(styles.content, className)}
          style={{ width }}
          align={align}
          side={side}
          sideOffset={6}
          collisionPadding={8}
          aria-label={ariaLabel}
        >
          {title && <p className={styles.title}>{title}</p>}
          {children}
        </RadixPopover.Content>
      </RadixPopover.Portal>
    </RadixPopover.Root>
  )
}
