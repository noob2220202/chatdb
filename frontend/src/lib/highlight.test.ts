import { describe, expect, it } from 'vitest'

import { findKeywordRanges, highlight, normalize, splitGraphemes } from './highlight'

/** 걸린 조각만 뽑는다. */
function matched(text: string, keywords: string[]): string[] {
  return highlight(text, keywords)
    .filter((segment) => segment.match)
    .map((segment) => segment.text)
}

describe('normalize', () => {
  it('전각 문자를 반각으로, 대문자를 소문자로 맞춘다', () => {
    expect(normalize('ＣＳＶ 견적')).toBe('csv 견적')
    expect(normalize('Straße')).toBe('strasse')
  })

  it('풀어 쓴 한글 자모를 한 글자로 합친다', () => {
    expect(normalize('견적')).toBe('견적')
  })
})

describe('highlight', () => {
  it('키워드가 없으면 문장을 한 조각으로 돌려준다', () => {
    expect(highlight('촬영 스튜디오 알아보는 중이에요', ['견적'])).toEqual([
      { text: '촬영 스튜디오 알아보는 중이에요', match: false },
    ])
    expect(highlight('견적 문의드려요', [])).toEqual([{ text: '견적 문의드려요', match: false }])
  })

  it('빈 문장은 빈 배열이다', () => {
    expect(highlight('', ['견적'])).toEqual([])
  })

  it('한 문장에서 여러 키워드를 모두 찾는다', () => {
    const text = '혹시 상세페이지 외주 맡겨보신 분 계세요? 견적이 어느 정도인지 궁금해요'
    expect(highlight(text, ['견적', '외주'])).toEqual([
      { text: '혹시 상세페이지 ', match: false },
      { text: '외주', match: true },
      { text: ' 맡겨보신 분 계세요? ', match: false },
      { text: '견적', match: true },
      { text: '이 어느 정도인지 궁금해요', match: false },
    ])
  })

  it('같은 키워드가 여러 번 나오면 모두 잡는다', () => {
    expect(matched('견적 받고 싶은데 견적서 양식 있나요', ['견적'])).toEqual(['견적', '견적'])
  })

  it('조각을 이어 붙이면 원문과 같다', () => {
    const text = '배대지 업체추천 좀 부탁드려요. 지금 쓰는 곳이 너무 느려서요'
    const joined = highlight(text, ['업체 추천', '배대지'])
      .map((segment) => segment.text)
      .join('')
    expect(joined).toBe(text)
  })

  it('띄어쓰기가 있는 키워드는 붙여 쓴 문장도 잡는다', () => {
    expect(matched('배대지 업체추천 좀 부탁드려요', ['업체 추천'])).toEqual(['업체추천'])
  })

  it('띄어쓰기가 있는 키워드는 띄어쓰기가 다른 문장도 잡고, 사이의 공백까지 한 조각으로 묶는다', () => {
    expect(matched('동대문 사입 대행 업체 추천 받습니다', ['업체 추천'])).toEqual(['업체 추천'])
    expect(matched('메타 광고  대행 맡기려는데', ['광고 대행'])).toEqual(['광고  대행'])
    expect(matched('광 고대행 문의', ['광고 대행'])).toEqual(['광 고대행'])
  })

  it('띄어쓰기가 없는 키워드는 띄어 쓴 문장을 잡지 않는다', () => {
    expect(matched('업체 추천 부탁드려요', ['업체추천'])).toEqual([])
  })

  it('대소문자와 전각/반각을 가리지 않는다', () => {
    expect(matched('csv로 받을 수 있나요', ['CSV'])).toEqual(['csv'])
    expect(matched('ＣＳＶ 파일 견적', ['csv'])).toEqual(['ＣＳＶ'])
    expect(matched('Smart Store 운영 대행', ['smartstore', 'smart store'])).toEqual(['Smart Store'])
  })

  it('겹치는 키워드는 하나로 합친다', () => {
    expect(matched('광고대행사 추천해 주세요', ['광고대행', '대행사'])).toEqual(['광고대행사'])
    expect(matched('견적서 보내 주세요', ['견적', '견적서'])).toEqual(['견적서'])
  })

  it('맞닿은 키워드도 한 조각으로 합친다', () => {
    expect(matched('외주견적 문의', ['외주', '견적'])).toEqual(['외주견적'])
  })

  it('빈 키워드와 공백뿐인 키워드는 무시한다', () => {
    expect(matched('견적 문의', ['', '   ', '견적'])).toEqual(['견적'])
  })

  it('키워드 앞뒤 공백은 떼고 찾는다', () => {
    expect(matched('견적 문의', ['  견적 '])).toEqual(['견적'])
  })

  it('풀어 쓴 한글(NFD)로 온 문장에서도 원문 위치를 정확히 돌려준다', () => {
    const decomposed = '견적 문의' // "견적 문의"를 자모로 풀어 쓴 것
    const segments = highlight(decomposed, ['견적'])
    expect(segments[0]).toEqual({ text: '견적', match: true })
    expect(segments[1]).toEqual({ text: ' 문의', match: false })
  })

  it('정규화하면 글자 수가 달라지는 문자가 있어도 위치가 밀리지 않는다', () => {
    // ㈜ 는 NFKC 에서 "(주)" 세 글자로 풀린다.
    const text = '㈜한빛 견적 요청'
    expect(matched(text, ['견적'])).toEqual(['견적'])
    expect(findKeywordRanges(text, ['견적'])).toEqual([{ start: 4, end: 6 }])
    // 풀린 글자 일부만 걸려도 원문의 그 글자 전체를 잡는다.
    expect(matched(text, ['주)한빛'])).toEqual(['㈜한빛'])
  })

  it('이모지가 섞여 있어도 위치가 맞는다', () => {
    expect(matched('👍🏽 견적 부탁드려요 🙏', ['견적'])).toEqual(['견적'])
  })
})

describe('findKeywordRanges', () => {
  it('시작 위치 순서로 돌려준다', () => {
    expect(findKeywordRanges('외주 견적 외주', ['견적', '외주'])).toEqual([
      { start: 0, end: 2 },
      { start: 3, end: 5 },
      { start: 6, end: 8 },
    ])
  })
})

describe('splitGraphemes', () => {
  it('한글을 글자 단위로 나눈다', () => {
    expect(splitGraphemes('업체 추천')).toEqual(['업', '체', ' ', '추', '천'])
  })
})
