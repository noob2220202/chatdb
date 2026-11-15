import { describe, expect, it } from 'vitest'

import { coverPoint, coverSize, placeLamp } from './lampAnchor'

const natural = { width: 1866, height: 1800 }
const lamp = { x: 0.2287, y: 0.41884 }

describe('coverSize', () => {
  it('상자를 빈틈없이 덮는 가장 작은 크기를 고른다', () => {
    // 시안: 933×900 상자에 정확히 절반 크기로 들어간다
    expect(coverSize({ width: 933, height: 900 }, natural)).toEqual({ width: 933, height: 900 })
    // 가로로 넓은 상자: 폭에 맞추고 세로가 넘친다
    const wide = coverSize({ width: 1866, height: 900 }, natural)
    expect(wide.width).toBe(1866)
    expect(wide.height).toBe(1800)
    // 세로로 긴 상자: 높이에 맞추고 가로가 넘친다
    const tall = coverSize({ width: 400, height: 1800 }, natural)
    expect(tall.height).toBe(1800)
    expect(tall.width).toBe(1866)
  })
})

describe('coverPoint', () => {
  it('시안의 판형(933×900, 왼쪽·위 기준)에서 램프는 (213.4, 377) 에 있다', () => {
    const point = coverPoint({ width: 933, height: 900 }, natural, lamp)
    expect(point.x).toBeCloseTo(213.4, 0)
    expect(point.y).toBeCloseTo(377, 0)
  })

  it('세로가 넘칠 때 object-position 이 아래일수록 점이 위로 올라간다', () => {
    const box = { width: 1866, height: 900 }
    const top = coverPoint(box, natural, lamp, { x: 0, y: 0 })
    const bottom = coverPoint(box, natural, lamp, { x: 0, y: 1 })
    expect(top.y).toBeCloseTo(0.41884 * 1800, 3)
    expect(bottom.y).toBeCloseTo(0.41884 * 1800 - 900, 3)
    expect(top.x).toBe(bottom.x)
  })

  it('가로가 넘칠 때 가운데 기준이면 넘친 만큼의 절반이 왼쪽으로 빠진다', () => {
    const box = { width: 400, height: 1800 }
    const point = coverPoint(box, natural, lamp, { x: 0.5, y: 0 })
    expect(point.x).toBeCloseTo(0.2287 * 1866 - (1866 - 400) / 2, 3)
  })
})

describe('placeLamp', () => {
  const sizes = [
    { width: 1200, height: 700 },
    { width: 1280, height: 720 },
    { width: 1440, height: 900 },
    { width: 1920, height: 1080 },
    { width: 2560, height: 1440 },
  ]

  it('어떤 창 크기에서도 램프는 상자 안에 있고, 돌려준 자리와 cover 계산이 맞는다', () => {
    for (const viewport of sizes) {
      const box = { width: viewport.width - 507, height: viewport.height }
      const placed = placeLamp(box, natural, lamp, 0.42)
      expect(placed.point.x).toBeGreaterThan(0)
      expect(placed.point.x).toBeLessThan(box.width)
      expect(placed.point.y).toBeGreaterThan(0)
      expect(placed.point.y).toBeLessThan(box.height)
      expect(placed.point).toEqual(coverPoint(box, natural, lamp, placed.position))
      expect(placed.position.y).toBeGreaterThanOrEqual(0)
      expect(placed.position.y).toBeLessThanOrEqual(1)
    }
  })

  it('세로로 넘칠 여유가 있으면 램프를 바라는 높이에 맞춘다', () => {
    const box = { width: 1413, height: 1080 }
    const placed = placeLamp(box, natural, lamp, 0.42)
    expect(placed.point.y).toBeCloseTo(0.42 * 1080, 3)
  })

  it('여유가 없으면 위에 붙인 채로 둔다', () => {
    const box = { width: 693, height: 700 }
    const placed = placeLamp(box, natural, lamp, 0.42)
    expect(placed.position).toEqual({ x: 0, y: 0 })
    expect(placed.point.y).toBeCloseTo(0.41884 * 700, 3)
  })

  it('바라는 높이가 닿지 않는 곳이면 닿는 데까지만 움직인다', () => {
    const box = { width: 1866, height: 900 }
    // 램프를 맨 위(0)에 두고 싶어도 사진은 900px 넘게 올라갈 수 없다
    const placed = placeLamp(box, natural, lamp, 0)
    expect(placed.position.y).toBeLessThanOrEqual(1)
    expect(placed.point.y).toBeGreaterThanOrEqual(0)
  })
})
