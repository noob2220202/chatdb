import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from 'react'

import { APP_VERSION } from '@/app/version'
import { formatFullDate } from '@/lib/format'
import { Logo } from '@/ui/Logo/Logo'

import styles from './AuthLayout.module.css'
import { placeLamp } from './lampAnchor'
import { OPERATOR_PHOTO as PHOTO } from './photo'

type Geometry = {
  /** 램프 중심(화면 틀 기준 px) */
  lampX: number
  lampY: number
  /** 램프 중심(사진 틀 기준 px) */
  plateX: number
  plateY: number
  /** 선이 시작하는 x: 헤드라인 둘째 줄의 끝 */
  from: number
  /** 종이와 사진의 경계 x */
  edge: number
  /** 사진이 그려진 배율(원본 1px 이 화면에서 몇 px 인지) */
  scale: number
  /** object-position 의 세로 값(0~1) */
  objectY: number
  /** 900px 아래: 사진이 위쪽 띠가 된다 */
  narrow: boolean
  /** 헤드라인 아래 글과 입력 칸이 겹칠 만큼 창이 낮다 */
  tight: boolean
}

const NARROW_QUERY = '(max-width: 899px)'
/** 헤드라인 끝과 선 사이의 틈 */
const LINE_GAP = 14

function sameGeometry(a: Geometry | null, b: Geometry): boolean {
  if (!a) return false
  const near = (x: number, y: number) => Math.abs(x - y) < 0.05
  return (
    near(a.lampX, b.lampX) &&
    near(a.lampY, b.lampY) &&
    near(a.plateX, b.plateX) &&
    near(a.plateY, b.plateY) &&
    near(a.from, b.from) &&
    near(a.edge, b.edge) &&
    near(a.scale * 1000, b.scale * 1000) &&
    near(a.objectY * 100, b.objectY * 100) &&
    a.narrow === b.narrow &&
    a.tight === b.tight
  )
}

export type AuthLayoutProps = {
  /** 헤드라인 두 줄. 선은 둘째 줄 끝에서 시작한다 */
  title: readonly [string, string]
  /** 헤드라인 아래 한 문단 */
  lede: ReactNode
  /** 램프와 선이 켜져 있는지 */
  lit: boolean
  /** 입력 칸과 버튼 */
  children: ReactNode
}

/**
 * 로그인·처음 설정 화면의 판짜기.
 * 왼쪽 단에 머리띠·헤드라인·입력 칸, 오른쪽에 사진. 헤드라인 둘째 줄 끝에서 사진 속 램프 하나까지 선이 이어진다.
 * 램프 자리는 사진의 원본 크기와 object-fit: cover 계산으로 구하고, 창 크기가 바뀔 때마다 다시 구한다.
 */
