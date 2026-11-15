import clsx from 'clsx'
import type { ReactNode } from 'react'

import styles from './SectionHead.module.css'

export interface SectionHeadProps {
  /** 꼭지 제목 */
  title: ReactNode
  /**
   * 1: 주요 꼭지. 2px 굵은 괘선 + 명조 18px
   * 2: 딸린 꼭지. 1px 괘선 + 명조 16px
   */
  level?: 1 | 2
  /** 오른쪽에 놓는 짧은 설명 (기간, 단위, 건수) */
  note?: ReactNode
  /** 오른쪽 끝에 놓는 동작 (더 보기 링크, 버튼) */
  action?: ReactNode
  /** 제목 요소. 기본은 level 1 → h2, level 2 → h3 */
  as?: 'h1' | 'h2' | 'h3' | 'h4'
  /** 제목 요소의 id (section 의 aria-labelledby 에 쓴다) */
  id?: string
  className?: string
}

/** 꼭지 머리: 괘선 + 명조 제목 + 오른쪽 설명·동작. */
export function SectionHead({
  title,
  level = 1,
  note,
  action,
  as,
  id,
  className,
}: SectionHeadProps) {
  const Heading = as ?? (level === 1 ? 'h2' : 'h3')
  return (
    <header
      className={clsx(styles.head, level === 1 ? styles.primary : styles.secondary, className)}
    >
      <Heading id={id} className={styles.title}>
        {title}
      </Heading>
      {(note || action) && (
        <div className={styles.side}>
          {note && <span className={styles.note}>{note}</span>}
          {action}
        </div>
      )}
    </header>
  )
}
