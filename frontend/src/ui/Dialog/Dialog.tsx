import { XIcon } from '@phosphor-icons/react'
import clsx from 'clsx'
import { Dialog as RadixDialog } from 'radix-ui'
import type { ReactElement, ReactNode } from 'react'

import { IconButton } from '@/ui/IconButton/IconButton'

import styles from './Dialog.module.css'

export type DialogProps = {
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** 여는 요소. open 을 직접 다루면 비워 둔다 */
  trigger?: ReactElement
  /** 명조로 적는 제목 */
  title: ReactNode
  /** 제목 아래 한두 줄 설명 */
  description?: ReactNode
  children?: ReactNode
  /** 아래쪽 동작 버튼들. 오른쪽에 붙는다(취소 → 주요 동작 순) */
  footer?: ReactNode
  /** sm 420 / md 560 / lg 760 */
  size?: 'sm' | 'md' | 'lg'
  /** 처리 중처럼 닫히면 안 될 때: Esc·바깥 누르기·닫기 버튼을 막는다 */
  locked?: boolean
  className?: string
}

/** 누르면 대화상자가 닫히는 요소를 감싼다: <DialogClose asChild><Button>취소</Button></DialogClose> */
export const DialogClose = RadixDialog.Close

/**
 * 열릴 때의 포커스: 닫기 버튼이 아니라 첫 입력 칸으로 보낸다(data-autofocus 가 붙은 요소가 있으면 그쪽).
 * 입력 칸이 없으면 종이 자체가 포커스를 받는다.
 */
function focusFirstField(event: Event) {
  const sheet = event.currentTarget
  if (!(sheet instanceof HTMLElement)) return
  const target = sheet.querySelector<HTMLElement>(
    '[data-autofocus], input:not([type="hidden"]):not(:disabled), textarea:not(:disabled), [role="combobox"]:not(:disabled)',
  )
  event.preventDefault()
  ;(target ?? sheet).focus()
}

/** 대화상자. 떠 있는 종이 한 장: 위에 2px 먹색 줄, 명조 제목, 동작은 오른쪽 아래. */
export function Dialog({
  open,
  onOpenChange,
  trigger,
  title,
  description,
  children,
  footer,
  size = 'md',
  locked = false,
  className,
}: DialogProps) {
  return (
    <RadixDialog.Root open={open} onOpenChange={onOpenChange}>
      {trigger && <RadixDialog.Trigger asChild>{trigger}</RadixDialog.Trigger>}
      <RadixDialog.Portal>
        <RadixDialog.Overlay className={styles.scrim} />
        <RadixDialog.Content
          className={clsx(styles.sheet, styles[size], className)}
          onOpenAutoFocus={focusFirstField}
          onEscapeKeyDown={(event) => locked && event.preventDefault()}
          onPointerDownOutside={(event) => locked && event.preventDefault()}
          onInteractOutside={(event) => locked && event.preventDefault()}
          {...(description ? {} : { 'aria-describedby': undefined })}
        >
          <header className={styles.head}>
            <div className={styles.heading}>
              <RadixDialog.Title className={styles.title}>{title}</RadixDialog.Title>
              {description && (
                <RadixDialog.Description className={styles.description}>
                  {description}
                </RadixDialog.Description>
              )}
            </div>
            {!locked && (
              <RadixDialog.Close asChild>
                <IconButton label="닫기" size="sm" className={styles.close} hideTooltip>
                  <XIcon aria-hidden="true" />
                </IconButton>
              </RadixDialog.Close>
            )}
          </header>
          {children && <div className={styles.body}>{children}</div>}
          {footer && <footer className={styles.foot}>{footer}</footer>}
        </RadixDialog.Content>
      </RadixDialog.Portal>
    </RadixDialog.Root>
  )
}
