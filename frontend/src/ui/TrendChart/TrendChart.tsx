import clsx from 'clsx'
import { line as d3Line } from 'd3-shape'
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
} from 'react'

import { formatIsoDay, formatNumber } from '@/lib/format'

import styles from './TrendChart.module.css'

export interface TrendPoint {
  /** "YYYY-MM-DD" */
  date: string
  /** 그날 키워드로 찾은 사람 수 */
  keyword: number
  /** 그날 활발한 유저로 찾은 사람 수 */
  activity: number
}

export interface TrendChartProps {
  /** 날짜 오름차순. 7일, 14일, 30일을 염두에 두고 그린다 */
  data: readonly TrendPoint[]
  /** 오늘 날짜 "YYYY-MM-DD". 그 열에 띠를 깔고 "오늘"이라고 적는다. 기본은 지금 날짜 */
  today?: string
  /** 차트의 이름 (읽어 주는 프로그램, 숨은 표의 제목) */
  title?: string
  /** 높이(px). 기본 296 */
  height?: number
  /** 세는 단위. 기본 "명" */
  unit?: string
  /** 가장 많았던 날을 각주(＊)로 적는다. 데이터에서 계산한 것만 적는다. 기본 true */
  footnote?: boolean
  /** 다시 불러오는 중: 이전 그림을 흐리게 둔다 */
  pending?: boolean
  className?: string
}

const SERIES = [
  { key: 'keyword', name: '키워드 감지' },
  { key: 'activity', name: '활발한 유저' },
] as const

type SeriesKey = (typeof SERIES)[number]['key']

const WEEKDAY_SHORT = new Intl.DateTimeFormat('ko-KR', { weekday: 'short' })
const WEEKDAY_LONG = new Intl.DateTimeFormat('ko-KR', { weekday: 'long' })

function parseIso(iso: string): Date {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(year ?? 1970, (month ?? 1) - 1, day ?? 1)
}

