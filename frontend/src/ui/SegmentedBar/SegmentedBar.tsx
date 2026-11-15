import clsx from 'clsx'
import { useState } from 'react'

import { formatNumber } from '@/lib/format'
import { RuleSwatch, RuleSwatchFill } from '@/ui/RuleSwatch/RuleSwatch'

import styles from './SegmentedBar.module.css'

export interface SegmentItem {
  id: string | number
  /** 규칙 이름 */
  label: string
  value: number
  /** 규칙의 무늬 순번 (lib/ruleSwatch) */
  swatch: number
}

export interface SegmentedBarProps {
  items: readonly SegmentItem[]
  /** 숫자 뒤의 단위. 기본 "명" */
  unit?: string
  /** 막대의 이름 (읽어 주는 프로그램용). 기본 "규칙별 비중" */
  label?: string
  /** 범례를 함께 보여 준다. 기본 true */
  legend?: boolean
  /** 막대 높이(px). 기본 28 */
  height?: number
  className?: string
}

/** 합이 정확히 100이 되도록 반올림한다 (나머지가 큰 순서로 1씩 더한다). */
export function roundPercents(values: readonly number[]): number[] {
  const total = values.reduce((sum, value) => sum + Math.max(0, value), 0)
  if (total <= 0) return values.map(() => 0)
  const exact = values.map((value) => (Math.max(0, value) / total) * 100)
  const floors = exact.map(Math.floor)
  let left = 100 - floors.reduce((sum, value) => sum + value, 0)
  const order = exact
    .map((value, index) => ({ index, rest: value - Math.floor(value) }))
    .sort((a, b) => b.rest - a.rest || a.index - b.index)
  for (const { index } of order) {
    if (left <= 0) break
    floors[index] = (floors[index] ?? 0) + 1
    left--
  }
  return floors
}

/** 하나의 전체를 규칙별로 나눈 막대. 조각은 규칙의 인쇄 무늬로 채우고, 사이는 종이색 2px 로 띄운다. */
export function SegmentedBar({
  items,
  unit = '명',
  label = '규칙별 비중',
  legend = true,
  height = 28,
  className,
}: SegmentedBarProps) {
  const [active, setActive] = useState<SegmentItem['id'] | null>(null)
  const percents = roundPercents(items.map((item) => item.value))
  const total = items.reduce((sum, item) => sum + Math.max(0, item.value), 0)
  const describe = (item: SegmentItem, index: number) =>
    `${item.label} ${formatNumber(item.value)}${unit}, ${percents[index] ?? 0}%`
  const summary =
    total > 0 ? `${label}. ${items.map(describe).join(' · ')}` : `${label}. 아직 값이 없어요`

  return (
    <div className={clsx(styles.root, className)}>
      <div
        className={clsx(styles.bar, total === 0 && styles.barEmpty)}
        style={{ height }}
        role="img"
        aria-label={summary}
      >
        {items.map((item, index) =>
          item.value > 0 ? (
            <span
              key={item.id}
              className={clsx(
                styles.segment,
                active !== null && active !== item.id && styles.dimmed,
              )}
              style={{ flexGrow: item.value }}
              onPointerEnter={() => setActive(item.id)}
              onPointerLeave={() => setActive(null)}
            >
              <RuleSwatchFill index={item.swatch} title={describe(item, index)} />
            </span>
          ) : null,
        )}
      </div>

      {legend && (
        <ul className={styles.legend}>
          {items.map((item, index) => (
            <li
              key={item.id}
              className={clsx(styles.legendItem, active === item.id && styles.legendActive)}
              onPointerEnter={() => setActive(item.id)}
              onPointerLeave={() => setActive(null)}
            >
              <RuleSwatch index={item.swatch} />
              <span className={styles.name}>{item.label}</span>
              <span className={styles.figure}>
                {formatNumber(item.value)}
                <span className="sr">{unit}</span>
              </span>
              <span className={styles.percent}>{total > 0 ? `${percents[index] ?? 0}%` : '–'}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
