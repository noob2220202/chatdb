import { describe, expect, it } from 'vitest'

import {
  SWATCH_PATTERNS,
  buildSwatchIndex,
  describeSwatch,
  swatchFor,
  swatchIndexOf,
  swatchSpec,
} from './ruleSwatch'

describe('buildSwatchIndex', () => {
  it('id 오름차순으로 0부터 순번을 매긴다', () => {
    const index = buildSwatchIndex([3, 12, 7])
    expect(index.get(3)).toBe(0)
    expect(index.get(7)).toBe(1)
    expect(index.get(12)).toBe(2)
  })

  it('목록의 순서가 달라도 결과가 같다', () => {
    const a = buildSwatchIndex([1, 2, 5, 9])
    const b = buildSwatchIndex([9, 5, 1, 2])
    expect(Array.from(a.entries()).sort()).toEqual(Array.from(b.entries()).sort())
  })

  it('같은 id 가 여러 번 들어와도 한 번만 센다', () => {
    const index = buildSwatchIndex([4, 4, 2, 2, 2])
    expect(index.size).toBe(2)
    expect(index.get(2)).toBe(0)
    expect(index.get(4)).toBe(1)
  })

  it('문자열이 아니라 숫자로 견준다 (10 이 9 보다 뒤)', () => {
    const index = buildSwatchIndex([10, 9, 100])
    expect(index.get(9)).toBe(0)
    expect(index.get(10)).toBe(1)
    expect(index.get(100)).toBe(2)
  })
})

describe('swatchIndexOf', () => {
  it('화면에 보이는 규칙이 줄어도 순번이 바뀌지 않는다', () => {
    const all = [1, 2, 3, 4]
    // 표를 걸러서 3번 규칙만 남아도, 순번은 전체 목록에서 정한다.
    expect(swatchIndexOf(3, all)).toBe(2)
  })

  it('목록에 없는 규칙은 -1', () => {
    expect(swatchIndexOf(99, [1, 2, 3])).toBe(-1)
    expect(swatchIndexOf(1, [])).toBe(-1)
  })
})

describe('swatchSpec', () => {
  it('처음 여덟 개는 서로 다른 무늬다', () => {
    const patterns = SWATCH_PATTERNS.map((_, index) => {
      const spec = swatchSpec(index)
      return spec.kind === 'pattern' ? spec.pattern : null
    })
    expect(patterns).toEqual([
      'solid',
      'hatch',
      'blank',
      'lines',
      'dots',
      'columns',
      'hatchWide',
      'cross',
    ])
    expect(new Set(patterns).size).toBe(8)
  })

  it('아홉 번째부터는 번호 상자다', () => {
    expect(swatchSpec(8)).toEqual({ kind: 'number', index: 8, number: 9 })
    expect(swatchSpec(23)).toEqual({ kind: 'number', index: 23, number: 24 })
  })

  it('음수와 정수가 아닌 값은 알 수 없음', () => {
    expect(swatchSpec(-1)).toEqual({ kind: 'unknown', index: -1 })
    expect(swatchSpec(1.5)).toEqual({ kind: 'unknown', index: -1 })
    expect(swatchSpec(Number.NaN)).toEqual({ kind: 'unknown', index: -1 })
  })
})

describe('swatchFor', () => {
  it('규칙 id 에서 바로 무늬를 구한다', () => {
    const all = [11, 14, 20, 31]
    expect(swatchFor(11, all)).toEqual({ kind: 'pattern', index: 0, pattern: 'solid' })
    expect(swatchFor(14, all)).toEqual({ kind: 'pattern', index: 1, pattern: 'hatch' })
    expect(swatchFor(20, all)).toEqual({ kind: 'pattern', index: 2, pattern: 'blank' })
    expect(swatchFor(31, all)).toEqual({ kind: 'pattern', index: 3, pattern: 'lines' })
    expect(swatchFor(5, all)).toEqual({ kind: 'unknown', index: -1 })
  })

  it('규칙이 열 개면 아홉·열 번째가 번호 상자가 된다', () => {
    const all = Array.from({ length: 10 }, (_, i) => (i + 1) * 3)
    expect(swatchFor(27, all)).toEqual({ kind: 'number', index: 8, number: 9 })
    expect(swatchFor(30, all)).toEqual({ kind: 'number', index: 9, number: 10 })
  })
})

describe('describeSwatch', () => {
  it('무늬를 말로 설명한다', () => {
    expect(describeSwatch(swatchSpec(1))).toBe('빗금 무늬')
    expect(describeSwatch(swatchSpec(8))).toBe('9번 상자')
    expect(describeSwatch(swatchSpec(-1))).toBe('무늬 없음')
  })
})
