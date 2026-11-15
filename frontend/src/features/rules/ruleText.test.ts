import { describe, expect, it } from 'vitest'

import { addKeywords, excludeSentence, ruleSentence, type RuleShape } from './ruleText'

const base: RuleShape = {
  kind: 'keyword',
  keywords: [],
  exclude_keywords: [],
  match_mode: 'any',
  min_messages: null,
  window_hours: null,
}

describe('규칙 문장', () => {
  it('키워드 규칙', () => {
    expect(ruleSentence({ ...base, keywords: ['견적', '외주'] })).toBe(
      '‘견적’, ‘외주’ 가운데 하나라도 나오면 받아 적어요.',
    )
    expect(ruleSentence({ ...base, keywords: ['견적', '외주'], match_mode: 'all' })).toBe(
      '‘견적’, ‘외주’이(가) 모두 나오면 받아 적어요.',
    )
    expect(ruleSentence(base)).toBe('키워드를 하나 이상 넣어 주세요.')
    expect(excludeSentence({ ...base, exclude_keywords: ['광고'] })).toBe(
      '‘광고’이(가) 함께 나오면 건너뛰어요.',
    )
  })
  it('활동량 규칙', () => {
    expect(ruleSentence({ ...base, kind: 'activity', min_messages: 30, window_hours: 24 })).toBe(
      '한 그룹에서 24시간 동안 메시지를 30개 넘게 보낸 사람을 받아 적어요.',
    )
  })
  it('키워드 더하기', () => {
    expect(addKeywords(['견적'], '외주, 견적\n 업체  추천 ')).toEqual(['견적', '외주', '업체 추천'])
  })
})
