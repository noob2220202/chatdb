import clsx from 'clsx'

import styles from './SlotDots.module.css'

/* 점 하나가 그룹 한 곳. 열 개씩 묶고, 한 줄에 스무 개까지 놓는다. */
const R = 2.5 // 점 반지름
const PITCH = 7 // 점 사이
const TENS_GAP = 4 // 열 개 묶음 사이에 더 띄우는 폭
const ROW_PITCH = 9 // 줄 사이
const PER_ROW = 20

function dotX(index: number): number {
  const col = index % PER_ROW
  return R + col * PITCH + (col >= 10 ? TENS_GAP : 0)
}

function dotY(index: number): number {
  return R + Math.floor(index / PER_ROW) * ROW_PITCH
}

function rowWidth(capacity: number): number {
  const cols = Math.min(Math.max(capacity, 1), PER_ROW)
  return dotX(cols - 1) + R
}

export type SlotTone = 'normal' | 'wait' | 'problem'

export interface SlotDotsProps {
  /** 들어가 있는 그룹 수 */
  joined: number
  /** 승인을 기다리거나 가입 차례를 기다리는 그룹 수 */
  pending?: number
  /** 계정 하나에 넣을 수 있는 그룹 수. 기본 20 */
  capacity?: number
  /**
   * 계정의 상태.
   *   normal  먹
   *   wait    황토 (잠시 대기)
   *   problem 모두 테만 남는다 (연결이 끊겨 듣지 못하는 자리)
   */
  tone?: SlotTone
  /** 대체 글. 비워 두면 숫자로 만든 문장을 쓴다 */
  label?: string
  className?: string
}

/** 계정의 그룹 자리. 찬 점 = 가입됨, 반쪽 점 = 기다리는 중, 테 = 빈 자리. */
export function SlotDots({
  joined,
  pending = 0,
  capacity = 20,
  tone = 'normal',
  label,
  className,
}: SlotDotsProps) {
  const total = Math.max(1, Math.floor(capacity))
  const on = Math.min(Math.max(0, Math.floor(joined)), total)
  const waiting = Math.min(Math.max(0, Math.floor(pending)), total - on)
  const free = total - on - waiting
  const rows = Math.ceil(total / PER_ROW)
  const width = rowWidth(total)
  const height = (rows - 1) * ROW_PITCH + R * 2

  const text =
    label ??
    [
      `${total}자리 가운데 ${on}곳에 들어가 있어요`,
      waiting > 0 ? `${waiting}곳은 기다리는 중이에요` : null,
      free > 0 ? `빈 자리는 ${free}곳이에요` : '빈 자리가 없어요',
      tone === 'problem' ? '지금은 연결이 끊겨 듣지 못해요' : null,
    ]
      .filter(Boolean)
      .join('. ')

  return (
    <svg
      className={clsx(styles.dots, styles[tone], className)}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={text}
      focusable="false"
    >
      {Array.from({ length: total }, (_, index) => {
        const cx = dotX(index)
        const cy = dotY(index)
        if (index < on) {
          return tone === 'problem' ? (
            <circle key={index} className={styles.dead} cx={cx} cy={cy} r={R - 0.7} />
          ) : (
            <circle key={index} className={styles.on} cx={cx} cy={cy} r={R} />
          )
        }
        if (index < on + waiting) {
          return tone === 'problem' ? (
            <circle key={index} className={styles.dead} cx={cx} cy={cy} r={R - 0.7} />
          ) : (
            <g key={index}>
              <circle className={styles.halfRing} cx={cx} cy={cy} r={R - 0.5} />
              <path className={styles.on} d={`M${cx} ${cy - R}a${R} ${R} 0 0 0 0 ${R * 2}z`} />
            </g>
          )
        }
        return <circle key={index} className={styles.free} cx={cx} cy={cy} r={R - 0.5} />
      })}
    </svg>
  )
}

export interface SlotDotsScaleProps {
  capacity?: number
  className?: string
}

/** 점 줄 위에 놓는 눈금 (1 · 5 · 10 · 15 · 20). 표 머리에 쓴다. */
export function SlotDotsScale({ capacity = 20, className }: SlotDotsScaleProps) {
  const total = Math.max(1, Math.floor(capacity))
  const shown = Math.min(total, PER_ROW)
  const ticks = [1, 5, 10, 15, 20].filter((tick) => tick <= shown)
  return (
    <span
      className={clsx(styles.scale, className)}
      style={{ width: rowWidth(total) }}
      aria-hidden="true"
    >
      {ticks.map((tick) => (
        <span key={tick} className={styles.tick} style={{ left: dotX(tick - 1) }}>
          {tick}
        </span>
      ))}
    </span>
  )
}
