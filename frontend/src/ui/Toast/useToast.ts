import { useContext } from 'react'

import { ToastContext, type ToastApi } from './toastContext'

/**
 * 알림 띠를 띄운다.
 *
 *   const toast = useToast()
 *   toast.show('3명의 @아이디를 복사했어요')
 *   toast.problem('내보내지 못했어요.', { action: { label: '다시 시도', onClick: retry } })
 */
export function useToast(): ToastApi {
  const api = useContext(ToastContext)
  if (!api) throw new Error('useToast 는 <ToastProvider> 안에서만 쓸 수 있어요.')
  return api
}
