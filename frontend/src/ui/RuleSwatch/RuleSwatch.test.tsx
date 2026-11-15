import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { RuleName, RuleSwatch, ruleSwatchLabel } from './RuleSwatch'

afterEach(cleanup)

describe('RuleSwatch', () => {
  it('처음 여덟 개는 그림으로 그린다', () => {
    for (let index = 0; index < 8; index++) {
      const { container } = render(<RuleSwatch index={index} />)
      expect(container.querySelector('svg')).not.toBeNull()
      cleanup()
    }
  })

  it('아홉 번째부터는 번호를 적는다', () => {
    const { container } = render(<RuleSwatch index={8} />)
    expect(container.querySelector('svg')).toBeNull()
    expect(container.textContent).toBe('9')
  })

  it('이름 옆에 놓이면 장식으로 본다', () => {
    const { container } = render(<RuleName index={1}>업체 찾는 사람</RuleName>)
    expect(container.querySelector('svg')?.getAttribute('aria-hidden')).toBe('true')
    expect(container.textContent).toBe('업체 찾는 사람')
  })

  it('무늬를 말로 설명한다', () => {
    expect(ruleSwatchLabel(0)).toBe('채움 무늬')
    expect(ruleSwatchLabel(11)).toBe('12번 상자')
  })
})
