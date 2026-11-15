import clsx from 'clsx'

import styles from './ProblemMark.module.css'

export type ProblemMarkProps = {
  /** 먹색 면 위에 놓일 때: 종이색 면에 먹색 × */
  onInk?: boolean
  className?: string
}

/** 문제 표식: 뒤집힌 네모 안의 ×. 빨강 대신 이 모양으로 문제를 알린다. 글과 함께 쓴다. */
export function ProblemMark({ onInk = false, className }: ProblemMarkProps) {
  return (
    <svg
      className={clsx(styles.mark, onInk && styles.onInk, className)}
      viewBox="0 0 14 14"
      width="14"
      height="14"
      aria-hidden="true"
      focusable="false"
    >
      <rect className={styles.plate} width="14" height="14" />
      <path className={styles.cross} d="M4 4l6 6M10 4l-6 6" />
    </svg>
  )
}
