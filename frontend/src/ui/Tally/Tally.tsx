import clsx from 'clsx'

import { formatNumber } from '@/lib/format'

import styles from './Tally.module.css'

/* 바를 정(正) 다섯 획. 한 획이 한 번이다. 쓰는 순서대로 그린다. */
const STROKES = [
  'M1.5 1.75H11.5', // 一 위 가로
  'M6.5 1.75V11.25', // 丨 가운데 세로
  'M6.5 6.25H10.5', // 가운데에서 오른쪽으로
  'M3.25 5.75V11.25', // 왼쪽 세로
  'M0.75 11.25H12.25', // 아래 가로
]

/** 이 횟수를 넘으면 획을 긋지 않고 숫자만 적는다 */
export const TALLY_LIMIT = 15

function Mark({ strokes }: { strokes: number }) {
  return (
    <svg className={styles.mark} width="13" height="13" viewBox="0 0 13 13" focusable="false">
      {/* 아직 긋지 않은 획은 옅게 남겨서 正 자의 자리를 잡아 둔다 */}
      {strokes < 5 && <path className={styles.ghost} d={STROKES.slice(strokes).join('')} />}
      <path d={STROKES.slice(0, strokes).join('')} />
    </svg>
  )
}

export interface TallyProps {
  /** 감지 횟수 */
  count: number
  /** 숫자 뒤에 붙는 단위. 기본 "회" */
  unit?: string
  /** 획을 긋지 않고 숫자만 보여 준다 */
  numeralOnly?: boolean
  /** 제외된 행처럼 흐리게 */
  muted?: boolean
  className?: string
}

/**
 * 감지 횟수를 正 자로 센다 (다섯 번에 한 글자). 옆에 숫자를 함께 적는다.
 * 15회를 넘으면 숫자만 적는다.
 */
export function Tally({
  count,
  unit = '회',
  numeralOnly = false,
  muted = false,
  className,
}: TallyProps) {
  const safe = Math.max(0, Math.floor(count))
  const showMarks = !numeralOnly && safe > 0 && safe <= TALLY_LIMIT
  const full = Math.floor(safe / 5)
  const rest = safe % 5

  return (
    <span className={clsx(styles.tally, muted && styles.muted, className)}>
      {showMarks && (
        <span className={styles.marks} aria-hidden="true">
          {Array.from({ length: full }, (_, index) => (
            <Mark key={index} strokes={5} />
          ))}
          {rest > 0 && <Mark strokes={rest} />}
        </span>
      )}
      <span className={styles.figure}>
        {formatNumber(safe)}
        <span className={styles.unit}>{unit}</span>
      </span>
    </span>
  )
}
