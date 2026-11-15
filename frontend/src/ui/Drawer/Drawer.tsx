import { XIcon } from '@phosphor-icons/react'
import clsx from 'clsx'
import { Dialog as RadixDialog } from 'radix-ui'
import type { ReactElement, ReactNode } from 'react'

import { IconButton } from '@/ui/IconButton/IconButton'

import styles from './Drawer.module.css'

export type DrawerProps = {
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** 여는 요소. open 을 직접 다루면 비워 둔다 */
  trigger?: ReactElement
  /** 명조로 적는 제목 */
  title: ReactNode
  /** 제목 위의 작은 머리말("수집된 유저" 등) */
  eyebrow?: ReactNode
  /** 제목 아래 한두 줄 설명 */
  description?: ReactNode
  children?: ReactNode
  /** 아래에 붙어 있는 동작 줄 */
  footer?: ReactNode
  /** 폭(px). 기본 480 */
  width?: number
  className?: string
}

/** 누르면 서랍이 닫히는 요소를 감싼다 */
export const DrawerClose = RadixDialog.Close

/** 오른쪽에서 나오는 종이 한 장. 목록을 떠나지 않고 자세히 볼 때 쓴다. 문법은 대화상자와 같다. */
export function Drawer({
  open,
  onOpenChange,
  trigger,
  title,
  eyebrow,
  description,
  children,
  footer,
  width = 480,
  className,
}: DrawerProps) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      {trigger && <RadixDialog.Trigger asChild>{trigger}</RadixDialog.Trigger>}
      <RadixDialog.Portal>
        <RadixDialog.Overlay className={styles.scrim} />
        <RadixDialog.Content
          className={clsx(styles.sheet, className)}
          style={{ width }}
          onOpenAutoFocus={(event) => {
            // 자세히 보는 화면이라 닫기 버튼보다 종이 자체가 포커스를 받는 편이 낫다.
            event.preventDefault()
            if (event.currentTarget instanceof HTMLElement) event.currentTarget.focus()
          }}
          {...(description ? {} : { 'aria-describedby': undefined })}
        >
          <header className={styles.head}>
            <div className={styles.heading}>
              {eyebrow && <p className={styles.eyebrow}>{eyebrow}</p>}
              <RadixDialog.Title className={styles.title}>{title}</RadixDialog.Title>
              {description && (
                <RadixDialog.Description className={styles.description}>
                  {description}
                </RadixDialog.Description>
              )}
            </div>
            <RadixDialog.Close asChild>
              <IconButton label="닫기" size="sm" className={styles.close} hideTooltip>
                <XIcon aria-hidden="true" />
              </IconButton>
            </RadixDialog.Close>
          </header>
          <div className={styles.body}>{children}</div>
          {footer && <footer className={styles.foot}>{footer}</footer>}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  )
}
