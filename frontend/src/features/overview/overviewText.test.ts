import { describe, expect, it } from 'vitest'

import { joinSummary, splitLinks } from './overviewText'

describe('개요 문장', () => {
  it('링크를 떼어 낸다', () => {
    expect(splitLinks(' t.me/a\n@b , t.me/a ')).toEqual(['t.me/a', '@b'])
  })
  it('가입 결과를 한 문장으로', () => {
    expect(
      joinSummary([{ outcome: 'queued' }, { outcome: 'queued' }, { outcome: 'duplicate' }]),
    ).toBe('2곳을 가입 대기열에 넣었어요. 1곳은 이미 있어요.')
  })
})
