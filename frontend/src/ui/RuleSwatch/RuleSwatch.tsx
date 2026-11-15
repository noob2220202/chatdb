import clsx from 'clsx'
import { useId, type CSSProperties, type ReactNode } from 'react'

import { describeSwatch, swatchSpec, type SwatchPattern } from '@/lib/ruleSwatch'

import styles from './RuleSwatch.module.css'

/* 12×12 눈금 위에 손으로 맞춘 무늬. 테두리 1px 안쪽 10px 에 그린다.
 * 가로줄·세로줄·점은 픽셀 눈금에 딱 맞고(1배율에서도 번지지 않는다),
 * 빗금은 테두리 안쪽까지만 닿도록 끝점을 직접 계산했다. */

/** 오른쪽 위로 올라가는 빗금: x + y = c */
function rise(c: number): string {
  return c <= 12 ? `M0.5 ${c - 0.5}L${c - 0.5} 0.5` : `M${c - 11.5} 11.5L11.5 ${c - 11.5}`
}

/** 왼쪽 위에서 내려오는 빗금: x − y = d */
function fall(d: number): string {
  return d >= 0 ? `M${d + 0.5} 0.5L11.5 ${11.5 - d}` : `M0.5 ${0.5 - d}L${11.5 + d} 11.5`
}

const HATCH = [2, 7, 12, 17, 22].map(rise).join('')
const HATCH_WIDE = [-7.5, 0, 7.5].map(fall).join('')
const CROSS = [6, 12, 18].map(rise).join('') + [-6, 0, 6].map(fall).join('')

function Glyph({ pattern }: { pattern: SwatchPattern }) {
  if (pattern === 'solid') return <rect width="12" height="12" className={styles.ink} />
  return (
    <>
      {pattern === 'hatch' && <path d={HATCH} className={styles.hatch} />}
      {pattern === 'hatchWide' && <path d={HATCH_WIDE} className={styles.hatch} />}
      {pattern === 'cross' && <path d={CROSS} className={styles.hatchFine} />}
      {pattern === 'lines' && (
        <path d="M1 3h10v2H1zM1 7h10v2H1z" className={styles.ink} shapeRendering="crispEdges" />
      )}
      {pattern === 'columns' && (
        <path d="M3 1h2v10H3zM7 1h2v10H7z" className={styles.ink} shapeRendering="crispEdges" />
      )}
      {pattern === 'dots' && (
        <g className={styles.ink}>
          <circle cx="4" cy="4" r="1.15" />
          <circle cx="8" cy="4" r="1.15" />
          <circle cx="4" cy="8" r="1.15" />
          <circle cx="8" cy="8" r="1.15" />
        </g>
      )}
      <rect
        x="0.5"
        y="0.5"
        width="11"
        height="11"
        className={styles.frame}
        shapeRendering="crispEdges"
      />
    </>
  )
}

export interface RuleSwatchProps {
  /** 규칙의 순번 (lib/ruleSwatch 의 buildSwatchIndex 로 구한다). 0–7 은 무늬, 8부터는 번호 상자 */
  index: number
  /** 한 변(px). 기본 12 */
  size?: number
  /** 제외된 행처럼 흐리게 보일 때 */
  muted?: boolean
  /** 읽어 주는 프로그램에 들려줄 말. 옆에 규칙 이름이 있으면 비워 둔다 */
  label?: string
  className?: string
}

/** 규칙의 인쇄 무늬. 범례·실시간 감지·표에서 같은 규칙은 같은 무늬다. */
export function RuleSwatch({ index, size = 12, muted = false, label, className }: RuleSwatchProps) {
  const spec = swatchSpec(index)
  const a11y = label
    ? ({ role: 'img', 'aria-label': label } as const)
    : ({ 'aria-hidden': true } as const)

  if (spec.kind !== 'pattern') {
    const scale = size / 12
    return (
      <span
        className={clsx(
          styles.numbered,
          spec.kind === 'unknown' && styles.unknown,
          muted && styles.muted,
          className,
        )}
        style={{ height: size, minWidth: size, fontSize: 9 * scale, lineHeight: `${size - 2}px` }}
        {...a11y}
      >
        {spec.kind === 'number' ? spec.number : ''}
      </span>
    )
  }

  return (
    <svg
      className={clsx(styles.swatch, muted && styles.muted, className)}
      width={size}
      height={size}
      viewBox="0 0 12 12"
      focusable="false"
      {...a11y}
    >
      <Glyph pattern={spec.pattern} />
    </svg>
  )
}

