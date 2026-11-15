import { describe, expect, it } from 'vitest'

import { validateSetup } from './validateSetup'

describe('validateSetup', () => {
  it('8자가 안 되면 몇 자인지 알려 준다', () => {
    expect(validateSetup('short', 'short')).toEqual({
      password: '8자 이상으로 정해 주세요. 지금은 5자예요.',
    })
  })

  it('두 칸이 다르면 둘째 칸에 알린다', () => {
    expect(validateSetup('correct horse', 'correct hors')).toEqual({
      confirm: '위와 똑같이 적어 주세요.',
    })
  })

  it('문제가 없으면 빈 객체다', () => {
    expect(validateSetup('correct horse', 'correct horse')).toEqual({})
  })
})
