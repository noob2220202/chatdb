import clsx from 'clsx'
import type { CSSProperties, ReactNode } from 'react'

import { formatNumber } from '@/lib/format'

import styles from './RankList.module.css'

export interface RankItem {
  id: string | number
  /** 이름 (그룹 이름 등) */
  label: ReactNode
  value: number
}

export interface RankListProps {
  items: readonly RankItem[]
  /** 숫자 뒤의 단위. 기본 "명" */
  unit?: string
  /**
   * 줄마다 밑 괘선의 일부를 먹으로 그어 비율을 보여 준다 (가장 큰 값이 줄 전체).
   * 굵은 막대를 줄마다 되풀이하지 않는다.
   */
  proportion?: boolean
  /** 비율의 기준. 기본은 목록에서 가장 큰 값 */
  max?: number
  /** 목록이 비었을 때 보여 줄 말 */
  empty?: ReactNode
  className?: string
}

/** 순위 목록: 번호 · 이름 · 오른쪽 정렬 모노 숫자, 가는 괘선. */
export function RankList({
  items,
  unit = '명',
  proportion = false,
  max,
  empty = '아직 순위를 매길 만큼 모이지 않았어요.',
  className,
}: RankListProps) {
  if (items.length === 0) {
    return <p className={clsx(styles.empty, className)}>{empty}</p>
  }
  const top = max ?? Math.max(...items.map((item) => item.value), 0)
  return (
    <ol className={clsx(styles.list, className)}>
      {items.map((item, index) => {
        const share = top > 0 ? Math.max(0, Math.min(1, item.value / top)) : 0
        return (
          <li
            key={item.id}
            className={clsx(styles.item, proportion && styles.withRule)}
            style={proportion ? ({ '--rank-share': share } as CSSProperties) : undefined}
          >
            <span className={styles.no}>{index + 1}</span>
            <span className={styles.name}>{item.label}</span>
            <span className={styles.figure}>
              {formatNumber(item.value)}
              <span className={styles.unit}>{unit}</span>
            </span>
          </li>
        )
      })}
    </ol>
  )
}