function todayIso(): string {
  const now = new Date()
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** "11.9" */
function axisDate(iso: string): string {
  const [, month, day] = iso.split('-')
  return `${Number(month)}.${Number(day)}`
}

/** 받침에 맞춰 "으로 / 로" 를 붙인다 */
function withRo(word: string): string {
  const code = word.charCodeAt(word.length - 1)
  if (code < 0xac00 || code > 0xd7a3) return `${word}로`
  const final = (code - 0xac00) % 28
  return final === 0 || final === 8 ? `${word}로` : `${word}으로`
}

const STEPS = [1, 2, 5, 10, 20, 25, 50]

/** 세로축: 0에서 시작해 깔끔한 수로 끝나는 눈금 3–5칸 */
export function niceScale(max: number): { top: number; ticks: number[] } {
  if (!(max > 0)) return { top: 4, ticks: [1, 2, 3, 4] }
  // 꼭대기가 가장 낮은 눈금을 고른다. 같으면 네 칸, 세 칸, 다섯 칸 순서로 고른다
  const preference = [4, 3, 5]
  let best: { top: number; step: number; count: number } | null = null
  for (let power = 0; power < 9; power++) {
    for (const base of STEPS) {
      const step = base * 10 ** power
      for (const count of preference) {
        const top = step * count
        if (top < max) continue
        const better =
          !best ||
          top < best.top ||
          (top === best.top && preference.indexOf(count) < preference.indexOf(best.count))
        if (better) best = { top, step, count }
      }
    }
    if (best) break
  }
  const chosen = best ?? { top: max, step: max / 4, count: 4 }
  return {
    top: chosen.top,
    ticks: Array.from({ length: chosen.count }, (_, index) => chosen.step * (index + 1)),
  }
}

export interface TrendPeak {
  date: string
  value: number
  index: number
}

/** 키워드 감지가 가장 많았던 날. 값이 없거나 같은 값이 둘 이상이면 null */
export function findPeak(data: readonly TrendPoint[]): TrendPeak | null {
  let peak: TrendPeak | null = null
  let tie = false
  data.forEach((point, index) => {
    if (!peak || point.keyword > peak.value) {
      peak = { date: point.date, value: point.keyword, index }
      tie = false
    } else if (point.keyword === peak.value) {
      tie = true
    }
  })
  const found = peak as TrendPeak | null
  return found && found.value > 0 && !tie ? found : null
}

const TOP = 36
const BOTTOM = 50
const LEFT = 34

/**
 * 하루하루 수집한 사람 수의 추이.
 * 키워드 감지는 빨간 선과 찬 점, 활발한 유저는 먹색 선과 빈 점으로 그린다
 * (색만으로 가르지 않는다: 점의 채움과 선 끝의 이름표가 함께 알려 준다).
 */
export function TrendChart({
  data,
  today,
  title = '수집 추이',
  height = 296,
  unit = '명',
  footnote = true,
  pending = false,
  className,
}: TrendChartProps) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(652)
  const [hover, setHover] = useState<number | null>(null)
  const [defaultToday] = useState(todayIso)
  const liveId = useId()
  const todayDate = today ?? defaultToday

  useEffect(() => {
    const wrap = wrapRef.current
    if (!wrap || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(([entry]) => {
      if (entry && entry.contentRect.width > 0) setWidth(Math.round(entry.contentRect.width))
    })
    observer.observe(wrap)
    return () => observer.disconnect()
  }, [])

  const count = data.length
  const maxValue = Math.max(0, ...data.map((point) => Math.max(point.keyword, point.activity)))
  const isEmpty = count === 0
  const isFlat = !isEmpty && maxValue === 0

  const layout = useMemo(() => {
    const compact = width < 440
    const right = compact ? 46 : 138
    const y0 = height - BOTTOM
    const span = Math.max(40, width - LEFT - right)
    const step = count > 1 ? span / (count - 1) : 0
    const x = (index: number) => (count > 1 ? LEFT + step * index : LEFT + span / 2)
    const scale = niceScale(maxValue)
    const y = (value: number) => y0 - (Math.max(0, value) / scale.top) * (y0 - TOP)
    const band = count > 1 ? Math.min(60, Math.max(12, step)) : 60
    // 날짜 이름표: 촘촘하면 솎아 낸다. 맨 끝(가장 최근)은 늘 남긴다
    const stride = step > 0 ? Math.max(1, Math.ceil(46 / step)) : 1
    return { compact, right, y0, step, x, y, scale, band, stride }
  }, [width, height, count, maxValue])

  const { x, y, y0, scale, band, stride, compact, step } = layout
  const todayIndex = data.findIndex((point) => point.date === todayDate)
  const lastIndex = count - 1
  const peak = useMemo(() => findPeak(data), [data])
  const dense = count > 14

  const paths = useMemo(() => {
    const build = (key: SeriesKey) =>
      d3Line<TrendPoint>()
        .x((_, index) => x(index))
        .y((point) => y(point[key]))(data as TrendPoint[]) ?? ''
    return { keyword: build('keyword'), activity: build('activity') }
  }, [data, x, y])

  /* 선 끝 이름표: 두 줄이 붙으면 살짝 벌린다 */
  const last = data[lastIndex]
  let endKeyword = last ? y(last.keyword) : 0
  let endActivity = last ? y(last.activity) : 0
  if (last && Math.abs(endKeyword - endActivity) < 18) {
    const middle = (endKeyword + endActivity) / 2
    const keywordOnTop = last.keyword >= last.activity
    endKeyword = middle + (keywordOnTop ? -9 : 9)
    endActivity = middle + (keywordOnTop ? 9 : -9)
  }
  const endX = last ? x(lastIndex) + (todayIndex === lastIndex ? band / 2 + 12 : 14) : 0

  const showMarker = (index: number) =>
    !dense || index === lastIndex || index === peak?.index || index === hover

  /* ── 가리키기 ── */
  const nearest = (clientX: number) => {
    const rect = wrapRef.current?.getBoundingClientRect()
    if (!rect || count === 0) return null
    const px = clientX - rect.left
    if (count === 1) return 0
    return Math.max(0, Math.min(count - 1, Math.round((px - LEFT) / step)))
  }
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => setHover(nearest(event.clientX))
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (count === 0) return
    const from = hover ?? lastIndex
    let next: number | null = null
    if (event.key === 'ArrowLeft') next = Math.max(0, from - 1)
    else if (event.key === 'ArrowRight') next = Math.min(lastIndex, from + 1)
    else if (event.key === 'Home') next = 0
    else if (event.key === 'End') next = lastIndex
    else if (event.key === 'Escape') {
      setHover(null)
      return
    }
    if (next !== null) {
      event.preventDefault()
      setHover(next)
    }
  }

  const hovered = hover !== null ? data[hover] : undefined
  const hoverX = hover !== null ? x(hover) : 0

  const peakPoint = peak ? data[peak.index] : undefined
  const peakNote =
    footnote && peak && peakPoint && count > 1
      ? `${WEEKDAY_LONG.format(parseIso(peak.date))}(${parseIso(peak.date).getMonth() + 1}월 ${parseIso(peak.date).getDate()}일)에 키워드 감지가 ${withRo(`${formatNumber(peak.value)}${unit}`)} 가장 많았어요.`
      : null

  return (
    <div className={clsx(styles.root, pending && styles.pending, className)}>
      {!isEmpty && (
        <p
          className={clsx(styles.legend, hover !== null && !isFlat && styles.legendHidden)}
          aria-hidden="true"
        >
          <span>
            <svg viewBox="0 0 26 10" width="26" height="10">
              <line x1="0" y1="5" x2="26" y2="5" className={styles.lineKeyword} />
              <circle cx="13" cy="5" r="4" className={styles.legendKeyword} />
            </svg>
            키워드 감지
          </span>
          <span>
            <svg viewBox="0 0 26 10" width="26" height="10">
              <line x1="0" y1="5" x2="26" y2="5" className={styles.lineActivity} />
              <circle cx="13" cy="5" r="3.2" className={styles.markerActivity} />
            </svg>
            활발한 유저
          </span>
        </p>
      )}

      <div
        ref={wrapRef}
        className={styles.plot}
        style={{ height }}
        tabIndex={isEmpty ? undefined : 0}
        role={isEmpty ? undefined : 'group'}
        aria-label={isEmpty ? undefined : `${title}. 왼쪽·오른쪽 화살표로 날짜를 옮겨 볼 수 있어요`}
        aria-describedby={isEmpty ? undefined : liveId}
        onPointerMove={isEmpty ? undefined : onPointerMove}
        onPointerDown={isEmpty ? undefined : onPointerMove}
        onPointerLeave={() => setHover(null)}
        onFocus={(event) => {
          if (event.target === event.currentTarget && hover === null && count > 0)
            setHover(lastIndex)
        }}
        onBlur={() => setHover(null)}
        onKeyDown={onKeyDown}
      >
        <svg
          className={styles.svg}
          width={width}
          height={height}
          aria-hidden="true"
          focusable="false"
        >
          {/* 오늘 열의 띠 */}
          {todayIndex >= 0 && (
            <rect
              className={styles.today}
              x={x(todayIndex) - band / 2}
              y={TOP - 14}
              width={band}
              height={y0 - TOP + 14}
            />
          )}

          {/* 가로 괘선과 눈금 */}
          {scale.ticks.map((tick, index) => {
            const ty = Math.round(y(tick)) + 0.5
            const isTop = index === scale.ticks.length - 1
            return (
              <g key={tick}>
                <line className={styles.grid} x1={0} x2={width} y1={ty} y2={ty} />
                {!isEmpty && !isFlat && (
                  <text className={styles.tick} x={0} y={ty - 5.5}>
                    {formatNumber(tick)}
                    {isTop ? unit : ''}
                  </text>
                )}
              </g>
            )
          })}
          <line
            className={isEmpty ? styles.baseEmpty : styles.base}
            x1={0}
            x2={width}
            y1={y0 + 0.5}
            y2={y0 + 0.5}
          />

          {!isEmpty && !isFlat && (
            <>
              <path className={styles.lineActivity} d={paths.activity} />
              <path className={styles.lineKeyword} d={paths.keyword} />
              {data.map((point, index) =>
                showMarker(index) ? (
                  <circle
                    key={`a${point.date}`}
                    className={styles.markerActivity}
                    cx={x(index)}
                    cy={y(point.activity)}
                    r={index === hover ? 5 : 4}
                  />
                ) : null,
              )}
              {data.map((point, index) =>
                showMarker(index) ? (
                  <circle
                    key={`k${point.date}`}
                    className={styles.markerKeyword}
                    cx={x(index)}
                    cy={y(point.keyword)}
                    r={index === hover ? 6 : 5}
                  />
                ) : null,
              )}

              {/* 가장 많았던 날 */}
              {peak && peakPoint && peak.index !== lastIndex && hover === null && (
                <text
                  className={styles.value}
                  x={x(peak.index)}
                  y={y(peak.value) - 13}
                  textAnchor="middle"
                >
                  {formatNumber(peak.value)}
                </text>
              )}

              {/* 선 끝 이름표 */}
              {last && (
                <>
                  <text x={endX} y={endKeyword + 5}>
                    <tspan className={styles.value}>{formatNumber(last.keyword)}</tspan>
                    {!compact && (
                      <tspan className={styles.valueName} dx="6">
                        키워드 감지
                      </tspan>
                    )}
                  </text>
                  <text x={endX} y={endActivity + 5}>
                    <tspan className={styles.value}>{formatNumber(last.activity)}</tspan>
                    {!compact && (
                      <tspan className={styles.valueName} dx="6">
                        활발한 유저
                      </tspan>
                    )}
                  </text>
                </>
              )}
            </>
          )}

          {/* 날짜 */}
          {data.map((point, index) => {
            if ((lastIndex - index) % stride !== 0) return null
            const isToday = index === todayIndex
            const weekday = WEEKDAY_SHORT.format(parseIso(point.date))
            return (
              <g key={point.date}>
                {stride > 1 && (
                  <line className={styles.stub} x1={x(index)} x2={x(index)} y1={y0} y2={y0 + 4} />
                )}
                <text
                  className={clsx(styles.day, isToday && styles.dayToday)}
                  x={x(index)}
                  y={y0 + 20}
                  textAnchor="middle"
                >
                  {isToday && step >= 62 ? `${weekday} · 오늘` : weekday}
                </text>
                <text className={styles.date} x={x(index)} y={y0 + 36} textAnchor="middle">
                  {axisDate(point.date)}
                </text>
              </g>
            )
          })}

          {/* 가리킨 날의 세로선 */}
          {hovered && !isFlat && (
            <line className={styles.cross} x1={hoverX} x2={hoverX} y1={0} y2={y0} />
          )}
        </svg>

        {isEmpty && (
          <div className={styles.message}>
            <p className={styles.messageTitle}>아직 그릴 추이가 없어요</p>
            <p>받아 적기 시작하면 하루에 점이 하나씩 찍혀요.</p>
          </div>
        )}
        {isFlat && (
          <div className={styles.message}>
            <p className={styles.messageTitle}>이 기간에는 받아 적은 사람이 없었어요</p>
            <p>찾는 말이 나오면 그날부터 선이 그려져요.</p>
          </div>
        )}

        {/* 가리킨 날의 쪽지: 범례 자리에 놓여서 그림을 가리지 않는다 */}
        {hovered && !isFlat && (
          <div
            ref={(element) => {
              // 쪽지의 폭을 재서, 세로선을 따라가되 차트 밖으로 나가지 않게 한다
              element?.style.setProperty('--tip-w', `${element.offsetWidth}px`)
            }}
            className={styles.tip}
            style={{ '--tip-x': `${hoverX}px` } as CSSProperties}
            aria-hidden="true"
          >
            <span className={styles.tipDate}>
              {formatIsoDay(hovered.date)}
              {hover === todayIndex ? ' · 오늘' : ''}
            </span>
            {SERIES.map((series) => (
              <span key={series.key} className={styles.tipRow}>
                <i className={clsx(styles.tipKey, styles[`tipKey-${series.key}`])} />
                <b>
                  {formatNumber(hovered[series.key])}
                  {unit}
                </b>
                {!compact && <span>{series.name}</span>}
              </span>
            ))}
          </div>
        )}
      </div>

      {peakNote && !isFlat && (
        <p className={styles.footnote}>
          <span className={styles.asterisk} aria-hidden="true">
            ＊
          </span>{' '}
          {peakNote}
        </p>
      )}

      {/* 키보드로 옮길 때 지금 가리킨 날을 읽어 준다 */}
      <p id={liveId} className="sr" aria-live="polite">
        {hovered
          ? `${formatIsoDay(hovered.date)}. 키워드 감지 ${formatNumber(hovered.keyword)}${unit}, 활발한 유저 ${formatNumber(hovered.activity)}${unit}.`
          : ''}
      </p>

      {/* 같은 내용을 표로 */}
      {!isEmpty && (
        <table className="sr">
          <caption>{title}</caption>
          <thead>
            <tr>
              <th scope="col">날짜</th>
              <th scope="col">키워드 감지</th>
              <th scope="col">활발한 유저</th>
            </tr>
          </thead>
          <tbody>
            {data.map((point) => (
              <tr key={point.date}>
                <th scope="row">{formatIsoDay(point.date)}</th>
                <td>
                  {formatNumber(point.keyword)}
                  {unit}
                </td>
                <td>
                  {formatNumber(point.activity)}
                  {unit}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
