import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { SlotDots } from './SlotDots'

afterEach(cleanup)

describe('SlotDots', () => {
  it('자리 수만큼 점을 찍는다', () => {
    const { container } = render(<SlotDots joined={13} pending={4} />)
    // 반쪽 점은 테 + 반원이라 원은 20개, 반원(path)은 4개
    expect(container.querySelectorAll('circle')).toHaveLength(20)
    expect(container.querySelectorAll('path')).toHaveLength(4)
  })

  it('점을 보지 않아도 알 수 있게 말로 적는다', () => {
    const { getByRole } = render(<SlotDots joined={13} pending={4} />)
    expect(getByRole('img').getAttribute('aria-label')).toBe(
      '20자리 가운데 13곳에 들어가 있어요. 4곳은 기다리는 중이에요. 빈 자리는 3곳이에요',
    )
  })

  it('가득 찼을 때', () => {
    const { getByRole } = render(<SlotDots joined={20} />)
    expect(getByRole('img').getAttribute('aria-label')).toBe(
      '20자리 가운데 20곳에 들어가 있어요. 빈 자리가 없어요',
    )
  })

  it('자리 수를 넘는 값은 자리 수까지만 그린다', () => {
    const { container } = render(<SlotDots joined={25} pending={3} capacity={20} />)
    expect(container.querySelectorAll('circle')).toHaveLength(20)
    expect(container.querySelectorAll('path')).toHaveLength(0)
  })

  it('스무 자리를 넘으면 줄을 바꾼다', () => {
    const one = render(<SlotDots joined={5} capacity={20} />)
    const height1 = Number(one.container.querySelector('svg')?.getAttribute('height'))
    cleanup()
    const two = render(<SlotDots joined={5} capacity={30} />)
    const height2 = Number(two.container.querySelector('svg')?.getAttribute('height'))
    expect(height2).toBeGreaterThan(height1)
    expect(two.container.querySelectorAll('circle')).toHaveLength(30)
  })

  it('연결이 끊긴 계정은 그 사실을 함께 말한다', () => {
    const { getByRole } = render(<SlotDots joined={13} tone="problem" />)
    expect(getByRole('img').getAttribute('aria-label')).toContain('지금은 연결이 끊겨 듣지 못해요')
  })
})
