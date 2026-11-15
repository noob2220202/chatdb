import { CaretLeft, CaretRight } from '@phosphor-icons/react'
import clsx from 'clsx'

import { formatNumber } from '@/lib/format'

import styles from './Pagination.module.css'

export interface PaginationProps {
  /** 지금 쪽 (1부터) */
  page: number
  /** 한 쪽에 보여 주는 수 */
  pageSize: number
  /** 전체 수 */
  total: number
  onPageChange: (page: number) => void
  /** 주면 한 쪽 크기를 고를 수 있다 */
  onPageSizeChange?: (pageSize: number) => void
  /** 고를 수 있는 한 쪽 크기. 기본 [50, 100] */
  pageSizes?: readonly number[]
  /** 세는 단위. 기본 "명" */
  unit?: string
  /** 정렬 기준을 말로: "마지막 감지가 가까운 순서" */
  sortLabel?: string
  /** 다시 불러오는 중: 누를 수 없게 한다 */
  pending?: boolean
  className?: string
}

/** 쪽 넘기기. 왼쪽에 "4,812명 가운데 1–50번째", 오른쪽에 한 쪽 크기와 이전 / 1 / 97 / 다음. */
export function Pagination({
  page,
  pageSize,
  total,
  onPageChange,
  onPageSizeChange,
  pageSizes = [50, 100],
  unit = '명',
  sortLabel,
  pending = false,
  className,
}: PaginationProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize))
  const current = Math.min(Math.max(1, page), pageCount)
  const first = total === 0 ? 0 : (current - 1) * pageSize + 1
  const last = Math.min(total, current * pageSize)
  const canPrev = current > 1 && !pending
  const canNext = current < pageCount && !pending

  return (
    <footer className={clsx(styles.pager, className)}>
      <p className={styles.range}>
        {total === 0 ? (
          <>보여 줄 항목이 없어요</>
        ) : (
          <>
            {formatNumber(total)}
            {unit} 가운데{' '}
            <b>
              {formatNumber(first)}–{formatNumber(last)}번째
            </b>
          </>
        )}
        {sortLabel && total > 0 && <> · {sortLabel}</>}
      </p>

      <div className={styles.controls}>
        {onPageSizeChange && (
          <div className={styles.sizes} role="group" aria-label="한 쪽에 보여 줄 수">
            <span className={styles.sizesLabel}>한 쪽에</span>
            {pageSizes.map((size) => (
              <button
                key={size}
                type="button"
                className={styles.size}
                aria-pressed={size === pageSize}
                disabled={pending}
                onClick={() => size !== pageSize && onPageSizeChange(size)}
              >
                {size}
                <span className="sr">{unit}씩</span>
              </button>
            ))}
          </div>
        )}

        <nav className={styles.nav} aria-label="쪽 넘기기">
          <button
            type="button"
            className={styles.step}
            disabled={!canPrev}
            onClick={() => onPageChange(current - 1)}
          >
            <CaretLeft size={12} aria-hidden />
            이전
          </button>
          <span className={styles.position} aria-current="page">
            <span className="sr">전체 {formatNumber(pageCount)}쪽 가운데 </span>
            {formatNumber(current)}
            <span className={styles.slash} aria-hidden="true">
              /
            </span>
            <span aria-hidden="true">{formatNumber(pageCount)}</span>
            <span className="sr">쪽</span>
          </span>
          <button
            type="button"
            className={styles.step}
            disabled={!canNext}
            onClick={() => onPageChange(current + 1)}
          >
            다음
            <CaretRight size={12} aria-hidden />
          </button>
        </nav>
      </div>
    </footer>
  )
}
