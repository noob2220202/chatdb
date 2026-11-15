import clsx from 'clsx'
import { Fragment, useMemo, type CSSProperties, type ReactNode } from 'react'

import { highlight, splitGraphemes } from '@/lib/highlight'

import styles from './KeywordText.module.css'

export interface KeywordTextProps {
  /** 받아 적은 문장 */
  text: string
  /** 걸린 키워드. 백엔드와 같은 기준으로 찾는다 (lib/highlight) */
  keywords: readonly string[]
  /**
   * quote: 인용문. 명조, 굵게 + 방점
   * table: 표 안. 고딕, 굵게 + 방점 + 옅은 밑칠 (훑어볼 때 눈에 걸리도록)
   */
  variant?: 'quote' | 'table'
  /** 문장을 “ ” 로 감싼다 */
  quoted?: boolean
  /** 이 줄 수를 넘으면 … 로 줄인다. 1이면 한 줄 */
  maxLines?: number
  /** 제외된 행: 방점과 굵기를 죽인다 */
  muted?: boolean
  className?: string
}

const WHITESPACE = /^\s+$/u

interface Glyph {
  char: string
  space: boolean
  /** 걸린 조각의 번호. 걸리지 않았으면 -1 */
  match: number
  /** 걸린 조각의 첫 글자 / 끝 글자인가 */
  first: boolean
  last: boolean
}

function toGlyphs(text: string, keywords: readonly string[]): Glyph[] {
  const glyphs: Glyph[] = []
  highlight(text, keywords).forEach((segment, index) => {
    const chars = splitGraphemes(segment.text)
    chars.forEach((char, at) => {
      glyphs.push({
        char,
        space: WHITESPACE.test(char),
        match: segment.match ? index : -1,
        first: segment.match && at === 0,
        last: segment.match && at === chars.length - 1,
      })
    })
  })
  return glyphs
}

/** 같은 성질(걸림 여부)의 글자를 잇달아 묶는다 */
function chunk<T>(items: readonly T[], same: (a: T, b: T) => boolean): T[][] {
  const groups: T[][] = []
  for (const item of items) {
    const group = groups[groups.length - 1]
    const previous = group?.[group.length - 1]
    if (group && previous !== undefined && same(previous, item)) group.push(item)
    else groups.push([item])
  }
  return groups
}

function edgeClass(glyph: Glyph): string | undefined {
  return clsx(glyph.first && styles.start, glyph.last && styles.end) || undefined
}

function renderWord(word: readonly Glyph[], key: number): ReactNode {
  if (word.every((glyph) => glyph.match === -1)) {
    return <Fragment key={key}>{word.map((glyph) => glyph.char).join('')}</Fragment>
  }
  // 걸린 글자가 든 낱말은 통째로 한 줄에 둔다 (글자마다 따로 놓여도 낱말 중간에서 끊기지 않도록)
  return (
    <span key={key} className={styles.word}>
      {chunk(word, (a, b) => a.match === b.match).map((run, index) =>
        run[0]?.match === -1 ? (
          <Fragment key={index}>{run.map((glyph) => glyph.char).join('')}</Fragment>
        ) : (
          <mark key={index} className={styles.kw}>
            {run.map((glyph, at) => (
              <i key={at} className={edgeClass(glyph)}>
                {glyph.char}
              </i>
            ))}
          </mark>
        ),
      )}
    </span>
  )
}

/**
 * 걸린 키워드를 드러낸 문장.
 * 키워드는 굵게 쓰고 글자마다 빨간 방점(글자 위에 켜진 램프)을 찍는다.
 */
export function KeywordText({
  text,
  keywords,
  variant = 'quote',
  quoted = false,
  maxLines,
  muted = false,
  className,
}: KeywordTextProps) {
  const body = useMemo(() => {
    const glyphs = toGlyphs(text, keywords)
    // 낱말과 공백으로 나눈다
    return chunk(glyphs, (a, b) => a.space === b.space).map((run, index) => {
      if (!run[0]?.space) return renderWord(run, index)
      const spaces = run.map((glyph) => glyph.char).join('')
      // 키워드 안의 띄어쓰기("업체 추천"의 빈칸)는 밑칠이 끊기지 않게 함께 칠한다
      return run.every((glyph) => glyph.match !== -1) ? (
        <mark key={index} className={styles.kw}>
          <i className={styles.gap}>{spaces}</i>
        </mark>
      ) : (
        <Fragment key={index}>{spaces}</Fragment>
      )
    })
  }, [text, keywords])

  const clamp = maxLines && maxLines > 0 ? maxLines : undefined
  return (
    <span
      className={clsx(
        styles.root,
        styles[variant],
        muted && styles.muted,
        clamp === 1 && styles.oneLine,
        clamp !== undefined && clamp > 1 && styles.clamp,
        className,
      )}
      style={
        clamp !== undefined && clamp > 1 ? ({ '--kw-lines': clamp } as CSSProperties) : undefined
      }
    >
      {quoted && '“'}
      {body}
      {quoted && '”'}
    </span>
  )
}
