/**
 * 수집 규칙마다 인쇄 무늬를 하나씩 정한다.
 *
 * 범례·실시간 감지·수집함 표에서 같은 규칙은 늘 같은 무늬로 보여야 한다.
 * 그래서 무늬는 "전체 규칙 id 를 오름차순으로 늘어놓았을 때 몇 번째인가"로만 정한다.
 * 화면에 지금 몇 개가 보이는지, 어떤 순서로 정렬했는지와는 상관이 없다.
 */

/** 무늬 여덟 가지. 12px 에서도 서로 헷갈리지 않는 순서로 골랐다. */
export const SWATCH_PATTERNS = [
  'solid', // 먹으로 꽉 채움
  'hatch', // 빗금 (오른쪽 위로)
  'blank', // 빈 상자
  'lines', // 가로줄
  'dots', // 점
  'columns', // 세로줄
  'hatchWide', // 성긴 빗금 (왼쪽 위로)
  'cross', // 격자
] as const

export type SwatchPattern = (typeof SWATCH_PATTERNS)[number]

export type SwatchSpec =
  | { kind: 'pattern'; index: number; pattern: SwatchPattern }
  /** 여덟 개를 넘으면 상자 안에 번호를 적는다. number 는 1부터 센 순번이다. */
  | { kind: 'number'; index: number; number: number }
  /** 목록에 없는 규칙 (지워진 규칙 등) */
  | { kind: 'unknown'; index: -1 }

/** 무늬 이름 (스크린 리더·범례 설명용) */
export const SWATCH_PATTERN_LABEL: Record<SwatchPattern, string> = {
  solid: '채움',
  hatch: '빗금',
  blank: '빈 상자',
  lines: '가로줄',
  dots: '점',
  columns: '세로줄',
  hatchWide: '성긴 빗금',
  cross: '격자',
}

/** 전체 규칙 id 목록 → (규칙 id → 순번). 순번은 id 오름차순으로 0부터 매긴다. */
export function buildSwatchIndex(allRuleIds: Iterable<number>): Map<number, number> {
  const sorted = Array.from(new Set(allRuleIds)).sort((a, b) => a - b)
  const index = new Map<number, number>()
  sorted.forEach((id, position) => index.set(id, position))
  return index
}

/** 규칙 하나의 순번. 목록에 없으면 -1. */
export function swatchIndexOf(ruleId: number, allRuleIds: Iterable<number>): number {
  return buildSwatchIndex(allRuleIds).get(ruleId) ?? -1
}

/** 순번 → 무늬. 0–7 은 무늬, 그 뒤로는 번호 상자, 음수는 '알 수 없음'. */
export function swatchSpec(index: number): SwatchSpec {
  if (!Number.isInteger(index) || index < 0) return { kind: 'unknown', index: -1 }
  const pattern = SWATCH_PATTERNS[index]
  if (pattern) return { kind: 'pattern', index, pattern }
  return { kind: 'number', index, number: index + 1 }
}

/** 규칙 id 에서 바로 무늬를 구한다. */
export function swatchFor(ruleId: number, allRuleIds: Iterable<number>): SwatchSpec {
  return swatchSpec(swatchIndexOf(ruleId, allRuleIds))
}

/** 무늬를 말로 설명한다: "빗금 무늬", "9번 상자" */
export function describeSwatch(spec: SwatchSpec): string {
  if (spec.kind === 'pattern') return `${SWATCH_PATTERN_LABEL[spec.pattern]} 무늬`
  if (spec.kind === 'number') return `${spec.number}번 상자`
  return '무늬 없음'
}