export function AuthLayout({ title, lede, lit, children }: AuthLayoutProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const plateRef = useRef<HTMLElement>(null)
  const titleRef = useRef<HTMLHeadingElement>(null)
  const anchorRef = useRef<HTMLSpanElement>(null)
  const heroRef = useRef<HTMLDivElement>(null)
  const formRef = useRef<HTMLDivElement>(null)
  const [geometry, setGeometry] = useState<Geometry | null>(null)

  useEffect(() => {
    const root = rootRef.current
    const plate = plateRef.current
    const titleEl = titleRef.current
    const anchor = anchorRef.current
    const hero = heroRef.current
    const form = formRef.current
    if (!root || !plate || !titleEl || !anchor || !hero || !form) return

    const measure = () => {
      const rootRect = root.getBoundingClientRect()
      const plateRect = plate.getBoundingClientRect()
      if (plateRect.width === 0 || plateRect.height === 0) return
      const narrow = window.matchMedia(NARROW_QUERY).matches
      const placed = placeLamp(
        { width: plateRect.width, height: plateRect.height },
        PHOTO.size,
        PHOTO.lamp,
        narrow ? 0.5 : 0.42,
      )
      const lampX = plateRect.left - rootRect.left + placed.point.x
      const lampY = plateRect.top - rootRect.top + placed.point.y
      const anchorRect = anchor.getBoundingClientRect()

      // 넓은 화면에서 헤드라인 묶음은 램프 높이에 맞춰 놓인다. 그 아래 끝이 입력 칸과 겹치는지 본다.
      const lineHeight = parseFloat(getComputedStyle(titleEl).lineHeight) || 0
      const heroBottom = lampY - 1.5 * lineHeight + hero.offsetHeight
      const formTop = form.getBoundingClientRect().top - rootRect.top
      const tight = !narrow && heroBottom > formTop - 20

      const next: Geometry = {
        lampX,
        lampY,
        plateX: placed.point.x,
        plateY: placed.point.y,
        from: anchorRect.right - rootRect.left + LINE_GAP,
        edge: plateRect.left - rootRect.left,
        scale: placed.scale,
        objectY: placed.position.y,
        narrow,
        tight,
      }
      setGeometry((current) => (sameGeometry(current, next) ? current : next))
    }

    const observer = new ResizeObserver(measure)
    observer.observe(root)
    observer.observe(plate)
    observer.observe(anchor)
    observer.observe(form)
    window.addEventListener('resize', measure)
    // 글자가 늦게 실리면 헤드라인의 폭이 달라진다.
    void document.fonts?.ready.then(measure)
    measure()

    return () => {
      observer.disconnect()
      window.removeEventListener('resize', measure)
    }
  }, [])

  const ringRadius = geometry ? Math.min(18, Math.max(10, 26 * geometry.scale)) : 13
  const lineEnd = geometry ? geometry.lampX - ringRadius : 0
  const lampRx = geometry ? PHOTO.lampRadius.x * PHOTO.size.width * geometry.scale : 0
  const lampRy = geometry ? PHOTO.lampRadius.y * PHOTO.size.width * geometry.scale : 0

  const rootStyle = { '--lamp-y': geometry ? `${geometry.lampY}px` : undefined } as CSSProperties

  return (
    <div
      ref={rootRef}
      className={styles.auth}
      style={rootStyle}
      data-lit={lit || undefined}
      data-ready={geometry ? true : undefined}
      data-tight={geometry?.tight || undefined}
    >
      <section className={styles.col}>
        <header className={styles.mast}>
          <Logo lit={lit} height={34} />
          <small className={styles.mastNote}>
            <b>{formatFullDate(new Date())}</b>
            혼자 쓰는 수집 콘솔
          </small>
        </header>

        <div ref={heroRef} className={styles.hero}>
          <h1 ref={titleRef} className={styles.title}>
            {title[0]}
            <br />
            <span ref={anchorRef}>{title[1]}</span>
          </h1>
          <p className={styles.lede}>{lede}</p>
        </div>

        <div ref={formRef} className={styles.form}>
          {children}
        </div>

        <footer className={styles.foot}>
          <p className={styles.caption}>
            <b>{PHOTO.caption}</b>
            {PHOTO.credit}
          </p>
          <span className={styles.version}>ChatDB {APP_VERSION}</span>
        </footer>
      </section>

      <figure ref={plateRef} className={styles.plate}>
        <img
          src={PHOTO.src}
          alt={PHOTO.alt}
          width={PHOTO.size.width}
          height={PHOTO.size.height}
          style={{ objectPosition: `0% ${((geometry?.objectY ?? 0) * 100).toFixed(3)}%` }}
          decoding="async"
        />
        {geometry && (
          <>
            {/* 사진에 칠해져 있는 색을 걷어 내 꺼진 램프로 되돌리고, 켜질 때만 빨강을 올린다 */}
            <i
              className={styles.lampOff}
              style={{
                left: geometry.plateX - lampRx - 1.5,
                top: geometry.plateY - lampRy - 1.5,
                width: lampRx * 2 + 3,
                height: lampRy * 2 + 3,
              }}
            />
            <i
              className={styles.lampOn}
              style={{
                left: geometry.plateX - lampRx,
                top: geometry.plateY - lampRy,
                width: lampRx * 2,
                height: lampRy * 2,
              }}
            />
          </>
        )}
      </figure>

      {geometry && (
        <svg className={styles.tether} aria-hidden="true" focusable="false">
          {!geometry.narrow && (
            <>
              {/* 꺼져 있을 때: 종이 위에서는 먹색, 사진 위에서는 종이색 실선 */}
              {geometry.from < geometry.edge && (
                <line
                  className={styles.wirePaper}
                  x1={geometry.from}
                  x2={Math.min(geometry.edge, lineEnd)}
                  y1={geometry.lampY}
                  y2={geometry.lampY}
                />
              )}
              {lineEnd > geometry.edge && (
                <line
                  className={styles.wirePhoto}
                  x1={Math.max(geometry.edge, geometry.from)}
                  x2={lineEnd}
                  y1={geometry.lampY}
                  y2={geometry.lampY}
                />
              )}
            </>
          )}
          <circle
            className={styles.ringOff}
            cx={geometry.lampX}
            cy={geometry.lampY}
            r={ringRadius}
          />
          {/* 켜질 때: 빨간 선이 헤드라인에서 램프까지 그어지고, 닿으면 램프가 들어온다 */}
          {!geometry.narrow && lineEnd > geometry.from && (
            <line
              className={styles.wireLit}
              pathLength={1}
              x1={geometry.from}
              x2={lineEnd}
              y1={geometry.lampY}
              y2={geometry.lampY}
            />
          )}
          <circle
            className={styles.ringLit}
            cx={geometry.lampX}
            cy={geometry.lampY}
            r={ringRadius}
          />
        </svg>
      )}
    </div>
  )
}
