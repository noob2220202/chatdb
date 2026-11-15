import { createContext, type ReactNode } from 'react'

export type ToastOptions = {
  /** 떠 있는 시간(ms). 기본: 보통 4초, 문제 8초 */
  duration?: number
  /** 띠 오른쪽의 동작 하나("되돌리기", "다시 시도") */
  action?: {
    label: string
    onClick: () => void
    /** 읽어 주는 프로그램에 들려줄 설명. 기본은 label */
    altText?: string
  }
}

export type ToastApi = {
  /** 보통 알림. "3명의 @아이디를 복사했어요" */
  show: (message: ReactNode, options?: ToastOptions) => string
  /** 문제 알림(× 표식). "내보내지 못했어요. 잠시 뒤에 다시 시도해 주세요." */
  problem: (message: ReactNode, options?: ToastOptions) => string
  /** id 를 주면 그 알림만, 안 주면 모두 닫는다 */
  dismiss: (id?: string) => void
}

export const ToastContext = createContext<ToastApi | null>(null)
