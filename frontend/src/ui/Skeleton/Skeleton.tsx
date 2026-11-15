import clsx from 'clsx'
import type { CSSProperties, ReactNode } from 'react'

import styles from './Skeleton.module.css'

type Size = number | string

function px(value: Size | undefined): string | undefined {
  return typeof value === 'number' ? `${value}px` : value
}

export interface SkeletonProps {
  /** 폭. 숫자는 px. 기본 100% */
  width?: Size
  /** 높이. 숫자는 px. 기본 12 */
  height?: Size
  className?: string
  style?: CSSProperties
}

/** 조용한 면 하나. 반짝이지 않는다. */
export function Skeleton({ width = '100%', height = 12, className, style }: SkeletonProps) {
  return (
    <span
      className={clsx(styles.block, className)}
      style={{ width: px(width), height: px(height), ...style }}
      aria-hidden="true"
    />
  )
}

export interface SkeletonStatusProps {
  /** 읽어 주는 프로그램에 들려줄 말. 기본 "불러오는 중이에요" */
  label?: string
  children: ReactNode
  className?: string
}

/** 자리 표시를 감싸서 "불러오는 중"임을 알린다. */
export function SkeletonStatus({
  label = '불러오는 중이에요',
  children,
  className,
}: SkeletonStatusProps) {
  return (
    <div className={className} role="status" aria-busy="true">
      <span className="sr">{label}</span>
      {children}
    </div>
  )
}

const TEXT_WIDTHS = ['100%', '94%', '62%', '88%', '74%']

export interface SkeletonTextProps {
  /** 줄 수. 기본 3 */
  lines?: number
  className?: string
}

/** 글 몇 줄의 자리 */
export function SkeletonText({ lines = 3, className }: SkeletonTextProps) {
  return (
    <span className={clsx(styles.text, className)} aria-hidden="true">
      {Array.from({ length: lines }, (_, index) => (
        <span
          key={index}
          className={styles.block}
          style={{ width: TEXT_WIDTHS[index % TEXT_WIDTHS.length], height: 10 }}
        />
      ))}
    </span>
  )
}

/* 행마다 칸 폭을 조금씩 달리해서 기계적인 줄무늬처럼 보이지 않게 한다 */
const ROW_PATTERNS: readonly (readonly number[])[] = [
  [112, 0.62, 148, 44],
  [96, 0.48, 132, 44],
  [124, 0.7, 120, 44],
  [88, 0.55, 156, 44],
  [104, 0.4, 140, 44],
]

export interface SkeletonRowsProps {
  /** 행 수. 기본 8 */
  rows?: number
  /** 행 높이: roomy(--row) / compact(--row-compact) */
  density?: 'roomy' | 'compact'
  className?: string
}

/** 표 본문의 자리: 가는 괘선으로 나뉜 행과 조용한 면 */
export function SkeletonRows({ rows = 8, density = 'roomy', className }: SkeletonRowsProps) {
  return (
    <div className={clsx(styles.rows, styles[density], className)} aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => {
        const pattern = ROW_PATTERNS[index % ROW_PATTERNS.length] ?? ROW_PATTERNS[0]
        const [lead = 100, stretch = 0.5, tail = 140, end = 44] = pattern ?? []
        return (
          <div key={index} className={styles.row}>
            <span className={styles.block} style={{ width: 15, height: 15 }} />
            <span className={styles.block} style={{ width: lead, height: 10 }} />
            <span className={styles.grow}>
              <span className={styles.block} style={{ width: `${stretch * 100}%`, height: 10 }} />
            </span>
            <span className={styles.block} style={{ width: tail, height: 10 }} />
            <span className={styles.block} style={{ width: end, height: 10 }} />
          </div>
        )
      })}
    </div>
  )
}

export interface SkeletonChartProps {
  /** 높이(px). 기본 296 */
  height?: number
  className?: string
}

/** 차트의 자리: 가는 괘선 네 줄과 바닥 선 */
export function SkeletonChart({ height = 296, className }: SkeletonChartProps) {
  return (
    <div className={clsx(styles.chart, className)} style={{ height }} aria-hidden="true">
      <span />
      <span />
      <span />
      <span />
    </div>
  )
}
