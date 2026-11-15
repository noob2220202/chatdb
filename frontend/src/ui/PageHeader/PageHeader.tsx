import clsx from 'clsx'
import type { ReactNode } from 'react'

import styles from './PageHeader.module.css'

export interface PageHeaderProps {
  /** 화면 제목 (명조) */
  title: ReactNode
  /** 제목 옆에 놓는 수: "전체 4,812명" */
  count?: ReactNode
  /** 제목 아래 한 줄 요약. 램프를 앞에 둘 수 있다 */
  summary?: ReactNode
  /** 오른쪽 자리: 수치나 버튼 */
  aside?: ReactNode
  className?: string
}

/** 화면 머리: 명조 제목, 옆에 붙는 수, 한 줄 요약, 오른쪽 자리. 사진은 넣지 않는다. */
export function PageHeader({ title, count, summary, aside, className }: PageHeaderProps) {
  return (
    <header className={clsx(styles.header, className)}>
      <div className={styles.main}>
        <div className={styles.titleRow}>
          <h1 className={styles.title}>{title}</h1>
          {count && <p className={styles.count}>{count}</p>}
        </div>
        {summary && <p className={styles.summary}>{summary}</p>}
      </div>
      {aside && <div className={styles.aside}>{aside}</div>}
    </header>
  )
}
