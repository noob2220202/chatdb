import { AlertDialog } from 'radix-ui'
import { useState, type ReactNode } from 'react'

import { Button } from '@/ui/Button/Button'

import styles from './ConfirmDialog.module.css'

export type ConfirmDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** 무엇을 하려는지 묻는 제목. "이 그룹에서 나갈까요?" */
  title: ReactNode
  /** 하고 나면 어떻게 되는지 한 문장으로. "수집된 유저 128명은 그대로 남아요." */
  consequence: ReactNode
  /** 확인 버튼의 말. 동작을 그대로 적는다: "나가기", "지우기" */
  confirmLabel: string
  cancelLabel?: string
  /** 약속(Promise)을 돌려주면 끝날 때까지 버튼이 처리 중이 되고, 성공하면 닫힌다. 실패하면 열어 둔다 */
  onConfirm: () => void | Promise<unknown>
}

/**
 * 되돌리기 어려운 일을 하기 전에 한 번 묻는다.
 * 결과를 한 문장으로 적고, 확인 버튼은 빨강이 아니라 먹색 면이다. 처음 포커스는 "취소"에 간다.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  consequence,
  confirmLabel,
  cancelLabel = '취소',
  onConfirm,
}: ConfirmDialogProps) {
  const [busy, setBusy] = useState(false)

  const confirm = async () => {
    const result = onConfirm()
    if (!(result instanceof Promise)) {
      onOpenChange(false)
      return
    }
    setBusy(true)
    try {
      await result
      onOpenChange(false)
    } catch {
      // 실패는 부른 쪽이 알린다(토스트 등). 다시 시도할 수 있게 열어 둔다.
    } finally {
      setBusy(false)
    }
  }

  return (
    <AlertDialog.Root open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className={styles.scrim} />
        <AlertDialog.Content className={styles.sheet}>
          <AlertDialog.Title className={styles.title}>{title}</AlertDialog.Title>
          <AlertDialog.Description className={styles.consequence}>
            {consequence}
          </AlertDialog.Description>
          <div className={styles.foot}>
            <AlertDialog.Cancel asChild>
              <Button variant="outline" disabled={busy}>
                {cancelLabel}
              </Button>
            </AlertDialog.Cancel>
            <Button variant="solid" loading={busy} onClick={confirm}>
              {confirmLabel}
            </Button>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  )
}
