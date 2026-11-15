import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { KeywordText } from './KeywordText'

afterEach(cleanup)

describe('KeywordText', () => {
  it('문장을 그대로 보여 주고 걸린 말만 mark 로 감싼다', () => {
    const text = '혹시 상세페이지 외주 맡겨보신 분 계세요? 견적이 어느 정도인지 궁금해요'
    const { container } = render(<KeywordText text={text} keywords={['견적', '외주']} />)
    expect(container.textContent).toBe(text)
    const marks = Array.from(container.querySelectorAll('mark')).map((mark) => mark.textContent)
    expect(marks).toEqual(['외주', '견적'])
  })

  it('걸린 글자마다 방점을 찍을 자리(i)를 만든다. 띄어쓰기에는 찍지 않는다', () => {
    const { container } = render(
      <KeywordText text="배대지 업체 추천 좀 부탁드려요" keywords={['업체 추천']} />,
    )
    const dotted = Array.from(container.querySelectorAll('mark i'))
      .filter((glyph) => glyph.textContent?.trim())
      .map((glyph) => glyph.textContent)
    expect(dotted).toEqual(['업', '체', '추', '천'])
    // 키워드 안의 띄어쓰기도 mark 안에 있어서 밑칠이 끊기지 않는다
    expect(
      Array.from(container.querySelectorAll('mark'), (mark) => mark.textContent).join(''),
    ).toBe('업체 추천')
  })

  it('걸린 글자가 든 낱말은 조사까지 한 덩어리로 묶는다', () => {
    const { container } = render(<KeywordText text="견적이 궁금해요" keywords={['견적']} />)
    const word = container.querySelector('mark')?.parentElement
    expect(word?.textContent).toBe('견적이')
  })

  it('quoted 를 주면 “ ” 로 감싼다', () => {
    const { container } = render(<KeywordText text="견적 문의" keywords={['견적']} quoted />)
    expect(container.textContent).toBe('“견적 문의”')
  })

  it('키워드가 없으면 mark 를 만들지 않는다', () => {
    const { container } = render(<KeywordText text="안녕하세요" keywords={[]} />)
    expect(container.querySelector('mark')).toBeNull()
    expect(container.textContent).toBe('안녕하세요')
  })
})
