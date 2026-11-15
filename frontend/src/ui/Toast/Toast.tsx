import { XIcon } from '@phosphor-icons/react'
import clsx from 'clsx'
import { Toast as RadixToast } from 'radix-ui'
import { useCallback, useMemo, useState, type ReactNode } from 'react'

import { ProblemMark } from '@/ui/Field/ProblemMark'

import styles from './Toast.module.css'
import { ToastContext, type ToastApi, type ToastOptions } from './toastContext'

export { useToast } from './useToast'
export type { ToastApi, ToastOptions } from './toastContext'

type ToastEntry = {
  id: string
  message: ReactNode
  variant: 'plain' | 'problem'
  duration: number
  action?: ToastOptions['action']
  open: boolean
}

const MAX_VISIBLE = 3
const DURATION = { plain: 4000, problem: 8000 } as const

let seed = 0

/**
 * 알림 띠. 화면 아래 가장자리에 먹색 띠가 올라오고 잠시 뒤 사라진다.
 * 앱 맨 위에 한 번 두고, 화면에서는 useToast() 로 띄운다.
 */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastEntry[]>([])

  const push = useCallback(
    (message: ReactNode, variant: 'plain' | 'problem', options: ToastOptions = {}) => {
      seed += 1
      const id = `toast-${seed}`
      setToasts((current) => [
        ...current.slice(-(MAX_VISIBLE - 1)),
        {
          id,
          message,
          variant,
          duration: options.duration ?? DURATION[variant],
          action: options.action,
          open: true,
        },
      ])
      return id
    },
    [],
  )

  const dismiss = useCallback((id?: string) => {
    setToasts((current) =>
      current.map((toast) =>
        id === undefined || toast.id === id ? { ...toast, open: false } : toast,
      ),
    )
  }, [])

  const remove = useCallback((id: string) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
  }, [])

  const api = useMemo<ToastApi>(
    () => ({
      show: (message, options) => push(message, 'plain', options),
      problem: (message, options) => push(message, 'problem', options),
      dismiss,
    }),
    [push, dismiss],
  )

  return (
    <ToastContext.Provider value={api}>
      <RadixToast.Provider swipeDirection="down" label="알림">
        {children}
        {toasts.map((toast) => (
          <RadixToast.Root
            key={toast.id}
            className={clsx(styles.band, toast.variant === 'problem' && styles.problem)}
            open={toast.open}
            duration={toast.duration}
            type={toast.variant === 'problem' ? 'foreground' : 'background'}
            onOpenChange={(open) => {
              if (open) return
              dismiss(toast.id)
              // 사라지는 움직임이 끝난 뒤에 목록에서 뺀다.
              window.setTimeout(() => remove(toast.id), 200)
            }}
          >
            {toast.variant === 'problem' && <ProblemMark onInk className={styles.mark} />}
            <RadixToast.Description className={styles.message}>
              {toast.message}
            </RadixToast.Description>
            {toast.action && (
              <RadixToast.Action
                className={styles.action}
                altText={toast.action.altText ?? toast.action.label}
                onClick={toast.action.onClick}
              >
                {toast.action.label}
              </RadixToast.Action>
            )}
            <RadixToast.Close className={styles.close} aria-label="알림 닫기">
              <XIcon size={14} aria-hidden="true" />
            </RadixToast.Close>
          </RadixToast.Root>
        ))}
        <RadixToast.Viewport className={styles.viewport} />
      </RadixToast.Provider>
    </ToastContext.Provider>
  )
}
