import clsx from 'clsx'
import type { ReactNode } from 'react'

import styles from './StatusLamp.module.css'

/**
 * 램프 낱말.
 *   lit     켜짐: 빨강, 찬 점. "새로 수집됨", "지금 받는 중"에만 쓴다
 *   ok      정상: 녹색, 찬 점
 *   wait    잠시 대기: 황토, 반쪽 점
 *   pending 하는 중: 먹, 반쪽 점 (문제는 아니고 아직 끝나지 않은 일)
 *   problem 문제: 먹색 면에 ×
 *   off     꺼짐: 테만 있는 점
 *   done    끝냄: 먹, 찬 점
 *   muted   빠짐: 짧은 줄
 */
export type LampKind = 'lit' | 'ok' | 'wait' | 'pending' | 'problem' | 'off' | 'done' | 'muted'

export interface StatusLampProps {
  kind: LampKind
  /** 지름(px). 기본 8 */
  size?: number
  /** 읽어 주는 프로그램에 들려줄 말. 없으면 장식으로 본다 (옆에 글자가 있을 때) */
  label?: string
  /** 지금 받는 중: 램프가 천천히 깜박인다 (lit 에만 쓴다) */
  live?: boolean
  /** 먹색 면 위에 놓일 때 */
  onInk?: boolean
  className?: string
}

function Shape({ kind }: { kind: LampKind }) {
  switch (kind) {
    case 'wait':
    case 'pending':
      // 반쪽 점: 테 + 왼쪽 절반
      return (
        <>
          <circle cx="6" cy="6" r="5.1" fill="none" strokeWidth="1.8" className={styles.stroke} />
          <path d="M6 0.9a5.1 5.1 0 0 0 0 10.2z" className={styles.fill} />
        </>
      )
    case 'off':
      return (
        <circle cx="6" cy="6" r="5.1" fill="none" strokeWidth="1.8" className={styles.stroke} />
      )
    case 'problem':
      // 먹색 면 + 종이색 ×
      return (
        <>
          <rect width="12" height="12" className={styles.fill} />
          <path
            d="M3.4 3.4l5.2 5.2M8.6 3.4l-5.2 5.2"
            fill="none"
            strokeWidth="1.8"
            strokeLinecap="square"
            className={styles.cross}
          />
        </>
      )
    case 'muted':
      return <rect x="0" y="5" width="12" height="2" className={styles.fill} />
    default:
      return <circle cx="6" cy="6" r="6" className={styles.fill} />
  }
}

/** 램프 하나. 모양과 색이 함께 뜻을 전한다. */
export function StatusLamp({
  kind,
  size = 8,
  label,
  live = false,
  onInk = false,
  className,
}: StatusLampProps) {
  // × 상자와 줄은 원보다 조금 커야 같은 크기로 보인다
  const box = kind === 'problem' ? size + 3 : size
  return (
    <svg
      className={clsx(
        styles.lamp,
        styles[kind],
        live && styles.live,
        onInk && styles.onInk,
        className,
      )}
      width={box}
      height={box}
      viewBox="0 0 12 12"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      <Shape kind={kind} />
    </svg>
  )
}

export interface StatusLabelProps {
  kind: LampKind
  children: ReactNode
  /** 램프 지름(px). 기본 8 */
  lampSize?: number
  /** 지금 받는 중 (lit) */
  live?: boolean
  className?: string
}

/**
 * 램프 + 글자. 상태는 항상 모양과 글자를 함께 쓴다.
 * 문제 상태는 빨강이 아니라 반전(먹색 면 + 종이색 글자 + ×)으로 드러낸다.
 */
export function StatusLabel({ kind, children, lampSize = 8, live, className }: StatusLabelProps) {
  if (kind === 'problem') {
    return (
      <span className={clsx(styles.label, styles.labelProblem, className)}>
        <svg
          className={styles.tagCross}
          width="9"
          height="9"
          viewBox="0 0 9 9"
          aria-hidden="true"
          focusable="false"
        >
          <path d="M1.2 1.2l6.6 6.6M7.8 1.2L1.2 7.8" fill="none" strokeWidth="1.6" />
        </svg>
        <span className={styles.text}>{children}</span>
      </span>
    )
  }
  return (
    <span className={clsx(styles.label, styles[`label-${kind}`], className)}>
      <StatusLamp kind={kind} size={lampSize} live={live} />
      <span className={styles.text}>{children}</span>
    </span>
  )
}

/* ── 제품의 상태값 → 램프와 글자 ─────────────────────────────
 * 어느 화면에서든 같은 상태는 같은 램프, 같은 말로 보인다. */

export type LeadStatus = 'new' | 'reviewed' | 'contacted' | 'excluded'
export type AccountStatus =
  'connecting' | 'active' | 'flood_wait' | 'reauth_required' | 'banned' | 'error' | 'offline'
export type GroupStatus = 'queued' | 'joining' | 'requested' | 'joined' | 'failed' | 'left'

export interface StatusMeaning {
  kind: LampKind
  label: string
}

export const LEAD_STATUS: Record<LeadStatus, StatusMeaning> = {
  new: { kind: 'lit', label: '새로 수집됨' },
  reviewed: { kind: 'off', label: '확인함' },
  contacted: { kind: 'done', label: '연락함' },
  excluded: { kind: 'muted', label: '제외' },
}

export const ACCOUNT_STATUS: Record<AccountStatus, StatusMeaning> = {
  connecting: { kind: 'pending', label: '연결하는 중' },
  active: { kind: 'ok', label: '정상' },
  flood_wait: { kind: 'wait', label: '잠시 대기' },
  reauth_required: { kind: 'problem', label: '다시 로그인 필요' },
  banned: { kind: 'problem', label: '계정 정지됨' },
  error: { kind: 'problem', label: '연결 끊김' },
  offline: { kind: 'off', label: '꺼 둠' },
}

export const GROUP_STATUS: Record<GroupStatus, StatusMeaning> = {
  queued: { kind: 'off', label: '가입 대기' },
  joining: { kind: 'pending', label: '가입하는 중' },
  requested: { kind: 'wait', label: '승인 기다리는 중' },
  joined: { kind: 'ok', label: '가입됨' },
  failed: { kind: 'problem', label: '가입 실패' },
  left: { kind: 'muted', label: '나간 그룹' },
}

interface EnumLabelProps<T extends string> {
  status: T
  /** 기본 문구 대신 쓸 말 (예: "14분 뒤 다시 시작") */
  children?: ReactNode
  className?: string
}

/** 수집한 유저의 상태 */
export function LeadStatusLabel({ status, children, className }: EnumLabelProps<LeadStatus>) {
  const meaning = LEAD_STATUS[status]
  return (
    <StatusLabel kind={meaning.kind} className={className}>
      {children ?? meaning.label}
    </StatusLabel>
  )
}

/** 텔레그램 계정의 상태 */
export function AccountStatusLabel({ status, children, className }: EnumLabelProps<AccountStatus>) {
  const meaning = ACCOUNT_STATUS[status]
  return (
    <StatusLabel kind={meaning.kind} className={className}>
      {children ?? meaning.label}
    </StatusLabel>
  )
}

/** 그룹 가입 상태 */
export function GroupStatusLabel({ status, children, className }: EnumLabelProps<GroupStatus>) {
  const meaning = GROUP_STATUS[status]
  return (
    <StatusLabel kind={meaning.kind} className={className}>
      {children ?? meaning.label}
    </StatusLabel>
  )
}
