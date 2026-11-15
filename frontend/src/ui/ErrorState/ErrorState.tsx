import clsx from 'clsx'
import type { ReactNode } from 'react'

import { Button } from '@/ui/Button/Button'

import styles from './ErrorState.module.css'

export interface ErrorStateProps {
  /** 무엇을 하지 못했는지: "수집함을 불러오지 못했어요" */
  title?: ReactNode
  /** 까닭과 다음에 할 일. API 오류 문장(errorMessage)을 그대로 넣어도 된다 */
  message?: ReactNode
  /** 다시 불러오기. 주지 않으면 버튼이 없다 */
  onRetry?: () => void
  /** 다시 불러오는 중 */
  retrying?: boolean
  /** 버튼 글자. 기본 "다시 불러오기" */
  retryLabel?: string
  /** 버튼 대신(또는 옆에) 놓을 다른 동작 */
  action?: ReactNode
  /** section: 꼭지 안 (기본) / inline: 표·목록 안의 한 줄 */
  size?: 'section' | 'inline'
  className?: string
}

/**
 * 오류 상태: 있는 그대로 말하고 "다시 불러오기"를 내민다.
 * 빨강을 쓰지 않는다. 문제는 반전(먹색 면의 ×)으로 드러낸다.
 */
export function ErrorState({
  title = '불러오지 못했어요',
  message = '잠시 뒤에 다시 시도해 주세요.',
  onRetry,
  retrying = false,
  retryLabel = '다시 불러오기',
  action,
  size = 'section',
  className,
}: ErrorStateProps) {
  return (
    <div className={clsx(styles.error, styles[size], className)} role="alert">
      <svg
        className={styles.mark}
        width="22"
        height="22"
        viewBox="0 0 22 22"
        aria-hidden="true"
        focusable="false"
      >
        <rect width="22" height="22" />
        <path d="M7 7l8 8M15 7l-8 8" />
      </svg>
      <div className={styles.body}>
        <p className={styles.title}>{title}</p>
        {message && <p className={styles.message}>{message}</p>}
        {(onRetry || action) && (
          <div className={styles.actions}>
            {onRetry && (
              <Button variant="outline" size="sm" onClick={onRetry} loading={retrying}>
                {retryLabel}
              </Button>
            )}
            {action}
          </div>
        )}
      </div>
    </div>
  )
}
