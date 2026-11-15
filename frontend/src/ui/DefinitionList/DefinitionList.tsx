import clsx from 'clsx'
import type { ReactNode } from 'react'

import styles from './DefinitionList.module.css'

export interface DefinitionListProps {
  children: ReactNode
  /** 이름 칸의 폭(px). 기본 200 */
  termWidth?: number
  className?: string
}

/** 설정 화면의 항목 목록: 이름 — 값·설명 — 동작. 줄마다 가는 괘선으로 나눈다. */
export function DefinitionList({ children, termWidth = 200, className }: DefinitionListProps) {
  return (
    <dl
      className={clsx(styles.list, className)}
      style={{ ['--dl-term' as string]: `${termWidth}px` }}
    >
      {children}
    </dl>
  )
}

export interface DefinitionItemProps {
  /** 항목 이름 */
  term: ReactNode
  /** 지금 값. 비워 두면 "정하지 않음" */
  value?: ReactNode
  /** 값 아래에 놓는 한 줄 설명 */
  help?: ReactNode
  /** 오른쪽 끝의 동작 (바꾸기 버튼, 스위치) */
  action?: ReactNode
  /** 값을 모노로 쓴다 (숫자, 식별자, 시각) */
  mono?: boolean
  className?: string
}

export function DefinitionItem({
  term,
  value,
  help,
  action,
  mono = false,
  className,
}: DefinitionItemProps) {
  const empty = value === undefined || value === null || value === ''
  return (
    <div className={clsx(styles.item, className)}>
      <dt className={styles.term}>{term}</dt>
      <dd className={styles.body}>
        <span className={clsx(styles.value, mono && styles.mono, empty && styles.empty)}>
          {empty ? '정하지 않음' : value}
        </span>
        {help && <span className={styles.help}>{help}</span>}
      </dd>
      {action && <dd className={styles.action}>{action}</dd>}
    </div>
  )
}