/* ── 면 채우기: 막대 조각처럼 크기가 정해지지 않은 상자를 같은 무늬로 채운다 ── */

function FillPattern({ pattern, id }: { pattern: SwatchPattern; id: string }) {
  switch (pattern) {
    case 'hatch':
      return (
        <pattern id={id} width="5" height="5" patternUnits="userSpaceOnUse">
          <path d="M-1 1l2-2M0 5l5-5M4 6l2-2" className={styles.hatch} />
        </pattern>
      )
    case 'hatchWide':
      return (
        <pattern id={id} width="7.5" height="7.5" patternUnits="userSpaceOnUse">
          <path d="M0 0l7.5 7.5M-1 6.5l2 2M6.5-1l2 2" className={styles.hatch} />
        </pattern>
      )
    case 'cross':
      return (
        <pattern id={id} width="6" height="6" patternUnits="userSpaceOnUse">
          <path d="M0 0l6 6M0 6l6-6" className={styles.hatchFine} />
        </pattern>
      )
    case 'lines':
      return (
        <pattern id={id} width="4" height="4" patternUnits="userSpaceOnUse">
          <rect y="2" width="4" height="2" className={styles.ink} shapeRendering="crispEdges" />
        </pattern>
      )
    case 'columns':
      return (
        <pattern id={id} width="4" height="4" patternUnits="userSpaceOnUse">
          <rect x="2" width="2" height="4" className={styles.ink} shapeRendering="crispEdges" />
        </pattern>
      )
    case 'dots':
      return (
        <pattern id={id} width="4" height="4" patternUnits="userSpaceOnUse">
          <circle cx="3" cy="3" r="1.15" className={styles.ink} />
        </pattern>
      )
    default:
      return null
  }
}

export interface RuleSwatchFillProps {
  index: number
  muted?: boolean
  className?: string
  style?: CSSProperties
  title?: string
}

/** 상자를 규칙의 무늬로 가득 채운다. 크기는 className / style 로 정한다 (기본은 부모를 꽉 채움). */
export function RuleSwatchFill({
  index,
  muted = false,
  className,
  style,
  title,
}: RuleSwatchFillProps) {
  const spec = swatchSpec(index)
  const patternId = `sw${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`

  let body: ReactNode = null
  if (spec.kind === 'pattern' && spec.pattern !== 'solid' && spec.pattern !== 'blank') {
    body = (
      <svg
        className={styles.fillSvg}
        width="100%"
        height="100%"
        aria-hidden="true"
        focusable="false"
      >
        <defs>
          <FillPattern pattern={spec.pattern} id={patternId} />
        </defs>
        <rect width="100%" height="100%" fill={`url(#${patternId})`} />
      </svg>
    )
  } else if (spec.kind === 'number') {
    body = <span className={styles.fillNumber}>{spec.number}</span>
  }

  return (
    <span
      className={clsx(
        styles.fill,
        spec.kind === 'pattern' && spec.pattern === 'solid' && styles.fillSolid,
        spec.kind === 'unknown' && styles.unknown,
        muted && styles.muted,
        className,
      )}
      style={style}
      title={title}
      aria-hidden="true"
    >
      {body}
    </span>
  )
}

export interface RuleNameProps {
  /** 규칙의 순번 */
  index: number
  children: ReactNode
  muted?: boolean
  className?: string
}

/** 무늬 + 규칙 이름. 실시간 감지와 표에서 쓴다. */
export function RuleName({ index, children, muted = false, className }: RuleNameProps) {
  return (
    <span className={clsx(styles.name, muted && styles.nameMuted, className)}>
      <RuleSwatch index={index} muted={muted} />
      <span className={styles.nameText}>{children}</span>
    </span>
  )
}

/** 무늬를 말로 설명한다 (범례의 대체 글 등에 쓴다) */
export function ruleSwatchLabel(index: number): string {
  return describeSwatch(swatchSpec(index))
}
