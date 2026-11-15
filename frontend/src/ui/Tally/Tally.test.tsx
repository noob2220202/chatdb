import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { Tally } from './Tally'

afterEach(cleanup)

describe('Tally', () => {
  it('다섯 번에 正 한 글자를 긋고 나머지는 획으로 남긴다', () => {
    const { container } = render(<Tally count={13} />)
    expect(container.querySelectorAll('svg')).toHaveLength(3) // 正 正 + 세 획
    expect(container.textContent).toBe('13회')
  })

  it('딱 떨어지면 덜 그은 글자가 없다', () => {
    const { container } = render(<Tally count={10} />)
    expect(container.querySelectorAll('svg')).toHaveLength(2)
  })

  it('15회를 넘으면 숫자만 적는다', () => {
    const { container } = render(<Tally count={16} />)
    expect(container.querySelector('svg')).toBeNull()
    expect(container.textContent).toBe('16회')
  })

  it('큰 수에는 쉼표를 찍는다', () => {
    const { container } = render(<Tally count={1280} unit="번" />)
    expect(container.textContent).toBe('1,280번')
  })

  it('획은 장식이라 읽어 주지 않는다', () => {
    const { container } = render(<Tally count={4} />)
    expect(container.querySelector('[aria-hidden="true"] svg')).not.toBeNull()
  })
})
