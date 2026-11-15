import clsx from 'clsx'
import { Link } from 'react-router-dom'

import { formatDateTime, formatFullDate, formatNumber, formatTime } from '@/lib/format'
import type { LiveState } from '@/lib/live'
import { ProblemMark } from '@/ui/Field/ProblemMark'

import type { ShellOverview, ShellSummary } from '../overview'
import styles from './AppShell.module.css'

type StatusLineProps = {
  overview: ShellOverview | undefined
  /** 개요를 불러오지 못했고 보여 줄 예전 값도 없을 때 */
  failed: boolean
  summary: ShellSummary
  live: LiveState
  onRetry: () => void
  /** 시험용: 지금 시각 */
  now?: Date
}

/** "오후 2:14에 마지막으로 받아 적었어요" — 오늘이 아니면 날짜를 앞에 붙인다. */
export function lastHitSentence(lastHitAt: string | null, now: Date): string {
  if (!lastHitAt) return '아직 받아 적은 게 없어요'
  const at = new Date(lastHitAt)
  const sameDay = at.toDateString() === now.toDateString()
  return `${sameDay ? formatTime(at) : formatDateTime(at, now)}에 마지막으로 받아 적었어요`
}

/** 머리띠 아래, 모든 화면에 있는 한 줄. 왼쪽은 오늘 날짜, 오른쪽은 지금 받고 있는지. */
export function StatusLine({
  overview,
  failed,
  summary,
  live,
  onRetry,
  now = new Date(),
}: StatusLineProps) {
  let state: { lamp: 'lit' | 'off'; word: string }
  if (summary.receiving) state = { lamp: 'lit', word: '받는 중' }
  else if (live !== 'open') state = { lamp: 'off', word: '다시 잇는 중' }
  else state = { lamp: 'off', word: '쉬는 중' }

  return (
    <div className={styles.dateline}>
      <strong className={styles.date}>{formatFullDate(now)}</strong>
      <div className={styles.statusClip}>
        {failed ? (
          <p className={styles.status} role="status">
            <span className={styles.statusItem}>상태를 불러오지 못했어요</span>
            <span className={styles.statusItem}>
              <button type="button" className={styles.statusLink} onClick={onRetry}>
                다시 불러오기
              </button>
            </span>
          </p>
        ) : overview ? (
          <p className={styles.status} role="status">
            <span className={clsx(styles.statusItem, styles.statusState)}>
              <i
                className={clsx(styles.lamp, state.lamp === 'off' && styles.lampOff)}
                aria-hidden="true"
              />
              <b>{state.word}</b>
            </span>
            <span className={styles.statusItem}>
              계정 {overview.accounts_connected}/{overview.accounts_total}
            </span>
            <span className={styles.statusItem}>
              그룹 {formatNumber(overview.groups_monitoring)}곳
            </span>
            {summary.attention > 0 && (
              <span className={styles.statusItem}>
                <Link className={styles.statusAlert} to="/accounts">
                  <ProblemMark />
                  계정 {summary.attention}개를 확인해 주세요
                </Link>
              </span>
            )}
            {overview.join_requests_pending > 0 && (
              <span className={styles.statusItem}>
                <Link className={styles.statusLink} to="/groups">
                  입장 승인 대기 {formatNumber(overview.join_requests_pending)}건
                </Link>
              </span>
            )}
            <span className={styles.statusItem}>{lastHitSentence(summary.lastHitAt, now)}</span>
          </p>
        ) : null}
      </div>
    </div>
  )
}
