/**
 * 문장에서 걸린 키워드의 자리를 찾는다.
 *
 * 백엔드(app/matching.py)와 같은 기준이다.
 *   · 전각/반각·호환 문자를 통일하고(NFKC) 대소문자를 없앤 뒤 비교한다.
 *   · 띄어쓰기가 있는 키워드는 붙여 쓴 경우도 잡는다 ("업체 추천" → "업체추천").
 *     띄어쓰기가 없는 키워드는 글자 그대로만 찾는다 (짧은 한 단어 키워드의 오탐 방지).
 *
 * 정규화하면 글자 수가 달라질 수 있어서, 정규화한 글자마다 원문 위치를 함께 들고 다닌다.
 */

export interface KeywordRange {
  /** 원문에서의 시작 위치 (UTF-16 단위, 포함) */
  start: number
  /** 원문에서의 끝 위치 (UTF-16 단위, 제외) */
  end: number
}

export interface HighlightSegment {
  text: string
  /** 키워드에 걸린 조각이면 true */
  match: boolean
}

const WHITESPACE = /\s/u

/** 파이썬 str.casefold() 에 맞춘 대소문자 접기. ß → ss, ς → σ 까지 맞춘다. */
function caseFold(text: string): string {
  let out = ''
  for (const char of text) {
    // 점 없는 ı 는 casefold 에서 그대로 남는다 (대문자를 거치면 i 가 되어 버린다).
    out += char === 'ı' ? char : char.toLowerCase().toUpperCase().toLowerCase()
  }
  return out
}

/** 비교용 정규화: NFKC + 대소문자 접기. 백엔드의 normalize() 와 같다. */
export function normalize(text: string): string {
  return caseFold(text.normalize('NFKC'))
}

interface Piece {
  char: string
  start: number
  end: number
}

type SegmenterLike = { segment(input: string): Iterable<{ segment: string; index: number }> }

let segmenter: SegmenterLike | null | undefined

function getSegmenter(): SegmenterLike | null {
  if (segmenter === undefined) {
    segmenter =
      typeof Intl !== 'undefined' && 'Segmenter' in Intl
        ? new Intl.Segmenter('ko', { granularity: 'grapheme' })
        : null
  }
  return segmenter
}

/**
 * 원문을 글자 덩어리(자소 묶음)로 나누고, 덩어리마다 정규화한다.
 * 풀어 쓴 한글 자모(ㄱ + ㅏ)처럼 합쳐져야 하는 글자가 한 덩어리로 묶이므로
 * 문장 전체를 정규화한 것과 결과가 같다.
 */
function toPieces(text: string): Piece[] {
  const pieces: Piece[] = []
  const push = (cluster: string, start: number) => {
    const end = start + cluster.length
    for (const char of normalize(cluster)) pieces.push({ char, start, end })
  }
  const seg = getSegmenter()
  if (seg) {
    for (const { segment, index } of seg.segment(text)) push(segment, index)
  } else {
    let index = 0
    for (const char of text) {
      push(char, index)
      index += char.length
    }
  }
  return pieces
}

function findAll(haystack: readonly string[], needle: readonly string[]): number[] {
  const found: number[] = []
  if (needle.length === 0 || needle.length > haystack.length) return found
  const last = haystack.length - needle.length
  outer: for (let i = 0; i <= last; i++) {
    for (let j = 0; j < needle.length; j++) {
      if (haystack[i + j] !== needle[j]) continue outer
    }
    found.push(i)
  }
  return found
}

/** 키워드가 걸린 자리를 원문 위치로 돌려준다. 겹치거나 맞닿은 자리는 하나로 합친다. */
export function findKeywordRanges(text: string, keywords: readonly string[]): KeywordRange[] {
  if (!text || keywords.length === 0) return []

  const pieces = toPieces(text)
  const chars = pieces.map((piece) => piece.char)
  const solid = pieces.filter((piece) => !WHITESPACE.test(piece.char))
  const solidChars = solid.map((piece) => piece.char)

  const ranges: KeywordRange[] = []
  for (const keyword of keywords) {
    const normalized = normalize(keyword).trim()
    if (!normalized) continue
    const needle = Array.from(normalized)
    const squashed = needle.filter((char) => !WHITESPACE.test(char))

    if (squashed.length !== needle.length) {
      // 띄어쓰기가 있는 키워드: 공백을 모두 빼고 비교한다. 원문의 띄어쓰기가 달라도 잡힌다.
      for (const at of findAll(solidChars, squashed)) {
        const first = solid[at]
        const last = solid[at + squashed.length - 1]
        if (first && last) ranges.push({ start: first.start, end: last.end })
      }
    } else {
      for (const at of findAll(chars, needle)) {
        const first = pieces[at]
        const last = pieces[at + needle.length - 1]
        if (first && last) ranges.push({ start: first.start, end: last.end })
      }
    }
  }

  ranges.sort((a, b) => a.start - b.start || a.end - b.end)
  const merged: KeywordRange[] = []
  for (const range of ranges) {
    const previous = merged[merged.length - 1]
    if (previous && range.start <= previous.end) {
      previous.end = Math.max(previous.end, range.end)
    } else {
      merged.push({ ...range })
    }
  }
  return merged
}

/** 문장을 "걸린 조각 / 그렇지 않은 조각"으로 나눈다. 조각을 이어 붙이면 원문과 같다. */
export function highlight(text: string, keywords: readonly string[]): HighlightSegment[] {
  if (!text) return []
  const ranges = findKeywordRanges(text, keywords)
  if (ranges.length === 0) return [{ text, match: false }]

  const segments: HighlightSegment[] = []
  let cursor = 0
  for (const { start, end } of ranges) {
    if (start > cursor) segments.push({ text: text.slice(cursor, start), match: false })
    segments.push({ text: text.slice(start, end), match: true })
    cursor = end
  }
  if (cursor < text.length) segments.push({ text: text.slice(cursor), match: false })
  return segments
}

/** 걸린 조각을 글자 단위로 나눈다 (방점을 글자마다 찍기 위해). 자소 묶음을 깨지 않는다. */
export function splitGraphemes(text: string): string[] {
  const seg = getSegmenter()
  if (seg) return Array.from(seg.segment(text), (part) => part.segment)
  return Array.from(text)
}
