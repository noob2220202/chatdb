import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'

import { Stepper } from './Stepper'

afterEach(cleanup)

it('지금 단계에만 aria-current 가 붙고, 지난 단계는 마침으로 읽힌다', () => {
  render(<Stepper steps={['전화번호', '인증 코드', '2단계 비밀번호']} current={1} />)
  const items = screen.getAllByRole('listitem')
  expect(items.map((item) => item.getAttribute('aria-current'))).toEqual([null, 'step', null])
  expect(items[0]?.textContent).toContain('마침')
  expect(items[2]?.textContent).not.toContain('마침')
})
