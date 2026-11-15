import clsx from 'clsx'
import type { CSSProperties, ReactNode } from 'react'

import { formatNumber } from '@/lib/format'

import styles from './Stat.module.css'

function display(value: number | string | null | undefined): string | null {
  if (value === null || value === undefined) return null
  return typeof value === 'number' ? formatNumber(value) : value
}

/* ── 장부: 수치 몇 줄을 괘선으로 묶는다 ───────────────────── */

export interface LedgerProps {
  children: ReactNode
  /** 장부의 이름 (읽어 주는 프로그램용) */
  label?: string
  className?: string
}

/** 수치 줄(StatRow)을 담는 장부. 위는 1px, 아래는 2px 괘선. */
export function Ledger({ children, label, className }: LedgerProps) {
  return (
    <ul className={clsx(styles.ledger, className)} aria-label={label}>
      {children}
    </ul>
  )
}

export interface StatRowProps {
  /** 무엇의 수인가 */
  label: ReactNode
  /** 한 문장 설명. 램프나 링크를 넣을 수 있다 */
  note?: ReactNode
  /** 수치. 숫자는 천 단위 쉼표를 붙여 보여 준다. null 이면 아직 모르는 값(–) */
  value: number | string | null
  /** 단위: 명, 건, 곳 */
  unit?: string
  /** 분모: 9 / 10 의 10 */
  of?: number | string
  className?: string
}

/** 장부 한 줄: 왼쪽에 이름과 설명, 오른쪽에 큰 명조 수치. */
export function StatRow({ label, note, value, unit, of, className }: StatRowProps) {
  const shown = display(value)
  const total = display(of)
  return (
    <li className={clsx(styles.row, !note && styles.rowPlain, className)}>
      <span className={styles.rowLabel}>{label}</span>
      <span className={styles.rowValue}>
        {shown === null ? (
          <span className={styles.unknown} aria-label="아직 알 수 없어요">
            –
          </span>
        ) : (
          <>
            {shown}
            {total !== null && (
              <span className={styles.of}>
                <span className={styles.slash} aria-hidden="true">
                  /
                </span>
                <span className="sr">가운데 전체 </span>
                {total}
              </span>
            )}
            {unit && <span className={styles.rowUnit}>{unit}</span>}
          </>
        )}
      </span>
      {note && <span className={styles.rowNote}>{note}</span>}
    </li>
  )
}

/* ── 머리 수치: 화면에 하나뿐인 큰 숫자 ───────────────────── */

export interface StatHeroProps {
  /** 숫자 위의 작은 제목: "오늘 수집" */
  label: ReactNode
  /** 제목부터 굵은 괘선까지의 높이(px). 옆 칸(장부, 사진)과 밑선을 맞출 때 쓴다 */
  height?: number
  /** 수치. null 이면 아직 모르는 값(–) */
  value: number | string | null
  /** 단위: 명 */
  unit?: string
  /** 굵은 괘선 아래에 놓는 한두 문장 */
  deck?: ReactNode
  className?: string
}

/** 아주 큰 명조 숫자가 2px 괘선 위에 앉는다. 화면에 하나만 쓴다. */
export function StatHero({ label, value, unit, deck, height, className }: StatHeroProps) {
  const shown = display(value)
  // 글자 수에 맞춰 크기를 줄인다 (쉼표는 반 글자로 센다)
  const chars =
    shown === null ? 1 : Array.from(shown).reduce((n, c) => n + (c === ',' ? 0.45 : 1), 0)
  return (
    <div className={clsx(styles.hero, className)}>
      <div
        className={styles.heroFigure}
        style={height !== undefined ? { minHeight: height } : undefined}
      >
        <p className={styles.heroLabel}>{label}</p>
        <p className={styles.heroNumber} style={{ '--stat-chars': chars } as CSSProperties}>
          {shown === null ? (
            <b className={styles.heroUnknown} role="img" aria-label="아직 알 수 없어요" />
          ) : (
            <b>{shown}</b>
          )}
          {unit && shown !== null && <span>{unit}</span>}
        </p>
      </div>
      {deck && <p className={styles.heroDeck}>{deck}</p>}
    </div>
  )
}
